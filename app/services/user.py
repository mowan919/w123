"""用户服务。

Frozen / 已裁定依据
------------------
- Spec `02 §2` 用户字段；`02 §3` 状态 ACTIVE / DISABLED / LOCKED。
- Spec `02 §4` 多角色（本 Phase 只做关联，权限并集计算属后续 Phase）。
- Spec `02 §5` 删除 = disable + logical delete，删除后普通查询不得返回。
- Spec `02 §6` 部门管理员只能管理范围内的用户。
- Spec `00 §2` 密码策略（12+、四类字符、最近 5 个不重复、重置后强制改密）。
- Spec `08 §4` 用户端点；人类裁定补齐 `POST /users/{id}/delete`
  与 `GET|PUT /users/{id}/roles`。
- Spec `10 §3` / `§10`：服务端二次校验 + DB 层范围约束。
- Spec `07 §2`：API JSON 中 BIGINT ID 为字符串（在 schema 层完成）。

关键安全行为
-----------
1. 目标用户与目标部门**都**必须落在操作者数据范围内，
   因此"修改 `department_id` 把用户挪出自己的范围"这条路走不通；
2. `update` 不接受 `status` 变更：禁用/启用必须走专门操作，
   以保证 USER_DISABLE / USER_ENABLE 审计不可被绕过；
3. 密码只以 argon2id 哈希落库；历史密码仅存哈希且保留最近 5 条；
4. 越权尝试一律写审计 FAILURE 记录。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditEvent, AuditRecorder, AuditResult, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.masking import mask_email, mask_phone
from app.core.scope import ResolvedScope
from app.core.security.password import (
    PASSWORD_HISTORY_SIZE,
    get_password_hasher,
    validate_password_policy,
)
from app.db.base import utc_now
from app.models.enums import UserStatus
from app.models.role import Role
from app.models.user import AdminUser
from app.repositories.department import DepartmentRepository
from app.repositories.permission import PermissionVersionRepository
from app.repositories.role import RoleRepository
from app.repositories.user import UserRepository
from app.services.authorization import AuthorizationService
from app.services.data_scope import DataScopeResolver


class _Unset:
    """哨兵类型：区分"未提供该字段"与"显式置为 None"。"""

    __slots__ = ()


_UNSET: Final = _Unset()


@dataclass(frozen=True, slots=True)
class UserPage:
    """用户分页结果（领域对象）。

    分页协议由人类裁定：请求 `pageNum` + `pageSize`；
    响应 `{list, total, pageNum, pageSize}`。
    """

    items: list[AdminUser]
    total: int
    page_num: int
    page_size: int


def _masked(value: str | None, masker: Callable[[str], str]) -> str | None:
    """对可选的敏感字段做脱敏；空值保持为空。"""
    return masker(value) if value else None


def _snapshot(user: AdminUser) -> dict[str, Any]:
    """生成审计用快照。

    绝不包含 `password_hash`（Spec `10 §4`）；
    手机号 / 邮箱按 `00 §8` 脱敏后再进入审计。
    """
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "department_id": user.department_id,
        "status": user.status.value if user.status is not None else None,
        "phone": _masked(user.phone, mask_phone),
        "email": _masked(user.email, mask_email),
        "must_change_password": user.must_change_password,
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
    }


class UserService:
    """用户业务服务。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._roles = RoleRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._departments = DepartmentRepository(session)
        self._scope = DataScopeResolver(self._departments)
        self._authz = AuthorizationService(session)
        self._audit = audit or NullAuditRecorder()

    # ------------------------------------------------------------------
    # 审计
    # ------------------------------------------------------------------
    def _record(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        result: AuditResult = AuditResult.SUCCESS,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        error_code: int | None = None,
    ) -> None:
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type="USER",
                resource_id=resource_id,
                operator_id=actor.user_id,
                operator_username=actor.username,
                result=result,
                before_data=before,
                after_data=after,
                error_code=error_code,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        )

    def _record_denied(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        error_code: int,
    ) -> None:
        self._record(
            actor=actor,
            action=action,
            resource_id=resource_id,
            result=AuditResult.FAILURE,
            error_code=error_code,
        )

    @contextmanager
    def _denial_audited(
        self, *, actor: CurrentActor, action: AuditAction, resource_id: int | None
    ) -> Iterator[None]:
        """把"越权 / 安全不变量拒绝"统一写成 FAILURE 审计（FIX-002）。

        约束：**权限拒绝不能因为异常提前返回而绕过 Audit。**
        因此所有范围校验、授权校验、安全不变量校验都必须包在本守卫内，
        而不是各自散落 try/except —— 散落写法必然漏掉某条路径。

        捕获 `PermissionDeniedError`（403 越权）与 `ConflictError`（409
        安全不变量，如"最后一个 SUPER_ADMIN"）两类拒绝，
        并按异常自带的 `code` 落 `error_code`，与响应体保持一致。
        """
        try:
            yield
        except (PermissionDeniedError, ConflictError) as exc:
            self._record_denied(
                actor=actor,
                action=action,
                resource_id=resource_id,
                error_code=exc.code,
            )
            raise

    # ------------------------------------------------------------------
    # 内部：范围 + 授权
    # ------------------------------------------------------------------
    async def _load_target(
        self, *, actor: CurrentActor, user_id: int
    ) -> tuple[AdminUser, ResolvedScope]:
        """读取目标用户并完成范围校验（越权尝试留痕）。"""
        scope = await self._scope.resolve(actor)
        user = await self._users.get(user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        if not scope.restrict_to_actor and not scope.is_unrestricted_departments:
            if user.department_id is None or not scope.allows_department(user.department_id):
                raise PermissionDeniedError("用户不在当前数据范围内")
        elif scope.restrict_to_actor and user.id != actor.user_id:
            raise PermissionDeniedError("用户不在当前数据范围内")

        return user, scope

    async def _load_manageable_target(
        self, *, actor: CurrentActor, user_id: int, action: AuditAction
    ) -> tuple[AdminUser, ResolvedScope]:
        """**管理目标**的唯一入口：读取目标 + 范围校验 + 可管理性校验。

        所有以"某个已存在用户"为目标的写操作（update / disable / enable /
        delete / reset-password / assign-roles）都必须经由此入口，
        不得各自实现范围判断，否则必然出现漏审计的路径。

        任何一步越权（含"非 SUPER_ADMIN 操作 SUPER_ADMIN"）都会写
        FAILURE 审计后抛出 `PermissionDeniedError`，保证越权尝试一律留痕。
        """
        with self._denial_audited(actor=actor, action=action, resource_id=user_id):
            user, scope = await self._load_target(actor=actor, user_id=user_id)
            await self._authz.assert_can_manage_user(actor=actor, target=user)
        return user, scope

    async def _assert_department_in_scope(
        self, *, scope: ResolvedScope, department_id: int | None
    ) -> None:
        """校验目标部门是否在范围内（防止改 department_id 绕行）。"""
        if department_id is None:
            if not scope.is_unrestricted_departments:
                raise PermissionDeniedError("非全局数据范围不允许把用户移出部门")
            return
        if not scope.allows_department(department_id):
            raise PermissionDeniedError("目标部门不在当前数据范围内")
        if await self._departments.get(department_id) is None:
            raise NotFoundError("目标部门不存在")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get(self, *, actor: CurrentActor, user_id: int) -> AdminUser:
        """按 ID 读取用户（含范围校验）。

        读取同样属于"数据范围越权"的探测面，因此拒绝也要留痕
        （FIX-002：拒绝不得因提前 raise 而绕过审计）。
        """
        with self._denial_audited(actor=actor, action=AuditAction.USER_READ, resource_id=user_id):
            user, _ = await self._load_target(actor=actor, user_id=user_id)
        return user

    async def list_users(
        self,
        *,
        actor: CurrentActor,
        page_num: int = 1,
        page_size: int = 20,
        department_id: int | None = None,
        status: UserStatus | None = None,
        keyword: str | None = None,
    ) -> UserPage:
        """分页列出范围内用户。

        `department_id` 过滤与数据范围取交集，
        因此传入范围外的部门 ID 会得到空结果而非越权数据。
        """
        if page_num < 1:
            raise BadRequestError("pageNum 必须大于等于 1")
        if not 1 <= page_size <= 100:
            raise BadRequestError("pageSize 必须在 1..100 之间")

        scope = await self._scope.resolve(actor)
        items = await self._users.list_in_scope(
            scope,
            page_num=page_num,
            page_size=page_size,
            department_id=department_id,
            status=status,
            keyword=keyword,
        )
        total = await self._users.count_in_scope(
            scope, department_id=department_id, status=status, keyword=keyword
        )
        return UserPage(items=items, total=total, page_num=page_num, page_size=page_size)

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    async def create(
        self,
        *,
        actor: CurrentActor,
        username: str,
        password: str,
        display_name: str,
        department_id: int | None = None,
        phone: str | None = None,
        email: str | None = None,
        role_ids: frozenset[int] | None = None,
    ) -> AdminUser:
        """创建用户。"""
        scope = await self._scope.resolve(actor)
        # 创建时目标用户尚不存在，校验对象是"目标部门"；
        # 它同样必须经由统一守卫留痕，不得单独 try/except。
        with self._denial_audited(actor=actor, action=AuditAction.USER_CREATE, resource_id=None):
            await self._assert_department_in_scope(scope=scope, department_id=department_id)

        password_hash = self._hash_new_password(password)

        if await self._users.get_by_username(username) is not None:
            raise ConflictError(f"登录名已存在：{username}")

        user = AdminUser(
            username=username,
            password_hash=password_hash,
            display_name=display_name,
            phone=phone,
            email=email,
            department_id=department_id,
            status=UserStatus.ACTIVE,
            failed_login_count=0,
            password_changed_at=utc_now(),
            # INTERIM：Spec 00 §2 只规定"管理员重置密码后"必须改密。
            # 创建用户同样是管理员设置初始口令，此处按同一意图处理（待确认）。
            must_change_password=True,
        )
        await self._users.add(user)

        if role_ids:
            # 创建用户同时尝试提权 → 记为角色授予越权（resource_id 取新用户）
            with self._denial_audited(
                actor=actor, action=AuditAction.USER_ROLE_ASSIGN, resource_id=user.id
            ):
                await self._authz.assert_can_assign_roles(actor=actor, role_ids=role_ids)
            roles = await self._roles.list_by_ids(sorted(role_ids))
            if len(roles) != len(role_ids):
                raise BadRequestError("包含不存在或已删除的角色")
            await self._roles.replace_user_roles(user.id, role_ids)

        self._record(
            actor=actor,
            action=AuditAction.USER_CREATE,
            resource_id=user.id,
            after=_snapshot(user),
        )
        return user

    # ------------------------------------------------------------------
    # 修改
    # ------------------------------------------------------------------
    async def update(
        self,
        *,
        actor: CurrentActor,
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
        phone: str | _Unset | None = _UNSET,
        email: str | _Unset | None = _UNSET,
        department_id: int | _Unset | None = _UNSET,
    ) -> AdminUser:
        """修改用户。

        `status` 与密码**不在此处**修改：分别走 `disable`/`enable` 与
        `reset_password`，以保证对应审计动作不可被绕过。
        """
        user, scope = await self._load_manageable_target(
            actor=actor, user_id=user_id, action=AuditAction.USER_UPDATE
        )
        before = _snapshot(user)

        if username is not None and username != user.username:
            existing = await self._users.get_by_username(username)
            if existing is not None:
                raise ConflictError(f"登录名已存在：{username}")
            user.username = username

        if display_name is not None:
            user.display_name = display_name

        if not isinstance(phone, _Unset):
            user.phone = phone

        if not isinstance(email, _Unset):
            user.email = email

        if not isinstance(department_id, _Unset):
            # 目标部门必须在范围内（不能把用户挪出/挪入越权部门）
            with self._denial_audited(
                actor=actor, action=AuditAction.USER_UPDATE, resource_id=user.id
            ):
                await self._assert_department_in_scope(scope=scope, department_id=department_id)
            user.department_id = department_id

        await self._session.flush()
        self._record(
            actor=actor,
            action=AuditAction.USER_UPDATE,
            resource_id=user.id,
            before=before,
            after=_snapshot(user),
        )
        return user

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    async def disable(self, *, actor: CurrentActor, user_id: int) -> AdminUser:
        """禁用用户。禁用后不能正常登录（登录侧在 Phase 4 校验 status）。"""
        return await self._change_status(
            actor=actor,
            user_id=user_id,
            new_status=UserStatus.DISABLED,
            action=AuditAction.USER_DISABLE,
        )

    async def enable(self, *, actor: CurrentActor, user_id: int) -> AdminUser:
        """启用用户。"""
        return await self._change_status(
            actor=actor,
            user_id=user_id,
            new_status=UserStatus.ACTIVE,
            action=AuditAction.USER_ENABLE,
        )

    async def _change_status(
        self,
        *,
        actor: CurrentActor,
        user_id: int,
        new_status: UserStatus,
        action: AuditAction,
    ) -> AdminUser:
        user, _ = await self._load_manageable_target(actor=actor, user_id=user_id, action=action)
        if new_status is UserStatus.DISABLED:
            # RISK-002：系统必须保留至少一个可用 SUPER_ADMIN。
            # 该拒绝属"安全不变量"，同样必须留 FAILURE 审计。
            with self._denial_audited(actor=actor, action=action, resource_id=user.id):
                await self._authz.assert_not_last_super_admin(target=user)

        before = _snapshot(user)
        user.status = new_status
        await self._session.flush()
        self._record(
            actor=actor,
            action=action,
            resource_id=user.id,
            before=before,
            after=_snapshot(user),
        )
        return user

    # ------------------------------------------------------------------
    # 逻辑删除（disable + logical delete，Spec 02 §5）
    # ------------------------------------------------------------------
    async def delete(self, *, actor: CurrentActor, user_id: int) -> AdminUser:
        """逻辑删除用户：置 `status = DISABLED` 且写入 `deleted_at`。

        绝不物理删除（AGENTS.md §7 / Spec 00 §6）。
        """
        user, _ = await self._load_manageable_target(
            actor=actor, user_id=user_id, action=AuditAction.USER_DELETE
        )
        # RISK-002：逻辑删除同样不能让系统失去最后一个 SUPER_ADMIN。
        with self._denial_audited(actor=actor, action=AuditAction.USER_DELETE, resource_id=user.id):
            await self._authz.assert_not_last_super_admin(target=user)

        before = _snapshot(user)
        user.status = UserStatus.DISABLED
        user.deleted_at = utc_now()
        await self._session.flush()
        self._record(
            actor=actor,
            action=AuditAction.USER_DELETE,
            resource_id=user.id,
            before=before,
            after=_snapshot(user),
        )
        return user

    # ------------------------------------------------------------------
    # 密码重置
    # ------------------------------------------------------------------
    async def reset_password(
        self, *, actor: CurrentActor, user_id: int, new_password: str
    ) -> AdminUser:
        """重置密码：写入历史、置强制改密标记。

        Session 撤销属 Phase 5（Session 未实现），此处不处理。
        """
        user, _ = await self._load_manageable_target(
            actor=actor, user_id=user_id, action=AuditAction.USER_RESET_PASSWORD
        )

        before = _snapshot(user)
        new_hash = await self._prepare_password_change(user=user, new_password=new_password)
        user.password_hash = new_hash
        user.password_changed_at = utc_now()
        user.must_change_password = True  # Spec 00 §2：管理员重置后首次登录必须改密
        await self._session.flush()

        self._record(
            actor=actor,
            action=AuditAction.USER_RESET_PASSWORD,
            resource_id=user.id,
            before=before,
            after=_snapshot(user),
        )
        return user

    async def change_own_password(
        self, *, actor: CurrentActor, current_password: str, new_password: str
    ) -> AdminUser:
        """用户修改**自己**的口令（RISK-001 的收尾路径）。

        为什么必须存在这个方法
        ----------------------
        Spec `00 §2` 要求"管理员重置密码后，首次登录必须修改密码"。
        "必须修改"如果不存在一条**解除**路径，用户将永远无法正常使用，
        即 `must_change_password` 只能置 True 而不能置 False —— 那不是策略，是死锁。
        因此本方法与其构成一对完整语义。

        安全要点
        --------
        1. 目标恒为 `actor.user_id`，**不接受外部传入 user_id**，
           从方法签名上消除 IDOR（越权改他人密码）的可能；
        2. 必须先校验当前口令，防止会话被盗后直接改密；
        3. 新口令同样受"最近 5 个不重复"策略约束（复用 `_prepare_password_change`）；
        4. 成功后 `must_change_password = False`。

        边界：HTTP 端点属 Phase 4 登录/认证流程（`04 §认证`），
        本 Phase 只交付可复用的业务动作与测试。
        """
        user = await self._users.get(actor.user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        with self._denial_audited(
            actor=actor, action=AuditAction.USER_CHANGE_PASSWORD, resource_id=user.id
        ):
            if not get_password_hasher().verify(current_password, user.password_hash):
                raise PermissionDeniedError("当前口令不正确")

        before = _snapshot(user)
        user.password_hash = await self._prepare_password_change(
            user=user, new_password=new_password
        )
        user.password_changed_at = utc_now()
        # RISK-001：本人已完成改密 → 解除强制改密
        user.must_change_password = False
        await self._session.flush()

        self._record(
            actor=actor,
            action=AuditAction.USER_CHANGE_PASSWORD,
            resource_id=user.id,
            before=before,
            after=_snapshot(user),
        )
        return user

    # ------------------------------------------------------------------
    # 角色关联
    # ------------------------------------------------------------------
    async def list_roles(self, *, actor: CurrentActor, user_id: int) -> list[Role]:
        """读取用户当前角色（含范围校验，拒绝留痕）。"""
        with self._denial_audited(actor=actor, action=AuditAction.USER_READ, resource_id=user_id):
            await self._load_target(actor=actor, user_id=user_id)
        return await self._roles.list_for_user(user_id)

    async def assign_roles(
        self, *, actor: CurrentActor, user_id: int, role_ids: frozenset[int]
    ) -> tuple[frozenset[int], frozenset[int]]:
        """整体替换用户角色。

        Returns:
            (before, after) 角色 ID 集合。
        """
        await self._load_manageable_target(
            actor=actor, user_id=user_id, action=AuditAction.USER_ROLE_ASSIGN
        )

        # 授予与撤销都需校验（撤销 SUPER_ADMIN 同样属于特权操作）
        before_roles = frozenset(await self._current_role_ids(user_id))
        with self._denial_audited(
            actor=actor, action=AuditAction.USER_ROLE_ASSIGN, resource_id=user_id
        ):
            await self._authz.assert_can_assign_roles(actor=actor, role_ids=role_ids)
            await self._authz.assert_can_assign_roles(actor=actor, role_ids=before_roles)

        if role_ids:
            roles = await self._roles.list_by_ids(sorted(role_ids))
            if len(roles) != len(role_ids):
                raise BadRequestError("包含不存在或已删除的角色")

        before, after = await self._roles.replace_user_roles(user_id, role_ids)
        # 角色授予 / 撤销直接改变该用户的有效权限 → 必须递增权限版本
        # （Spec `11 §2`：权限修改必须更新 / 递增 permission version）。
        # 漏掉这一步的后果是"权限已改但缓存仍有效"，违反 `00 §1#5` 立即生效。
        await self._versions.bump()
        self._record(
            actor=actor,
            action=AuditAction.USER_ROLE_ASSIGN,
            resource_id=user_id,
            before={"role_ids": sorted(before)},
            after={"role_ids": sorted(after)},
        )
        return before, after

    async def _current_role_ids(self, user_id: int) -> set[int]:
        return {role.id for role in await self._roles.list_for_user(user_id)}

    # ------------------------------------------------------------------
    # 密码内部逻辑
    # ------------------------------------------------------------------
    @staticmethod
    def _hash_new_password(password: str) -> str:
        """校验策略并生成哈希。"""
        violations = validate_password_policy(password)
        if violations:
            raise BadRequestError(
                "密码不符合策略：" + "; ".join(v.message for v in violations),
                data={"violations": [v.code for v in violations]},
            )
        return get_password_hasher().hash(password)

    async def _prepare_password_change(self, *, user: AdminUser, new_password: str) -> str:
        """生成新哈希并维护密码历史。

        顺序（保证"最近 5 个密码不可重复"语义正确）：
        1. 校验新密码不重复于**当前密码**与最近 5 条历史；
        2. 把当前哈希追加进历史；
        3. 裁剪历史到 5 条；
        4. 返回新哈希（由调用方写入 `password_hash`）。
        """
        new_hash = self._hash_new_password(new_password)
        hasher = get_password_hasher()

        if hasher.verify(new_password, user.password_hash):
            raise BadRequestError("新密码不能与当前密码相同")

        recent = await self._users.list_password_hashes(user.id, limit=PASSWORD_HISTORY_SIZE)
        for old_hash in recent:
            if hasher.verify(new_password, old_hash):
                raise BadRequestError(
                    f"新密码不能与最近 {PASSWORD_HISTORY_SIZE} 次使用过的密码重复"
                )

        await self._users.append_password_history(user.id, user.password_hash)
        await self._users.prune_password_history(user.id, keep=PASSWORD_HISTORY_SIZE)
        return new_hash


__all__ = ["UserPage", "UserService"]
