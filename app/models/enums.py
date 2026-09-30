"""业务枚举。

Frozen 依据
-----------
- Spec `02 §3` 用户状态：至少 ACTIVE / DISABLED / LOCKED。
             （`DELETED` 不进入 status 枚举，逻辑删除统一由 `deleted_at` 表达，
              见 Spec `00 §6` / `07 §3`。）
- Spec `02 §1` 部门支持禁用 → DepartmentStatus 取 ACTIVE / DISABLED。
- Spec `03 §2` Role 含 status，未给定取值 → 取 ACTIVE / DISABLED。
- Spec `04 §6` MFA 生命周期 → `MfaStatus` 三态（DISABLED / SETUP / ENABLED）。
- Spec `04 §3` Session 需记录 `revoke_reason`（取值域未规定 → INTERIM）。

注意：枚举值使用大写字符串，与 Spec 表述一致；Python 侧使用 `StrEnum`
以便直接参与 JSON 序列化与字符串比较。
"""

from __future__ import annotations

from enum import StrEnum


class DepartmentStatus(StrEnum):
    """部门状态。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class UserStatus(StrEnum):
    """用户状态。

    Spec `02 §3`：ACTIVE / DISABLED / LOCKED。
    LOCKED 与 `locked_until` 并存（02 §3 允许两者表达同一语义）。
    逻辑删除状态由 `deleted_at` 表达，不在本枚举内。
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"


class RoleStatus(StrEnum):
    """角色状态（本 Phase 只落库，不实现 Role 业务）。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class DictStatus(StrEnum):
    """字典类型 / 字典项的状态（Spec `05 §2` / `05 §3` 均含 `status`）。

    Spec 未给定取值域，沿用本项目各实体统一的 ACTIVE / DISABLED 语义
    （与 `DepartmentStatus` / `RoleStatus` / `PermissionStatus` 一致）。
    `DISABLED` 的字典类型不参与公开查询；`DISABLED` 的字典项不下发。

    为什么不与 `RoleStatus` 复用一个枚举：本项目既有约定是**每个实体拥有
    自己的状态枚举**（部门 / 用户 / 角色 / 权限资源各自一个），
    这样"某实体的状态新增一个取值"不会波及其他实体的取值域。
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class SystemParamType(StrEnum):
    """系统参数的类型（Spec `05 §5`："参数必须有类型"）。

    Spec **未枚举**具体类型，因此本取值域属 INTERIM 技术取值。取值依据是
    `05 §5` 自己给出的四个示例参数所需的**最小**类型集合：

    | 示例参数 | 需要类型 |
    |---|---|
    | session timeout | `INT`（秒） |
    | login max attempts | `INT` |
    | password minimum length | `INT` |
    | MFA default policy | `BOOL` |
    | （通用文本配置） | `STRING` |

    刻意**不**引入 JSON / FLOAT / 列表等类型：Spec 没有任何示例需要它们，
    增加类型等于发明未被要求的表达能力；而每个新类型都要定义
    "解析失败怎么办"，是纯粹的待冻结项增量。
    """

    STRING = "STRING"
    INT = "INT"
    BOOL = "BOOL"


class SystemParamStatus(StrEnum):
    """系统参数的状态（Spec `05 §5`："参数必须有…状态…"）。

    语义（**已登记 INTERIM/JUDGMENT-7-02**，Spec 未规定）：
    读取方遇到 `DISABLED` 的参数必须 **fail-closed**，而不是"按默认值生效"
    或"当作未配置"。理由见 `app/services/system_param.py` 的模块文档：
    静默按默认值生效会让"停用"变成无操作；静默当作未配置会让
    "停用"与"缺失"不可区分 —— 两者都是**静默的安全降级**。
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class PermissionResourceType(StrEnum):
    """权限资源类型（Phase 3 / DD-20 已冻结）。

    依据 Spec `00 §3` / `03 §5~§9` 的五段权限链：
        Page / Menu / Button / API / Field
    """

    PAGE = "PAGE"
    MENU = "MENU"
    BUTTON = "BUTTON"
    API = "API"
    FIELD = "FIELD"


class PermissionStatus(StrEnum):
    """权限资源状态。

    Spec 未单独规定资源状态取值，故复用业务表统一的 ACTIVE / DISABLED
    语义（与 `RoleStatus` 一致）。DISABLED 的资源不参与有效权限计算。
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class FieldAccessLevel(StrEnum):
    """字段权限等级（Spec `03 §9` / `00 §3`）。

    四级取值直接来自冻结 Spec，不可增删。

    合并序（DD-06 已冻结：**最宽松者胜**）::

        HIDDEN < READ_ONLY < VISIBLE < EDITABLE

    注意：该方向与 `00 §1#2`"权限取并集"同向，因此 `HIDDEN`
    **不能**覆盖其他角色授予的 `VISIBLE`。若要"HIDDEN 一票否决"
    必须由人类重新裁定（见 `docs/DESIGN-DECISIONS.md` DD-06）。
    """

    HIDDEN = "HIDDEN"
    READ_ONLY = "READ_ONLY"
    VISIBLE = "VISIBLE"
    EDITABLE = "EDITABLE"

    @property
    def rank(self) -> int:
        """合并用的序（越大越宽松）。"""
        return _FIELD_ACCESS_RANK[self]


#: 字段等级 → 合并序。集中一处，避免比较逻辑散落。
_FIELD_ACCESS_RANK: dict[FieldAccessLevel, int] = {
    FieldAccessLevel.HIDDEN: 0,
    FieldAccessLevel.READ_ONLY: 1,
    FieldAccessLevel.VISIBLE: 2,
    FieldAccessLevel.EDITABLE: 3,
}

#: 字段等级中"可以读到值"的集合（HIDDEN 之外都可以读）。
#: 供 Phase 8 输出字段策略时判断"是否应下发该字段"。
FIELD_ACCESS_READABLE: frozenset[FieldAccessLevel] = frozenset(
    {
        FieldAccessLevel.READ_ONLY,
        FieldAccessLevel.VISIBLE,
        FieldAccessLevel.EDITABLE,
    }
)

#: 字段等级中"可以写入"的集合。
FIELD_ACCESS_WRITABLE: frozenset[FieldAccessLevel] = frozenset({FieldAccessLevel.EDITABLE})


def most_permissive_field_level(
    levels: list[FieldAccessLevel] | tuple[FieldAccessLevel, ...] | frozenset[FieldAccessLevel],
) -> FieldAccessLevel | None:
    """按 DD-06 冻结的"最宽松者胜"合并字段等级。空输入返回 None。"""
    if not levels:
        return None
    return max(levels, key=lambda level: level.rank)


class HttpMethod(StrEnum):
    """API 资源支持的 HTTP 方法（DD-20 已冻结的取值域）。"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class SessionRevokeReason(StrEnum):
    """会话被撤销的原因（写入 `sessions.revoke_reason`）。

    Spec `04 §3` 要求记录 `revoke_reason`，但**未规定取值域**，
    因此本枚举属 INTERIM 技术取值，集中定义以免散落字符串
    （`revoke_reason` 只有本模块的所有者会写，取值完全可控）。

    取值说明：

    - `LOGOUT`：用户本人登出（`04 §4` "仅本人 logout"）；
    - `ADMIN_REVOKE`：管理员踢出单个会话（`04 §4` revoke one，Session Phase 落地）；
    - `REVOKE_ALL`：管理员踢出某用户全部会话（`04 §4` revoke all，同上）；
    - `TOKEN_REUSE_DETECTED`：检测到已轮换的 Refresh Token 被复用（DD-02 P4）；
    - `SUPERSEDED`：同账号新登录成功，旧会话被自动顶替下线
      （`DESIGN-DECISIONS §31`，人类裁定"新登录踢旧会话"）。
      与 `REVOKE_ALL` 的区别：它由**系统**在登录路径发起，不是管理员动作。
    """

    LOGOUT = "LOGOUT"
    ADMIN_REVOKE = "ADMIN_REVOKE"
    REVOKE_ALL = "REVOKE_ALL"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"  # noqa: S105 - 撤销原因枚举值
    SUPERSEDED = "SUPERSEDED"


class RefreshTokenRetirement(StrEnum):
    """已退役 Refresh Token 的退役原因（写入 `session_refresh_token_history.reason`）。

    与 `SessionRevokeReason` 分开的原因：退役原因与"会话为何被撤销"是两个问题。
    本枚举只有两种取值，且**恰好**对应两种截然不同的处理路径：

    - `ROTATED`：被正常轮换取代 → 该哈希若再次出现即为**盗用信号**
      （真正合法的持有者已经换到了新令牌），必须触发 family revocation；
    - `SESSION_REVOKED`：所属会话被撤销而一并失效 → 该哈希再次出现
      只是"拿着作废令牌再试一次"，属正常失败，**不得**误报为盗用。
    """

    ROTATED = "ROTATED"
    SESSION_REVOKED = "SESSION_REVOKED"


class MfaStatus(StrEnum):
    """用户 MFA 生命周期状态（Spec `04 §6` 冻结的三态）。

    ```text
    DISABLED → SETUP → ENABLED
    ```
    """

    DISABLED = "DISABLED"
    SETUP = "SETUP"
    ENABLED = "ENABLED"


class MfaPolicySubject(StrEnum):
    """MFA 策略的主体类型（DD-24 方案 A / Spec `04 §7`）。

    `04 §7` 冻结了 `user > role > system` 三层，其中 **system** 级
    由配置 / 系统参数提供，**不需要**落库；落库的是这里两种主体。

    为什么用"类型 + ID"而不是两张表或两个可空外键：见
    `app/models/mfa.py::MfaPolicy` 的类文档。
    本枚举只负责把"策略可以作用于什么"写成封闭集合 ——
    开放枚列会让"第三种主体"在无声中出现在库里。
    """

    USER = "USER"
    ROLE = "ROLE"


class AnnouncementAudience(StrEnum):
    """公告受众（`DESIGN-DECISIONS §32`；Spec 未定义）。

    只有两种，且**刻意不做**"指定用户 / 指定部门"：

    - `ALL`：全部 ACTIVE 且未删除的用户；
    - `ROLE`：**直接分配**了指定角色的用户。

    ⚠️ `ROLE` 用"直接分配"而不是"有效角色（含继承）"，这不是疏漏而是
    一次有意分叉：角色继承（DD-05）是**权限**关系 ——
    "他继承了这个角色的权限"不等于"他是这个角色的人"。
    公告受众是组织归属问题，用 `user_roles` 直接分配判定；
    若将来人类认为继承者也算受众，改动只在
    `NotificationRepository.resolve_role_audience` 一处（加一次
    `RoleInheritanceService.expand_role_ids` 的**反向**展开）。
    这一条明确登记在 §32，避免它被当成 bug 反复"修"。
    """

    ALL = "ALL"
    ROLE = "ROLE"


class NotificationCategory(StrEnum):
    """站内通知的分类（`DESIGN-DECISIONS §32`）。

    Spec 里**没有**站内通知这一域（`docs/spec/` 全 17 个文档零提及），
    因此这两个取值属技术推导。分类不是"展示标签"而是**语义分叉**：

    - `SYSTEM`：由**服务端事件**产生，收件人由事件本身决定
      （谁的会话被顶替、谁的口令被重置）。人不能凭空造一条，
      因此它没有对应的管理端点。
    - `ANNOUNCEMENT`：由**管理员**发布，收件人按**受众规则**扇出
      （全员 / 指定角色）。

    为什么不合并成一个类型、用 `event_code` 是否为空来区分：
    "谁有权产生它"是权限问题（前者无入口、后者需 `NOTIFICATION_MANAGE`），
    用可空列表达权限边界，就得在每个判权点重新推一遍"这行算不算公告"。
    """

    SYSTEM = "SYSTEM"
    ANNOUNCEMENT = "ANNOUNCEMENT"


class NotificationLevel(StrEnum):
    """站内通知的轻重（`DESIGN-DECISIONS §32`）。

    与 `AuditResult` 那类"枚举即真值"的不同之处：本枚举**只影响展示**
    （颜色 / 是否置顶），不参与任何判定。这正是它该进字典
    （`notification_level`，运营可改文案）而 `AuditResult` 不进字典的原因 ——
    字典是可改的数据，把判定依据放进可改数据等于把规则交给运营。
    """

    INFO = "INFO"
    WARNING = "WARNING"
    IMPORTANT = "IMPORTANT"


# ===========================================================================
# 业务用户 / 成长 / 工具 / 博客 域枚举（V3.1 数据库设计基线）
# ---------------------------------------------------------------------------
# 仅收录 DDL 基线或域文档**显式给出取值域**的列；未给出取值域的 status /
# 类型列一律用普通 VARCHAR（不发明取值、不猜业务规则，见 DESIGN-DECISIONS §33）。
# ===========================================================================


class BizUserLoginIdentityType(StrEnum):
    """业务用户登录身份类型（`02 统一业务用户域 §3`）。

    `USERNAME` / `EMAIL` / `PHONE` 三种，域文档显式枚举。
    """

    USERNAME = "USERNAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class ToolExecutionMode(StrEnum):
    """工具执行模式（`04 Tools 工具域 §2`）。

    `FRONTEND` 纯前端执行 / `BACKEND` 后端执行 / `ASYNC` 异步执行。
    """

    FRONTEND = "FRONTEND"
    BACKEND = "BACKEND"
    ASYNC = "ASYNC"


class ToolLifecycleStatus(StrEnum):
    """工具生命周期状态（`04 Tools 工具域 §2`）。

    `DRAFT` 草稿 / `TESTING` 测试中 / `ACTIVE` 已上线 / `DISABLED` 已下线。
    """

    DRAFT = "DRAFT"
    TESTING = "TESTING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ToolAccessSubjectType(StrEnum):
    """工具访问主体类型（`04 Tools 工具域 §5`）。

    `GUEST` 游客 / `USER_LEVEL` 用户等级（必须同时带 `user_level_id`）。
    """

    GUEST = "GUEST"
    USER_LEVEL = "USER_LEVEL"


class BlogAuthorApplicationStatus(StrEnum):
    """博客作者申请状态（`05 Blog 博客域 §2`）。

    `PENDING` 待审核 / `APPROVED` 通过 / `REJECTED` 拒绝。
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BlogArticleStatus(StrEnum):
    """博客文章状态（`05 Blog 博客域 §4`）。

    `DRAFT` 草稿 / `PENDING_REVIEW` 待审核 / `REJECTED` 驳回 /
    `PUBLISHED` 已发布 / `OFFLINE` 已下线。
    """

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    OFFLINE = "OFFLINE"


class CosmeticType(StrEnum):
    """装扮类型（`03 用户成长中心 §11`）。

    `AVATAR` 头像 / `AVATAR_FRAME` 头像框 / `CROWN` 皇冠 /
    `BADGE` 徽章 / `TITLE` 头衔 / `NAME_EFFECT` 昵称特效。
    """

    AVATAR = "AVATAR"
    AVATAR_FRAME = "AVATAR_FRAME"
    CROWN = "CROWN"
    BADGE = "BADGE"
    TITLE = "TITLE"
    NAME_EFFECT = "NAME_EFFECT"


# 其余未在 DDL 基线 / 域文档显式枚举取值域的 status / 类型列
# （如 biz_user.status、tool_category.status、blog_category.status、
# blog_author.status、blog_comment.status、各类 rule/level/cosmetic 的 status、
# 以及 visibility / gender / operator_type / transaction_type / source_type /
# event_type / result 等）一律以普通 VARCHAR 落库，取值域等待冻结决策，
# 不在 Agent 侧发明。


__all__ = [
    "FIELD_ACCESS_READABLE",
    "FIELD_ACCESS_WRITABLE",
    "AnnouncementAudience",
    "BizUserLoginIdentityType",
    "BlogArticleStatus",
    "BlogAuthorApplicationStatus",
    "CosmeticType",
    "DepartmentStatus",
    "DictStatus",
    "FieldAccessLevel",
    "HttpMethod",
    "MfaPolicySubject",
    "MfaStatus",
    "NotificationCategory",
    "NotificationLevel",
    "PermissionResourceType",
    "PermissionStatus",
    "RefreshTokenRetirement",
    "RoleStatus",
    "SessionRevokeReason",
    "SystemParamStatus",
    "SystemParamType",
    "ToolAccessSubjectType",
    "ToolExecutionMode",
    "ToolLifecycleStatus",
    "UserStatus",
    "most_permissive_field_level",
]
