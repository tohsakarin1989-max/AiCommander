import { Button, Form, Input, InputNumber, Select, Switch } from 'antd'
import type { FormInstance } from 'antd'
import { oilUnitOptions } from './CaseSourceFields'

const { Option } = Select

interface CaseEntryPrecheckProps {
  form: FormInstance
  onBonusVehicleScopeChange: (checked: boolean) => void
  onBonusPersonScopeChange: (checked: boolean) => void
}

export const CaseEntryPrecheck = ({ form, onBonusVehicleScopeChange, onBonusPersonScopeChange }: CaseEntryPrecheckProps) => {
  const watchedBonusHasVehicle = Form.useWatch('bonus_has_vehicle', form)
  const watchedBonusHasPerson = Form.useWatch('bonus_has_person', form)
  return (<>
      <p className="narr">只补录已经掌握的人员和车辆。未发现、未查明不等于必须补填；资料完整性与分析能力由保存预检分别提示。</p>
      <div className="cases-bonus-scope-grid">
        <div>
          <Form.Item name="bonus_has_vehicle" valuePropName="checked" noStyle>
            <Switch size="small" onChange={onBonusVehicleScopeChange} />
          </Form.Item>
          <b>涉案车辆资料</b>
          <span>车辆类别、车牌和处置状态</span>
        </div>
        <div>
          <Form.Item name="bonus_has_person" valuePropName="checked" noStyle>
            <Switch size="small" onChange={onBonusPersonScopeChange} />
          </Form.Item>
          <b>涉案人员资料</b>
          <span>已掌握的人员、角色和处理情况</span>
        </div>
        <div>
          <Form.Item name="bonus_has_oil" valuePropName="checked" noStyle>
            <Switch size="small" />
          </Form.Item>
          <b>涉油检斤处置</b>
          <span>油量、含水率和入库/回收</span>
        </div>
        <div>
          <Form.Item name="bonus_has_police" valuePropName="checked" noStyle>
            <Switch size="small" />
          </Form.Item>
          <b>报案立案佐证</b>
          <span>报案、立案和公安联系人</span>
        </div>
      </div>

      {watchedBonusHasVehicle && (
        <Form.List name="initial_vehicles">
          {(fields, { add, remove }) => (
            <div className="cases-bonus-draft">
              <div className="cases-bonus-draft-head">
                <span>涉案车辆</span>
                <Button size="small" onClick={() => add({})}>增加车辆</Button>
              </div>
              {fields.map(({ key, name, ...restField }) => (
                <div key={key} className="cases-bonus-draft-row">
                  <Form.Item {...restField} name={[name, 'id']} hidden>
                    <Input />
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'vehicle_type']}
                    label="车辆考核类别"
                  >
                    <Select allowClear placeholder="请选择车辆类别">
                      {['摩托车（电动车）', '5吨以下机动车', '5吨以上机动车', '重型挂车', '机动船', '3吨以下炼化油罐', '3吨以上炼化油罐'].map(option => (
                        <Option key={option} value={option}>{option}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'plate_number']}
                    label="车牌/编号"
                  >
                    <Input placeholder="可选" />
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'handling_status']}
                    label="车辆处理"
                  >
                    <Select allowClear placeholder="请选择">
                      {['移交公安', '扣押停放', '待处理', '返还'].map(option => (
                        <Option key={option} value={option}>{option}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Button size="small" disabled={fields.length === 1} onClick={() => remove(name)}>
                    删除
                  </Button>
                  <details style={{ gridColumn: '1 / -1' }}>
                    <summary>载油与道路通行条件（选填）</summary>
                    <Form.Item {...restField} name={[name, 'oil_volume']} label="车辆载油记录"><InputNumber min={0} /></Form.Item>
                    <Form.Item {...restField} name={[name, 'oil_volume_unit']} label="载油单位"><Select options={oilUnitOptions} placeholder="单位未知" /></Form.Item>
                    <p>只填写已掌握的车辆条件。车辆总重不是载油量或核定载质量，未知时留空，不影响案件保存。</p>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
                      <Form.Item {...restField} name={[name, 'road_vehicle_kind']} label="道路计算车型">
                        <Select allowClear placeholder="未知则留空" options={[{ value: 'auto', label: '小客车' }, { value: 'truck', label: '货车' }]} />
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'height_m']} label="车高（米）" rules={[{ type: 'number', min: 0.01 }]}>
                        <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} placeholder="选填" />
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'gross_weight_t']} label="车辆总重（吨）" rules={[{ type: 'number', min: 0.01 }]}>
                        <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} placeholder="选填" />
                      </Form.Item>
                    </div>
                  </details>
                </div>
              ))}
            </div>
          )}
        </Form.List>
      )}

      {watchedBonusHasPerson && (
        <Form.List name="initial_persons">
          {(fields, { add, remove }) => (
            <div className="cases-bonus-draft">
              <div className="cases-bonus-draft-head">
                <span>抓获/涉案人员</span>
                <Button size="small" onClick={() => add({})}>增加人员</Button>
              </div>
              {fields.map(({ key, name, ...restField }) => (
                <div key={key} className="cases-bonus-draft-row">
                  <Form.Item {...restField} name={[name, 'id']} hidden>
                    <Input />
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'name']}
                    label="姓名/代称"
                  >
                    <Input placeholder="可选" />
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'handling_status']}
                    label="人员处理类型"
                  >
                    <Select allowClear placeholder="请选择处理类型">
                      {['移交公安', '刑事拘留', '行政拘留', '治安拘留', '行政处罚', '教育放行', '待核查'].map(option => (
                        <Option key={option} value={option}>{option}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'role']}
                    label="人员角色"
                  >
                    <Input placeholder="如司机、协助人员" />
                  </Form.Item>
                  <Button size="small" disabled={fields.length === 1} onClick={() => remove(name)}>
                    删除
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Form.List>
      )}
    </>
  )
}
