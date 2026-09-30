"""V3.1 结构层通用 CRUD 底座（VCTN §33）。

仅承载「配置 / 字典 / 流水」类实体的标准 CRUD 数据与权限口径；
业务规则（等级计算 / 积分记账 / 工具执行 / 博客发布流）属 §09-D 未冻结项，
不在此下沉（见 `base.py` 模块文档）。
"""

from app.crud.base import BaseCrudRepository, BaseCrudService, CrudPage

__all__ = ["BaseCrudRepository", "BaseCrudService", "CrudPage"]
