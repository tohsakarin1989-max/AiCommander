"""Dedicated map worker; core workers do not consume this queue."""
from app.database import SessionLocal
from app.services.map_package_import_worker import process_next
from app.services.map_auto_publication import publish_next
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.maps.process_import', queue='map_build',
                 soft_time_limit=1800, time_limit=1860, ignore_result=True)
def process_map_import():
    with SessionLocal() as db:
        validation = process_next(db)
        publication = publish_next(db)
        return {'validation': validation, 'publication': publication}
