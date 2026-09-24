"""会话数据访问（Phase 4 / DD-02 方案 A）。

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
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RefreshTokenRetirement, SessionRevokeReason
from app.models.session import SessionRefreshTokenHistory, UserSession

#: `last_active_at` 的写入抑制窗口。
#:
#: INTERIM 技术取值：Spec 未规定"最近活动"的更新粒度。
#: 取 60 秒的理由：`04 §5` 的在线状态判定粒度是分钟级，
#: 更细的粒度换不到可观测收益，却让每个请求都产生一次 UPDATE。
#: 该值只影响"最近的活跃时间戳有多新"，**不影响**任何鉴权判定。
SESSION_ACTIVITY_WRITE_INTERVAL = timedelta(seconds=60)


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
        """撤销会话（幂等：已撤销则返回 False 且不改写原因）。

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


__all__ = ["SESSION_ACTIVITY_WRITE_INTERVAL", "SessionRepository"]
