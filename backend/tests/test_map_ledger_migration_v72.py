"""Disposable SQLite upgrade with real pre-existing parent and child records."""
from sqlalchemy import create_engine, inspect, text

from tests.test_result_material_migration_v65 import migrate


def test_v72_upgrade_preserves_detail_ids_original_bytes_and_enables_autoincrement(tmp_path):
    url = f"sqlite:///{tmp_path / 'synthetic-v72.sqlite'}"
    result = migrate(url, "upgrade", "v71d01")
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) VALUES(7201,'V72-SYNTHETIC','合成原始记录',1)"))
        db.execute(text("INSERT INTO case_locations(id,case_id,role,precision,source_note) VALUES(7201,7201,'incident','unknown','原始地点')"))
        db.execute(text("INSERT INTO oil_measurements(id,case_id,value,unit,stage,method,water_cut_basis,source_note) "
                        "VALUES(7201,7201,12,'tonne','recovered','合成称重','质量口径','原始计量')"))
        db.execute(text("INSERT INTO evidence_objects(id,storage_key,availability,sensitivity,content) VALUES(7201,'synthetic-original','available','internal',:raw)"), {"raw": b'v72-synthetic-raw'})
        db.execute(text("INSERT INTO source_references(id,case_id,evidence_object_id,kind,locator) VALUES(7201,7201,7201,'original','{}')"))
    result = migrate(url, "upgrade", "v72m01")
    assert result.returncode == 0, result.stderr
    engine.dispose()
    with engine.begin() as db:
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        assert db.scalar(text("SELECT source_note FROM case_locations WHERE id=7201")) == "原始地点"
        assert db.scalar(text("SELECT unit FROM oil_measurements WHERE id=7201")) == "tonne"
        assert db.scalar(text("SELECT content FROM evidence_objects WHERE id=7201")) == b'v72-synthetic-raw'
        assert db.scalar(text("SELECT evidence_object_id FROM source_references WHERE id=7201")) == 7201
        for table in ("case_locations", "oil_measurements", "case_vehicles", "case_persons", "case_evidence",
                      "oil_recovery_records", "case_tips", "case_source_links", "evidence_objects", "source_references"):
            ddl = db.scalar(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": table})
            assert "AUTOINCREMENT" in ddl, table
        db.execute(text("DELETE FROM case_locations WHERE id=7201"))
        db.execute(text("INSERT INTO case_locations(case_id,role,precision) VALUES(7201,'incident','unknown')"))
        assert db.scalar(text("SELECT id FROM case_locations WHERE case_id=7201")) > 7201
        assert "map_field_decisions" in inspect(db).get_table_names()
        assert "original_evidence_object_id" in {column["name"] for column in inspect(db).get_columns("map_ingest_runs")}
    result = migrate(url, "downgrade", "v71d01")
    assert result.returncode == 0, result.stderr
    engine.dispose()
