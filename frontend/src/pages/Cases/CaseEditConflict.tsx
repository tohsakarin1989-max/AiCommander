import { useState } from 'react'
import { Alert, Button, Radio } from 'antd'
import { entryDifferenceFields, resolveEntryDifferences } from './caseDraftSnapshot'
import { importFieldLabels } from './importCorrection'

const labels: Record<string, string> = { ...importFieldLabels, initial_vehicles: '车辆明细（整组）', initial_persons: '人员明细（整组）',
  initial_locations: '地点明细（整组）', initial_measurements: '测量明细（整组）', bonus_has_vehicle: '车辆资料开关',
  bonus_has_person: '人员资料开关', bonus_has_oil: '涉油资料开关', bonus_has_police: '报案资料开关', time_precision: '时间精度', time_timezone: '记录时区' }
Object.assign(labels, { values: '草稿表单内容（整份）', assistant_text: '辅助录入原文', assistant_source_text: '提取时原文', had_incident_locations: '原有案发地点明细状态' })
Object.assign(labels, { entry_location_role: '本次地点角色', feedback_changed_fields: '已明确修改的反馈字段', feedback_initial_known_fields: '原记录已确认的反馈字段' })

const display = (value: unknown) => value == null || value === '' ? '未填写' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)

export default function CaseEditConflict({ mine, latest, revision, kind = 'case', onResolve }: {
  mine: Record<string, unknown>; latest: Record<string, unknown>; revision: number
  kind?: 'case' | 'draft'
  onResolve: (resolved: Record<string, unknown>) => void
}) {
  const [choices, setChoices] = useState<Record<string, 'mine' | 'latest'>>({})
  const fields = entryDifferenceFields(mine, latest)
  return <section className="case-edit-conflict" aria-label="案件编辑版本冲突比较">
    <Alert type="warning" showIcon message={`${kind === 'case' ? '案件' : '私有草稿'}已变化，原输入未覆盖服务器记录`}
      description={`服务器当前${kind === 'case' ? '来源' : '草稿'}版本 ${revision}。逐项核对下列差异；明细整组比较，不按姓名、序号或数组位置自动合并。完成比较只返回表单，仍需再次保存。`} />
    {fields.length === 0 && <p>当前字段与服务器一致，可采用当前版本返回表单。</p>}
    {fields.map(field => <fieldset key={field} style={{ margin: '14px 0', border: '1px solid var(--line)', padding: 12 }}>
      <legend>{labels[field] || field}</legend>
      <div className="case-conflict-columns"><div><strong>我的输入</strong><pre>{display(mine[field])}</pre></div><div><strong>服务器最新</strong><pre>{display(latest[field])}</pre></div></div>
      <Radio.Group aria-label={`确认${labels[field] || field}`} value={choices[field]} onChange={event => setChoices(previous => ({ ...previous, [field]: event.target.value }))}>
        <Radio value="mine">保留我的这一项</Radio><Radio value="latest">采用服务器这一项</Radio>
      </Radio.Group>
    </fieldset>)}
    <Button type="primary" disabled={fields.some(field => !choices[field])}
      onClick={() => onResolve(resolveEntryDifferences(mine, latest, choices))}>采用比较结果，返回表单</Button>
  </section>
}
