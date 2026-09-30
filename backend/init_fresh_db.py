"""Initialize an explicitly selected EMPTY database without touching a working DB.

The existing migration chain remains the authoritative schema (including PostGIS
indexes and vector constraints). This is not a destructive reset/import command.
"""
import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def initialize_empty_database(database_url: str, *, confirmed: bool = False) -> str:
    if not confirmed:
        raise ValueError("explicit_empty_database_confirmation_required")
    url = make_url(database_url)
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("only_sqlite_and_postgresql_supported")
    if url.get_backend_name() == "sqlite" and (not url.database or url.database == ":memory:" or not Path(url.database).is_absolute()):
        raise ValueError("fresh_sqlite_requires_explicit_absolute_file")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            if inspect(connection).get_table_names() or inspect(connection).get_view_names():
                raise ValueError("target_not_empty_no_changes_performed")
            if connection.dialect.name == "postgresql" and connection.scalar(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                      AND n.nspname NOT LIKE 'pg_toast%'
                      AND n.nspname NOT LIKE 'pg_temp_%'
                      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                )
            """)):
                raise ValueError("target_not_empty_no_changes_performed")
            # env.py accepts this prechecked connection; never fall back to settings.
            config = Config(str(Path(__file__).parent / "alembic.ini"))
            config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            return connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="只初始化明确指定的空库；不会删除、导入或改动现用数据库")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--confirm-empty-target", action="store_true")
    args = parser.parse_args()
    revision = initialize_empty_database(args.database_url, confirmed=args.confirm_empty_target)
    print(f"空库初始化完成，迁移版本 {revision}。尚未导入业务资料或配置模型。")


if __name__ == "__main__":
    main()
