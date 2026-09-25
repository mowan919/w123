"""应用配置。

Spec 13 §2 Configuration：敏感配置不得硬编码
（DB password / Redis password / signing secret / encryption key / MFA encryption key），
应通过环境变量或正式 Secret Management 注入。

本模块只从环境变量 / .env 读取，仓库内不保存任何真实凭据。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "dev", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """运行时配置。所有字段均可通过环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "VCTN"
    app_env: AppEnv = "local"
    debug: bool = False

    # Spec 08 §1 Base：/api/v1/admin
    api_v1_prefix: str = "/api/v1/admin"

    # 认证端点前缀（Phase 4）。
    #
    # INTERIM（已向人类报备并获批）：Spec `08 §3` 只给出 `/auth/*` 相对路径，
    # 而 `08 §1` 的 Base 是 `/api/v1/admin`。认证端点**不属于** admin 资源域
    # （登录时尚未成为"管理员操作者"），因此独立为 `/api/v1/auth`。
    # 该取值记录在 `docs/DESIGN-DECISIONS.md`，Spec 冻结后只需改此一处。
    auth_v1_prefix: str = "/api/v1/auth"

    # 公开查询前缀（Phase 7）。
    #
    # Spec `05 §4` / `08 §9` 把公开字典查询写成 `/api/v1/dicts/{dictCode}`，
    # 即**不在** admin 资源域下。这里显式给出前缀而不是复用 admin 前缀：
    # 把"公开域"与"资源域"写在同一处配置里，边界才看得见（`08 §1` 的 Base 是
    # `/api/v1/admin`，任何不落在它下面的路径都必须有明确出处）。
    #
    # 注意：`05 §4`/`08 §9` 只规定路径，**未**规定认证要求 → 本端点仍要求
    # 已认证（JUDGMENT-7-03，理由见 `app/api/v1/endpoints/dicts.py`）。
    public_v1_prefix: str = "/api/v1"

    # Spec 06 §4 / 13 §5 Logging
    log_level: LogLevel = "INFO"
    log_json: bool = True

    # ------------------------------------------------------------------
    # PostgreSQL
    # 本地开发不安装实例，通过环境变量指向可用地址
    # ------------------------------------------------------------------
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "vctn"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "vctn"

    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # ------------------------------------------------------------------
    # Redis
    # 注意：Redis Key 命名规范尚未冻结（UNRESOLVED DESIGN DECISION），
    # 本阶段只建立连接，不定义任何 key 结构。
    # ------------------------------------------------------------------
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr = SecretStr("")
    redis_socket_timeout: float = 5.0

    # ------------------------------------------------------------------
    # Snowflake
    # Frozen（Spec 00 §6 / 07 §2 / 15 D-014）：BIGINT + Snowflake，
    # API JSON 序列化为字符串，禁止自增业务 ID，禁止 UUID 业务主键。
    #
    # 以下位分配与 epoch 参数属于 DD-14 的技术参数，
    # Spec 尚未冻结 → UNRESOLVED DESIGN DECISION，此处为保守默认值，
    # 必须可由环境变量覆盖，待人类冻结后回填。
    # ------------------------------------------------------------------
    snowflake_worker_id: int = Field(default=1, ge=0)
    snowflake_datacenter_id: int = Field(default=1, ge=0)
    snowflake_epoch_ms: int = 1735689600000  # 2025-01-01T00:00:00Z

    # ------------------------------------------------------------------
    # Secrets —— 13 §2
    #
    # DD-02 已裁定为**不透明令牌**（不签发 JWT），因此当前实现
    # **不使用** `signing_secret`。仍然保留该配置项与 prod fail-closed 校验：
    # 它是 Spec `13 §2` 冻结的密钥清单的一部分，
    # 而"移除一个冻结要求"不属于实现阶段可以自行决定的事（Spec 14 §1）。
    # 未使用 ≠ 可以删除；如需移除，应由人类在 Spec 中裁定。
    #
    # `encryption_key` / `mfa_encryption_key` 由 Phase 5（MFA Secret 加密保存，
    # `04 §6`）使用。
    # ------------------------------------------------------------------
    signing_secret: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")
    mfa_encryption_key: SecretStr = SecretStr("")

    # ------------------------------------------------------------------
    # MFA 策略（DD-01 方案 A 已裁定）
    #
    # Spec `04 §7` 冻结了策略层级 `user > role > system`，但 V1 具体 Provider
    # 未冻结。DD-01 方案 A 的落地口径：
    #   - 系统级默认值 = 本配置项（**默认 False**：不要求 MFA）；
    #   - user / role 两级策略的存储属 Phase 5；
    #   - 若本项被设为 True 而系统尚无可用 Provider，
    #     `MfaService.check_login` 会 **fail-closed 报错**而不是静默放行。
    # 因此在 Phase 5 落地 Provider 之前，把它改成 True 会让登录**明确失败**，
    # 这正是期望行为（配置问题必须立刻可见）。
    # ------------------------------------------------------------------
    mfa_required_default: bool = False

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("api_v1_prefix", "auth_v1_prefix", "public_v1_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("api_v1_prefix 必须以 / 开头")
        return value.rstrip("/") or "/"

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> Settings:
        """生产环境禁止使用空密钥启动。

        安全默认值：保守实现，只阻止明显不安全的 prod 启动；
        local / dev / test 环境放行，便于无凭据的开发与测试。
        """
        if self.app_env != "prod":
            return self

        missing: list[str] = []
        if not self.postgres_password.get_secret_value():
            missing.append("POSTGRES_PASSWORD")
        if not self.redis_password.get_secret_value():
            missing.append("REDIS_PASSWORD")
        if not self.signing_secret.get_secret_value():
            missing.append("SIGNING_SECRET")
        if not self.encryption_key.get_secret_value():
            missing.append("ENCRYPTION_KEY")
        # DD-22 P2：MFA Secret 的加密密钥同样必须在 prod 显式提供。
        # 缺它的话，`MfaSecretBox` 会在**第一次有人启用 MFA 时**才失败 ——
        # 把一个"启动时就该炸"的配置错误，推迟成运行期某个用户点击后的报错。
        if not self.mfa_encryption_key.get_secret_value():
            missing.append("MFA_ENCRYPTION_KEY")
        if missing:
            raise ValueError("生产环境缺少必需的密钥配置：" + ", ".join(missing))
        return self

    # ------------------------------------------------------------------
    # Derived
    # ------------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN（asyncpg 驱动）。"""
        password = quote_plus(self.postgres_password.get_secret_value())
        user = quote_plus(self.postgres_user)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_safe(self) -> str:
        """脱敏后的 DSN，可安全写入日志。"""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:***"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis DSN。"""
        password = self.redis_password.get_secret_value()
        auth = f":{quote_plus(password)}@" if password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def redis_url_safe(self) -> str:
        """脱敏后的 Redis DSN，可安全写入日志。"""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程级单例配置。"""
    return Settings()


settings = get_settings()
