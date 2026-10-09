from sqlalchemy import create_engine, text
import pytest

from init_fresh_db import initialize_empty_database


def test_explicit_fresh_target_initializes_and_refuses_second_run(tmp_path):
    url = f"sqlite:///{tmp_path / 'new-v61.db'}"
    assert initialize_empty_database(url, confirmed=True) == "v94o01"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO cases(case_number,description,time_precision) VALUES ('SYNTHETIC','保留原文','unknown')"))
    with pytest.raises(ValueError, match="target_not_empty"):
        initialize_empty_database(url, confirmed=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT description FROM cases")) == "保留原文"
        assert connection.scalar(text("SELECT COUNT(*) FROM case_revisions")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM result_catalog_projections")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM result_catalog_references")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM case_history_vector_reuse")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM case_import_source_records")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM output_templates")) == 0
    engine.dispose()


def test_fresh_target_cannot_implicitly_use_configured_database(tmp_path):
    with pytest.raises(ValueError, match="confirmation"):
        initialize_empty_database(f"sqlite:///{tmp_path / 'never-created.db'}")
    assert not (tmp_path / "never-created.db").exists()
    with pytest.raises(ValueError, match="explicit_absolute"):
        initialize_empty_database("sqlite:///aicommander.db", confirmed=True)
