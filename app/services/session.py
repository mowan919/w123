"""会话服务：创建 / 认证 / 刷新轮换 / 撤销（Phase 4 / DD-02 方案 A）。

Frozen 依据
-----------
- Spec `04 §1`：登录后 create session → issue token。
- Spec `04 §3`：Session 必须记录会话与令牌信息；Refresh Token 只存哈希。
- Spec `04 §5`：在线状态由有效 Session / 最近活动计算（判定规则属 Session Phase）。
- Spec `10 §4`：不得记录 token 明文。
- Spec `10 §7`：**Revoke 后 Token 必须不能继续访问。**
- DD-02 方案 A（已裁定）：不透明令牌 + PG 唯一真源，Access 15min / Refresh 7 天 /
  每次轮换 / 复用即撤销整个会话；并发刷新按**串行化**处理（P7）。

`10 §7` 是如何被满足的
---------------------
**每次请求**都用 `access_token_hash` 查 `sessions` 并检查 `revoked_at`。
因此撤销动作一旦提交，下一个请求必然被拒 —— 不存在"令牌在 TTL 内仍然可用"的窗口。
这也解释了为什么不需要 denylist，以及为什么本方案不需要签名密钥。

令牌复用检测（DD-02 P4）与并发刷新（P7）的关系
-------------------------------------------
两者共用同一条判定："**这个 refresh token 已经不是当前有效的那个**"。
区别只在原因：

| 情形 | 处理 |
|---|---|
| 命中了已退役且原因为 `ROTATED` 的哈希 | 盗用信号 → 撤销整个会话 + 记 `AUTH_TOKEN_REUSE_DETECTED` |
| 并发刷新导致 CAS 失败 | 竞争失败 → 同上（宁可多撤销一次，也不放过真实盗用） |
| 命中了已退役且原因为 `SESSION_REVOKED` 的哈希 | 会话本就已撤销 → 普通 401，**不**误报 |
| 完全查不到 | 普通 401 |

为什么"并发刷新"要按盗用处理：若把竞争失败当作"换个令牌继续"，
攻击者只要制造并发就能绕过 P7 的串行化要求；
而合法客户端的并发刷新本就是它自己的 bug，撤销一次会话是合理的代价
（已向人类报备，见 `docs/DESIGN-DECISIONS.md` DD-02 落地说明）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import AuthenticationError
from app.core.security.device import describe_device
from app.core.security.token import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    generate_token,
    hash_token,
)
from app.db.base import utc_now
from app.models.enums import RefreshTokenRetirement, SessionRevokeReason, UserStatus
from app.models.session import UserSession
from app.models.user import AdminUser
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.services.actor_factory import ActorFactory
from app.services.auth_audit import AuthAudit, AuthOperator

#: 对外统一的认证失败文案。
#:
#: Spec `10 §5`：不得泄露用户是否存在等不必要信息。
#: 令牌无效 / 过期 / 已撤销 / 所属用户被禁用**一律**返回同一句话 ——
#: 区分它们会让攻击者能通过错误文案枚举"哪些令牌曾经存在"。
_UNAUTHENTICATED_MESSAGE = "认证失败或登录状态已失效"


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """一对新签发的令牌（明文只在此对象与其响应体中存在）。"""

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """一次成功认证的结果。"""

    session: UserSession
    user: AdminUser
    actor: CurrentActor


def rotated_access_expiry(now: datetime, *, refresh_expires_at: datetime) -> datetime:
    """轮换后新 Access Token 的到期时间。

    ## 为什么必须封顶到会话总寿命

    `refresh()` 会在会话**最后一段**时间被合法调用 ——
    例如某人在第 6 天 23 点 55 分刷新，此时会话总寿命只剩 5 分钟，
    而 Access 的名义 TTL 是 15 分钟。若直接写 `now + 15min`，会产生两个后果：

    1. **越界值**：`expires_at` 晚于 `refresh_expires_at`，
       即"access 名义上比它所属的会话活得更久"。
       授权判定读的是 `expires_at`，这种错位值把
       "会话总寿命是硬上界"（DD-02 P2）表达成了两句互相矛盾的话。
    2. **数据库约束拒绝**：`sessions` 上有
       `refresh_expires_at >= expires_at` 的 CHECK，
       该 UPDATE 会失败并回滚 —— 表现为会话末尾一次**必然发生**的 5xx，
       也就是"每个会话在最后 15 分钟里刷新必定报错"。

    封顶之后不变量变为**构造性成立**（`expires_at <= refresh_expires_at` 恒真），
    CHECK 退化为纯粹的"TTL 用反"探针；
    同时客户端拿到的 `access_expires_at` 与实际可用时间一致 ——
    否则客户端会以为还有 15 分钟，实际 5 分钟后就被拒。

    注意这**不**延长会话：`refresh_expires_at` 本身不被触碰（DD-02 P2 固化为不滑动），
    因此本函数只会把 access 的到期时间**提前**至多到会话结束，绝不会推后。
    """
    return min(now + ACCESS_TOKEN_TTL, refresh_expires_at)


class SessionService:
    """会话生命周期服务。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._sessions = SessionRepository(session)
        self._users = UserRepository(session)
        self._actors = ActorFactory(session)
        self._audit = AuthAudit(audit)

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    async def create(
        self,
        *,
        user: AdminUser,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> tuple[UserSession, IssuedTokens]:
        """为一次成功登录创建会话并签发令牌对。

        令牌明文**只在此处产生**，随后立即被哈希；
        返回的 `IssuedTokens` 是明文唯一的出口（交给响应体）。
        """
        issued_at = now or utc_now()
        access_token = generate_token()
        refresh_token = generate_token()

        user_session = UserSession(
            user_id=user.id,
            access_token_hash=hash_token(access_token),
            refresh_token_hash=hash_token(refresh_token),
            login_at=issued_at,
            last_active_at=issued_at,
            expires_at=issued_at + ACCESS_TOKEN_TTL,
            refresh_expires_at=issued_at + REFRESH_TOKEN_TTL,
            ip=ip,
            user_agent=user_agent,
            device=describe_device(user_agent),
        )
        await self._sessions.add(user_session)

        return user_session, IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=user_session.expires_at,
            refresh_expires_at=user_session.refresh_expires_at,
        )

    # ------------------------------------------------------------------
    # 认证（每请求热路径）
    # ------------------------------------------------------------------
    async def authenticate(
        self,
        *,
        access_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> AuthenticatedSession:
        """校验 Access Token 并返回认证上下文。

        校验顺序（每一步失败都返回**同一个** 401 文案）：

        1. 按哈希查会话 —— 查不到即无效；
        2. 会话已撤销（`10 §7` 的落地判定）；
        3. Access Token 已过期；
        4. 会话总寿命（Refresh）已过；
        5. 所属用户仍存在、未逻辑删除、状态为 ACTIVE。

        第 3、4 步合并在同一处判定，且第 4 步是**冗余保险**：
        `expires_at <= refresh_expires_at` 由 `sessions` 上的 CHECK 强制、
        且轮换时由 `rotated_access_expiry` 构造性保证，
        因此"refresh 已过期"必然蕴含"access 已过期"。
        之所以仍显式写着它，是因为**安全判定的冗余与业务判定的冗余价值不同**：
        一旦将来有人放宽或移除那条 CHECK（例如 DD-02 若改判为滑动续期），
        少写这一个 OR 就会静默地把"会话总寿命是硬上界"变成一句空话。
        删掉它能让一个用例更容易写，但代价是删掉一条安全性质 —— 不划算。

        第 5 步也不可省略：`04 §1` 只在登录时检查 status，
        但用户可能在会话存活期间被禁用 —— 若不在每次认证时复查，
        "禁用用户"将无法即时生效（`02 §5` 要求删除后普通查询不得返回）。

        Raises:
            AuthenticationError: 任一校验失败。
        """
        checked_at = now or utc_now()
        session = await self._sessions.get_by_access_token_hash(hash_token(access_token))

        if session is None:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=AuthOperator(ip=ip, user_agent=user_agent),
                resource_type="SESSION",
                reason="ACCESS_TOKEN_UNKNOWN",
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        operator = await self._operator_for(session.user_id, ip=ip, user_agent=user_agent)

        if session.revoked_at is not None:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=session.id,
                reason="SESSION_REVOKED",
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        # 两个到期检查缺一不可，理由见 docstring 第 3、4 步。
        if session.is_access_expired(checked_at) or session.is_refresh_expired(checked_at):
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=session.id,
                reason="ACCESS_TOKEN_EXPIRED",
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        user = await self._users.get(session.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=session.id,
                reason="USER_NOT_ACTIVE",
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        operator = AuthOperator.of_user(
            user_id=user.id, username=user.username, ip=ip, user_agent=user_agent
        )
        await self._sessions.touch(session, now=checked_at)
        actor = await self._actors.build(user, ip=ip, user_agent=user_agent)

        return AuthenticatedSession(session=session, user=user, actor=actor)

    # ------------------------------------------------------------------
    # 刷新轮换
    # ------------------------------------------------------------------
    async def refresh(
        self,
        *,
        refresh_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> tuple[UserSession, IssuedTokens]:
        """用 Refresh Token 换取新的令牌对（轮换 + 复用检测）。

        Raises:
            AuthenticationError: 令牌无效 / 已过期 / 会话已撤销 / 检测到复用。
        """
        checked_at = now or utc_now()
        presented_hash = hash_token(refresh_token)

        session = await self._sessions.get_by_refresh_token_hash(presented_hash)
        if session is None:
            await self._handle_unknown_refresh_token(
                presented_hash=presented_hash, ip=ip, user_agent=user_agent, now=checked_at
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        operator = await self._operator_for(session.user_id, ip=ip, user_agent=user_agent)

        if session.revoked_at is not None or session.is_refresh_expired(checked_at):
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=session.id,
                reason=(
                    "SESSION_REVOKED" if session.revoked_at is not None else "REFRESH_TOKEN_EXPIRED"
                ),
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        user = await self._users.get(session.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=session.id,
                reason="USER_NOT_ACTIVE",
            )
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        access_token = generate_token()
        new_refresh_token = generate_token()
        # 先把旧 refresh 留档再轮换：顺序不可颠倒 ——
        # 若先轮换，旧哈希就无从记录，复用检测将永久失效。
        await self._sessions.record_retired_refresh_token(
            session_id=session.id,
            token_hash=presented_hash,
            reason=RefreshTokenRetirement.ROTATED,
            retired_at=checked_at,
        )
        rotated = await self._sessions.rotate_tokens(
            session,
            access_token_hash=hash_token(access_token),
            refresh_token_hash=hash_token(new_refresh_token),
            access_expires_at=rotated_access_expiry(
                checked_at, refresh_expires_at=session.refresh_expires_at
            ),
            last_active_at=checked_at,
            ip=ip,
            user_agent=user_agent,
        )
        if not rotated:
            # 并发刷新竞争失败（DD-02 P7）：按复用处理。
            await self._revoke_for_reuse(session=session, operator=operator, now=checked_at)
            raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)

        return session, IssuedTokens(
            access_token=access_token,
            refresh_token=new_refresh_token,
            access_expires_at=session.expires_at,
            refresh_expires_at=session.refresh_expires_at,
        )

    async def _operator_for(
        self, user_id: int, *, ip: str | None, user_agent: str | None
    ) -> AuthOperator:
        """构造尽量完整的审计操作者（能取到用户名就带上）。

        用户名不是敏感项（`10 §4` 只禁止记录口令 / 哈希 / 令牌明文 / MFA Secret），
        而带上它能让安全日志不必再回查一次用户表 —— 取证时这一点很关键。
        """
        user = await self._users.get(user_id)
        if user is None:
            return AuthOperator(user_id=user_id, ip=ip, user_agent=user_agent)
        return AuthOperator.of_user(
            user_id=user.id, username=user.username, ip=ip, user_agent=user_agent
        )

    async def _handle_unknown_refresh_token(
        self,
        *,
        presented_hash: str,
        ip: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> None:
        """处理"当前令牌表里查不到"的 Refresh Token。

        这是区分**盗用**与**普通无效令牌**的唯一分支点：

        - 命中 `ROTATED` 记录 → 曾合法、已被轮换取代 → 盗用信号；
        - 命中 `SESSION_REVOKED` 记录 → 所属会话已撤销 → 普通失败；
        - 完全没有记录 → 普通失败。
        """
        retired = await self._sessions.get_retired_refresh_token(presented_hash)
        if retired is None:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=AuthOperator(ip=ip, user_agent=user_agent),
                resource_type="SESSION",
                reason="REFRESH_TOKEN_UNKNOWN",
            )
            return

        session = await self._sessions.get(retired.session_id)
        operator = await self._operator_for(retired.session_id, ip=ip, user_agent=user_agent)

        if retired.reason is not RefreshTokenRetirement.ROTATED:
            # 会话早已被撤销，令牌随之失效 —— 这是正常的失败，不误报盗用。
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=retired.session_id,
                reason="REFRESH_TOKEN_SESSION_REVOKED",
            )
            return

        if session is None:  # pragma: no cover - 外键 RESTRICT 保证不会发生
            return

        if session.revoked_at is not None:
            # 会话已在别处被撤销：无需重复撤销，也不必告警（避免噪声掩盖真信号）。
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type="SESSION",
                resource_id=session.id,
                reason="REFRESH_TOKEN_AFTER_REVOKE",
            )
            return

        await self._revoke_for_reuse(session=session, operator=operator, now=now)

    async def _revoke_for_reuse(
        self,
        *,
        session: UserSession,
        operator: AuthOperator,
        now: datetime,
    ) -> None:
        """检测到 Refresh Token 复用 → 撤销该会话的**全部**令牌（family revocation）。

        撤销的是会话本身（access + refresh 同时失效），
        这正是 DD-02 P4 的语义：一旦怀疑令牌泄漏，
        不能只作废那一个 refresh —— 攻击者可能已经用旧 refresh 换到了新的 access。
        """
        revoked = await self._sessions.revoke(
            session, reason=SessionRevokeReason.TOKEN_REUSE_DETECTED, now=now
        )
        if revoked:
            await self._sessions.record_retired_refresh_token(
                session_id=session.id,
                token_hash=session.refresh_token_hash,
                reason=RefreshTokenRetirement.SESSION_REVOKED,
                retired_at=now,
            )
        self._audit.failure(
            action=AuditAction.AUTH_TOKEN_REUSE_DETECTED,
            operator=operator,
            resource_type="SESSION",
            resource_id=session.id,
            reason="REFRESH_TOKEN_REUSE",
            error_code=int(AuthenticationError.code),
        )

    # ------------------------------------------------------------------
    # 撤销
    # ------------------------------------------------------------------
    async def revoke(
        self,
        session: UserSession,
        *,
        reason: SessionRevokeReason,
        now: datetime | None = None,
    ) -> bool:
        """撤销指定会话（幂等）。

        实现委托给 `SessionRepository.revoke_and_retire` ——
        "会话终结"（置撤销标记 + 留档 refresh 哈希）全系统只有那一处实现，
        因此**本人登出**与**管理员踢下线**对令牌与取证线索的影响完全一致。

        Returns:
            True = 本次调用真正撤销了它；False = 它此前已撤销。
            两种情况下 `10 §7` 都成立（令牌都已不可用），
            因此调用方应把两者都视为成功（DD-11 方案 A：语义幂等）。
        """
        return await self._sessions.revoke_and_retire(session, reason=reason, now=now or utc_now())

    async def logout(
        self,
        *,
        access_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """登出（撤销当前会话）。

        DD-11 方案 A 的**语义幂等**：令牌无效 / 会话已撤销时**不报 401**，
        直接视为成功。理由：登出的意图是"让我退出"，
        而该意图在"会话早已失效"时已经达成；
        返回 401 只会让客户端把一次成功的登出当成错误，
        进而重试或弹出无意义提示。

        注意这与"未认证请求"不同：本方法由端点调用，
        端点已经（通过宽松依赖）确认调用者持有有效会话；
        此处只覆盖"会话在登出前恰好过期/被撤销"的竞态。

        Returns:
            True = 本次调用真正撤销了会话；False = 会话此前已失效。
        """
        checked_at = now or utc_now()
        session = await self._sessions.get_by_access_token_hash(hash_token(access_token))
        if session is None:
            return False

        operator = await self._operator_for(session.user_id, ip=ip, user_agent=user_agent)
        revoked = await self.revoke(session, reason=SessionRevokeReason.LOGOUT, now=checked_at)
        self._audit.success(
            action=AuditAction.AUTH_LOGOUT,
            operator=operator,
            resource_type="SESSION",
            resource_id=session.id,
            after={"already_revoked": not revoked},
        )
        return revoked


__all__ = ["AuthenticatedSession", "IssuedTokens", "SessionService"]
