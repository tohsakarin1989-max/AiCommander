"""旧知识入口的响应适配，不创建第二套检索索引。"""
from app.services.case_history_retrieval import CaseHistoryRetrieval


def history_candidates(db, query: str, case_id: int | None, limit: int) -> tuple[list, dict]:
    result = CaseHistoryRetrieval.search(db, query=query, filters={'case_id': case_id}, limit=limit)
    items = []
    for item in result['items']:
        kind = 'case_profile' if item['source_type'] == 'case' else 'experience_card'
        items.append({**item, 'source_type': kind, 'history_source_type': item['source_type']})
    return items, {key: value for key, value in result.items() if key != 'items'}


def merge_source_ranks(history: list, supplements: list, limit: int) -> list:
    # Lexical and fused-vector scores are not numerically comparable to legacy
    # document scores. Interleave source ranks, keeping each branch's own order.
    supplements.sort(key=lambda item: item.get('score', 0), reverse=True)
    rows = []
    for rank in range(max(len(history), len(supplements))):
        for items in (history, supplements):
            if rank < len(items):
                rows.append(items[rank])
    return rows[:limit]
