import { Button, Form, Input, InputNumber, Select, Space, Typography } from 'antd'

/** Optional administrator fields; never added to the ordinary case workflow. */
export default function NewRoadConnectionFields() {
  return <>
    <Typography.Paragraph>仅用于公共地图尚未收录的新道路。分段从 1 开始，起点和终点按导入线形的顺序确定。
      请使用核查资料中明确的公共节点编号；系统不会按距离吸附，也不会自动授予通行许可。</Typography.Paragraph>
    <Form.Item name="publicSourceHash" label="公共道路源版本（SHA-256）"
      extra="填写道路源 PBF 的校验值，不是地图瓦片或整个更新包的校验值。"
      rules={[{ required: true, pattern: /^[a-f0-9]{64}$/, message: '请输入 64 位小写 SHA-256' }]}>
      <Input maxLength={64} autoComplete="off" />
    </Form.Item>
    <Form.List name="newConnections">
      {(fields, { add, remove }) => <>
        {fields.map(field => <div key={field.key}>
          <Typography.Text>连接点 {field.name + 1}</Typography.Text>
          <Space wrap align="start">
            <Form.Item name={[field.name, 'segment']} label="道路分段" rules={[{ required: true }]}>
              <InputNumber min={1} max={10000} precision={0} />
            </Form.Item>
            <Form.Item name={[field.name, 'endpoint']} label="线形端点" rules={[{ required: true }]}>
              <Select style={{ minWidth: 100 }} options={[{ value: 'start', label: '起点' }, { value: 'end', label: '终点' }]} />
            </Form.Item>
            <Form.Item name={[field.name, 'node']} label="公共节点编号" rules={[{ required: true, pattern: /^[1-9][0-9]*$/, message: '请输入正整数编号' }]}>
              <Input inputMode="numeric" autoComplete="off" style={{ width: 190 }} />
            </Form.Item>
          </Space>
          <Button type="link" onClick={() => remove(field.name)} aria-label={`移除连接点 ${field.name + 1}`}>移除</Button>
        </div>)}
        <Button onClick={() => add({ segment: 1, endpoint: 'start', node: '' })}>添加连接点</Button>
      </>}
    </Form.List>
  </>
}
