import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CaseSemanticProfile, { semanticTimeLabel } from './CaseSemanticProfile'
import type { CaseSemantics } from '../../services/intelligenceFlow'

const payload: CaseSemantics = {
  rule_version: 'test-rule', method: 'local_dictionary_rules',
  assertions: [{ category: 'vehicle', value: '罐车', kind: 'negated', is_official_fact: false,
    reference: { field: 'description', source_sha256: 'hash', start: 0, end: 5, quote: '未发现罐车' } }],
}

describe('案件语义画像展示', () => {
  it('模型片段与规则分开显示，部分、故障、未知不冒充完整事实', () => {
    for (const [status, label] of [['partial', '部分结果'], ['unavailable', '暂不可用'], ['ready', '已返回']]) {
      const html = renderToStaticMarkup(<CaseSemanticProfile semantics={{ ...payload,
        model_extraction: { status, adapter_version: 'test', version: 'model-v1', model_id: 1,
          items: status === 'unavailable' ? [] : payload.assertions,
          rejected_items: status === 'partial' ? 1 : 0, boundary: '引用通过不代表模型判断正确。' },
      }} />)
      expect(html).toContain(label)
      expect(html).toContain('不代表完整覆盖原文')
      expect(html).toContain('规则画像继续可用')
      expect(html).toContain('model-v1')
      if (status === 'unavailable') expect(html).toContain('不表示没有线索')
      else expect(html).toContain('模型判断待核对')
    }
  })
  it('保留否定类型和原文出处，不称为已核实事实', () => {
    const html = renderToStaticMarkup(<CaseSemanticProfile semantics={payload} />)
    expect(html).toContain('原文否定')
    expect(html).toContain('未发现罐车')
    expect(html).toContain('不是核实结论')
    expect(html).toContain('查看原文出处')
  })
  it('旧画像、加载和失败状态各自说明，不把失败当空结果', () => {
    expect(renderToStaticMarkup(<CaseSemanticProfile />)).toContain('尚无语义画像')
    expect(renderToStaticMarkup(<CaseSemanticProfile loading />)).toContain('正在读取')
    const error = renderToStaticMarkup(<CaseSemanticProfile error semantics={payload} />)
    expect(error).toContain('无法读取')
    expect(error).not.toContain('罐车')
  })
  it('更新时明确提示这是上次处理结果', () => {
    expect(renderToStaticMarkup(<CaseSemanticProfile updating semantics={payload} />)).toContain('上一次处理结果')
  })
  it('未知类型不升级为明确陈述，原文HTML只以文本展示', () => {
    const item = { ...payload.assertions[0], kind: 'unknown', value: '<script>alert(1)</script>' }
    const html = renderToStaticMarkup(<CaseSemanticProfile semantics={{ ...payload, assertions: [item] }} />)
    expect(html).toContain('类型待核')
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
  })
  it('无词项不被表达为无线索', () => {
    expect(renderToStaticMarkup(<CaseSemanticProfile semantics={{ ...payload, assertions: [] }} />)).toContain('不表示案件没有线索')
  })
  it('小时精度不显示成原文明示的分钟', () => {
    expect(semanticTimeLabel('2026-09-11T02:00', 'hour')).toBe('2026-09-11 02时')
    expect(semanticTimeLabel('2026-09-11T02:15', 'minute')).toBe('2026-09-11 02:15')
  })
  it('片段保留动作否定、缺口和模型未启用状态，不扩大为事实或必填任务', () => {
    const html = renderToStaticMarkup(<CaseSemanticProfile semantics={{ ...payload, event_fragments: {
      schema_version: 'event-fragments-5.1-1', deep_model_status: 'not_enabled',
      boundary: '句内共现不证明实际轨迹。', coverage: { state: 'partial', limit: 100, omitted_fragments: 1 },
      items: [{ id: 'one', reference: payload.assertions[0].reference,
        actions: [{ value: '转运', kind: 'negated', reference: payload.assertions[0].reference, is_official_fact: false }],
        assertion_indices: [0, 999], time_interval_indices: [], missing_dimensions: ['upstream'],
        relation_status: 'sentence_cooccurrence_only', is_official_fact: false }],
    } }} />)
    expect(html).toContain('转运（原文否定）')
    expect(html).toContain('罐车（原文否定）')
    expect(html).toContain('提取不完整')
    expect(html).toContain('深层模型理解未启用')
    expect(html).toContain('不作为新增必填要求')
  })
})
