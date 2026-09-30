import { useState } from 'react'
import { Button, DatePicker, Form, Input, Modal, Select } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { caseApi } from '../../services/cases'
import type { CaseTip } from '../../types'
import { serializeCaseTime } from '../../utils/caseValues'

export default function RecordIntake({ onCase, areaId, scopes }: {
  onCase: () => void; areaId?: number; scopes: Array<{ operational_area_id: number; area_name: string }>
}) {
  const navigate = useNavigate()
  const cache = useQueryClient()
  const [form] = Form.useForm()
  const [open, setOpen] = useState(false)
  const save = useMutation({ mutationFn: (value: Partial<CaseTip>) => caseApi.createCaseTip(value), onSuccess: () => { setOpen(false); form.resetFields(); void cache.invalidateQueries({ queryKey: ['case-tips'] }) } })
  return <>
    <details className="case-intake-choice"><summary className="btn-primary">＋ 记录资料</summary>
      <p>先选择记录身份。线索、独立事件不会自动成为案件。</p>
      <Button onClick={onCase}>新建案件</Button>
      <Button onClick={() => navigate('/events')}>登记独立事件</Button>
      <Button onClick={() => { save.reset(); form.setFieldsValue({ operational_area_id: areaId }); setOpen(true) }}>记录未核实线索</Button>
    </details>
    <Modal title="记录未核实线索" open={open} onCancel={() => setOpen(false)} confirmLoading={save.isPending} okText="保存线索" onOk={async () => {
      try { const values = await form.validateFields(); save.mutate({ ...values, operational_area_id: values.operational_area_id ?? areaId, reported_at: serializeCaseTime(values.reported_at) ?? null }) } catch { /* Form displays field errors. */ }
    }}>
      <p>只记录已知内容，时间不明可留空。保存不会自动建案、合并案件或形成结论。</p>
      <Form form={form} layout="vertical">
        {scopes.length > 1 && <Form.Item name="operational_area_id" label="所属厂区" rules={[{ required: true }]}><Select options={scopes.map(item => ({ value: item.operational_area_id, label: item.area_name }))} /></Form.Item>}
        <Form.Item name="content" label="线索内容" rules={[{ required: true, whitespace: true, message: '请写下已知线索' }]}><Input.TextArea rows={4} /></Form.Item>
        <Form.Item name="location" label="发现地点或区域"><Input /></Form.Item>
        <Form.Item name="reported_at" label="获知时间（可未知）"><DatePicker showTime /></Form.Item>
      </Form>
      {save.isError && <p role="alert">线索未保存，请检查内容和当前权限后重试。</p>}
    </Modal>
  </>
}
