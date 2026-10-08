import { renderToStaticMarkup } from 'react-dom/server'
import { Form } from 'antd'
import { describe, expect, it } from 'vitest'
import { CaseSourceCollections } from './CaseSourceFields'
import { buildCaseEntrySubmitPayload } from './caseEntrySubmitPayload'

describe('来源明细表单身份注册', () => {
  it('真实 Form.List 为同值明细分别注册隐藏 ID，重排后仍按原 ID 提交', () => {
    const values = {
      initial_locations: [8, 3].map(id => ({ id, role: 'discovery', precision: 'unknown' })),
      initial_measurements: [9, 2].map(id => ({ id, value: 1, unit: 'liter', stage: 'seized' })),
    }
    const html = renderToStaticMarkup(<Form initialValues={values}><CaseSourceCollections locationsEnabled measurementsEnabled /></Form>)
    for (const [field, ids] of Object.entries({ initial_locations: [8, 3], initial_measurements: [9, 2] })) {
      ids.forEach((id, index) => {
        expect(html).toContain(`id="${field}_${index}_id"`)
        expect(html).toMatch(new RegExp(`id="${field}_${index}_id"[^>]*value="${id}"`))
      })
    }
    const reordered = buildCaseEntrySubmitPayload({ ...values, initial_locations: [...values.initial_locations].reverse(),
      initial_measurements: [...values.initial_measurements].reverse() }, { mode: 'edit' })
    expect(reordered.initial_locations?.map(row => row.id)).toEqual([3, 8])
    expect(reordered.initial_measurements?.map(row => row.id)).toEqual([2, 9])
  })

  it('明细读取失败时不挂载 ID 或编辑表单，不把缓存当作可编辑内容', () => {
    const html = renderToStaticMarkup(<Form initialValues={{ initial_locations: [{ id: 7 }], initial_measurements: [{ id: 9 }] }}>
      <CaseSourceCollections locationsEnabled={false} measurementsEnabled={false} /></Form>)
    expect(html).toContain('地点明细读取失败')
    expect(html).toContain('测量明细读取失败')
    expect(html).not.toContain('initial_locations_0_id')
    expect(html).not.toContain('initial_measurements_0_id')
  })
})
