"""Optional derived-index maintenance, outside every business save transaction."""
from app.database import SessionLocal
from app.services.result_catalog_projection import reconcile_catalog
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.materials.reconcile_catalog', soft_time_limit=50, time_limit=60, ignore_result=True)
def reconcile_material_catalog():
    with SessionLocal() as db:
        return reconcile_catalog(db)
