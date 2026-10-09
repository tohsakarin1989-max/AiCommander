"""Immutable, scope-owned presentation choices. No business text or expressions."""
from uuid import uuid4

from app.database import require_area_write_access
from app.models.output_template import OutputTemplate
from app.services.intelligent_query_tasks import _identity
from app.services.case_table_export import validate_output_configuration
from app.services.result_presentation import validate_sections


def _view(row):
    return {'id': row.id, 'kind': row.kind, 'name': row.name, 'version': row.version,
            'operational_area_id': row.operational_area_id, 'configuration': row.configuration,
            'created_at': row.created_at, 'boundary': '用户配置，未经过单位官方表样确认；保存后不可变，更改请另存。'}


def validate_configuration(kind, configuration):
    if kind == 'case_ledger':
        return validate_output_configuration(configuration)
    if kind == 'material_sections' and isinstance(configuration, dict) and set(configuration) == {'sections'}:
        return {'sections': validate_sections(configuration['sections'])}
    raise ValueError('输出模板配置无效')


def list_templates(db, kind, area_id=None):
    _identity(db)
    if kind not in {'case_ledger', 'material_sections'}:
        raise ValueError('输出模板类型无效')
    query = db.query(OutputTemplate).filter_by(kind=kind)
    if area_id is not None:
        query = query.filter_by(operational_area_id=area_id)
    return [_view(row) for row in query.order_by(OutputTemplate.created_at.desc(), OutputTemplate.id).limit(200)]


def read_template(db, identifier, kind):
    _identity(db)
    row = db.query(OutputTemplate).filter_by(id=identifier, kind=kind).populate_existing().first()
    if row is None:
        raise PermissionError('输出模板不存在或当前不可访问')
    return _view(row)


def save_template(db, *, name, kind, configuration, operational_area_id=None):
    user = _identity(db)
    if user.role not in {'admin', 'analyst'}:
        raise PermissionError('只读账号不可保存输出模板')
    area_id = require_area_write_access(db, operational_area_id)
    if area_id is None or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('模板名称或保存范围无效')
    row = OutputTemplate(id=str(uuid4()), kind=kind, name=name.strip(), operational_area_id=area_id,
                         created_by=user.id, version=1,
                         configuration=validate_configuration(kind, configuration))
    db.add(row)
    db.flush()
    return _view(row)
