import { Button, Form, Input, InputNumber, Select, Space } from 'antd'
import type { MapImportTemplate, MapTemplateCreate } from '../../services/mapFoundation'
import type { MapFieldContract, MapImportStructure } from '../../services/mapLedgerImports'
import { valueStateLabels } from './mapLedgerPresentation'

export interface LedgerTemplateValues {
  name: string; sheet_name?: string; header_row: number
  coordinate_system: string; coordinate_unit: 'degree' | 'meter'; axis_order: 'lon_lat' | 'lat_lon'
  field_mapping: Record<string, string>; field_units?: Record<string, string>; expected_headers?: string
}
export function ledgerTemplatePayload(sourceId: number, values: LedgerTemplateValues): MapTemplateCreate {
  const mapping = Object.fromEntries(Object.entries(values.field_mapping).filter(([, value]) => !!value?.trim()).map(([key, value]) => [key, value.trim()]))
  const units = Object.fromEntries(Object.entries(values.field_units || {}).filter(([, value]) => !!value?.trim()).map(([key, value]) => [key, value.trim()]))
  const headers = (values.expected_headers || '').split('\n').map(value => value.trim()).filter(Boolean)
  return { source_id: sourceId, name: values.name.trim(), sheet_name: values.sheet_name?.trim() || undefined,
    header_row: values.header_row, coordinate_system: values.coordinate_system, coordinate_unit: values.coordinate_unit,
    axis_order: values.axis_order, field_mapping: mapping, field_units: units,
    ...(headers.length ? { expected_structure: { headers, sheet_name: values.sheet_name?.trim() || null, header_row: values.header_row } } : {}) }
}

export default function MapLedgerTemplateForm({ sourceId, contract, selected, structure, busy, onSave, onDirtyChange }: {
  sourceId: number; contract: MapFieldContract; selected?: MapImportTemplate; structure?: MapImportStructure
  busy: boolean; onSave: (payload: MapTemplateCreate) => void; onDirtyChange: () => void
}) {
  const [form] = Form.useForm<LedgerTemplateValues>()
  const basic = new Set(['external_id', 'name', 'asset_type', 'longitude', 'latitude', 'address'])
  const renderField = (field: MapFieldContract['fields'][number]) => <Form.Item key={field.key} name={['field_mapping', field.key]}
    label={`${field.label}列`} extra={field.description} rules={field.required ? [{ required: true, message: `请指定${field.label}对应的原列名` }] : undefined}>
    {structure ? <Select allowClear showSearch placeholder="选择原表中的实际列名" options={structure.headers.filter(Boolean).map(value => ({ value, label: value }))} />
      : <Input placeholder={`先上传文件可选择真实列名，例如 ${field.label}`} />}
  </Form.Item>
  return <Form name={`map-template-${sourceId}`} form={form} layout="vertical" disabled={busy} initialValues={{ header_row: 1, axis_order: 'lon_lat', field_mapping: {
    external_id: '井号', name: '井名', asset_type: '类型', longitude: '经度', latitude: '纬度',
  } }} onValuesChange={onDirtyChange} onFinish={values => onSave(ledgerTemplatePayload(sourceId, values))}>
    <Space wrap>
      {selected && <Button onClick={() => {
        form.resetFields()
        form.setFieldsValue({ ...selected, sheet_name: selected.sheet_name || undefined,
          field_mapping: Object.fromEntries(contract.fields.map(field => [field.key, selected.field_mapping[field.key] || ''])),
          field_units: { water_cut_unit: '', production_output_unit: '', ...selected.field_units },
          expected_headers: selected.expected_structure?.headers.join('\n') || '' })
        onDirtyChange()
      }}>复用所选模板字段配置</Button>}
      {structure && <Button onClick={() => {
        form.setFieldsValue({ expected_headers: structure.headers.join('\n'), sheet_name: structure.sheet_name || undefined, header_row: structure.header_row,
          field_mapping: Object.fromEntries(contract.fields.map(field => [field.key, structure.headers.includes(field.label) ? field.label : ''])) })
        onDirtyChange()
      }}>采用实际表头并带出同名字段</Button>}
    </Space>
    <Form.Item name="name" label="模板名称" rules={[{ required: true }]}><Input placeholder="同名保存会产生新版本，旧批次仍保留原模板" /></Form.Item>
    <Form.Item name="sheet_name" label="工作表名称">{structure?.available_sheets?.length
      ? <Select options={structure.available_sheets.map(value => ({ value, label: value }))} />
      : <Input placeholder="CSV 留空；Excel 首次上传后选择实际工作表" />}</Form.Item>
    <Form.Item name="header_row" label="表头所在行" rules={[{ required: true }]}><InputNumber min={1} max={100} /></Form.Item>
    <Form.Item name="coordinate_system" label="来源明确的坐标系" rules={[{ required: true, message: '请向来源确认坐标系，不能从坐标数值猜测' }]}>
      <Select placeholder="必须明确选择，不自动猜测" options={[
        { value: 'wgs84', label: 'WGS84 经纬度' }, { value: 'cgcs2000_geographic', label: 'CGCS2000 经纬度' },
        { value: 'gcj02', label: 'GCJ-02' }, { value: 'bd09', label: 'BD-09' },
      ]} />
    </Form.Item>
    <Form.Item name="coordinate_unit" label="坐标单位" rules={[{ required: true }]}>
      <Select placeholder="与来源声明一致" options={[{ value: 'degree', label: '度（以上四类经纬度来源）' }]} />
    </Form.Item>
    <p>米制投影与本地控制点转换尚未完成来源参数和误差核验，本入口不接收；不能把仿射近似当作准确投影。</p>
    <Form.Item name="axis_order" label="坐标列顺序"><Select options={[{ value: 'lon_lat', label: '经度、纬度' }, { value: 'lat_lon', label: '纬度、经度' }]} /></Form.Item>
    {contract.fields.filter(field => basic.has(field.key)).map(renderField)}
    <details><summary>生产属性、有效期和明确处理语义（按来源映射）</summary>
      {contract.fields.filter(field => !basic.has(field.key)).map(renderField)}
      <p>{contract.value_states.map(state => `${state}：${valueStateLabels[state] || state}`).join('；')}。空白不是删除，清空与撤销必须由来源明确声明。</p>
    </details>
    <details><summary>模板单位与结构约束（检测后续漂移）</summary>
      <Form.Item name={['field_units', 'water_cut_unit']} label="预期含水率单位"><Input placeholder="例如 %；不提供时不额外约束" /></Form.Item>
      <Form.Item name={['field_units', 'production_output_unit']} label="预期产量单位"><Input placeholder="例如 吨；发生变化先核对，不自动换算" /></Form.Item>
      <Form.Item name="expected_headers" label="已确认表头（每行一个，保留来源顺序）" extra="换列顺序和新增未映射备注不阻断；缺映射列、重名、工作表或表头行变化须核对。">
        <Input.TextArea rows={5} />
      </Form.Item>
    </details>
    <Button htmlType="submit" loading={busy}>保存为模板新版本</Button>
  </Form>
}
