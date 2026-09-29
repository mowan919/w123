"""初始口令的复杂度豁免（`RESOLVED-29-01`）。

为什么单开一个文件
------------------
`tests/test_user_service.py` 里对应的两条用例用固定 ID 造树（部门 1~6、
角色 9001 起），在**共享开发库**里会撞上 `scripts/seed_data.py` 留下的种子行
（已知的环境问题：整套 forced red 399 例）。把本轮新增的语义放进那个文件，
等于把它写在一个永远跑不红的上下文里 —— 改坏了也看不出来。

这里刻意**不造部门树**：超管 + `department_id=None` 是合法组合，
既够验证"初始口令要不要查复杂度"，又不碰任何既有行的唯一索引。
"""

from __future__ import annotations

import uuid

import pytest

from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError
from app.core.security.password import get_password_hasher
from app.services.user import UserService

pytestmark = pytest.mark.integration

ROOT_ACTOR = CurrentActor.super_admin(user_id=1001, username="root")


def _username(prefix: str) -> str:
    """每次都不一样：共享库里的同名行会让"唯一索引"变成干扰项。"""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def test_create_accepts_simple_initial_password(db_session) -> None:
    """初始口令不必含大小写 / 数字 / 符号。

    它是管理员临时签发、用户首次登录就被强制换掉的一次性凭据
    （理由见 `UserService._hash_new_password`）。
    """
    service = UserService(db_session)

    user = await service.create(
        actor=ROOT_ACTOR,
        username=_username("simple-init"),
        password="123456",
        display_name="简单初始口令",
        department_id=None,
    )

    assert get_password_hasher().verify("123456", user.password_hash) is True
    # 豁免的前提：它活不到第二次登录。缺这条，本用例就是给弱口令开后门。
    assert user.must_change_password is True


async def test_reset_accepts_simple_new_password(db_session) -> None:
    """管理员重置出来的同样是**初始口令**，同样豁免。

    其它约束一个没松：仍必须置 `must_change_password = True`。
    """
    service = UserService(db_session)
    user = await service.create(
        actor=ROOT_ACTOR,
        username=_username("reset-init"),
        password="Alpha-Passw0rd!01",
        display_name="待重置",
        department_id=None,
    )

    updated = await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password="123456")

    assert get_password_hasher().verify("123456", updated.password_hash) is True
    assert updated.must_change_password is True


async def test_self_change_still_enforces_policy(db_session) -> None:
    """豁免**只**给初始口令 —— 用户自己改的口令仍走完整策略。

    少了这条，"复杂度策略"就只对一半场景生效：管理员随便设个弱的没关系，
    用户想改还得凑齐大小写数字符号。这是本轮裁定最容易写坏的一处边界。
    """
    service = UserService(db_session)
    user = await service.create(
        actor=ROOT_ACTOR,
        username=_username("self-change"),
        password="123456",
        display_name="初始口令很弱",
        department_id=None,
    )

    with pytest.raises(BadRequestError, match="密码"):
        await service.change_own_password(
            actor=CurrentActor.super_admin(user_id=user.id, username=user.username),
            current_password="123456",
            new_password="weak",
        )

    # 改没成功 → 弱口令仍在，且标记未解除（不许"改密失败却放行"）。
    assert get_password_hasher().verify("123456", user.password_hash) is True
    assert user.must_change_password is True


async def test_empty_initial_password_is_rejected(db_session) -> None:
    """免复杂度 ≠ 可以不给口令。

    "不查构成"说的是不查大小写 / 数字 / 符号，不是允许空串 ——
    那是**没有口令**，任何场景下都不接受。
    """
    service = UserService(db_session)
    with pytest.raises(BadRequestError, match="不能为空"):
        await service.create(
            actor=ROOT_ACTOR,
            username=_username("empty-init"),
            password="   ",
            display_name="空口令",
            department_id=None,
        )
