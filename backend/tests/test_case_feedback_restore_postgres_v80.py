"""Two explicit phases used only by verify-v80-postgres-restore.py.

The orchestrator uses native pg_dump/pg_restore between the phases, with two
empty databases in one disposable, network-isolated PostgreSQL container.
"""
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
import re
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.services.case_feedback_semantics import feedback_state, known_feedback_value


PHASE = os.environ.get("AIC_V80_RESTORE_PHASE")
URL = os.environ.get("AIC_V80_RESTORE_URL")
EVIDENCE = Path(os.environ.get("AIC_V80_RESTORE_EVIDENCE", "/evidence"))
pytestmark = pytest.mark.skipif(not PHASE or not URL, reason="requires isolated restore orchestrator")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _engine(database):
    url = make_url(URL)
    assert url.host == "127.0.0.1" and url.username == "postgres" and url.database == database
    return create_engine(URL)


def _comparable(snapshot):
    """Only known, lossless PostgreSQL 16 dump/reparse spellings.

    Keep the raw definitions in evidence; do not ignore constraints or strip
    arbitrary parentheses/casts (which could change a predicate's meaning).
    """
    result = deepcopy(snapshot)
    constant = r"'(?:[^']|'')*'::character varying"
    array = re.compile(r"\(ARRAY\[(" + constant + r"(?:, " + constant + r")*)\]\)::text\[\]")

    def definition(value):
        value = array.sub(lambda match: "ARRAY[" + ", ".join(
            f"({item})::text" for item in re.findall(constant, match[1])) + "]", value)
        value = value.replace("((dimension >= 1) AND (dimension <= 4096)) AND (vector_dims(embedding) = dimension)",
                              "(dimension >= 1) AND (dimension <= 4096) AND (vector_dims(embedding) = dimension)")
        value = value.replace("((longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision)) AND",
                              "(longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision) AND")
        return value

    for key in ("indexes", "constraints"):
        for row in result[key]:
            row[-1] = definition(row[-1])
    return result


def _snapshot(engine):
    with engine.connect() as db:
        columns = [list(row) for row in db.execute(text("SELECT table_name,column_name,ordinal_position,"
            "data_type,udt_name,is_nullable,column_default FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name,ordinal_position"))]
        indexes = [list(row) for row in db.execute(text("SELECT tablename,indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename,indexname"))]
        constraints = [list(row) for row in db.execute(text("SELECT c.relname,k.conname,pg_get_constraintdef(k.oid) "
            "FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' ORDER BY c.relname,k.conname"))]
        tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        quote = engine.dialect.identifier_preparer.quote
        counts = {table: db.scalar(text(f"SELECT count(*) FROM public.{quote(table)}")) for table in tables}
        rows = db.execute(text("SELECT row_to_json(c) FROM cases c ORDER BY id")).scalars().all()
        sequences = {}
        for name in db.execute(text("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")).scalars():
            sequences[name] = list(db.execute(text(f"SELECT last_value,is_called FROM public.{quote(name)}")).one())
        semantics = {row["case_number"]: {field: {"state": feedback_state(row, field),
            "known_value": known_feedback_value(row, field)} for field in ("police_reported", "case_filed")} for row in rows}
        return {"revision": db.scalar(text("SELECT version_num FROM alembic_version")), "columns": columns,
            "indexes": indexes, "constraints": constraints, "table_counts": counts, "sequences": sequences,
            "case_records": rows, "feedback_semantics": semantics}


@pytest.mark.skipif(PHASE != "seed", reason="seed phase only")
def test_seed_legacy_and_new_feedback_before_native_backup(record_property):
    engine = _engine("aicommander_v80_restore_source")
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": URL, "ENABLE_VECTOR_DB": "false", "ENABLE_AGENT_LAB": "false", "AGENT_MODE": "off"}

    def migrate(revision):
        completed = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=backend, env=env, capture_output=True, text=True, timeout=90)
        assert completed.returncode == 0, completed.stderr

    migrate("v75r01")
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(case_number,description,police_reported,case_filed) VALUES "
            "('RESTORE-LEGACY','合成旧记录：历史默认值，来源未确认。',false,true),"
            "('RESTORE-NULL','合成旧记录：未获反馈，不能解释为否。',null,null)"))
    migrate("v80f01")
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(case_number,description,police_reported,case_filed,feedback_known_fields) VALUES "
            "('RESTORE-NEW','升级后新增原文：已明确报案；立案反馈为否，移交不等于办结。',true,false,"
            "CAST('[\"police_reported\",\"case_filed\"]' AS JSON)),"
            "('RESTORE-UNKNOWN','升级后新增原文：仅登记掌握情况，尚未获得后续反馈。',null,null,CAST('[]' AS JSON))"))
    before = _snapshot(engine)
    assert before["revision"] == "v80f01" and before["table_counts"]["cases"] == 4
    assert before["feedback_semantics"]["RESTORE-LEGACY"]["police_reported"] == {"state": "legacy_unverified", "known_value": None}
    assert before["feedback_semantics"]["RESTORE-NEW"]["case_filed"] == {"state": "known", "known_value": False}
    assert before["feedback_semantics"]["RESTORE-NEW"]["police_reported"] == {"state": "known", "known_value": True}
    assert before["feedback_semantics"]["RESTORE-NULL"]["police_reported"]["state"] == "unknown"
    assert before["feedback_semantics"]["RESTORE-UNKNOWN"]["case_filed"]["state"] == "unknown"
    (EVIDENCE / "before-restore.json").write_text(json.dumps(before, ensure_ascii=False, sort_keys=True, indent=2))
    record_property("source_snapshot_sha256", _digest(before))
    record_property("source_case_count", 4)
    engine.dispose()


@pytest.mark.skipif(PHASE != "verify", reason="restore verification phase only")
def test_native_restore_preserves_schema_new_originals_and_feedback_semantics(record_property):
    engine = _engine("aicommander_v80_restore_target")
    before = json.loads((EVIDENCE / "before-restore.json").read_text())
    restored = _snapshot(engine)
    (EVIDENCE / "after-restore.json").write_text(json.dumps(restored, ensure_ascii=False, sort_keys=True, indent=2))
    assert _comparable(restored) == _comparable(before)
    assert restored["revision"] == "v80f01" and restored["table_counts"]["cases"] == 4
    assert next(row for row in restored["case_records"] if row["case_number"] == "RESTORE-NEW")["description"].startswith("升级后新增原文")
    # Recovery should also preserve a usable primary-key sequence. Roll back
    # the new row; the original restored cases are never overwritten.
    with engine.connect() as db:
        transaction = db.begin()
        identifier = db.scalar(text("INSERT INTO cases(case_number,description) "
            "VALUES ('RESTORE-ID-PROBE','合成恢复后的序列检查') RETURNING id"))
        assert identifier > max(row["id"] for row in restored["case_records"])
        transaction.rollback()
    source_url = make_url(URL).set(database="aicommander_v80_restore_source")
    source_engine = create_engine(source_url)
    assert _snapshot(source_engine) == before  # Dump/restore never modifies the source.
    differences = [{"kind": key, "table": source[0], "name": source[1], "before": source[-1], "after": target[-1]}
        for key in ("indexes", "constraints") for source, target in zip(before[key], restored[key]) if source != target]
    summary = {"schema_version": "v80-feedback-restore-evidence-1", "synthetic_only": True,
        "revision": restored["revision"], "tables_compared": len(restored["table_counts"]),
        "cases_compared": len(restored["case_records"]), "snapshot_sha256": _digest(restored),
        "canonical_snapshot_sha256": _digest(_comparable(restored)),
        "schema_records_sequences_equal_after_known_pg_deparse_normalization": True,
        "equivalent_definition_spellings": differences, "source_unchanged": True,
        "restored_insert_sequence_works": True, "feedback_semantics": restored["feedback_semantics"]}
    (EVIDENCE / "restore-verification.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    for key in ("revision", "tables_compared", "cases_compared", "snapshot_sha256"):
        record_property(key, summary[key])
    engine.dispose()
    source_engine.dispose()
