import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { caseApi } from '../../services/cases'
import { suggestionsApi } from '../../services/suggestions'
import type { Case, CaseDiagram, CaseProcessingCard } from '../../types'
import './CaseReviewCockpit.css'

type Tone = 'blue' | 'green' | 'amber' | 'red' | 'teal'

interface CaseFactView {
  timeLabel: string
  locationLabel: string
  vehicleLabel: string
  plateLabel: string
  oilLabel: string
  dispositionLabel: string
  evidenceGaps: string[]
  weakTags: string[]
  readiness: string
  confidence: number | null
}

const fallbackCases: Case[] = [
  {
    id: 2,
    case_number: '20260102-001',
    occurred_time: '2026-01-02 19:00:00',
    latitude: 47.057434,
    longitude: 123.878915,
    description: '保卫大队在齐齐哈尔市昂昂溪区，抓获盗油车辆一台，一汽解放成品油罐车。车牌照：黑E11111，车内有油，共计10吨。盗油车辆和嫌疑人移交油田分局刑侦九大队，车内原油由九厂保卫大队回收。已立案。',
    quality_score: 32.57,
    quality_level: 'low',
    quality_issues: {
      score: 32.57,
      level: 'low',
      category_scores: {},
      warnings: [{ field: 'case_evidence', message: '涉案车辆证据照片/拓印不完整' }],
      recommendations: ['补齐车辆明细、人员明细、油量字段和证据材料。'],
      facts: {},
      missing_required: [
        { field: 'location', label: '案发地点', reason: '业务细则要求完整报送' },
        { field: 'case_type', label: '案件类型', reason: '业务细则要求完整报送' },
        { field: 'report_time', label: '报送时间', reason: '业务细则要求完整报送' },
        { field: 'report_unit', label: '报送/责任单位', reason: '业务细则要求完整报送' },
        { field: 'source_type', label: '案件线索来源', reason: '业务细则要求完整报送' },
        { field: 'vehicles', label: '涉案车辆明细', reason: '业务细则要求完整报送' },
        { field: 'persons', label: '抓获人员明细', reason: '业务细则要求完整报送' },
        { field: 'oil_volume', label: '涉案原油数量/检斤数量', reason: '业务细则要求完整报送' },
      ],
    },
    status: 'pending',
  },
  {
    id: 1,
    case_number: '20251130-001',
    occurred_time: '2025-11-30 16:00:00',
    latitude: 46.3939,
    longitude: 124.789681,
    case_type: '涉油其他',
    oil_volume: 0.1,
    description: '敖南保卫班在大庆市红岗区创业村庄两公里树林带，抓获盗油车辆银色哈飞微型一台，无牌照，车内原油两袋，共计0.1吨，盗油车辆暂扣保卫大队收油队，原油由保卫大队收油队回收。',
    quality_score: 39.36,
    quality_level: 'low',
    quality_issues: {
      score: 39.36,
      level: 'low',
      category_scores: {},
      warnings: [{ field: 'case_evidence', message: '涉案车辆证据照片/拓印不完整' }],
      recommendations: ['补齐车辆明细、人员明细、原油性质和处理方式。'],
      facts: {},
      missing_required: [
        { field: 'location', label: '案发地点', reason: '业务细则要求完整报送' },
        { field: 'report_time', label: '报送时间', reason: '业务细则要求完整报送' },
        { field: 'report_unit', label: '报送/责任单位', reason: '业务细则要求完整报送' },
        { field: 'source_type', label: '案件线索来源', reason: '业务细则要求完整报送' },
        { field: 'vehicles', label: '涉案车辆明细', reason: '业务细则要求完整报送' },
        { field: 'persons', label: '抓获人员明细', reason: '业务细则要求完整报送' },
        { field: 'oil_nature', label: '原油性质', reason: '业务细则要求完整报送' },
      ],
    },
    status: 'pending',
  },
]

const stages: Array<{ step: number; title: string; meta: string; tone: Tone }> = [
  { step: 1, title: '录入预检', meta: '先提示，不强制保存', tone: 'green' },
  { step: 2, title: '证据补齐', meta: '缺项优先级', tone: 'amber' },
  { step: 3, title: '待办分流', meta: '按质量/风险排队', tone: 'blue' },
  { step: 4, title: '处理卡', meta: '事实/推断分层', tone: 'teal' },
  { step: 5, title: '人工确认', meta: '链条不自动认定', tone: 'red' },
  { step: 6, title: '报告审稿', meta: '引用来源校验', tone: 'blue' },
]

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function textOf(value: unknown, fallback = '待补录'): string {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

function formatTime(value?: string): string {
  if (!value) return '待补录'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : value
}

function extractBetween(text: string, pattern: RegExp, fallback = '待核验'): string {
  const match = text.match(pattern)
  return match?.[1]?.trim() || fallback
}

function extractOil(text: string, structured?: number): string {
  if (typeof structured === 'number') return `${structured} 吨`
  const match = text.match(/共计\s*([0-9]+(?:\.[0-9]+)?)\s*吨/)
  return match?.[1] ? `${match[1]} 吨，待入结构字段` : '待补录'
}

function extractPlate(text: string): string {
  if (text.includes('无牌照') || text.includes('无牌')) return '无牌照'
  return extractBetween(text, /车牌照[:：]\s*([^，。\s]+)/, '待核验')
}

function extractVehicle(text: string): string {
  if (!text) return '待补录'
  return extractBetween(text, /抓获盗油车辆(?:一台，)?([^，。]+)/, '描述中有车辆线索，待结构化')
}

function extractLocation(caseItem: Case): string {
  if (caseItem.location) return caseItem.location
  const description = caseItem.description ?? ''
  return extractBetween(description, /在([^，。]+)，抓获/, caseItem.latitude && caseItem.longitude ? '经纬度已存在，地点字段为空' : '待补录')
}

function buildFactView(caseItem: Case | null): CaseFactView {
  if (!caseItem) {
    return {
      timeLabel: '待选择',
      locationLabel: '待选择',
      vehicleLabel: '待选择',
      plateLabel: '待选择',
      oilLabel: '待选择',
      dispositionLabel: '待选择',
      evidenceGaps: [],
      weakTags: [],
      readiness: '待选择案件',
      confidence: null,
    }
  }
  const description = caseItem.description ?? ''
  const features = asRecord(caseItem.features)
  const management = asRecord(features.management)
  const qualityGaps = caseItem.quality_issues?.missing_required?.map(item => item.label) ?? []
  const managementGaps = Array.isArray(management.missing_fields) ? management.missing_fields.map(String) : []
  const confidence = typeof features.confidence === 'number' ? features.confidence : null
  const time = dayjs(caseItem.occurred_time)
  const weakTags = [
    time.isValid() && time.hour() >= 18 ? '夜间时段' : time.isValid() && time.hour() >= 12 ? '下午时段' : '',
    time.isValid() && [11, 0, 1].includes(time.month()) ? '冬季时段' : '',
    description.includes('罐车') ? '罐车/储油车辆' : '',
    description.includes('林带') ? '隐蔽空间' : '',
    '技防覆盖待核实',
  ].filter(Boolean)

  return {
    timeLabel: formatTime(caseItem.occurred_time),
    locationLabel: extractLocation(caseItem),
    vehicleLabel: extractVehicle(description),
    plateLabel: caseItem.vehicle_info?.plate_number ?? extractPlate(description),
    oilLabel: extractOil(description, caseItem.oil_volume),
    dispositionLabel: description.includes('移交') ? '移交公安/刑侦队伍，待补材料' : description.includes('暂扣') ? '暂扣并回收，待补材料' : '待补录',
    evidenceGaps: qualityGaps.length ? qualityGaps : managementGaps,
    weakTags,
    readiness: caseItem.latitude && caseItem.longitude ? '时空研判可用，串案需补证' : '缺少坐标，时空研判受限',
    confidence,
  }
}

function missingCount(caseItem: Case): number {
  return caseItem.quality_issues?.missing_required?.length
    ?? (Array.isArray(caseItem.features?.management?.missing_fields) ? caseItem.features.management.missing_fields.length : 0)
}

function qualityClass(caseItem: Case): Tone {
  const score = caseItem.quality_score ?? 0
  if (score >= 80) return 'green'
  if (score >= 60) return 'amber'
  return 'red'
}

function topCardGaps(card?: CaseProcessingCard | null, fallback: string[] = []) {
  const cardItems = (card?.gap_groups ?? [])
    .flatMap(group => group.items.map(item => ({
      key: `${group.key}-${String(item.field ?? item.label ?? Math.random())}`,
      title: textOf(item.label ?? group.label, group.label),
      meta: textOf(item.reason ?? group.impacted_modules.join('、'), '影响后续研判或报告'),
      severity: group.severity,
      route: group.route,
    })))
  if (cardItems.length) return cardItems.slice(0, 4)
  return fallback.slice(0, 4).map((label, index) => ({
    key: `fallback-${label}`,
    title: label,
    meta: index < 2 ? '缺少结构化记录，阻断自动串案' : '影响报告引用和经验卡沉淀',
    severity: index < 2 ? 'high' : 'medium',
    route: '/cases',
  }))
}

const CaseReviewCockpit: React.FC = () => {
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null)

  const casesQuery = useQuery({
    queryKey: ['case-review-cockpit', 'cases'],
    queryFn: () => caseApi.getCases({ limit: 60 }),
    staleTime: 60_000,
    retry: 1,
  })

  const suggestionsQuery = useQuery({
    queryKey: ['case-review-cockpit', 'suggestions'],
    queryFn: () => suggestionsApi.list({ limit: 80, status: 'open' }),
    staleTime: 60_000,
    retry: 1,
  })

  const cases = useMemo(() => {
    const source = casesQuery.data?.length ? casesQuery.data : fallbackCases
    return [...source]
      .sort((a, b) => (a.quality_score ?? 100) - (b.quality_score ?? 100))
      .slice(0, 8)
  }, [casesQuery.data])

  useEffect(() => {
    if (selectedCaseId == null && cases.length) {
      setSelectedCaseId(cases[0].id)
    }
  }, [cases, selectedCaseId])

  const selectedCase = cases.find(item => item.id === selectedCaseId) ?? cases[0] ?? null
  const selectedFacts = useMemo(() => buildFactView(selectedCase), [selectedCase])

  const processingCardQuery = useQuery({
    queryKey: ['case-review-cockpit', 'processing-card', selectedCase?.id],
    queryFn: () => caseApi.getProcessingCard(selectedCase!.id),
    enabled: Boolean(selectedCase),
    retry: 1,
  })

  const diagramQuery = useQuery({
    queryKey: ['case-review-cockpit', 'diagram', selectedCase?.id],
    queryFn: () => caseApi.getCaseDiagram(selectedCase!.id),
    enabled: Boolean(selectedCase),
    retry: 1,
  })

  const chainLinksQuery = useQuery({
    queryKey: ['case-review-cockpit', 'chain-links', selectedCase?.id],
    queryFn: () => caseApi.getChainLinks(selectedCase!.id),
    enabled: Boolean(selectedCase),
    retry: 1,
  })

  const openSuggestions = suggestionsQuery.data?.suggestions ?? []
  const lowQualityCount = (casesQuery.data ?? fallbackCases).filter(item => (item.quality_score ?? 100) < 60).length
  const manualReviewCount = openSuggestions.filter(item => ['review', 'experience', 'processing_card', 'report_quality'].includes(String(item.type))).length || cases.filter(item => missingCount(item) >= 6).length
  const reportReadyCount = cases.filter(item => (item.quality_score ?? 0) >= 70 && missingCount(item) <= 3).length
  const gaps = topCardGaps(processingCardQuery.data, selectedFacts.evidenceGaps)
  const diagram = diagramQuery.data as CaseDiagram | undefined
  const chainCount = chainLinksQuery.data?.length ?? 0
  const graphBoundary = chainCount > 0
    ? `已有 ${chainCount} 条链条记录，仍需人工确认后进入正式报告。`
    : '当前无正式链条记录；图谱仅展示事实节点、弱线索和待补证缺口。'

  return (
    <div className="page-full crc-page">
      <section className="crc-workflow">
        <div className="crc-stage-strip">
          {stages.map(stage => (
            <div key={stage.step} className={`crc-stage crc-stage--${stage.tone}${stage.step === 3 ? ' is-active' : ''}`}>
              <span>{stage.step}</span>
              <strong>{stage.title}</strong>
              <small>{stage.meta}</small>
            </div>
          ))}
        </div>
        <div className="crc-metrics">
          <div><span>低质量案件</span><strong>{lowQualityCount}</strong></div>
          <div><span>待人工确认</span><strong>{manualReviewCount}</strong></div>
          <div><span>可出报告</span><strong>{reportReadyCount}</strong></div>
        </div>
      </section>

      <section className="crc-grid">
        <aside className="crc-panel crc-queue">
          <div className="crc-panel-head">
            <div>
              <h2>案件队列</h2>
              <p>按办理价值排序</p>
            </div>
            <span className="crc-chip crc-chip--amber">A 阶段</span>
          </div>
          <div className="crc-tabs">
            <button className="is-on">待补证</button>
            <button>待复核</button>
            <button>可报告</button>
          </div>
          <div className="crc-case-list">
            {cases.slice(0, 5).map(item => {
              const count = missingCount(item)
              const score = item.quality_score ?? 0
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`crc-case-row${selectedCase?.id === item.id ? ' is-selected' : ''}`}
                  onClick={() => setSelectedCaseId(item.id)}
                >
                  <span className="crc-case-line">
                    <strong>{item.case_number}</strong>
                    <em className={`crc-chip crc-chip--${qualityClass(item)}`}>{item.quality_level ?? 'unknown'} {Math.round(score)}</em>
                  </span>
                  <span className="crc-case-desc">{extractLocation(item)} · {item.case_type || extractVehicle(item.description ?? '')}</span>
                  <span className="crc-progress">
                    <i><b style={{ width: `${Math.min(96, Math.max(18, score))}%` }} /></i>
                    <small>{count} 缺项</small>
                  </span>
                </button>
              )
            })}
          </div>
          <div className="crc-ai-intake">
            <div className="crc-ai-title">AI 案情录入副驾驶</div>
            <dl>
              <div><dt>从描述识别车辆</dt><dd>{selectedFacts.vehicleLabel}</dd></div>
              <div><dt>从描述识别油量</dt><dd>{selectedFacts.oilLabel}</dd></div>
              <div><dt>阻断自动结论</dt><dd>{selectedFacts.evidenceGaps.length ? `缺 ${selectedFacts.evidenceGaps.length} 项证据` : '待人工复核'}</dd></div>
            </dl>
          </div>
        </aside>

        <main className="crc-center">
          <section className="crc-panel crc-case-card">
            <div className="crc-card-head">
              <div>
                <h2>案件处理卡</h2>
                <p>{selectedCase?.case_number ?? '未选择'} · 当前选中</p>
              </div>
              <div className="crc-card-tags">
                <span className="crc-chip crc-chip--red">不满足自动串案</span>
                <span className="crc-chip crc-chip--blue">需人工复核</span>
              </div>
            </div>
            <div className="crc-card-body">
              <div className="crc-fact-grid">
                <div className="crc-fact"><span>发生时间</span><strong>{selectedFacts.timeLabel}</strong></div>
                <div className="crc-fact"><span>地点信息</span><strong>{selectedFacts.locationLabel}</strong></div>
                <div className="crc-fact"><span>车辆线索</span><strong>{selectedFacts.vehicleLabel}<br />车牌：{selectedFacts.plateLabel}</strong></div>
                <div className="crc-fact"><span>油品/处置</span><strong>{selectedFacts.oilLabel}<br />{selectedFacts.dispositionLabel}</strong></div>
              </div>
              <div className="crc-ai-card">
                <div className="crc-ai-card-head">
                  <strong>AI 处理建议</strong>
                  <span className="crc-chip crc-chip--amber">
                    {selectedFacts.confidence == null ? '待计算' : `${selectedFacts.confidence.toFixed(2)} 置信`}
                  </span>
                </div>
                <p>可确认的是案情文本、时间、经纬度和部分车辆/油量线索；当前不能确认上下游链条。优先补齐结构化车辆、人员、证据和报送信息，再进入报告引用。</p>
                <div className="crc-actions">
                  <button>生成补证清单</button>
                  <button>转人工确认</button>
                </div>
              </div>
            </div>
          </section>

          <section className="crc-lower">
            <article className="crc-panel crc-evidence">
              <div className="crc-panel-head">
                <div>
                  <h2>证据补齐清单</h2>
                  <p>{selectedFacts.readiness}</p>
                </div>
                <span className="crc-chip crc-chip--red">{selectedFacts.evidenceGaps.length || gaps.length} 项缺口</span>
              </div>
              <div className="crc-evidence-tabs">
                <span>车辆</span>
                <span>人员</span>
                <span>油品</span>
                <span>报送</span>
              </div>
              <div className="crc-check-list">
                {gaps.map((gap, index) => (
                  <div key={gap.key} className="crc-check">
                    <span className={`crc-check-dot ${gap.severity === 'high' || index < 2 ? 'is-hot' : 'is-warn'}`}>{gap.severity === 'high' || index < 2 ? '!' : '?'}</span>
                    <div>
                      <strong>{gap.title}</strong>
                      <small>{gap.meta}</small>
                    </div>
                    <em>{gap.severity === 'high' || index < 2 ? '高' : '中'}</em>
                  </div>
                ))}
              </div>
            </article>

            <article className="crc-panel crc-graph">
              <div className="crc-panel-head">
                <div>
                  <h2>一案一图 / 弱线索核验</h2>
                  <p>{diagram ? `${diagram.nodes.length} 节点 · ${diagram.edges.length} 关系` : '辅助模块'}</p>
                </div>
                <span className="crc-chip crc-chip--amber">不作主结论</span>
              </div>
              <div className="crc-mini-map">
                <span className="crc-map-node crc-map-node--one">当前案</span>
                <span className="crc-map-node crc-map-node--two">相似案</span>
                <i />
              </div>
              <p className="crc-graph-note">{graphBoundary}</p>
            </article>
          </section>
        </main>

        <aside className="crc-panel crc-review">
          <div className="crc-panel-head">
            <div>
              <h2>报告审稿与经验卡</h2>
              <p>事实可引用，推断需确认</p>
            </div>
            <span className="crc-chip crc-chip--teal">AI 审稿</span>
          </div>

          <div className="crc-review-block">
            <div className="crc-review-title">
              <strong>引用审查</strong>
              <span className="crc-chip crc-chip--green">可引用</span>
            </div>
            <p className="crc-quote">可引用：{selectedFacts.timeLabel}，{selectedFacts.locationLabel}，描述中包含 {selectedFacts.vehicleLabel}、{selectedFacts.plateLabel} 和油量 {selectedFacts.oilLabel}。</p>
            <p className="crc-redline">不可直接引用：与其他案件存在上下游关系。当前缺少正式链条记录和交叉证据。</p>
          </div>

          <div className="crc-review-block">
            <div className="crc-review-title">
              <strong>研判分层</strong>
              <span className="crc-chip crc-chip--amber">人工确认前</span>
            </div>
            <div className="crc-layer crc-layer--fact"><b>事实层</b><span>时间、经纬度、案情文本、车辆和油量线索可展示。</span></div>
            <div className="crc-layer crc-layer--weak"><b>弱线索</b><span>{selectedFacts.weakTags.slice(0, 4).join('、') || '待提取'}，进入经验卡时必须标注来源。</span></div>
            <div className="crc-layer crc-layer--block"><b>阻断项</b><span>{selectedFacts.evidenceGaps.slice(0, 4).join('、') || '暂无'}，禁止自动串案。</span></div>
          </div>

          <div className="crc-review-block">
            <div className="crc-review-title">
              <strong>报告草稿骨架</strong>
              <span className="crc-chip crc-chip--blue">待补证</span>
            </div>
            <dl className="crc-draft">
              <div><dt>案情摘要</dt><dd>可生成，但关键字段需同步结构化。</dd></div>
              <div><dt>证据附件</dt><dd>{selectedFacts.evidenceGaps.length ? selectedFacts.evidenceGaps.slice(0, 3).join('、') : '待人工确认完整性'}。</dd></div>
              <div><dt>研判建议</dt><dd>仅建议补证和复核，不给串案结论。</dd></div>
            </dl>
          </div>
        </aside>
      </section>
    </div>
  )
}

export default CaseReviewCockpit
