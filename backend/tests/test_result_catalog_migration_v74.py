"""Disposable SQLite migration; the projection contains no original materials."""
from sqlalchemy import create_engine, inspect, text

from tests.test_result_material_migration_v65 import migrate


def test_v74_catalog_migration_is_empty_reversible_and_preserves_originals(tmp_path):
    url = f"sqlite:///{tmp_path / 'catalog-v74.sqlite'}"
    result = migrate(url, 'upgrade', 'v74n01')
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) "
                        "VALUES(7401,'V74-ORIGINAL','迁移前原文不能复制到投影',1)"))
    for direction, target in [('upgrade', 'v74c01'), ('downgrade', 'v74n01'), ('upgrade', 'v74c01')]:
        result = migrate(url, direction, target)
        assert result.returncode == 0, result.stderr
    engine.dispose()
    with engine.begin() as db:
        schema = inspect(db)
        assert {'ix_result_catalog_checked', 'ix_result_catalog_subject'} == {
            item['name'] for item in schema.get_indexes('result_catalog_projections')}
        assert schema.get_indexes('result_catalog_references')[0]['column_names'] == ['reference_kind', 'reference_id']
        assert db.scalar(text('SELECT COUNT(*) FROM result_catalog_projections')) == 0
        assert db.scalar(text('SELECT COUNT(*) FROM result_catalog_references')) == 0
        assert db.scalar(text('SELECT description FROM cases WHERE id=7401')) == '迁移前原文不能复制到投影'
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()
