import { Col, Form, Row, Select } from 'antd'
import type { FormInstance } from 'antd'
import { changedFeedbackFields, feedbackFields, feedbackFormChoice } from './caseFeedback'

export default function CaseFeedbackFields({ form }: { form: FormInstance }) {
  return <section aria-label="已知公安反馈">
    <p>只登记已掌握的信息。移交公安不代表已立案或已办结；未获反馈可以保留未知。旧草稿中未明确确认的反馈也保持未知，可在此重新核对。</p>
    <Row gutter={12}>{feedbackFields.map(field => <Col key={field} xs={24} sm={12}>
      <Form.Item name={field} label={field === 'police_reported' ? '报案情况' : '立案反馈'}
        getValueProps={value => ({ value: feedbackFormChoice({ ...form.getFieldsValue(true), [field]: value }, field) })}
        getValueFromEvent={value => value === 'yes' ? true : value === 'no' ? false : null}>
        <Select onChange={() => form.setFieldValue('feedback_changed_fields', changedFeedbackFields(form.getFieldValue('feedback_changed_fields'), field))}
          options={[
            { value: 'unknown', label: field === 'case_filed' ? '未知／未获反馈' : '未知／未掌握' },
            { value: 'yes', label: field === 'case_filed' ? '已确认立案' : '已报案' },
            { value: 'no', label: field === 'case_filed' ? '明确未立案' : '明确未报案' },
          ]} />
      </Form.Item>
    </Col>)}</Row>
  </section>
}
