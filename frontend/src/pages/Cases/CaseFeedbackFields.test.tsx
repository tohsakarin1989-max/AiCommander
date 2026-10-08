import { renderToStaticMarkup } from 'react-dom/server'
import { Form } from 'antd'
import { describe, expect, it } from 'vitest'
import CaseFeedbackFields from './CaseFeedbackFields'

function Fixture({ values }: { values: Record<string, unknown> }) {
  const [form] = Form.useForm()
  return <Form form={form} initialValues={values}><CaseFeedbackFields form={form} /></Form>
}

describe('三态反馈表单', () => {
  it('未知和旧草稿false都显示未知，不能显示成明确否', () => {
    const html = renderToStaticMarkup(<Fixture values={{ police_reported: false, case_filed: false }} />)
    expect(html).toContain('未知／未掌握'); expect(html).toContain('未知／未获反馈')
    expect(html).not.toContain('title="明确未报案"')
    expect(html).toContain('移交公安不代表已立案或已办结')
  })
  it('有来源标记的明确否和是按真实状态呈现', () => {
    const html = renderToStaticMarkup(<Fixture values={{ police_reported: false, case_filed: true,
      feedback_initial_known_fields: ['police_reported', 'case_filed'] }} />)
    expect(html).toContain('明确未报案'); expect(html).toContain('已确认立案')
  })
})
