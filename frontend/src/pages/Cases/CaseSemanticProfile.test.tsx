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
})
