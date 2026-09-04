#!/usr/bin/env python3
"""将 AICommander SQLite 业务数据一次性迁移到空 PostgreSQL 数据库。"""

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Boolean, Date, DateTime, JSON, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models  # noqa: E402,F401
from app.database import Base  # noqa: E402


EXPECTED_ALEMBIC_HEAD = "f7d2a9c4b610"
SKIPPED_TABLES = {"users", "user_sessions", "audit_logs"}
SCHEMA_SEEDED_CONFIG_KEYS = {
    "chain_radius_km",
    "chain_time_window_days",
    "chain_min_confidence",
}


class MigrationError(RuntimeError):
    pass


def _fernet(secret: str) -> Fernet:
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _decrypt_source_secret(value: str, source_secret: str) -> str:
    try:
        return _fernet(source_secret).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise MigrationError("源数据库密钥无法使用提供的 SOURCE_SECRET_KEY 解密") from exc


def _encrypt_target_secret(value: str, target_secret: str) -> str:
    return _fernet(target_secret).encrypt(value.encode()).decode()


def transform_sensitive_row(
    table_name: str,
    row: dict[str, Any],
    *,
    source_secret: str | None,
    target_secret: str,
) -> dict[str, Any]:
    transformed = dict(row)
    if table_name == "ai_models" and transformed.get("api_key"):
        if not source_secret:
            raise MigrationError("迁移 AI 模型配置必须提供源系统 SECRET_KEY")
        plaintext = _decrypt_source_secret(str(transformed["api_key"]), source_secret)
        transformed["api_key"] = _encrypt_target_secret(plaintext, target_secret)

    if table_name == "system_configs" and transformed.get("config_type") == "api_key":
        stored = str(transformed.get("config_value") or "")
        if stored:
            if transformed.get("is_encrypted") == "true":
                if not source_secret:
                    raise MigrationError("迁移已加密系统配置必须提供源系统 SECRET_KEY")
                plaintext = _decrypt_source_secret(stored, source_secret)
            else:
                plaintext = stored
            transformed["config_value"] = _encrypt_target_secret(plaintext, target_secret)
        else:
            transformed["config_value"] = ""
        transformed["is_encrypted"] = "true"
    return transformed


def _convert_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(column.type, JSON) and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise MigrationError(f"{column.table.name}.{column.name} 包含无效 JSON") from exc
    if isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise MigrationError(f"{column.table.name}.{column.name} 包含无效时间") from exc
    if isinstance(column.type, Date) and not isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise MigrationError(f"{column.table.name}.{column.name} 包含无效日期") from exc
    return value


def prepare_row(
    table: Table,
    source_row: dict[str, Any],
    *,
    source_secret: str | None,
    target_secret: str,
) -> dict[str, Any]:
    known_columns = {column.name: column for column in table.columns}
    row = {
        name: _convert_value(known_columns[name], value)
        for name, value in source_row.items()
        if name in known_columns
    }
    return transform_sensitive_row(
        table.name,
        row,
        source_secret=source_secret,
        target_secret=target_secret,
    )


def _chunks(rows: list[dict[str, Any]], size: int = 200) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index:index + size]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ordered_target_tables(source_tables: set[str]) -> list[Table]:
    candidates = {
        name: table
        for name, table in Base.metadata.tables.items()
        if name in source_tables and name not in SKIPPED_TABLES
    }
    dependencies: dict[str, set[str]] = {}
    for name, table in candidates.items():
        dependencies[name] = {
            foreign_key.column.table.name
            for foreign_key in table.foreign_keys
            if foreign_key.column.table.name in candidates
            and foreign_key.column.table.name != name
            and not (name == "meetings" and foreign_key.parent.name == "final_report_id")
        }

    ordered: list[Table] = []
    emitted: set[str] = set()
    while len(ordered) < len(candidates):
        ready = sorted(
            name
            for name, required in dependencies.items()
            if name not in emitted and required <= emitted
        )
        if not ready:
            remaining = sorted(set(candidates) - emitted)
            raise MigrationError(f"无法解析数据表迁移顺序: {remaining}")
        for name in ready:
            ordered.append(candidates[name])
            emitted.add(name)
    return ordered


def _remove_schema_seed_rows(target: Connection, table: Table) -> int:
    rows = target.execute(select(table.c.config_key)).all()
    if not rows:
        return 0
    keys = {str(row[0]) for row in rows}
    if not keys <= SCHEMA_SEEDED_CONFIG_KEYS:
        return 0
    target.execute(table.delete())
    return len(rows)


def _verify_source(source: Connection) -> None:
    result = source.execute(text("PRAGMA integrity_check")).scalar()
    if result != "ok":
        raise MigrationError(f"源 SQLite 完整性检查失败: {result}")


def _verify_target(target: Connection, allow_sqlite_target: bool) -> None:
    dialect = target.engine.dialect.name
    if dialect != "postgresql" and not allow_sqlite_target:
        raise MigrationError("目标数据库必须是 PostgreSQL")
    inspector = inspect(target)
    if "alembic_version" not in inspector.get_table_names():
        raise MigrationError("目标数据库尚未运行 Alembic 迁移")
    head = target.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if head != EXPECTED_ALEMBIC_HEAD:
        raise MigrationError(
            f"目标数据库版本为 {head!r}，要求 {EXPECTED_ALEMBIC_HEAD!r}"
        )


def _reset_postgres_sequence(target: Connection, table: Table) -> None:
    if target.engine.dialect.name != "postgresql":
        return
    integer_primary_keys = [
        column for column in table.primary_key.columns
        if column.autoincrement is True or column.autoincrement == "auto"
    ]
    if len(integer_primary_keys) != 1:
        return
    column = integer_primary_keys[0]
    preparer = target.engine.dialect.identifier_preparer
    table_name = preparer.quote(table.name)
    column_name = preparer.quote(column.name)
    target.execute(text(
        "SELECT setval(pg_get_serial_sequence(:table_name, :column_name), "
        f"COALESCE((SELECT MAX({column_name}) FROM {table_name}), 1), "
        f"EXISTS(SELECT 1 FROM {table_name}))"
    ), {"table_name": table.name, "column_name": column.name})


def migrate(
    source_path: Path,
    target_url: str,
    *,
    source_secret: str | None,
    target_secret: str,
    allow_sqlite_target: bool = False,
) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise MigrationError(f"源数据库不存在: {source_path}")
    if not target_secret:
        raise MigrationError("目标系统 SECRET_KEY 不能为空")

    source_url = f"sqlite:///file:{source_path}?mode=ro&uri=true"
    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    source_tables = set(source_metadata.tables)
    target_tables = _ordered_target_tables(source_tables)

    report: dict[str, Any] = {
        "source": str(source_path),
        "source_sha256": _sha256_file(source_path),
        "target_dialect": target_engine.dialect.name,
        "alembic_head": EXPECTED_ALEMBIC_HEAD,
        "tables": {},
    }

    with source_engine.connect() as source, target_engine.begin() as target:
        _verify_source(source)
        _verify_target(target, allow_sqlite_target)

        target_table_names = set(inspect(target).get_table_names())
        business_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name in target_table_names and name not in SKIPPED_TABLES
        ]
        seeded_rows_removed = 0
        system_configs = Base.metadata.tables.get("system_configs")
        if system_configs is not None and "system_configs" in source_tables:
            seeded_rows_removed = _remove_schema_seed_rows(target, system_configs)
        target_counts = {
            table.name: target.execute(select(func.count()).select_from(table)).scalar_one()
            for table in business_tables
        }
        nonempty = {name: count for name, count in target_counts.items() if count > 0}
        if nonempty:
            raise MigrationError(f"目标业务表必须为空，发现已有数据: {nonempty}")
        report["removed_schema_seed_rows"] = seeded_rows_removed

        deferred_report_links: list[tuple[int, int]] = []
        for target_table in target_tables:
            source_table = source_metadata.tables[target_table.name]
            statement = select(source_table)
            if len(source_table.primary_key.columns):
                statement = statement.order_by(*source_table.primary_key.columns)
            raw_rows = [dict(row._mapping) for row in source.execute(statement)]
            if target_table.name == "meetings":
                for row in raw_rows:
                    if row.get("id") is not None and row.get("final_report_id") is not None:
                        deferred_report_links.append((int(row["id"]), int(row["final_report_id"])))
                        row["final_report_id"] = None
            rows = [
                prepare_row(
                    target_table,
                    row,
                    source_secret=source_secret,
                    target_secret=target_secret,
                )
                for row in raw_rows
            ]
            for batch in _chunks(rows):
                if batch:
                    target.execute(target_table.insert(), batch)
            _reset_postgres_sequence(target, target_table)
            target_count = target.execute(select(func.count()).select_from(target_table)).scalar_one()
            if target_count != len(raw_rows):
                raise MigrationError(
                    f"{target_table.name} 核数失败: source={len(raw_rows)}, target={target_count}"
                )
            report["tables"][target_table.name] = {
                "source_rows": len(raw_rows),
                "target_rows": target_count,
            }

        if deferred_report_links:
            meetings = Base.metadata.tables["meetings"]
            for meeting_id, report_id in deferred_report_links:
                result = target.execute(
                    meetings.update()
                    .where(meetings.c.id == meeting_id)
                    .values(final_report_id=report_id)
                )
                if result.rowcount != 1:
                    raise MigrationError(f"会议 {meeting_id} 的报告关联恢复失败")
        report["restored_meeting_report_links"] = len(deferred_report_links)

    report["table_count"] = len(report["tables"])
    report["row_count"] = sum(item["target_rows"] for item in report["tables"].values())
    report["status"] = "success"
    return report


def _read_secret_file(path: str | None) -> str | None:
    if not path:
        return os.getenv("SOURCE_SECRET_KEY")
    secret_path = Path(path).expanduser()
    if not secret_path.is_file():
        raise MigrationError(f"源密钥文件不存在: {secret_path}")
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise MigrationError("源密钥文件为空")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="源 SQLite 数据库文件")
    parser.add_argument(
        "--target-url",
        default=os.getenv("DATABASE_URL"),
        help="目标 PostgreSQL URL，默认读取 DATABASE_URL",
    )
    parser.add_argument("--source-secret-key-file", help="源系统 SECRET_KEY 文件")
    parser.add_argument("--report", help="迁移核验报告 JSON 输出路径")
    parser.add_argument("--allow-sqlite-target-for-tests", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.target_url:
        raise MigrationError("必须通过 --target-url 或 DATABASE_URL 指定目标数据库")
    target_secret = os.getenv("SECRET_KEY")
    if not target_secret:
        raise MigrationError("目标环境缺少 SECRET_KEY")

    report = migrate(
        Path(args.source),
        args.target_url,
        source_secret=_read_secret_file(args.source_secret_key_file),
        target_secret=target_secret,
        allow_sqlite_target=args.allow_sqlite_target_for_tests,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MigrationError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
