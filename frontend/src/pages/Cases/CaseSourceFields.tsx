import { Button, Col, DatePicker, Form, Input, InputNumber, Row, Select } from 'antd'
import type { FormInstance } from 'antd'
import { oilUnitLabels } from '../../utils/caseValues'
import { locationCoordinateError } from './caseLocationDraft'

export const oilUnitOptions = Object.entries(oilUnitLabels).map(([value, label]) => ({ value, label }))
export const locationRoleLabels = { incident: '案发地点', discovery: '发现／查获地点', mentioned: '原文提及', source_candidate: '来源线索地点', custody: '保管地点' }
export const measurementStageLabels = { involved: '涉案记录', seized: '查获', transferred: '移交', recovered: '回收', unknown: '环节未知' }

export function CaseTimeFields({ form }: { form: FormInstance }) {
  const precision = Form.useWatch('time_precision', form) || 'unknown'
  return <section aria-label="案件时间记录">
    <Form.Item name="time_precision" label="发生时间的明确程度" initialValue="unknown">
      <Select options={[{ value: 'exact', label: '已知精确时刻' }, { value: 'interval', label: '已知时间区间' }, { value: 'unknown', label: '时间尚不明确' }]} />
    </Form.Item>
    {precision === 'exact' && <Form.Item name="occurred_time" label="发生时刻" rules={[{ required: true, message: '请选择时刻，或将明确程度改为时间尚不明确' }]}>
      <DatePicker showTime style={{ width: '100%' }} />
    </Form.Item>}
    {precision === 'interval' && <Row gutter={12}>
      <Col xs={24} sm={12}><Form.Item name="occurred_from" label="发生区间起点" rules={[{ required: true, message: '请填写区间起点，或保留为未知' }]}><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col>
      <Col xs={24} sm={12}><Form.Item name="occurred_to" label="发生区间终点" dependencies={['occurred_from']} rules={[
        { required: true, message: '请填写区间终点，或保留为未知' },
        ({ getFieldValue }) => ({ validator(_, value) { const start = getFieldValue('occurred_from'); return !value || !start || value.valueOf() >= start.valueOf() ? Promise.resolve() : Promise.reject(new Error('区间终点不能早于起点')) } }),
      ]}><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col>
    </Row>}
    <Form.Item name="time_expression" label="原文时间表述"><Input placeholder="如：昨晚、九月上旬；不会据此自动编造时刻" /></Form.Item>
    <Row gutter={12}>
      <Col xs={24} sm={12}><Form.Item name="time_timezone" label="记录时区" initialValue="Asia/Shanghai"><Select options={[{ value: 'Asia/Shanghai', label: '北京时间（UTC+8）' }, { value: 'UTC', label: 'UTC' }]} /></Form.Item></Col>
      <Col xs={24} sm={12}><Form.Item name="discovered_at" label="发现时间（与发生时间分开）"><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col>
    </Row>
  </section>
}

export function CaseSourceCollections({ locationsEnabled, measurementsEnabled }: { locationsEnabled: boolean; measurementsEnabled: boolean }) {
  return <details className="case-source-editor"><summary>补充地点角色与油品测量（按需）</summary>
    <p>不同地点不合并成一个点；不同单位、环节的数量不直接相加。没有准确位置可只填原文。登记案发地点后，主地图点以唯一且精确的案发地点为准；区域、未知或多处案发地点不显示为一个精确点。</p>
    {!locationsEnabled ? <p role="alert">地点明细读取失败，本次保存不覆盖原明细。</p> : <Form.List name="initial_locations">{(fields, { add, remove }) => <>
      <h4>地点记录</h4>{fields.map(({ key, name, ...rest }) => <fieldset key={key}><legend>地点 {name + 1}</legend>
        <Form.Item {...rest} name={[name, 'id']} hidden><Input /></Form.Item>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'role']} label="地点角色" rules={[{ required: true }]}><Select options={Object.entries(locationRoleLabels).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'precision']} label="位置精度"><Select options={[{ value: 'unknown', label: '未明确' }, { value: 'area', label: '仅知区域' }, { value: 'exact', label: '已知精确位置' }]} /></Form.Item></Col></Row>
        <Form.Item {...rest} name={[name, 'description']} label="地点原文"><Input placeholder="如：井场东侧，不用填写假坐标" /></Form.Item>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'ui_latitude']} label="已核对的纬度（可选）" dependencies={[[ 'initial_locations', name, 'ui_longitude' ], [ 'initial_locations', name, 'precision' ]]} rules={[
          ({ getFieldValue }) => ({ validator() { const error = locationCoordinateError(getFieldValue(['initial_locations', name]) || {}); return error ? Promise.reject(new Error(error)) : Promise.resolve() } }),
        ]}><InputNumber min={-90} max={90} style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'ui_longitude']} label="已核对的经度（可选）"><InputNumber min={-180} max={180} style={{ width: '100%' }} /></Form.Item></Col></Row>
        <p>精确位置必须同时提供经纬度。区域仅保留范围，不用中心点替代入口。</p>
        <Form.Item {...rest} name={[name, 'source_note']} label="来源说明"><Input /></Form.Item>
        <Form.Item {...rest} name={[name, 'geometry']} hidden><Input /></Form.Item>
        <Button size="small" onClick={() => remove(name)}>移除此地点</Button>
      </fieldset>)}<Button onClick={() => add({ role: 'mentioned', precision: 'unknown', geometry: null })}>增加地点记录</Button>
    </>}</Form.List>}
    {!measurementsEnabled ? <p role="alert">测量明细读取失败，本次保存不覆盖原明细。</p> : <Form.List name="initial_measurements">{(fields, { add, remove }) => <>
      <h4>油品测量</h4>{fields.map(({ key, name, ...rest }) => <fieldset key={key}><legend>测量 {name + 1}</legend>
        <Form.Item {...rest} name={[name, 'id']} hidden><Input /></Form.Item>
        <Row gutter={12}><Col xs={24} sm={8}><Form.Item {...rest} name={[name, 'value']} label="数量" rules={[{ required: true, message: '无数量时请先移除此测量行' }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24} sm={8}><Form.Item {...rest} name={[name, 'unit']} label="单位"><Select options={oilUnitOptions} /></Form.Item></Col>
          <Col xs={24} sm={8}><Form.Item {...rest} name={[name, 'stage']} label="业务环节"><Select options={Object.entries(measurementStageLabels).map(([value, label]) => ({ value, label }))} /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'method']} label="测量方法"><Input placeholder="如：地磅检斤、流量计" /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'measured_at']} label="测量时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'water_cut']} label="含水率（%）"><InputNumber min={0} max={100} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item {...rest} name={[name, 'water_cut_basis']} label="含水率口径"><Input placeholder="如：抽样质量分数；不明可留空" /></Form.Item></Col></Row>
        <Form.Item {...rest} name={[name, 'source_note']} label="来源说明"><Input /></Form.Item>
        <Button size="small" onClick={() => remove(name)}>移除此测量</Button>
      </fieldset>)}<Button onClick={() => add({ unit: 'unknown', stage: 'unknown' })}>增加测量记录</Button>
    </>}</Form.List>}
  </details>
}
