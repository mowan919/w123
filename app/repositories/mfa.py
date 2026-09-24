"""MFA 策略 / 凭据 / 挑战的数据访问层（DD-24 方案 A）。

本模块只做数据访问，**不含**任何具体算法：
V1 Provider 未冻结（`00 §4` / `16 §1`），因此这里出现的最多只是
"某个 Provider 的名字"，没有任何 TOTP / WebAuthn / SMS 相关逻辑。

多角色策略的合并口径
--------------------
一个用户可能有多个角色。`04 §7` 只规定了"**层级间**"的优先级
（`user > role > system`），没有规定"**同一层级内**多个角色之间"怎么合并。

本实现取：**任一角色要求 ⇒ 要求**（OR）；全部角色都未表态 ⇒ 返回 `None`。

理由不是偏好，而是看另一端会导致什么：若取"某个角色明确不要求 ⇒ 不要求"，
那么同时持有「要求 MFA 的高敏角色」和「明确不要求的普通角色」的用户，
会因为后者而**静默地**失去二次验证。这是一次安全弱化，
而使用者完全不会察觉 —— 项目规则禁止自行弱化已有安全要求，因此只有 OR 可写。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.token import hash_token
from app.models.enums import MfaPolicySubject, MfaStatus
from app.models.mfa import MfaChallenge, MfaPolicy, UserMfa


class MfaRepository:
    """MFA 三张表的仓储。生命周期与提交边界由服务层掌握。"""

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 凭据（user_mfa）
    # ------------------------------------------------------------------

    async def get_credential(self, *, user_id: int, provider: str) -> UserMfa | None:
        """按 (user_id, provider) 取凭据；不存在返回 None（不抛异常）。"""
        stmt = select(UserMfa).where(UserMfa.user_id == user_id, UserMfa.provider == provider)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def ensure_credential(self, *, user_id: int, provider: str) -> UserMfa:
        """取凭据，不存在则创建一条 `DISABLED` 占位行。

        为什么需要"占位行"：生命周期 `DISABLED → SETUP → ENABLED` 需要一个
        稳定载体。若启用/禁用时反复新建行，会在 `(user_id, provider)`
        唯一键上不停冲突，而"哪一行才是最新的"也会变成第二个真相。
        """
        existing = await self.get_credential(user_id=user_id, provider=provider)
        if existing is not None:
            return existing
        row = UserMfa(user_id=user_id, provider=provider, status=MfaStatus.DISABLED)
        self._session.add(row)
        await self._session.flush()
        return row

    async def apply_status(self, row: UserMfa, status: MfaStatus, *, now: datetime) -> UserMfa:
        """切换生命周期状态，并按语义补写对应时间戳。

        时间戳的写入规则刻意**不对称**：

        - 进入 `SETUP`：写 `setup_at`，并清空 `enabled_at`
          （重新配网意味着旧的启用事实不再成立）；
        - 进入 `ENABLED`：写 `enabled_at`；
        - 进入 `DISABLED`：清空 `enabled_at` **与**密文 ——
          禁用后系统里不该继续留着一份可还原 Secret 的密文，
          它已不使用，留着就是纯泄漏面。

        `verified_at` 不在本方法内动，由 `mark_verified` 单独更新。
        """
        row.status = status
        if status is MfaStatus.SETUP:
            row.setup_at = now
            row.enabled_at = None
        elif status is MfaStatus.ENABLED:
            row.enabled_at = now
        else:
            row.enabled_at = None
            row.encrypted_secret = None
        self._session.add(row)
        await self._session.flush()
        return row

    async def put_secret(self, row: UserMfa, *, encrypted_secret: str) -> UserMfa:
        """写入密文。入参必须是**已加密**的串 —— 本方法不再替调用方加密。

        为什么不由仓储负责加密：加密需要 AAD（绑定 user_id + provider），
        其正确性依赖调用上下文。把"是否已加密"藏进仓储后，
        "某处忘了加密"会变成运行时才炸、且看不出原因的问题。
        """
        row.encrypted_secret = encrypted_secret
        self._session.add(row)
        await self._session.flush()
        return row

    async def mark_verified(self, row: UserMfa, *, now: datetime) -> UserMfa:
        """记录最近一次校验成功的时间。"""
        row.verified_at = now
        self._session.add(row)
        await self._session.flush()
        return row

    # ------------------------------------------------------------------
    # 策略（mfa_policies）
    # ------------------------------------------------------------------

    async def get_policy(
        self, *, subject_type: MfaPolicySubject, subject_id: int
    ) -> MfaPolicy | None:
        """取某主体的策略行；不存在返回 None。"""
        stmt = select(MfaPolicy).where(
            MfaPolicy.subject_type == subject_type, MfaPolicy.subject_id == subject_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_policy_required(self, *, user_id: int) -> bool | None:
        """用户级策略取值。`None` = 未表态（**不等于** False）。"""
        row = await self.get_policy(subject_type=MfaPolicySubject.USER, subject_id=user_id)
        return None if row is None else row.required

    async def get_role_policy_required(self, *, role_ids: Sequence[int]) -> bool | None:
        """由一组角色合并出的策略取值（OR）。

        Returns:
            `None`：没有任何角色表态，交由下一层（system）决定；
            `bool`：至少一个角色明确表态时的合并结果。

        """
        if not role_ids:
            return None
        stmt = select(MfaPolicy.required).where(
            MfaPolicy.subject_type == MfaPolicySubject.ROLE,
            MfaPolicy.subject_id.in_(role_ids),
        )
        rows = list((await self._session.execute(stmt)).scalars())
        if not rows:
            return None
        stated = [value for value in rows if value is not None]
        if not stated:
            return None
        return any(stated)

    async def set_policy(
        self, *, subject_type: MfaPolicySubject, subject_id: int, required: bool | None
    ) -> MfaPolicy:
        """写入 / 覆盖策略。`required=None` = 该层行存在但明确弃权。"""
        row = await self.get_policy(subject_type=subject_type, subject_id=subject_id)
        if row is None:
            row = MfaPolicy(subject_type=subject_type, subject_id=subject_id)
        row.required = required
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_policy(self, *, subject_type: MfaPolicySubject, subject_id: int) -> bool:
        """删除策略行（回到"完全未表态"）。返回是否真的删掉了东西。

        用 `RETURNING id` 统计删除行数，而不是 `CursorResult.rowcount`：
        `AsyncSession.execute` 声明返回基类 `Result`，`rowcount` 只存在于
        `CursorResult`（与 `permission.py` / `user.py` 同样的 mypy --strict 处理）。
        """
        stmt = (
            delete(MfaPolicy)
            .where(
                MfaPolicy.subject_type == subject_type,
                MfaPolicy.subject_id == subject_id,
            )
            .returning(MfaPolicy.id)
        )
        rows = list((await self._session.execute(stmt)).scalars())
        return bool(rows)

    # ------------------------------------------------------------------
    # 挑战（mfa_challenges）
    # ------------------------------------------------------------------

    async def create_challenge(
        self, *, user_id: int, provider: str, token: str, expires_at: datetime
    ) -> MfaChallenge:
        """落一条挑战记录，库内**只存令牌哈希**。

        明文令牌由调用方生成并持有（用于回给客户端）；本方法不返回它，
        以避免"返回值里有明文"这件事被后续代码无意传播。
        """
        row = MfaChallenge(
            user_id=user_id,
            provider=provider,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_challenge_by_token(self, token: str) -> MfaChallenge | None:
        """按**明文**令牌查挑战（内部先哈希再比对）。

        库中只有哈希，因此只能按哈希命中 ——
        这正是 `uq_mfa_challenges_token_hash` 必须唯一的原因。
        """
        stmt = select(MfaChallenge).where(MfaChallenge.token_hash == hash_token(token))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def record_failed_attempt(self, row: MfaChallenge) -> MfaChallenge:
        """累计一次失败尝试。**是否因此作废由服务层判定**（阈值在服务层）。"""
        row.attempts += 1
        self._session.add(row)
        await self._session.flush()
        return row

    async def consume_challenge(self, row: MfaChallenge, *, now: datetime) -> MfaChallenge:
        """核销挑战（成功，或达到失败上限后）。

        幂等：已核销的行再次调用**不会**改写 `consumed_at`。
        并发提交同一个令牌时，第二个请求不应把第一个的核销时间改掉 ——
        那是改写取证事实。
        """
        if row.consumed_at is None:
            row.consumed_at = now
            self._session.add(row)
            await self._session.flush()
        return row


__all__ = ["MfaRepository"]
