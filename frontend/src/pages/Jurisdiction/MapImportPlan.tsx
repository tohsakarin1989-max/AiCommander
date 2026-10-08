import { Alert, Space, Table, Tag } from 'antd'
import type { MapImportField, MapLedgerPreview, MapPlanRow } from '../../services/mapLedgerImports'
import { displayMapValue, groupLabels, groupReasonLabels, mapRowLabels, valueStateLabels } from './mapLedgerPresentation'
import { LedgerComparisonView } from './MapLedgerComparison'

export function MapPlanDetails({ row, fields }: { row: MapPlanRow; fields: MapImportField[] }) {
  const label = (key: string) => fields.find(field => field.key === key)?.label || key
  return <div>
    <p>设施：{row.asset_id ? `#${row.asset_id} · 当前版本 ${row.asset_version ?? '未记录'}` : '尚未确定身份'}</p>
    {row.errors.map((error, index) => <p key={index}>{label(error.field)}：{error.message}（{error.code}）</p>)}
    {row.changes.length > 0 && <Table size="small" rowKey="field" pagination={false} dataSource={row.changes} columns={[
      { title: '字段', dataIndex: 'field', render: label }, { title: '原值', dataIndex: 'old', render: displayMapValue },
      { title: '本次值', dataIndex: 'new', render: displayMapValue },
    ]} />}
    {row.groups.map(group => <details key={group.group}><summary>{groupLabels[group.group] || group.group} · {valueStateLabels[group.state] || group.state} · {groupReasonLabels[group.reason] || group.reason || group.status}</summary>
      <Table size="small" rowKey="field" pagination={false}
        dataSource={Array.from(new Set([...Object.keys(group.old), ...Object.keys(group.new)])).map(field => ({ field, old: group.old[field], new: group.new[field] }))}
        columns={[{ title: '字段', dataIndex: 'field', render: label }, { title: '原采用值', dataIndex: 'old', render: displayMapValue }, { title: '本次完整组', dataIndex: 'new', render: displayMapValue }]} />
    </details>)}
  </div>
}

export default function MapImportPlan({ preview, fields }: { preview: MapLedgerPreview; fields: MapImportField[] }) {
  return <section aria-label="逐行导入差异预览">
    {preview.ledger_comparison && <LedgerComparisonView comparison={preview.ledger_comparison} declaration={preview.ledger_declaration} />}
    <Space wrap>{Object.entries(mapRowLabels).map(([key, label]) => <Tag key={key}>{label} {preview.counts[key as keyof typeof mapRowLabels] ?? 0}</Tag>)}</Space>
    {preview.drift.map((item, index) => <Alert key={index} type="warning" showIcon message={item.message}
      description={`${item.field}：${displayMapValue(item.old)} → ${displayMapValue(item.new)}。请核对来源并另存模板，再重新预览。`} />)}
    {(preview.rows_complete === false || preview.rows.length < preview.total_rows) && <Alert type="info" showIcon
      message={`共 ${preview.total_rows} 行，当前预览展示前 ${preview.rows.length} 行；分类统计覆盖全表。写入后的完整逐行回执可在最近批次中翻页查看。`} />}
    <Table size="small" rowKey="row_number" dataSource={preview.rows} pagination={{ pageSize: 10, showSizeChanger: false }}
      expandable={{ expandedRowRender: row => <MapPlanDetails row={row} fields={fields} /> }} columns={[
        { title: '原表行号', dataIndex: 'row_number' },
        { title: '处理结果', dataIndex: 'classification', render: value => mapRowLabels[value as keyof typeof mapRowLabels] || value },
        { title: '变更与异常', render: (_, row) => row.errors.map(error => error.message).join('；') || (row.changes.length ? `${row.changes.length} 项变更，展开核对` : '无字段变化') },
      ]} />
    <p>坐标、含水率、产量按字段组整体采用；未知、未提供、清空与撤销不同。此表是预览，提交时还会核验当前版本。</p>
  </section>
}
