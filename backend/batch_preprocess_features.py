"""Enqueue the existing versioned pipeline, never write old feature JSON.

Uses the configured application database. Resume with next_after_id; ordinary
workers consume the durable outbox. This command does not call a model.
"""
import argparse
import json

from app.database import SessionLocal
from app.services.case_pipeline_service import CasePipelineService


def run() -> None:
    parser = argparse.ArgumentParser(description="补充标准画像事件，不改写原始案件或历史 features")
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    if args.after_id < 0 or not 1 <= args.limit <= 5000:
        parser.error("after-id 必须非负，limit 必须在 1—5000 之间")
    with SessionLocal() as db:
        result = CasePipelineService.backfill(db, limit=args.limit, after_id=args.after_id)
    print(json.dumps({**result, "source": "case_revision_outbox_profile",
        "message": "已检查并补充统一流水线事件；画像由后台 Worker 生成。"}, ensure_ascii=False))


if __name__ == "__main__":
    run()
