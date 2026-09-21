"""Export the selected topic revision, without statistics or model re-execution."""
from app.services import analysis_topic_service as topics
from app.services.case_result_document import CaseResultDocument, DocumentBlock
from app.services.case_result_export import render_docx
from app.services.case_result_pdf import _convert_generated_docx
from app.services.document_budget import document_budget
from app.services.intelligent_query_document import _rows
from app.services.topic_projections import resolve_references


def build_topic_document(db, topic_id, revision):
    topic = topics._owned(db, topic_id)
    snapshot = topics._snapshot(db, topic_id, revision)
    topics.validate_snapshot_access(db, snapshot)
    aggregate = snapshot.payload['aggregate']
    references = resolve_references(db, snapshot.payload.get('references', {}))
    blocks = [
        DocumentBlock('heading', '专题研判与周期材料'),
        DocumentBlock('paragraph', f'专题当前名称：{topic.title}；引用成果第 {revision} 版。'),
        DocumentBlock('paragraph', '这是冻结成果，不重新抽取案情或计算道路。分析案组不等于正式串并案、真实团伙或已经认定的事实。'),
        DocumentBlock('table', '成果版本', (
            ('成果编号', snapshot.id), ('内容校验', snapshot.content_sha256),
            ('形成时间', snapshot.created_at.isoformat()),
        )),
        DocumentBlock('table', '筛选条件', tuple(_rows(topic.filters))),
    ]
    for title, key in [('授权集合与扫描完整度', 'coverage'), ('总体统计', 'statistics'),
                       ('条件分布（按案件去重）', 'patterns'), ('表述缺失比例及分母', 'missingness'),
                       ('已有模型提取状态（候选，不计入条件统计）', 'model_extraction'),
                       ('匹配案组来源', 'members'), ('不同或相反表述来源', 'counterexamples'),
                       ('资料不足来源', 'unknown')]:
        value = aggregate.get(key, [])
        if key == 'patterns':
            value = [{k: v for k, v in item.items() if k != 'case_ids'} for item in value]
        blocks.append(DocumentBlock('table', title, tuple(_rows(value))))
    blocks.append(DocumentBlock('table', '独立事件补充（不与案件相加）', tuple(_rows(
        {key: value for key, value in snapshot.payload['events'].items() if key != 'source_manifest'}))))
    blocks.append(DocumentBlock('table', '与上一成果的变化', tuple(_rows(snapshot.changes))))
    if references['history'] is not None:
        blocks.append(DocumentBlock('table', '历史案件与已确认经验（独立参考，不计入本期统计）',
                                    tuple(_rows(references['history']))))
    for title, key in [('已有案件候选及反向依据', 'case_results'), ('已有道路依据', 'roads'),
                       ('同辖区既有日/周材料', 'briefs'), ('地图版本引用', 'maps')]:
        blocks.append(DocumentBlock('table', title, tuple(_rows(references[key]))))
    blocks.append(DocumentBlock('paragraph',
        '日/周材料只作同辖区背景，未套用专题语义条件，不与专题统计合并。地图沿用上述版本；'
        '未生成未核验的道路示意图。原文依据可用本版专题的案件画像引用回查。'
        '缺少表述不等于现实中不存在，未知不得当作否定。'))
    if sum(len(block.rows) for block in blocks) > 10000:
        raise ValueError('topic_document_too_large')
    return CaseResultDocument('topic-document-5.3-1', snapshot.id, snapshot.content_sha256, tuple(blocks))


@document_budget
def export_topic_document(db, topic_id, revision, format):
    if format not in {'docx', 'pdf'}:
        raise ValueError('topic_document_format')
    document = build_topic_document(db, topic_id, revision)
    data = render_docx(document)
    if format == 'pdf':
        data = _convert_generated_docx(data)
    db.expire_all()
    latest = topics.read_topic(db, topic_id, revision=revision)['snapshot']
    if latest['content_sha256'] != document.content_sha256:
        raise PermissionError('topic_document_changed')
    return document, data
