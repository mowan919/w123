"""认证服务：登录 / 登出 / 刷新 / 当前用户 / 本人改密（Phase 4）。

Frozen 依据
-----------
Spec `04 §1` 登录流程（顺序即本文件的执行顺序）：

```text
username/password → user lookup → status check → lock check → password verify
→ MFA check → create session → issue token → audit/security log → response
```

Spec `04 §2` / `00 §2` 密码策略：>=12 / 四类字符 / 最近 5 个不重复 /
90 天 / 连续 5 次失败锁 30 分钟 / 管理员重置后首次登录强制改密。

Spec `10 §5`：登录失败信息**不得泄露用户是否存在等不必要信息**。

Spec `10 §4`：不得记录 password / password hash / token 明文。

失败文案的统一（`10 §5` 的落地方式）
----------------------------------
对外一律 `_INVALID_CREDENTIALS_MESSAGE`，覆盖四种内部原因：

| 内部原因 | 对外文案 |
|---|---|
| 用户不存在 | 用户名或密码错误 |
| 口令错误 | 用户名或密码错误 |
| 账号被锁定 | 用户名或密码错误 |
| 账号被禁用 | 用户名或密码错误 |

若按原因给出不同文案，攻击者就能用"文案差异"批量探测
哪些用户名真实存在（user enumeration）。内部原因只写入审计
（`AuthAudit.failure(reason=...)`），供运维诊断 —— 这才是它该在的地方。

关于锁定计数的两个刻意选择（已在决策台账登记）
-------------------------------------------
1. **`status` 不因锁定而改为 `LOCKED`**：锁定语义完全由 `locked_until` 表达。
   理由：`locked_until` 到期即自动解锁（无需后台任务），
   若同时改 `status`，到期后 `status` 仍停留在 LOCKED，
   账号会被**永久锁死**；而"到期后自动清 status"又需要一个后台任务，
   等于为了一个可计算的字段引入作业依赖。
   `02 §3` 允许 `LOCKED` 状态存在（供管理员手工设置），
   与"自动锁定用 `locked_until`"并不冲突。
2. **达到阈值后不清零计数，只设 `locked_until`**（人类已批准）：
   "consecutive failures"的语义要求**登录成功**才清零。
   若解锁时清零，攻击者只需等到锁定期结束就能立刻再获得 5 次尝试。
   代价是"锁定期过后再错一次即再次锁定"，属可接受的保守取向。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, AuditResult, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import AuthenticationError, ConfigurationError
from app.core.security.password import (
    LOCKOUT_DURATION,
    MAX_FAILED_LOGIN_ATTEMPTS,
    get_password_hasher,
    is_password_expired,
)
from app.db.base import utc_now
from app.models.enums import UserStatus
from app.models.session import UserSession
from app.models.user import AdminUser
from app.repositories.user import UserRepository
from app.services.auth_audit import AuthAudit, AuthOperator
from app.services.mfa import MfaService
from app.services.mfa_management import MfaManagementService
from app.services.session import IssuedTokens, SessionService
from app.services.user import UserService

#: 对外统一的登录失败文案（Spec `10 §5`，见模块 docstring）。
_INVALID_CREDENTIALS_MESSAGE = "用户名或密码错误"

#: 认证审计使用的资源类型。
_AUTH_RESOURCE = "AUTH"
_SESSION_RESOURCE = "SESSION"


@dataclass(frozen=True, slots=True)
class LoginResult:
    """一次成功登录的结果。

    `must_change_password` 为 True 时，客户端**必须**先调用本人改密接口；
    服务端侧由 `app.api.deps.get_current_actor` 强制拦截其他受保护请求
    （否则该标志只是装饰，见 `docs/DESIGN-DECISIONS.md` INTERIM-4-02）。

    `mfa_setup_required` 表示"策略要求二次验证，但该用户尚未完成绑定"。
    此时登录**不被阻断**（见 `login` 第 6c 步的注释）：阻断会形成死锁，
    因为绑定本身需要一个已认证的会话。
    """

    user: AdminUser
    session: UserSession
    tokens: IssuedTokens
    must_change_password: bool
    mfa_setup_required: bool = False


@dataclass(frozen=True, slots=True)
class MfaPendingResult:
    """口令已通过、二次验证未完成的中间态（DD-23 方案 A）。

    此时**没有 Session、没有令牌** —— 只有一个一次性挑战令牌。
    客户端必须带上它调用 `POST /auth/mfa/verify` 才能完成登录。

    为什么不给任何可用的 access token：给了就等于承认"第一因素已足够"，
    之后要求二次验证只是礼貌性询问。
    """

    mfa_token: str
    expires_at: datetime
    provider: str


class AuthService:
    """认证业务服务。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditRecorder | None = None,
        mfa: MfaService | None = None,
        mfa_management: MfaManagementService | None = None,
    ) -> None:
        self._session = session
        self._recorder: AuditRecorder = audit or NullAuditRecorder()
        self._audit = AuthAudit(self._recorder)
        self._users = UserRepository(session)
        self._sessions = SessionService(session, audit=self._recorder)
        self._mfa = mfa or MfaService()
        self._mfa_management = mfa_management or MfaManagementService(session, audit=self._recorder)
        # 本人改密复用 Phase 2 的实现（口令策略、历史 5 条、审计口径都只此一份）。
        self._user_service = UserService(session, audit=self._recorder)

    # ------------------------------------------------------------------
    # 登录（Spec 04 §1 的九个步骤）
    # ------------------------------------------------------------------
    async def login(
        self,
        *,
        username: str,
        password: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> LoginResult | MfaPendingResult:
        """执行登录流程。

        Returns:
            `LoginResult`：登录完成（已签发会话与令牌）；
            `MfaPendingResult`：口令已通过，但还需要二次验证（DD-23 方案 A）。

        Raises:
            AuthenticationError: 任一环节失败（对外文案统一，见模块 docstring）。
        """
        checked_at = now or utc_now()

        # ---- 1. user lookup -------------------------------------------
        user = await self._users.get_by_username(username)
        if user is None:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=AuthOperator(username=username, ip=ip, user_agent=user_agent),
                resource_type=_AUTH_RESOURCE,
                reason="UNKNOWN_USER",
                error_code=int(AuthenticationError.code),
            )
            raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE)

        operator = AuthOperator.of_user(
            user_id=user.id, username=user.username, ip=ip, user_agent=user_agent
        )

        # ---- 2. status check -----------------------------------------
        if user.status is not UserStatus.ACTIVE:
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type=_AUTH_RESOURCE,
                reason=f"STATUS_{user.status.value}",
                error_code=int(AuthenticationError.code),
            )
            raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE)

        # ---- 3. lock check -------------------------------------------
        # 锁定期已过时**就地解锁**（惰性解锁，无需后台任务）；
        # 计数刻意保留，理由见模块 docstring。
        if user.locked_until is not None:
            if user.locked_until > checked_at:
                self._audit.failure(
                    action=AuditAction.AUTH_LOGIN_FAILURE,
                    operator=operator,
                    resource_type=_AUTH_RESOURCE,
                    reason="LOCKED",
                    error_code=int(AuthenticationError.code),
                )
                raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE)
            user.locked_until = None
            await self._session.flush()

        # ---- 4. password verify --------------------------------------
        if not get_password_hasher().verify(password, user.password_hash):
            locked = await self._register_login_failure(user, now=checked_at)
            self._audit.failure(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                operator=operator,
                resource_type=_AUTH_RESOURCE,
                reason="LOCKOUT_TRIGGERED" if locked else "BAD_PASSWORD",
                error_code=int(AuthenticationError.code),
            )
            if locked:
                # 锁定是独立的安全事件（`04 §8` 单列），必须单独可检索：
                # 只记"登录失败"会让"账号正在被暴力破解"淹没在失败噪声里。
                self._audit.record(
                    action=AuditAction.AUTH_LOCKOUT,
                    operator=operator,
                    resource_type=_AUTH_RESOURCE,
                    result=AuditResult.FAILURE,
                    reason="MAX_FAILED_ATTEMPTS",
                    after={
                        "failed_login_count": user.failed_login_count,
                        "locked_until": user.locked_until.isoformat()
                        if user.locked_until
                        else None,
                    },
                )
            raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE)

        # ---- 5. 凭据正确 → 清零失败计数 --------------------------------
        # "consecutive" 语义要求成功即清零（`04 §2`）。
        user.failed_login_count = 0
        user.locked_until = None

        # ---- 6. MFA check（Spec 04 §1 第 6 步 / DD-01 方案 A） --------
        # 位置必须在"口令已验证"之后、"签发令牌"之前：
        # 若放在口令之前，攻击者无需口令即可触发 MFA 流程；
        # 若放在签发之后，就会先给出可用令牌再要求二次验证 —— 保护形同虚设。
        #
        # Phase 4 的 `MfaService.check_login` 只回答"策略要不要 + Provider 有没有"，
        # 策略要求却无可用 Provider 时它 **fail-closed**（抛 ConfigurationError）。
        # 该行为保持不变，此处不另造分支。
        await self._mfa.check_login(user_id=user.id)

        # 6b. 该用户**已绑定**二次验证 → 停下来，签发挑战（DD-23 方案 A）。
        #
        # 注意判定依据是"是否已绑定"而不是"策略是否要求"：
        #   已启用 ⇒ 必须验（启用的意义就在于此，与策略无关）；
        #   策略要求但未绑定 ⇒ 见下方 6c。
        # 若反过来只看策略，那么"用户自己开了 MFA、策略却没要求"时
        # 二次验证会被跳过 —— 启用按钮就变成了装饰。
        credential = await self._mfa_management.enabled_credential(user_id=user.id)
        if credential is not None:
            provider_name = self._mfa_management.active_provider_name()
            if provider_name is None:  # 理论上不可达：有凭据 ⇒ 有 Provider
                raise ConfigurationError("MFA 凭据存在，但当前没有可用的 Provider")
            issued = await self._mfa_management.issue_challenge(
                user_id=user.id, provider_name=provider_name, now=checked_at
            )
            # 挑战签发**不单独产生审计事件**：`04 §8` 的安全日志清单只有
            # MFA setup / enable / disable / failure 四类，新增动作属于扩展 Spec，
            # 因此这里保持沉默；真正需要留痕的是随后可能发生的 `MFA_FAILURE`，
            # 以及在挑战成功核销时由 `complete_mfa_login` 记录的登录成功事件。
            # （登记为 FINDING-MFA，便于后续裁定是否补这个事件。）
            #
            # 关键：**不创建 Session**。口令通过只代表"第一因素正确"，
            # 此时若建会话，只输对密码的人会出现在在线用户列表里（DD-23 方案 A）。
            return MfaPendingResult(
                mfa_token=issued.token,
                expires_at=issued.expires_at,
                provider=issued.provider,
            )

        # 6c. 策略要求 MFA，但用户尚未完成绑定。
        #
        # 这里**不阻断登录**：绑定（`POST /auth/mfa/setup`）需要一个已认证的会话，
        # 若在此拒绝，用户就永远走不到绑定那一步 —— 那是死锁，不是安全。
        # 因此放行并在结果里如实标记，由客户端引导用户去绑定。
        # 该取舍登记为 JUDGMENT-MFA-01（Spec 未规定未绑定时的处置）。
        requirement = await self._mfa_management.requirement_for(user_id=user.id)
        setup_required = requirement.required

        # ---- 7. 口令到期 → 强制改密（DD-02 P8） ------------------------
        password_expired = is_password_expired(user.password_changed_at, now=checked_at)
        if password_expired:
            user.must_change_password = True
        await self._session.flush()

        # ---- 8. create session → issue token -------------------------
        user_session, tokens = await self._sessions.create(
            user=user, ip=ip, user_agent=user_agent, now=checked_at
        )

        # ---- 9. audit / security log --------------------------------
        self._audit.success(
            action=AuditAction.AUTH_LOGIN_SUCCESS,
            operator=operator,
            resource_type=_SESSION_RESOURCE,
            resource_id=user_session.id,
            after={
                "must_change_password": user.must_change_password,
                "password_expired": password_expired,
                "mfa_setup_required": setup_required,
            },
        )

        return LoginResult(
            user=user,
            session=user_session,
            tokens=tokens,
            must_change_password=user.must_change_password,
            mfa_setup_required=setup_required,
        )

    async def complete_mfa_login(
        self,
        *,
        mfa_token: str,
        code: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> LoginResult:
        """核销 MFA 挑战并**续完登录**（DD-23 方案 A 的另一半）。

        口令已在 `login` 的第 1~5 步验证过（挑战就是这个事实的凭证），
        因此这里不需要、也不应该再收一次密码 —— 重收等于把密码的暴露面
        再放大一次。此处只完成 `04 §1` 的第 7~9 步。

        Raises:
            MfaChallengeInvalidError / MfaCodeRejectedError: 挑战或动态码不通过。
            AuthenticationError: 该用户在挑战签发后已被禁用 / 删除。
        """
        checked_at = now or utc_now()
        user_id = await self._mfa_management.redeem_challenge(
            token=mfa_token, code=code, now=checked_at
        )
        user = await self._users.get(user_id)
        if user is None or user.status is not UserStatus.ACTIVE or user.deleted_at:
            # 挑战签发后账号被处置过 —— 不能因为"曾经验过一次"就放行。
            raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE)

        password_expired = is_password_expired(user.password_changed_at, now=checked_at)
        if password_expired:
            user.must_change_password = True
        await self._session.flush()

        user_session, tokens = await self._sessions.create(
            user=user, ip=ip, user_agent=user_agent, now=checked_at
        )
        self._audit.success(
            action=AuditAction.AUTH_LOGIN_SUCCESS,
            operator=AuthOperator.of_user(
                user_id=user.id, username=user.username, ip=ip, user_agent=user_agent
            ),
            resource_type=_SESSION_RESOURCE,
            resource_id=user_session.id,
            after={
                "must_change_password": user.must_change_password,
                "password_expired": password_expired,
                "via": "MFA_CHALLENGE",
            },
        )
        return LoginResult(
            user=user,
            session=user_session,
            tokens=tokens,
            must_change_password=user.must_change_password,
            mfa_setup_required=False,
        )

    async def _register_login_failure(self, user: AdminUser, *, now: datetime) -> bool:
        """累加连续失败次数，达到阈值则上锁。

        Returns:
            True = 本次失败触发了锁定。
        """
        user.failed_login_count += 1
        locked = user.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS
        if locked:
            user.locked_until = now + LOCKOUT_DURATION
        await self._session.flush()
        return locked

    # ------------------------------------------------------------------
    # 登出 / 刷新（委托 SessionService，保持单一实现）
    # ------------------------------------------------------------------
    async def logout(
        self,
        *,
        access_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """登出（语义幂等，见 `SessionService.logout`）。"""
        return await self._sessions.logout(
            access_token=access_token, ip=ip, user_agent=user_agent, now=now
        )

    async def refresh(
        self,
        *,
        refresh_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> tuple[UserSession, IssuedTokens]:
        """刷新令牌（轮换 + 复用检测，见 `SessionService.refresh`）。"""
        return await self._sessions.refresh(
            refresh_token=refresh_token, ip=ip, user_agent=user_agent, now=now
        )

    # ------------------------------------------------------------------
    # 当前用户 / 本人改密
    # ------------------------------------------------------------------
    async def me(self, *, actor: CurrentActor) -> AdminUser:
        """返回当前操作者的用户记录。

        已由依赖层完成认证，因此此处只需按 `actor.user_id` 读取；
        仍做一次存在性检查（会话存活期间账号可能被逻辑删除），
        以避免返回一个"已被删除但仍持有令牌"的账号。

        Raises:
            AuthenticationError: 用户已不存在（统一 401，不暴露细节）。
        """
        user = await self._users.get(actor.user_id)
        if user is None:
            raise AuthenticationError("认证失败或登录状态已失效")
        return user

    async def change_own_password(
        self,
        *,
        actor: CurrentActor,
        current_password: str,
        new_password: str,
    ) -> AdminUser:
        """本人改密（`04 §2`"forced password change" 的解除路径）。

        直接委托 `UserService.change_own_password` —— 该方法在 Phase 2 交付时
        就明确"HTTP 端点属 Phase 4"，其内部已包含：

        - 目标恒为 `actor.user_id`（签名上消除 IDOR）；
        - 先校验当前口令；
        - 新口令受"最近 5 个不重复"约束；
        - 成功后 `must_change_password = False`；
        - 审计 `USER_CHANGE_PASSWORD`（对应 `04 §8` 的 password change）。

        本方法**不复写**任何上述逻辑：口令策略与历史校验只允许有一份实现，
        否则两处规则必然漂移（Phase 3 已经吃过"两份真相"的教训）。
        """
        return await self._user_service.change_own_password(
            actor=actor, current_password=current_password, new_password=new_password
        )


__all__ = ["AuthService", "LoginResult"]
