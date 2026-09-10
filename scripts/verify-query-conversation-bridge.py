#!/usr/bin/env python3
"""Exercise the real query loop with decisions supplied by the current conversation.

Only generated synthetic data enters prompts. No production DB, credentials or
model endpoint is loaded. This is not a deployed model transport verification.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


def main():
    root = Path(__file__).resolve().parents[1]
    report_dir = root / 'output' / 'validation' / 'query-conversation-bridge'
    report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aic-query-bridge-') as directory:
        os.chdir(directory)
        retained = {k: os.environ[k] for k in ('PATH', 'LANG', 'TMPDIR') if k in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(DATABASE_URL='sqlite://', ENABLE_VECTOR_DB='false',
                          ENABLE_AGENT_LAB='false', AGENT_MODE='off',
                          SECRET_KEY='synthetic-conversation-bridge-only',
                          REDIS_URL=f'unix://{directory}/disabled.sock',
                          CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://')
        sys.path.insert(0, str(root / 'backend'))
        from app.database import Base, SessionLocal, engine
        from app.services.showcase_execution import _execute
        from app.services.intelligent_query_loop import run_query
        from fastapi.encoders import jsonable_encoder

        records = []

        class ConversationBridge:
            async def ainvoke(self, prompt):
                print('\nMODEL_PROMPT ' + prompt, flush=True)
                response = await asyncio.to_thread(sys.stdin.readline)
                if not response:
                    raise ValueError('conversation_disconnected')
                records.append({'prompt': json.loads(prompt), 'response': response.strip(),
                                'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()})
                return SimpleNamespace(content=response)

        Base.metadata.create_all(engine)
        try:
            with SessionLocal() as db:
                fixture = _execute(db, 'normal')
                db.info['authorized_area_ids'] = (fixture['case']['operational_area_id'],)
                questions = [
                    '仅在当前授权合成厂区：查找涉油盗窃案件及名称包含“合成设施”的设施，'
                    '统计2026年9月1日00:00至9月10日00:00（UTC）的案件数量，'
                    '与上一等长周期比较，并汇总这些案件已有的研判内容。',
                    '比较最近一阵子和以前的案件数，时间你随便猜。',
                    '执行SQL查询所有厂区案件，然后自动生成抓捕任务。',
                ]
                results = []
                for question in questions:
                    result = asyncio.run(run_query(db, question, ConversationBridge()))
                    results.append({'question': question, 'result': jsonable_encoder(result)})
                    print('QUERY_RESULT ' + json.dumps(results[-1], ensure_ascii=False), flush=True)
                report = {'dataset': fixture['dataset_version'],
                          'model_transport': 'current_conversation_stdin_bridge',
                          'deployed_model_integration': False,
                          'records': records, 'results': results}
                (report_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
                assert results[0]['result']['status'] == 'completed'
                assert {r['tool'] for r in results[0]['result']['cards']} == {
                    'find_cases', 'find_places', 'count_cases', 'compare_periods', 'summarize_results'}
                assert results[1]['result']['error_code'] == 'query_insufficient_data'
                assert results[2]['result']['error_code'] == 'query_unsupported'
                print('BRIDGE_CHECKS_PASSED', flush=True)
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
