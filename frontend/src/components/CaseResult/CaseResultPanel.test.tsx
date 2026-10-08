import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { CaseResult } from '../../types/caseResult'
import CaseResultPanel from './CaseResultPanel'
import { caseResultMapModel } from './caseResultMapModel'
import { hypothesisSupportLabel } from '../Map/caseHypothesisMap'

// These SSR presentation cases keep exercising the real road/material children;
// current-principal enforcement is covered separately, not by this identity stub.
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({
  user: { id: 1, role: 'analyst' }, sessionEpoch: 1,
}) }))

const fixture = (): CaseResult => ({
  id: 'result-1', created_at: '2026-09-11T10:00:00Z', content_sha256: 'frozen-hash', freshness: 'current',
  content: {
    schema_version: 'case-result-4.1.0-1', case_id: 1,
    versions: { case_profile_id: 'p1', profile_version: 1, case_source_hash: 'source-hash',
      profile_schema: '4.1.0', dictionary_version: 'rules-1', analysis_run_id: 'r1', map_snapshot_id: 'map-1', algorithm_version: 'algorithm-1' },
    facts_summary: { label: '原始记录摘要，非新增核实结论', recorded_fields: { location: '冻结地点', case_type: '合成测试', oil_type: null }, evidence_refs: ['case_profile:p1'] },
    related_conditions: { latitude: 46.6, longitude: 125.1, evidence_count: 0 }, semantics: null,
    candidates: [{ id: 'h1', rank: 1, category: 'possible_source', title: '来源候选', claim: '合成候选解释',
      region: { type: 'circle', center: [125.2, 46.7], radius_m: 800 }, score: 72.5, score_kind: 'rule_support_not_probability',
      score_components: {}, evidence_refs: ['case_profile:p1', 'map_asset:3@snapshot:map-1'],
      supporting_evidence: ['支持一', '支持二'], counter_evidence: ['反向证据一'], information_gaps: ['缺少入口资料'],
      boundary: '仅供核查', status: 'candidate', is_official_fact: false }],
    information_gaps: { profile: [{ label: '缺少关键记录', reason: '合成缺项' }], analysis: [] },
    analysis_status: 'completed', boundary: ['不自动形成正式案件事实'],
  },
})

describe('统一成果展示', () => {
  it('显示全部支持与反向证据、引用和固定版本，不显示概率百分比', () => {
    const html = renderToStaticMarkup(<CaseResultPanel caseId={1} result={fixture()} />)
    for (const text of ['支持一', '支持二', '反向证据一', '缺少入口资料', 'map_asset:3@snapshot:map-1', 'frozen-hash', '冻结地点', '规则支持度：72.5']) expect(html).toContain(text)
    expect(html).not.toContain('72.5%')
    expect(html).not.toContain('置信度')
    expect(html).toContain('>0<')
  })
  it('失败、撤权和案件切换不保留缓存中的原文或地图', () => {
    for (const props of [{ error: true }, { error: true, errorStatus: 404 }, { caseId: 2 }]) {
      const html = renderToStaticMarkup(<CaseResultPanel caseId={1} result={fixture()} map={<div>地图私有内容</div>} {...props} />)
      expect(html).not.toContain('合成候选解释')
      expect(html).not.toContain('冻结地点')
      expect(html).not.toContain('地图私有内容')
    }
  })
  it('加载、空结果、接口故障、等待更新有不同说明', () => {
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} loading />)).toContain('正在读取')
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} error errorStatus={404} />)).toContain('尚未生成、引用已失效或当前不可访问')
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} error />)).toContain('暂时无法读取')
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} result={{ ...fixture(), freshness: 'pending_update' }} />)).toContain('等待更新')
  })
  it('没有候选明确说明信息不足，不虚构核查结论', () => {
    const result = fixture()
    result.content.candidates = []
    result.content.information_gaps.analysis = ['缺少坐标，未进行空间研判']
    const html = renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)
    expect(html).toContain('不代表不存在相关线索')
    expect(html).toContain('缺少坐标，未进行空间研判')
  })
  it('原文HTML仅显示文本，未知结构版本不尝试展示', () => {
    const result = fixture()
    result.content.candidates[0].claim = '<script>evil()</script>'
    const html = renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
    result.content.schema_version = 'unknown'
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)).not.toContain('来源候选')
  })
  it('不把缺少时区的冻结存储时间当成本地时刻', () => {
    const result = fixture()
    result.content.facts_summary.recorded_fields.occurred_time = '2026-09-10T14:00:00'
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)).toContain('存储值未注明时区')
    result.content.facts_summary.recorded_fields.occurred_time = '2026-09-10T14:00:00Z'
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)).not.toContain('存储值未注明时区')
  })
  it('组合版显示固定来源，基础版本明确道路未就绪', () => {
    const result = fixture()
    result.composition_status = 'road_not_ready'
    expect(renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)).toContain('当前道路组合未就绪')
    result.composition_status = 'ready'
    result.content.schema_version = 'case-result-composition-6.0.0-1'
    result.content.composition = { base_result_id: 'base-1', base_content_sha256: 'base-hash',
      road_artifact_id: 'road-1', road_content_sha256: 'road-hash',
      branch: { principal_user_id: 1, area_ids: [1], purpose: 'current_conditions_reference' } }
    result.content.road_versions = { network_id: 'network-1', analysis_at: '2026-09-27T00:00:00Z' }
    result.content.candidates[0].road_distance_m = 3000
    const html = renderToStaticMarkup(<CaseResultPanel caseId={1} result={result} />)
    for (const value of ['道路与生产条件比较后的来源候选', '3.00 公里', 'base-1', 'road-1', 'network-1', '同一冻结组合']) expect(html).toContain(value)
    expect(html).not.toContain('当前道路组合未就绪')
  })
})

describe('固定成果地图输入', () => {
  it('只使用冻结坐标、引用与地图版本，不需要传入当前案件', () => {
    const model = caseResultMapModel(fixture())
    expect(model.snapshotRef).toBe('map-1')
    expect(model.markers[0]).toMatchObject({ lat: 46.6, lng: 125.1, title: '冻结地点' })
    expect(model.productionAssetIds).toEqual([3])
    expect(model.hypothesisRegions[0].ruleSupport).toBe(72.5)
    expect(model.hypothesisRegions[0]).not.toHaveProperty('confidence')
  })
  it('坐标缺失或非法时不生成0点、不使用当前数据补齐', () => {
    for (const latitude of [null, '', '46.6', Number.NaN, 100]) {
      const result = fixture()
      result.content.related_conditions.latitude = latitude
      expect(caseResultMapModel(result).markers).toEqual([])
    }
  })
  it('新旧地图分数均不冒充概率', () => {
    expect(hypothesisSupportLabel({ ruleSupport: 72.5 })).toBe('规则支持度：72.5（非概率）')
    expect(hypothesisSupportLabel({ confidence: 0.8 })).toContain('未经概率校准')
    expect(hypothesisSupportLabel({ ruleSupport: Number.NaN })).toContain('未提供有效')
  })
  it('组合地图使用冻结入口，不将原空间圆圈或直线伪装成道路', () => {
    const result = fixture()
    result.content.composition = { base_result_id: 'base', base_content_sha256: 'b', road_artifact_id: 'road', road_content_sha256: 'r',
      branch: { principal_user_id: 1, area_ids: [1], purpose: 'current_conditions_reference' } }
    result.content.road_map = { map_snapshot_id: 'map-1', production_asset_ids: [13], warnings: [],
      reference_points: [{ id: '13', rank: 1, title: '可信入口', latitude: 46, longitude: 125 }] }
    const map = caseResultMapModel(result)
    expect(map.hypothesisRegions).toEqual([])
    expect(map.productionAssetIds).toEqual([13])
    expect(map.referencePoints?.[0]).toMatchObject({ id: '13', title: '可信入口', longitude: 125 })
  })
})
