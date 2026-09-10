"""Explicit disposable PostgreSQL migration + real road service verification."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Barrier


def main():
    from sqlalchemy.engine import make_url
    url = make_url(os.environ.get("DATABASE_URL", ""))
    if (os.environ.get("AIC_DISPOSABLE_ROAD_PG") != "1" or url.host != "127.0.0.1"
            or url.database != "aic_road_test" or url.get_backend_name() != "postgresql"):
        raise RuntimeError("explicit_local_disposable_database_required")
    backend = Path(__file__).resolve().parents[1] / "backend"
    os.environ["SECRET_KEY"] = "disposable-road-verification-only"
    os.environ["ENVIRONMENT"] = "development"
    sys.path.insert(0, str(backend))
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session
    from app.models.user import User
    from app.models.map_foundation import OperationalArea, MapSource
    from app.models.internal_roads import InternalRoadImport
    from app.services.internal_road_service import ingest_roads, read_import, review_feature, road_catalog, RoadReviewConflict
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    engine = create_engine(url, connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=10000"})
    if inspect(engine).has_table("alembic_version"):
        raise RuntimeError("database_must_be_new")
    command.upgrade(config, "2cef953868c3")
    feature = {"type": "Feature", "id": "road-1", "geometry": {"type": "LineString", "coordinates": [[125, 46], [125.01, 46.01]]},
               "properties": {"name": "合成道路", "kind": "road"}}
    with Session(engine) as db:
        db.add(User(id=991, username="road-pg-check", display_name="合成测试", password_hash="not-a-login", role="admin"))
        db.add(OperationalArea(id=991, code="road-test", name="合成区域"))
        db.flush()
        db.add(MapSource(id=991, source_key="synthetic-road", name="合成道路来源", source_type="internal_gis", operational_area_id=991))
        db.flush()
        db.add(InternalRoadImport(id=1, source_id=991, operational_area_id=991, input_sha256="a" * 64,
            schema_version="internal-road-preview-4.1.0-1", features=[feature], warnings=[], created_by=991))
        db.commit()
        # Explicit ID seed must not leave the PostgreSQL sequence behind.
        db.execute(text("SELECT setval(pg_get_serial_sequence('internal_road_imports','id'),1,true)"))
        db.execute(text("INSERT INTO internal_road_reviews (import_id,operational_area_id,feature_id,sequence,request_key,decision,note,evidence_reference,created_by) "
                        "VALUES (1,991,'road-1',1,'pg-old-review','verified','仅核验资料','合成台账',991)"))
        db.commit()
    command.upgrade(config, "4ef1b75a80e5")
    with Session(engine) as db:
        db.info.update(authorized_area_ids=(991,), area_access_levels={991: "manage"})
        old = read_import(db, 991, 1)
        assert old["features"] == [feature]
        assert old["feature_reviews"]["road-1"]["connection_evidence"] is None
        assert road_catalog(db, 991)["items"][0]["last_verified_import_id"] == 1
        entry = {"type": "Feature", "id": "entry-1", "geometry": {"type": "Point", "coordinates": [125, 46]},
                 "properties": {"name": "合成入口", "kind": "entrance", "road_id": "road-1"}}
        payload = {"type": "FeatureCollection", "coordinate_system": "EPSG:4326", "features": [entry]}
        imported, created = ingest_roads(db, 991, payload, 991)
        db.commit()
        assert created
        repeated, created = ingest_roads(db, 991, payload, 991)
        assert not created and repeated["id"] == imported["id"]
        record = read_import(db, 991, imported["id"])
        assert record["entrance_checks"][0]["road_import_id"] == 1
        evidence = {"input_sha256": imported["input_sha256"], "request_key": "pg-entry-review", "previous_review_id": None,
                    "decision": "verified", "note": "合成连接核验", "evidence_reference": "合成依据",
                    "connection_evidence": {"road_import_id": 1, "road_source_sha256": "a" * 64, "status": "connected"}}
        review, created = review_feature(db, 991, imported["id"], "entry-1", evidence, 991)
        db.commit()
        assert created and not review["routing_available"]
        assert read_import(db, 991, imported["id"])["entrance_checks"][0]["recorded_connection_evidence"] == evidence["connection_evidence"]
        db.info["authorized_area_ids"] = ()
        try:
            road_catalog(db, 991)
            raise AssertionError("scope_not_enforced")
        except LookupError:
            pass
    concurrent_payload = {"type": "FeatureCollection", "coordinate_system": "EPSG:4326", "features": [{
        "type": "Feature", "id": "concurrent-road", "geometry": feature["geometry"],
        "properties": {"name": "合成并发道路", "kind": "road"}}]}
    barrier = Barrier(4, timeout=10)

    def concurrent_import(_):
        with Session(engine) as db:
            db.info.update(authorized_area_ids=(991,), area_access_levels={991: "manage"})
            barrier.wait()
            result, created = ingest_roads(db, 991, concurrent_payload, 991)
            db.commit()
            return result, created

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(concurrent_import, i) for i in range(4)]
        imports = [future.result(timeout=30) for future in futures]
    assert sum(created for _, created in imports) == 1
    assert len({result["id"] for result, _ in imports}) == 1
    concurrent_batch = imports[0][0]
    barrier = Barrier(4, timeout=10)

    def concurrent_review(index):
        with Session(engine) as db:
            db.info.update(authorized_area_ids=(991,), area_access_levels={991: "manage"})
            decision = {"input_sha256": concurrent_batch["input_sha256"],
                        "request_key": f"pg-concurrent-review-{index}", "previous_review_id": None,
                        "decision": "verified", "note": f"合成核验人{index}", "evidence_reference": "合成依据"}
            barrier.wait()
            try:
                result, created = review_feature(db, 991, concurrent_batch["id"], "concurrent-road", decision, 991)
                db.commit()
                assert created
                return result["id"]
            except RoadReviewConflict:
                db.rollback()
                return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(concurrent_review, i) for i in range(4)]
        reviews = [future.result(timeout=30) for future in futures]
    assert sum(result is not None for result in reviews) == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM internal_road_imports WHERE input_sha256=:sha"),
                                  {"sha": concurrent_batch["input_sha256"]}).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM internal_road_feature_versions WHERE import_id=:id"),
                                  {"id": concurrent_batch["id"]}).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM internal_road_reviews WHERE import_id=:id"),
                                  {"id": concurrent_batch["id"]}).scalar_one() == 1
    print("postgres_road_concurrent_import_and_review_passed")
    command.downgrade(config, "3df0a64979d4")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT note FROM internal_road_reviews WHERE request_key='pg-old-review'")).scalar() == "仅核验资料"
    command.upgrade(config, "4ef1b75a80e5")
    # Re-establish a version-bound connection after the intentionally lossy
    # downgrade, so the subsequent backup drill includes non-null JSON evidence.
    with Session(engine) as db:
        db.info.update(authorized_area_ids=(991,), area_access_levels={991: "manage"})
        current = read_import(db, 991, imported["id"])
        restored_evidence = dict(evidence, request_key="pg-entry-after-upgrade",
                                 previous_review_id=current["feature_reviews"]["entry-1"]["id"])
        result, created = review_feature(db, 991, imported["id"], "entry-1", restored_evidence, 991)
        db.commit()
        assert created and result["connection_evidence"] == evidence["connection_evidence"]
    print("postgres_road_migration_and_services_passed")
    engine.dispose()


if __name__ == "__main__":
    main()
