"""Run the same source-ACL/JSON search regressions against an opt-in synthetic PG.

The fixed container/loopback binding is verified, a unique database is created,
and no old database is touched. Every test is rolled back; the database remains.
"""
import json
import os
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.database import Base
from tests.test_facility_search_v73 import (
    seed_search,
    test_normal_and_assistant_search_share_current_fields_and_paging,
    test_early_historical_name_and_explicit_source_id_have_labels,
    test_revoked_scope_source_and_mixed_sources_are_filtered_before_count,
    test_history_and_alias_stop_matching_after_source_revocation,
    test_historical_mixed_cross_area_sources_and_revoked_identity_are_not_aliases,
    test_scope_and_inactive_assets_are_filtered_before_assistant_count,
    test_latest_binding_controls_alias_and_revocation_never_falls_back,
    test_malformed_source_provenance_fails_closed_without_sql_error,
    test_literal_keyword_not_wildcard,
    test_empty_and_database_failure_are_not_confused,
)

pytestmark = pytest.mark.skipif(os.environ.get("AIC_V73_DISPOSABLE_PG") != "1",
                              reason="requires explicit disposable PostgreSQL search validation")


@pytest.fixture(scope="module")
def synthetic_pg():
    container, username = "aic-v70-validation-pg", "aic_v70_synthetic"
    password = os.environ.get("AIC_V70_SYNTHETIC_PASSWORD")
    assert password, "only the disposable container password may be supplied"
    inspected = subprocess.run(["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", container],
                              capture_output=True, check=True, timeout=20)
    assert json.loads(inspected.stdout).get("5432/tcp") == [{"HostIp": "127.0.0.1", "HostPort": "15470"}]
    name = f"aic_v73_search_{uuid4().hex[:10]}"
    url = URL.create("postgresql+psycopg2", username=username, password=password,
                     host="127.0.0.1", port=15470, database="postgres")
    admin = create_engine(url)
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            assert connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}) is None
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    engine = create_engine(url.set(database=name))
    print("Synthetic v7.3 search database retained:", name)
    try:
        # The disposable image already contains pgvector; metadata references
        # its type even though these search tests never calculate embeddings.
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def search(synthetic_pg):
    with synthetic_pg.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as db:
            yield seed_search(db)
        transaction.rollback()
