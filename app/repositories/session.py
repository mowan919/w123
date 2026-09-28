"""会话数据访问（Phase 4 认证 / Phase 5 会话管理）。

设计要点
-------
1. **按令牌哈希反查**是每个请求的热路径，因此 `access_token_hash` 与
   `refresh_token_hash` 上都有唯一索引（唯一性同时保证"一个令牌只对应一个会话"）。
2. **轮换是原地替换**：`sessions` 行始终只保存**当前**令牌哈希，
   旧 refresh 哈希移入 `session_refresh_token_history`。
   之所以不移入"新行 + 软删除"，是因为"哪个令牌有效"必须只有一处真相。
3. `touch` 采用**写抑制**：只有距上次活动超过 `SESSION_ACTIVITY_WRITE_INTERVAL`
   才写库。否则每个受保护请求都会 UPDATE 一次 `sessions`，
   在高频轮询下把认证热路径变成写热点。
4. 计数用 `RETURNING` 而非 `rowcount`（理由同 `UserRepository.prune_password_history`：
   `AsyncSession.execute` 声明返回基类 `Result`，`rowcount` 只存在于 `CursorResult`）。
5. **会话终结只有一处实现**（`revoke_and_retire`）：本人登出、管理员踢单个、
   管理员踢全部三类调用方共用同一段代码，避免"登出做了 A、踢下线只做了 B"
   这类语义漂移（`10 §7` 对三者提出的是同一个要求：令牌立即不可用）。
6. **管理侧列表的范围条件下推到 SQL**（`10 §10`）：`sessions` 与 `admin_users`
   join 后直接施加 `user_scope_condition`，绝不允许"先取全部再在内存过滤"。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, distinct, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import ResolvedScope
from app.models.enums import (
    RefreshTokenRetirement,
    SessionRevokeReason,
    UserStatus,
)
from app.models.session import SessionRefreshTokenHistory, UserSession
from app.models.user import AdminUser
from app.repositories.scope_filters import user_scope_condition

#: `last_active_at` 的写入抑制窗口。
#:
#: INTERIM 技术取值：Spec 未规定"最近活动"的更新粒度。
#: 取 60 秒的理由：`04 §5` 的在线状态判定粒度是分钟级，
#: 更细的粒度换不到可观测收益，却让每个请求都产生一次 UPDATE。
#: 该值只影响"最近的活跃时间戳有多新"，**不影响**任何鉴权判定。
SESSION_ACTIVITY_WRITE_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class SessionListFilters:
    """管理侧会话列表的**筛选条件集合**。

    为什么不把六个参数一路透传：`_admin_conditions` 是列表与计数的
    **唯一条件构造点**，而条件数量会随界面演进增加。"每个方法各加一个
    同名参数"的写法只要漏掉一层（列表加了、计数忘了），
    就会出现"总数与页内条数对不上"——那是最难被发现的一类分页缺陷。
    收敛成一个值对象后，漏传在类型层面就是不可能的。

    `online` 是三态（`None` / `True` / `False`），不是布尔：
    它必须能表达"不筛选"，而 `False` 已经被"仅离线"占用。
    """

    online: bool | None = None
    ip: str | None = None
    device: str | None = None
    login_from: datetime | None = None
    login_to: datetime | None = None

    @property
    def is_empty(self) -> bool:
        """是否所有筛选项都未施加（审计里用它表示"没有任何筛选"）。"""
        return (
            self.online is None
            and self.ip is None
            and self.device is None
            and self.login_from is None
            and self.login_to is None
        )

    def audit_summary(self) -> dict[str, object]:
        """审计用的**存在性**摘要 —— 刻意不含任何查询值。

        与 `Phase 7` 对系统参数的裁定同一口径（参数审计只记
        `value_is_set` / 长度，不记值）：审计是 append-only 且保留两年，
        把管理员**搜过哪个 IP**写进去，等于给审计表积累一批
        "谁在排查谁的登录"的画像数据，而它对追责没有用途 ——
        真正要追责的动作是 `revoke`，那条事件自带完整 before/after。
        """
        return {
            "online": self.online,
            "ip_filter": self.ip is not None,
            "device_filter": self.device is not None,
            "login_range_filter": self.login_from is not None or self.login_to is not None,
        }


def online_session_condition(now: datetime) -> ColumnElement[bool]:
    """**在线会话**的 SQL 条件（`04 §5` 在线状态判定的落地）。

    INTERIM-4-04：Spec `04 §5` 只说"在线状态由有效 Session / 最近活动**等**规则
    计算"，未给数值口径。本实现取：

    ```text
    在线 = 会话未撤销 且 会话总寿命（refresh）未过
    ```

    两个刻意的取舍：

    1. **不把 access 到期算作离线**。access 只活 15 分钟，
       若把它算进来，那么"用户开着页面但 20 分钟没动"就会显示离线 ——
       而客户端只要 refresh 一下就能继续用，会话并未结束。
       因此判定用 refresh（会话总寿命），不用 access。
    2. **不引入空闲阈值**（如"30 分钟无活动即离线"）。
       Spec 未规定该数值，自造数值等于发明业务规则；
       需要按空闲度判断时，调用方读响应里的 `last_active_at` 自行判断。

    与实体方法 `UserSession.is_active` 语义完全一致
    （SQL 版与 Python 版必须同源，否则会出现"列表说在线、鉴权说失效"）。
    此外**在线**还要求所属用户为 ACTIVE 且未逻辑删除 ——
    该部分条件在 `_admin_conditions` 中与用户表一起施加，
    因为 `authenticate()` 要求"会话有效 **且** 用户 ACTIVE"，
    被禁用用户的会话实际不可用，报其为"在线"会与系统自身的有效性定义矛盾。
    """
    return and_(
        UserSession.revoked_at.is_(None),
        UserSession.refresh_expires_at > now,
    )


class SessionRepository:
    """会话仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def add(self, user_session: UserSession) -> UserSession:
        """新增会话并 flush（拿到唯一约束的校验结果）。"""
        self._session.add(user_session)
        await self._session.flush()
        return user_session

    async def touch(
        self,
        user_session: UserSession,
        *,
        now: datetime,
        interval: timedelta = SESSION_ACTIVITY_WRITE_INTERVAL,
    ) -> bool:
        """更新 `last_active_at`（带写抑制）。返回是否真的写库。"""
        if now - user_session.last_active_at < interval:
            return False
        user_session.last_active_at = now
        await self._session.flush()
        return True

    async def rotate_tokens(
        self,
        user_session: UserSession,
        *,
        access_token_hash: str,
        refresh_token_hash: str,
        access_expires_at: datetime,
        last_active_at: datetime,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> bool:
        """**CAS** 轮换当前令牌对（并发安全的唯一轮换入口）。

        ## 为什么必须是 CAS 而不是直接改 ORM 对象

        DD-02 P7 要求"同一 refresh token 并发提交两次"时**只能有一次成功**。
        若两个并发请求各自读到同一行再各自覆盖，就会出现"两次轮换都成功"：

        - 数据库里留下**后写入者**的哈希，客户端却可能持有先写入者的令牌；
        - 更糟的是复用检测拿不到任何信号（两边都被视作合法轮换），
          一次真实的令牌盗用会被静默吞掉。

        用 `WHERE access_token_hash = 旧值 AND revoked_at IS NULL` 作为 CAS 条件后，
        第二个请求的 `UPDATE` 影响 0 行 —— 调用方据此判定"轮换竞争失败"，
        并按**令牌复用**处理（撤销整个会话），
        这既满足 P7（串行化），又不会放过盗用信号。

        ## 为什么不动 `refresh_expires_at`

        DD-02 P2 冻结为"7 天固定，**不滑动**"。因此轮换只前移 access 的到期时间，
        会话总寿命恒为登录时刻 + 7 天，不能被无限刷新延长。

        Returns:
            True = 本请求赢得轮换；False = 会话已被并发请求轮换过。
        """
        result = await self._session.execute(
            update(UserSession)
            .where(
                UserSession.id == user_session.id,
                UserSession.access_token_hash == user_session.access_token_hash,
                UserSession.revoked_at.is_(None),
            )
            .values(
                access_token_hash=access_token_hash,
                refresh_token_hash=refresh_token_hash,
                expires_at=access_expires_at,
                last_active_at=last_active_at,
                ip=ip if ip is not None else UserSession.ip,
                user_agent=user_agent if user_agent is not None else UserSession.user_agent,
            )
            .returning(UserSession.id)
        )
        rotated = result.scalars().all()
        if not rotated:
            return False
        # ORM 对象与数据库已不一致，显式同步，避免后续读到自己过期的旧值。
        user_session.access_token_hash = access_token_hash
        user_session.refresh_token_hash = refresh_token_hash
        user_session.expires_at = access_expires_at
        user_session.last_active_at = last_active_at
        if ip is not None:
            user_session.ip = ip
        if user_agent is not None:
            user_session.user_agent = user_agent
        return True

    async def revoke(
        self,
        user_session: UserSession,
        *,
        reason: SessionRevokeReason,
        now: datetime,
    ) -> bool:
        """置撤销标记（幂等：已撤销则返回 False 且不改写原因）。

        这是**底层原语**：只改 `sessions` 两列，不碰退役哈希留档。
        业务代码请不要直接调用它，改用 `revoke_and_retire`
        —— 否则会漏掉 refresh 哈希留档，使三个终结入口语义不一致。
        保留本方法是因为它是最小原子单元，便于单独测试与复用。

        `revoked_at` 一旦写入即**立即**生效（Spec `10 §7`），
        因为每次请求都会读取该列。不改写已有的 `revoke_reason`：
        第一个原因才是真相（例如先因盗用被撤销，事后登出不应覆盖它）。
        """
        if user_session.revoked_at is not None:
            return False
        user_session.revoked_at = now
        user_session.revoke_reason = reason
        await self._session.flush()
        return True

    async def revoke_and_retire(
        self,
        user_session: UserSession,
        *,
        reason: SessionRevokeReason,
        now: datetime,
    ) -> bool:
        """终结一个会话：置撤销标记 + 把当前 refresh 哈希留档。

        ## 为什么单独一个方法

        "会话终结"在本系统里有三个触发点：

        | 触发点 | reason |
        |---|---|
        | 本人登出（`POST /auth/logout`） | `LOGOUT` |
        | 管理员踢单个（`POST /sessions/{id}/revoke`） | `ADMIN_REVOKE` |
        | 管理员踢全部 / 盗用检测 | `ADMIN_REVOKE` / `TOKEN_REUSE_DETECTED` |

        三者对 `10 §7` 的义务完全相同（"Revoke 后 Token 必须不能继续访问"），
        因此**必须**共用同一段实现。若各自写一份，迟早出现
        "登出额外退役了 refresh 哈希、踢下线没有"这类不一致 ——
        不一致本身不是安全问题，但它会让"取证时能否追到这个令牌"取决于
        用户是被踢还是自己退出，属于不应存在的差异。

        Returns:
            True = 本次调用真正撤销了它；False = 它此前已撤销（幂等，DD-11 方案 A）。
        """
        revoked = await self.revoke(user_session, reason=reason, now=now)
        if revoked:
            await self.record_retired_refresh_token(
                session_id=user_session.id,
                token_hash=user_session.refresh_token_hash,
                reason=RefreshTokenRetirement.SESSION_REVOKED,
                retired_at=now,
            )
        return revoked

    async def record_retired_refresh_token(
        self,
        *,
        session_id: int,
        token_hash: str,
        reason: RefreshTokenRetirement,
        retired_at: datetime,
    ) -> None:
        """把一枚退役的 Refresh Token 哈希留档（用于盗用检测与取证）。

        ## 为什么必须是 `ON CONFLICT DO NOTHING`

        这条记录表达的是集合成员关系（"这个哈希曾经合法过"），
        重复写入在语义上毫无意义。而在**并发刷新**场景下重复是必然发生的：

        ```text
        请求 A：留档 R1(ROTATED) → CAS 轮换成功
        请求 B：留档 R1(ROTATED) → CAS 失败 → 撤销会话
                → 还要把"当前" refresh（此刻仍是 R1）留档为 SESSION_REVOKED
        ```

        若用普通 INSERT，请求 B 的第二次留档会撞 `uq_session_refresh_token_history_token_hash`
        并抛 `IntegrityError` —— 后果是**本该完成的会话撤销被事务回滚**，
        即"检测到令牌盗用却没能撤销它"。这是必须消除的失败模式，
        而 `DO NOTHING` 恰好把它变成幂等操作：

        - 首次留档的原因被**保留**（后到的原因不改写先到的）；
        - 重复留档不再影响事务；
        - 误报由读路径负责排除（已撤销的会话不会触发 reuse 告警，
          见 `SessionService._handle_unknown_refresh_token`）。
        """
        await self._session.execute(
            pg_insert(SessionRefreshTokenHistory)
            .values(
                session_id=session_id,
                token_hash=token_hash,
                reason=reason,
                retired_at=retired_at,
            )
            .on_conflict_do_nothing(index_elements=["token_hash"])
        )
        await self._session.flush()

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    async def get(self, session_id: int) -> UserSession | None:
        """按会话 ID 读取。"""
        stmt = select(UserSession).where(UserSession.id == session_id)
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_access_token_hash(self, token_hash: str) -> UserSession | None:
        """按 Access Token 哈希读取（每请求热路径）。"""
        stmt = select(UserSession).where(UserSession.access_token_hash == token_hash)
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_refresh_token_hash(self, token_hash: str) -> UserSession | None:
        """按 **当前有效** Refresh Token 哈希读取。"""
        stmt = select(UserSession).where(UserSession.refresh_token_hash == token_hash)
        return (await self._session.execute(stmt)).scalars().first()

    async def get_retired_refresh_token(self, token_hash: str) -> SessionRefreshTokenHistory | None:
        """按哈希读取**已退役**的 Refresh Token 记录。

        只有当前令牌查不到时才会走到这里 —— 这是判定"盗用"与
        "普通无效令牌"的关键分支。
        """
        stmt = select(SessionRefreshTokenHistory).where(
            SessionRefreshTokenHistory.token_hash == token_hash
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def count_active_for_user(self, user_id: int, *, now: datetime) -> int:
        """统计用户当前有效会话数（未撤销且 refresh 未过期）。"""
        stmt = (
            select(func.count())
            .select_from(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.refresh_expires_at > now,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # 管理侧查询（`10 §10`：范围条件下推到 SQL）
    # ------------------------------------------------------------------
    def _admin_conditions(
        self,
        scope: ResolvedScope,
        *,
        now: datetime,
        filters: SessionListFilters,
        user_id: int | None,
    ) -> list[ColumnElement[bool]]:
        """管理侧列表 / 计数的查询条件（唯一构造点，保证两者口径一致）。

        ## 在线三态

        "在线"是**用户与会话的联合状态**（见 `online_session_condition`），
        因此判定的完整形态是：

        ```text
        online_condition = 会话未撤销 且 会话总寿命未过 且 用户 ACTIVE
        ```

        `online=False`（仅离线）**直接取上面这个条件的逻辑非**，而不是另写一组
        `撤销 OR 过期 OR 非 ACTIVE`。后者看起来等价，实际是两个必然漂移的
        表达式：将来只要给"在线"补一条（比如把某种会话排除在外），
        忘记同步另一个，就会出现"既不在在线列表、也不在离线列表里"的会话
        —— 分页总数对不上，且没有任何报错。用 `~` 之后，
        "离线 = 在线的补集"变成结构性事实，不依赖维护者的记性。

        ## 为什么筛选条件都在 SQL 层

        `10 §10` 要求带数据范围的查询真正约束在 SQL 层。这些筛选项与
        数据范围走的是**同一个** `WHERE`，因此不存在"先按范围取一页、
        再在内存里挑出符合筛选的那几条"这种做法导致的"页内只剩 2 条"。
        """
        conditions: list[ColumnElement[bool]] = [
            # 逻辑删除的用户不得出现在普通查询中（`02 §5`）；
            # 其会话也已无法通过认证（`authenticate` 会拒绝删除用户）。
            AdminUser.deleted_at.is_(None),
            user_scope_condition(scope),
        ]
        if user_id is not None:
            conditions.append(UserSession.user_id == user_id)

        if filters.online is not None:
            online_condition = and_(
                online_session_condition(now),
                AdminUser.status == UserStatus.ACTIVE,
            )
            conditions.append(online_condition if filters.online else ~online_condition)

        if filters.ip:
            conditions.append(UserSession.ip.ilike(f"%{filters.ip}%"))
        if filters.device:
            # 一个输入框同时匹配设备粗分类与原始 UA：真实数据里
            # "Windows 10 / Chrome" 这类串只存在其中一个字段上，
            # 只查 device 会漏掉 UA 里才有的浏览器名。
            pattern = f"%{filters.device}%"
            conditions.append(
                or_(UserSession.device.ilike(pattern), UserSession.user_agent.ilike(pattern))
            )
        if filters.login_from is not None:
            conditions.append(UserSession.login_at >= filters.login_from)
        if filters.login_to is not None:
            conditions.append(UserSession.login_at <= filters.login_to)
        return conditions

    async def list_for_admin(
        self,
        scope: ResolvedScope,
        *,
        now: datetime,
        page_num: int,
        page_size: int,
        filters: SessionListFilters | None = None,
        user_id: int | None = None,
    ) -> list[tuple[UserSession, AdminUser]]:
        """分页列出**范围内**用户的会话（含已撤销 / 已过期）。

        返回会话与所属用户的二元组：列表需要展示"这是谁的会话"，
        而单独再查一次用户会在同一次响应里产生 N+1 查询。

        排序 `login_at DESC, id DESC`：`login_at` 是 Spec `04 §3` 的字段，
        `id` 为 Snowflake（单调递增）作为同秒并列时的稳定次序 ——
        没有第二排序键时，分页在并列数据上可能出现重复 / 漏行。
        """
        conditions = self._admin_conditions(
            scope, now=now, filters=filters or SessionListFilters(), user_id=user_id
        )
        stmt = (
            select(UserSession, AdminUser)
            .join(AdminUser, AdminUser.id == UserSession.user_id)
            .where(*conditions)
            .order_by(UserSession.login_at.desc(), UserSession.id.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    async def count_for_admin(
        self,
        scope: ResolvedScope,
        *,
        now: datetime,
        filters: SessionListFilters | None = None,
        user_id: int | None = None,
    ) -> int:
        """统计范围内会话总数（与 `list_for_admin` 使用**完全相同**的条件）。"""
        conditions = self._admin_conditions(
            scope, now=now, filters=filters or SessionListFilters(), user_id=user_id
        )
        stmt = (
            select(func.count())
            .select_from(UserSession)
            .join(AdminUser, AdminUser.id == UserSession.user_id)
            .where(*conditions)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_users_for_admin(
        self,
        scope: ResolvedScope,
        *,
        now: datetime,
        filters: SessionListFilters | None = None,
    ) -> int:
        """统计范围内的**会话所属用户数**（按 `user_id` 去重）。

        与 `count_for_admin` 的区别只有一个：`COUNT(DISTINCT user_id)`
        而不是 `COUNT(*)`。两者共用同一个 `_admin_conditions`，
        因此"在线用户数 ≤ 在线会话数"是结构性事实，不会因为某天
        给在线判定补一条条件而漂移到"在线用户比在线会话还多"。

        ## 为什么必须去重

        一个人开三个浏览器 → 3 条会话、1 个人。报表上写"在线用户 3"
        是**错的**（它会随用户多开标签页线性增长），而且错得很隐蔽：
        数字看起来完全合理。Spec `04 §5` 要的是"后台在线用户查询"，
        主体是**用户**。
        """
        conditions = self._admin_conditions(
            scope, now=now, filters=filters or SessionListFilters(), user_id=None
        )
        stmt = (
            select(func.count(distinct(UserSession.user_id)))
            .select_from(UserSession)
            .join(AdminUser, AdminUser.id == UserSession.user_id)
            .where(*conditions)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_active_for_user(self, user_id: int, *, now: datetime) -> list[UserSession]:
        """列出该用户**当前仍有效**的会话（未撤销且 refresh 未过期）。

        只取有效会话，而不是"所有未撤销的会话"：
        后者会把早已自然过期的会话也打上 `ADMIN_REVOKE` ——
        那等于**改写历史**，让审计再也无法区分
        "这个会话是到期结束的"与"这个会话是被人踢掉的"。
        """
        stmt = select(UserSession).where(
            UserSession.user_id == user_id,
            online_session_condition(now),
        )
        return list((await self._session.execute(stmt)).scalars().all())


__all__ = [
    "SESSION_ACTIVITY_WRITE_INTERVAL",
    "SessionListFilters",
    "SessionRepository",
    "online_session_condition",
]
