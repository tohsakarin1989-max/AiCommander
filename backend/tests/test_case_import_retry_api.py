from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import case_imports, cases
from app.database import get_db
from test_case_search_page import search_db  # noqa: F401


def test_retry_api_success_and_rejected_scope(search_db):
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases")
    app.include_router(case_imports.router, prefix="/api/case-imports")
    app.dependency_overrides[get_db] = lambda: search_db
    with TestClient(app) as client:
        imported = client.post("/api/cases/import?operational_area_id=1&time_zone=Asia/Shanghai", files={"file": ("a.csv",
            "案发时间,案情描述,经度\n2026-09-10 08:00,待纠正,错误坐标\n".encode())})
        assert imported.status_code == 200
        batch_id = imported.json()["batch_id"]
        path = f"/api/case-imports/batches/{batch_id}"
        assert client.get(path).json()["rows"][0]["time_zone"] == "Asia/Shanghai"
        assert client.post(path + "/retry", json={"rows": [{"row": 2, "revision": 0, "changes": {"commit": True}}]}).status_code == 422
        payload = {"rows": [{"row": 2, "revision": 0, "changes": {"longitude": "125"}}]}
        assert client.post(path + "/retry", json=payload).json()["created"] == 1
        assert client.post(path + "/retry", json=payload).json()["created"] == 0
        assert client.get(path).json()["rows"] == []
        search_db.info["authorized_area_ids"] = (2,)
        assert client.get(path).status_code == 404
        assert client.post(path + "/retry", json=payload).status_code == 404
