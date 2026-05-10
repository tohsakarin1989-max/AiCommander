from app.database import SessionLocal
from app.services.chain_analysis_service import ChainAnalysisService
from app.tasks.celery_app import celery_app


@celery_app.task
def scan_chain_links_task(case_id: int) -> dict:
    db = SessionLocal()
    try:
        links = ChainAnalysisService.scan_chain_links(case_id, db)
        return {"case_id": case_id, "link_count": len(links)}
    except Exception as exc:
        return {"case_id": case_id, "error": str(exc)}
    finally:
        db.close()
