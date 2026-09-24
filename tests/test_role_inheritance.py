"""角色继承测试（Task 3.5 / DD-05 已冻结，方案 A）。

覆盖点
-----
- **方向正确性**：`child 继承 parent`（`child ∈ ancestors(parent)` 才是环）。
  方向写反会让真正的环被放行，因此既要有"成环被拒"的用例，
  也要有"菱形依赖被放行"的用例，防止把正确结构误拒。
- **三重环路防护**：
  1. 数据库 CHECK 阻止自环；
  2. 写入期检测阻止成环（唯一能在入库前拦住的地方）；
  3. 读取期递归 CTE（`UNION`）+ 深度上限，保证"已存在的环不拖垮系统"。
- 幂等授予不抖动权限版本；真实变更必须递增；
- 深度上限 fail-closed（超限抛错，而不是静默返回可疑集合）；
- 授权拒绝留 FAILURE 审计。

不覆盖（属其他 Phase / 其他模块）
------------------------------
- 继承对有效权限的影响 → `tests/test_effective_permission.py`；
- Role CRUD → `tests/test_role_service.py`；
- HTTP 端点（Phase 8）。
"""

from __future__ import annotations

import pytest

from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.repositories.permission import (
    PermissionVersionRepository,
    RoleInheritanceDepthExceededError,
    RoleInheritanceRepository,
)
from app.services.effective_permission import MAX_ROLE_INHERITANCE_DEPTH
from app.services.role_inheritance import RoleInheritanceService
from tests.factories import link_role_inheritance, make_role

pytestmark = pytest.mark.integration

ROOT = CurrentActor.super_admin(user_id=9001, username="root")
ADMIN = CurrentActor(
    user_id=9002,
    username="dept-admin",
    role_codes=frozenset({"DEPT_ADMIN"}),
    data_scope=DataScope.DEPARTMENT_CHILDREN,
    department_id=1,
)


async def _version(session) -> int:
    return await PermissionVersionRepository(session).get()


async def _seed_roles(session, role_ids: list[int]) -> None:
    for role_id in role_ids:
        await make_role(session, role_id=role_id, role_code=f"R{role_id}")


# ===========================================================================
# 授予
# ===========================================================================
class TestGrant:
    async def test_grant_creates_relation_and_bumps_version(
        self, db_session, audit_recorder
    ) -> None:
        await _seed_roles(db_session, [1001, 1002])
        before = await _version(db_session)

        service = RoleInheritanceService(db_session, audit=audit_recorder)
        chain = await service.grant(actor=ROOT, parent_role_id=1001, child_role_id=1002)

        assert chain.parent_role_ids == frozenset({1001})
        assert chain.ancestor_role_ids == frozenset({1001})
        assert await _version(db_session) == before + 1

        event = audit_recorder.find(str(AuditAction.ROLE_INHERITANCE_GRANT))
        assert event is not None
        # 审计挂在**子角色**上：它才是权限变化的主体。
        assert event.resource_id == 1002

    async def test_grant_is_idempotent(self, db_session) -> None:
        """重复授予同一关系不产生副作用，也不抖动版本（否则缓存会反复失效）。"""
        await _seed_roles(db_session, [1011, 1012])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1011, child_role_id=1012)
        after_first = await _version(db_session)

        chain = await service.grant(actor=ROOT, parent_role_id=1011, child_role_id=1012)
        assert await _version(db_session) == after_first
        assert chain.parent_role_ids == frozenset({1011})

    async def test_self_inheritance_is_rejected(self, db_session, audit_recorder) -> None:
        """自继承是**入参错误（400）**，不是安全事件，因此不留 FAILURE 审计。

        这是 `AuditGuard` 的既定口径：只有"我们拒绝了某个请求"里的
        **权限拒绝（403）与状态冲突（409）**才记 FAILURE；
        参数错误与 404 属正常输入校验，记进去会淹没真实的安全信号。
        本用例把该口径钉死，避免有人"顺手"把 400 也接进审计。
        """
        await _seed_roles(db_session, [1021])
        service = RoleInheritanceService(db_session, audit=audit_recorder)
        with pytest.raises(BadRequestError, match="自继承"):
            await service.grant(actor=ROOT, parent_role_id=1021, child_role_id=1021)
        assert audit_recorder.failures() == []

    async def test_direct_cycle_is_rejected(self, db_session, audit_recorder) -> None:
        """A→B 之后 B→A 必须被拒（否则 A、B 互为祖先，形成环）。"""
        await _seed_roles(db_session, [1031, 1032])
        service = RoleInheritanceService(db_session, audit=audit_recorder)
        await service.grant(actor=ROOT, parent_role_id=1031, child_role_id=1032)

        with pytest.raises(ConflictError, match="循环继承"):
            await service.grant(actor=ROOT, parent_role_id=1032, child_role_id=1031)
        assert len(audit_recorder.failures()) == 1

    async def test_transitive_cycle_is_rejected(self, db_session) -> None:
        """A→B→C 之后 C→A 会闭合出 3 节点环，必须被拒。

        只检查"直接父子互换"的实现会放过这里 ——
        因此这条用例专门钉住**传递性**检测。
        """
        await _seed_roles(db_session, [1041, 1042, 1043])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1041, child_role_id=1042)
        await service.grant(actor=ROOT, parent_role_id=1042, child_role_id=1043)

        with pytest.raises(ConflictError, match="循环继承"):
            await service.grant(actor=ROOT, parent_role_id=1043, child_role_id=1041)

    async def test_diamond_dependency_is_allowed(self, db_session) -> None:
        """菱形依赖（A→B、A→C、B→D、C→D）是合法 DAG，**不得**被拒。

        没有这条用例，一个"只要祖先集合有交集就拒绝"的过度保守实现
        会静默通过所有环用例，却挡住正常的多重继承。
        """
        await _seed_roles(db_session, [1051, 1052, 1053, 1054])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1051, child_role_id=1052)
        await service.grant(actor=ROOT, parent_role_id=1051, child_role_id=1053)
        await service.grant(actor=ROOT, parent_role_id=1052, child_role_id=1054)
        chain = await service.grant(actor=ROOT, parent_role_id=1053, child_role_id=1054)

        assert chain.parent_role_ids == frozenset({1052, 1053})
        assert chain.ancestor_role_ids == frozenset({1051, 1052, 1053})

    async def test_missing_role_returns_400(self, db_session) -> None:
        """两端角色都必须真实存在 —— 给 400 而不是让 FK 抛 500。"""
        await _seed_roles(db_session, [1061])
        service = RoleInheritanceService(db_session)
        with pytest.raises(BadRequestError, match="parent_role_id"):
            await service.grant(actor=ROOT, parent_role_id=999_999, child_role_id=1061)
        with pytest.raises(BadRequestError, match="child_role_id"):
            await service.grant(actor=ROOT, parent_role_id=1061, child_role_id=999_999)

    async def test_soft_deleted_role_cannot_be_linked(self, db_session) -> None:
        from app.db.base import utc_now

        role = await make_role(db_session, role_id=1071, role_code="DELETED")
        await _seed_roles(db_session, [1072])
        role.deleted_at = utc_now()
        await db_session.flush()

        service = RoleInheritanceService(db_session)
        with pytest.raises(BadRequestError):
            await service.grant(actor=ROOT, parent_role_id=1071, child_role_id=1072)

    async def test_grant_requires_authorization(self, db_session, audit_recorder) -> None:
        await _seed_roles(db_session, [1081, 1082])
        service = RoleInheritanceService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.grant(actor=ADMIN, parent_role_id=1081, child_role_id=1082)
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_INHERITANCE_GRANT)


# ===========================================================================
# 解除
# ===========================================================================
class TestRevoke:
    async def test_revoke_removes_relation_and_bumps_version(self, db_session) -> None:
        await _seed_roles(db_session, [1101, 1102])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1101, child_role_id=1102)
        before = await _version(db_session)

        chain = await service.revoke(actor=ROOT, parent_role_id=1101, child_role_id=1102)

        assert chain.parent_role_ids == frozenset()
        assert chain.ancestor_role_ids == frozenset()
        assert await _version(db_session) == before + 1

    async def test_revoke_missing_returns_404(self, db_session) -> None:
        await _seed_roles(db_session, [1111, 1112])
        service = RoleInheritanceService(db_session)
        with pytest.raises(NotFoundError, match="继承关系不存在"):
            await service.revoke(actor=ROOT, parent_role_id=1111, child_role_id=1112)

    async def test_revoke_requires_authorization(self, db_session, audit_recorder) -> None:
        await _seed_roles(db_session, [1121, 1122])
        service = RoleInheritanceService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.revoke(actor=ADMIN, parent_role_id=1121, child_role_id=1122)
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_INHERITANCE_REVOKE)

    async def test_revoke_does_not_touch_other_edges(self, db_session) -> None:
        """解除一条边不得影响其他边（`remove` 必须带完整复合键）。"""
        await _seed_roles(db_session, [1131, 1132, 1133])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1131, child_role_id=1133)
        await service.grant(actor=ROOT, parent_role_id=1132, child_role_id=1133)

        chain = await service.revoke(actor=ROOT, parent_role_id=1131, child_role_id=1133)
        assert chain.parent_role_ids == frozenset({1132})


# ===========================================================================
# 查询与展开
# ===========================================================================
class TestChainAndExpansion:
    async def test_list_chain_reports_both_directions(self, db_session) -> None:
        await _seed_roles(db_session, [1201, 1202, 1203])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1201, child_role_id=1202)
        await service.grant(actor=ROOT, parent_role_id=1202, child_role_id=1203)

        chain = await service.list_chain(actor=ROOT, role_id=1202)
        assert chain.direct_parents == frozenset({1201})
        assert chain.direct_children == frozenset({1203})
        assert chain.ancestor_role_ids == frozenset({1201})

    async def test_list_chain_missing_returns_404(self, db_session) -> None:
        service = RoleInheritanceService(db_session)
        with pytest.raises(NotFoundError):
            await service.list_chain(actor=ROOT, role_id=9_999_999)

    async def test_expand_includes_self_and_all_ancestors(self, db_session) -> None:
        await _seed_roles(db_session, [1211, 1212, 1213])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1211, child_role_id=1212)
        await service.grant(actor=ROOT, parent_role_id=1212, child_role_id=1213)

        expanded = await service.expand_role_ids(frozenset({1213}))
        assert expanded == frozenset({1211, 1212, 1213})

    async def test_expand_empty_returns_empty(self, db_session) -> None:
        service = RoleInheritanceService(db_session)
        assert await service.expand_role_ids(frozenset()) == frozenset()

    async def test_expand_unions_multiple_starting_points(self, db_session) -> None:
        await _seed_roles(db_session, [1221, 1222, 1223])
        service = RoleInheritanceService(db_session)
        await service.grant(actor=ROOT, parent_role_id=1221, child_role_id=1222)
        await service.grant(actor=ROOT, parent_role_id=1222, child_role_id=1223)

        expanded = await service.expand_role_ids(frozenset({1222, 1223}))
        assert expanded == frozenset({1221, 1222, 1223})


# ===========================================================================
# 深度上限（fail-closed）
# ===========================================================================
class TestDepthCap:
    async def test_default_cap_is_32(self) -> None:
        assert MAX_ROLE_INHERITANCE_DEPTH == 32

    async def test_repo_raises_when_chain_exceeds_cap(self, db_session) -> None:
        """仓储层直接暴露异常，供调用方决定如何呈现（服务层转 409）。"""
        await _seed_roles(db_session, [1301, 1302, 1303, 1304, 1305])
        for parent, child in ((1301, 1302), (1302, 1303), (1303, 1304), (1304, 1305)):
            await link_role_inheritance(db_session, parent_role_id=parent, child_role_id=child)

        repo = RoleInheritanceRepository(db_session)
        with pytest.raises(RoleInheritanceDepthExceededError, match="深度超过上限"):
            await repo.ancestor_ids([1305], max_depth=3)

    async def test_repo_accepts_chain_within_cap(self, db_session) -> None:
        await _seed_roles(db_session, [1311, 1312, 1313])
        await link_role_inheritance(db_session, parent_role_id=1311, child_role_id=1312)
        await link_role_inheritance(db_session, parent_role_id=1312, child_role_id=1313)

        repo = RoleInheritanceRepository(db_session)
        assert await repo.ancestor_ids([1313], max_depth=4) == frozenset({1311, 1312})

    async def test_grant_refuses_when_existing_data_already_too_deep(self, db_session) -> None:
        """库里已有异常长链 → 拒绝继续写入，让运维先修数据，而不是把异常扩散。"""
        await _seed_roles(db_session, [1321, 1322, 1323, 1324, 1325, 1326])
        for parent, child in ((1321, 1322), (1322, 1323), (1323, 1324), (1324, 1325)):
            await link_role_inheritance(db_session, parent_role_id=parent, child_role_id=child)

        service = RoleInheritanceService(db_session, max_depth=3)
        with pytest.raises(ConflictError, match="深度超过 3"):
            await service.grant(actor=ROOT, parent_role_id=1325, child_role_id=1326)

    async def test_list_chain_turns_depth_error_into_409(self, db_session) -> None:
        await _seed_roles(db_session, [1331, 1332, 1333, 1334, 1335])
        for parent, child in ((1331, 1332), (1332, 1333), (1333, 1334), (1334, 1335)):
            await link_role_inheritance(db_session, parent_role_id=parent, child_role_id=child)

        service = RoleInheritanceService(db_session, max_depth=3)
        with pytest.raises(ConflictError):
            await service.list_chain(actor=ROOT, role_id=1335)


# ===========================================================================
# 读取期环路安全（"最后一道防线"）
# ===========================================================================
class TestReadPathCycleSafety:
    """服务层会拒绝成环，所以这些用例**绕过服务直接写库**。

    这正是要覆盖的场景：写入期检测被绕过（人为直连数据库）之后，
    读路径仍必须终止且返回可解释的结果，而不是无限递归把进程挂死。

    注意：外键**不保证无环**，只保证"被引用的行存在"。
    直接插入 `A.parent = B` 会被拒绝只是因为 `B` 尚不存在；
    先建好两端再补边即可成环 —— 所以"数据库能拦住环"是错误认知。
    """

    async def test_expand_terminates_on_cycle(self, db_session) -> None:
        await _seed_roles(db_session, [1401, 1402])
        await link_role_inheritance(db_session, parent_role_id=1401, child_role_id=1402)
        await link_role_inheritance(db_session, parent_role_id=1402, child_role_id=1401)

        service = RoleInheritanceService(db_session)
        expanded = await service.expand_role_ids(frozenset({1402}))
        # 环收敛为同一闭包，且自身不会被当作祖先重复计入。
        assert expanded == frozenset({1401, 1402})

    async def test_expand_terminates_on_three_node_cycle(self, db_session) -> None:
        await _seed_roles(db_session, [1411, 1412, 1413])
        await link_role_inheritance(db_session, parent_role_id=1411, child_role_id=1412)
        await link_role_inheritance(db_session, parent_role_id=1412, child_role_id=1413)
        await link_role_inheritance(db_session, parent_role_id=1413, child_role_id=1411)

        service = RoleInheritanceService(db_session)
        expanded = await service.expand_role_ids(frozenset({1411}))
        assert expanded == frozenset({1411, 1412, 1413})

    async def test_ancestor_ids_excludes_self_even_on_cycle(self, db_session) -> None:
        """`自身 ∈ 祖先` 没有业务含义，且会污染并集计算 —— 必须剔除。"""
        await _seed_roles(db_session, [1421, 1422])
        await link_role_inheritance(db_session, parent_role_id=1421, child_role_id=1422)
        await link_role_inheritance(db_session, parent_role_id=1422, child_role_id=1421)

        repo = RoleInheritanceRepository(db_session)
        ancestors = await repo.ancestor_ids([1421], max_depth=32)
        assert 1421 not in ancestors
        assert ancestors == frozenset({1422})

    async def test_grant_refuses_edge_that_lies_on_existing_cycle(self, db_session) -> None:
        """库里已有环时，**落在环上的**边必须被拒 —— 即使它"已经存在"。

        为什么这个场景有意义：成环检测发生在幂等短路**之前**，
        所以重复提交一条环上的边不会被当成"无副作用的幂等操作"放行，
        而是明确报 409，提示运维库里存在需要修复的环。

        注意语义边界（下一条用例覆盖）：往环**外面**挂新节点不成环，因此允许。
        "拒绝一切写入"是过度保守，会挡住正常运维操作。
        """
        await _seed_roles(db_session, [1431, 1432])
        await link_role_inheritance(db_session, parent_role_id=1431, child_role_id=1432)
        await link_role_inheritance(db_session, parent_role_id=1432, child_role_id=1431)

        service = RoleInheritanceService(db_session)
        with pytest.raises(ConflictError, match="循环继承"):
            await service.grant(actor=ROOT, parent_role_id=1432, child_role_id=1431)

    async def test_grant_allows_attaching_outside_node_to_cyclic_data(self, db_session) -> None:
        """环外节点可以正常挂接：环只由环上的节点构成。

        这条用例与上一条互为边界，防止有人把实现改成
        "发现环就拒绝一切写入"——那会让系统在数据受损时彻底不可运维。
        """
        await _seed_roles(db_session, [1441, 1442, 1443])
        await link_role_inheritance(db_session, parent_role_id=1441, child_role_id=1442)
        await link_role_inheritance(db_session, parent_role_id=1442, child_role_id=1441)

        service = RoleInheritanceService(db_session)
        chain = await service.grant(actor=ROOT, parent_role_id=1441, child_role_id=1443)
        assert chain.parent_role_ids == frozenset({1441})
