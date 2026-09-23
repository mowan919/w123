# ===========================================================================
# VCTN API 镜像
#
# 说明：
# - 基础镜像标签属于 DD-16（运行时版本已由人类裁定为 Python 3.14），
#   slim 变体为保守选择，可按需调整。
# - 以非 root 用户运行，符合最小权限原则。
# ===========================================================================

FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

WORKDIR /srv/app

# 先装依赖，利用镜像层缓存
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi==0.141.1" \
    "uvicorn[standard]==0.53.0" \
    "sqlalchemy[asyncio]==2.0.54" \
    "asyncpg==0.31.0" \
    "alembic==1.20.0" \
    "pydantic==2.13.5" \
    "pydantic-settings==2.15.0" \
    "redis==8.1.0"

# 再复制应用代码
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --shell /usr/sbin/nologin vctn \
    && chown -R vctn:vctn /srv/app
USER vctn

EXPOSE 8000

# 探针：Spec 13 §4 —— application health
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
