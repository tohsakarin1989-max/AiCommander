from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.database import Base
from app.utils.logger import logger


def ensure_auto_created_schema(engine: Engine) -> None:
    """
    AUTO_CREATE_TABLES 适用于本地 SQLite/轻量部署。create_all 只会建表不会补列，
    这里为已存在的表补充新增的可空列，避免本地旧库在模型升级后直接查询失败。
    正式环境仍应优先使用 Alembic 迁移。
    """
    with engine.begin() as conn:
        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        preparer = conn.dialect.identifier_preparer

        for table in Base.metadata.tables.values():
            if table.name not in table_names:
                continue

            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns or column.primary_key:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    logger.warning(
                        "跳过自动补列 %s.%s：非空且无默认值，请使用 Alembic 迁移",
                        table.name,
                        column.name,
                    )
                    continue

                type_sql = column.type.compile(dialect=conn.dialect)
                sql = (
                    f"ALTER TABLE {preparer.quote(table.name)} "
                    f"ADD COLUMN {preparer.quote(column.name)} {type_sql}"
                )
                try:
                    conn.exec_driver_sql(sql)
                    existing_columns.add(column.name)
                    logger.info("已自动补充数据库列 %s.%s", table.name, column.name)
                except Exception as exc:
                    logger.warning("自动补充数据库列 %s.%s 失败: %s", table.name, column.name, exc)
