"""Preserve query catalog admission without constructing its export document."""


def validate_query_material(task):
    # Reuse the export's traversal/labels and limits, not its document builder.
    from app.services.intelligent_query_document import TOOLS, _rows

    result = task.get('result') or {}
    if task['status'] not in {'completed', 'degraded'} or not result.get('cards'):
        raise ValueError('query_document_not_ready')
    tables = [{'query_id': task['id'], 'status': task['status'],
               'completed_at': task.get('completed_at'), 'error_code': result.get('error_code'),
               'result_sha256': ''}]
    if task.get('followup_context'):
        tables.append(task['followup_context'])
    tables.append(result.get('query_conditions', {}))
    if result.get('answer'):
        answer = result['answer']
        # Keep malformed saved answers from entering a formerly unreadable catalog.
        answer['summary'], answer['boundary']
        for finding in answer['findings']:
            finding['text']
            '、'.join(finding['evidence_refs'])
        tables.append(answer['information_gaps'])
    for card in result['cards']:
        if card.get('tool') not in TOOLS:
            raise ValueError('query_document_unknown_tool')
        tables.extend([card.get('data', {}), card.get('evidence', {}), card.get('information_gaps', [])])
    tables.append(result.get('trace', []))
    count = 0
    for value in tables:
        for _ in _rows(value):
            count += 1
            if count > 10000:
                raise ValueError('query_document_too_large')
