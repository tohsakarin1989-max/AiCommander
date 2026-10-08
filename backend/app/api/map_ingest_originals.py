"""Administrator-only ledger-original retrieval through a scoped import ID."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.map_foundation import _require_admin
from app.database import get_db
from app.services.map_ingest_originals import read_original


router = APIRouter()


@router.get("/map-ingest-runs/{run_id}/original")
def download_map_ingest_original(run_id: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        content, filename = read_original(db, run_id)
    except LookupError:
        raise HTTPException(404, "台账批次不存在或当前无权读取") from None
    except ValueError as exc:
        detail = ("该批次仅有行级目录，原件未留存或已撤销" if str(exc) == "original_unavailable"
                  else "台账原件校验失败，未提供下载")
        raise HTTPException(409, detail) from None
    return Response(content, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename=ledger-original; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    })
