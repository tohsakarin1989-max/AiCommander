import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Empty, Input, Select, Spin, message } from 'antd'
import {
  CalculatorOutlined,
  DatabaseOutlined,
  FileProtectOutlined,
  SearchOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { caseApi } from '../../services/cases'
import type { BonusAssessment, Case } from '../../types'
import { bonusAccountingEnabled } from '../../config/features'
import {
  buildCaseBonusRows,
  buildCaseBonusSummary,
  type CaseBonusGateStatus,
  type CaseBonusRow,
} from './caseBonusAccountingModel'
import './CaseBonusAccounting.css'

const gateLabel: Record<CaseBonusGateStatus, string> = {
  ready: '材料齐全',
  blocked_by_materials: '材料未齐',
  rules_not_configured: '细则待配置',
  unknown: '待核验',
}

const materialStatusLabel: Record<string, string> = {
  satisfied: '已齐',
  partial: '待附件',
  missing: '缺失',
  not_required: '未触发',
}

const bonusStatusLabel: Record<string, string> = {
  calculated: '已测算',
  blocked_by_materials: '材料阻断',
  rules_not_configured: '细则待配置',
  not_applicable: '未触发',
}

function formatMoney(amount?: number | null) {
  if (amount == null) return '—'
  return `¥ ${amount.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

function gateClass(status: CaseBonusGateStatus) {
  return `case-bonus-gate case-bonus-gate--${status}`
}

function matchesKeyword(row: CaseBonusRow, keyword: string) {
  if (!keyword) return true
  const haystack = [
    row.caseNumber,
    row.location,
    row.reportUnit,
  ].filter(Boolean).join(' ').toLowerCase()
  return haystack.includes(keyword.toLowerCase())
}

const CaseBonusAccounting: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const queryCaseId = Number(searchParams.get('caseId'))
  const [selectedId, setSelectedId] = useState<number | null>(Number.isFinite(queryCaseId) && queryCaseId > 0 ? queryCaseId : null)
  const [keyword, setKeyword] = useState('')
  const [gateFilter, setGateFilter] = useState<CaseBonusGateStatus | 'all'>('all')

  if (!bonusAccountingEnabled) {
    return (
      <div className="page case-bonus-page">
        <Alert
          type="warning"
          showIcon
          message="案件奖金核算未启用"
          description="该模块属于内部复核事项，需同时启用前端 VITE_ENABLE_BONUS_ACCOUNTING 和后端 ENABLE_BONUS_ACCOUNTING 后访问。"
        />
      </div>
    )
  }

  const { data: cases = [], isLoading: casesLoading } = useQuery<Case[]>({
    queryKey: ['case-bonus-cases'],
    queryFn: () => caseApi.getCases({ limit: 500 }),
    refetchInterval: 60_000,
  })

  const selectedCase = useMemo(
    () => cases.find(caseItem => caseItem.id === selectedId) ?? null,
    [cases, selectedId],
  )

  const {
    data: selectedAssessment,
    isLoading: assessmentLoading,
    isError: assessmentError,
  } = useQuery<BonusAssessment>({
    queryKey: ['case-bonus-assessment', selectedId],
    queryFn: () => caseApi.getBonusAssessment(selectedId!),
    enabled: selectedId != null,
  })

  const calculateMutation = useMutation({
    mutationFn: () => caseApi.calculateBonusAssessment(selectedId!),
    onSuccess: (assessment) => {
      queryClient.setQueryData(['case-bonus-assessment', selectedId], assessment)
      queryClient.invalidateQueries({ queryKey: ['case-bonus-cases'] })
      message.success('已重新测算，等待人工复核')
    },
    onError: () => message.error('测算失败，请检查案件材料和奖金细则配置'),
  })

  useEffect(() => {
    if (Number.isFinite(queryCaseId) && queryCaseId > 0) {
      setSelectedId(queryCaseId)
    }
  }, [queryCaseId])

  const rows = useMemo(() => buildCaseBonusRows(cases, selectedAssessment ? { [selectedAssessment.case_id]: selectedAssessment } : {}), [cases, selectedAssessment])
  const summary = useMemo(() => buildCaseBonusSummary(rows), [rows])

  const filteredRows = useMemo(() => {
    const kw = keyword.trim()
    return rows.filter(row => {
      if (gateFilter !== 'all' && row.gateStatus !== gateFilter) return false
      return matchesKeyword(row, kw)
    })
  }, [gateFilter, keyword, rows])

  useEffect(() => {
    if (selectedId == null && rows.length > 0) {
      setSelectedId(rows[0].caseId)
    }
  }, [rows, selectedId])

  const selectCase = (id: number) => {
    setSelectedId(id)
    setSearchParams({ caseId: String(id) })
  }

  const handleCalculate = () => {
    if (selectedId == null) {
      message.warning('请先选择案件')
      return
    }
    calculateMutation.mutate()
  }

  const renderRow = (row: CaseBonusRow) => (
    <button
      key={row.caseId}
      type="button"
      className={`case-bonus-row${row.caseId === selectedId ? ' selected' : ''}`}
      onClick={() => selectCase(row.caseId)}
    >
      <span className="case-bonus-row-main">
        <b>{row.caseNumber}</b>
        <small>{row.location}</small>
      </span>
      <span className="case-bonus-row-meta">
        <span className={gateClass(row.gateStatus)}>{gateLabel[row.gateStatus]}</span>
        <small>{row.missingCount > 0 ? `缺 ${row.missingCount} 项` : '无缺项'}</small>
      </span>
    </button>
  )

  const renderAssessment = () => {
    if (!selectedCase) {
      return <Empty description="请选择左侧案件" />
    }
    if (assessmentLoading) {
      return <Spin tip="加载奖金测算结果..." />
    }
    if (assessmentError || !selectedAssessment) {
      return (
        <Alert
          type="warning"
          showIcon
          message="暂未取得测算结果"
          description="可先检查案件材料是否齐全，或返回案件列表补录佐证材料。"
        />
      )
    }

    const activeItems = selectedAssessment.bonus_items.filter(item => item.status !== 'not_applicable')
    const blocked = selectedAssessment.material_gate.status === 'blocked_by_materials'

    return (
      <>
        <div className="case-bonus-detail-head">
          <div>
            <span className="case-bonus-private"><FileProtectOutlined /> 内部复核</span>
            <h2>{selectedAssessment.case_number}</h2>
            <p>{selectedCase.location || '未填写地点'} · {selectedCase.report_unit || '未填写责任单位'}</p>
          </div>
          <div className="case-bonus-total">
            <span>建议测算额</span>
            <strong>{formatMoney(selectedAssessment.total_suggested_amount)}</strong>
          </div>
        </div>

        <div className="case-bonus-gatebar">
          <span className={gateClass(selectedAssessment.material_gate.status)}>
            {gateLabel[selectedAssessment.material_gate.status]}
          </span>
          <span>
            材料 {selectedAssessment.material_gate.satisfied_count}/{selectedAssessment.material_gate.required_count}
          </span>
          <span>
            {selectedAssessment.ready_for_review ? '可进入人工复核' : '暂不进入人工复核'}
          </span>
        </div>

        {blocked && (
          <Alert
            type="warning"
            showIcon
            className="case-bonus-alert"
            message="材料未齐，暂不建议进入奖金计算"
            description={selectedAssessment.material_gate.missing_materials.join('、') || '缺少奖金考核关键佐证材料。'}
          />
        )}

        <section className="case-bonus-section">
          <div className="case-bonus-section-head">材料门禁</div>
          <div className="case-bonus-material-grid">
            {selectedAssessment.material_checks.map(item => (
              <div key={item.requirement_key} className={`case-bonus-material case-bonus-material--${item.status}`}>
                <b>{item.label}</b>
                <span>{materialStatusLabel[item.status] || item.status}</span>
                <small>{item.note || item.trigger_reason || '按奖金考核材料清单核验。'}</small>
              </div>
            ))}
          </div>
        </section>

        <section className="case-bonus-section">
          <div className="case-bonus-section-head">奖金细则测算</div>
          <div className="case-bonus-items">
            {activeItems.length === 0 ? (
              <Empty description="暂无可测算条目" />
            ) : activeItems.map(item => (
              <div key={item.key} className={`case-bonus-item case-bonus-item--${item.status}`}>
                <div>
                  <b>{item.label}</b>
                  <span>{item.formula}</span>
                  {item.blocked_by.length > 0 && <small>阻断材料：{item.blocked_by.join('、')}</small>}
                </div>
                <strong>{item.status === 'calculated' ? formatMoney(item.suggested_amount) : bonusStatusLabel[item.status]}</strong>
              </div>
            ))}
          </div>
        </section>

        {selectedAssessment.distribution && selectedAssessment.distribution.length > 0 && (
          <section className="case-bonus-section">
            <div className="case-bonus-section-head">分配建议</div>
            <div className="case-bonus-distribution">
              {selectedAssessment.distribution.map(item => (
                <div key={item.squad}>
                  <span>{item.squad}</span>
                  <b>{item.count} 人</b>
                  <strong>{formatMoney(item.amount)}</strong>
                </div>
              ))}
            </div>
          </section>
        )}

        {selectedAssessment.warnings && selectedAssessment.warnings.length > 0 && (
          <Alert
            type="info"
            showIcon
            className="case-bonus-alert"
            message="复核提示"
            description={selectedAssessment.warnings.join('；')}
          />
        )}

        <div className="case-bonus-boundary">
          <WarningOutlined /> {selectedAssessment.boundary}
        </div>
      </>
    )
  }

  return (
    <div className="page case-bonus-page">
      <header className="card case-bonus-hero">
        <div>
          <span className="case-bonus-private"><DatabaseOutlined /> 案件内业</span>
          <h1>案件奖金核算</h1>
          <p>按案件材料齐全情况和奖金考核细则做测算，结果保留人工复核边界。</p>
        </div>
        <div className="case-bonus-hero-actions">
          <Button onClick={() => navigate('/cases')}>返回案件列表</Button>
          <Button type="primary" icon={<CalculatorOutlined />} onClick={handleCalculate} loading={calculateMutation.isPending} disabled={!selectedId}>
            重新测算
          </Button>
        </div>
      </header>

      <section className="case-bonus-kpis">
        <div className="card case-bonus-kpi">
          <span>纳入核算</span>
          <b>{summary.total}</b>
          <small>当前案件列表</small>
        </div>
        <div className="card case-bonus-kpi case-bonus-kpi--good">
          <span>材料齐全</span>
          <b>{summary.ready}</b>
          <small>可进入测算</small>
        </div>
        <div className="card case-bonus-kpi case-bonus-kpi--warn">
          <span>材料阻断</span>
          <b>{summary.blocked}</b>
          <small>需补佐证</small>
        </div>
        <div className="card case-bonus-kpi">
          <span>已加载测算</span>
          <b>{summary.assessed}</b>
          <small>仅统计已打开案件</small>
        </div>
        <div className="card case-bonus-kpi">
          <span>已加载复核</span>
          <b>{summary.readyForReview}</b>
          <small>{formatMoney(summary.suggestedAmount)}</small>
        </div>
      </section>

      <section className="case-bonus-workspace">
        <aside className="card case-bonus-list">
          <div className="case-bonus-list-tools">
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索案件编号、地点、单位"
              value={keyword}
              onChange={event => setKeyword(event.target.value)}
            />
            <Select
              value={gateFilter}
              onChange={setGateFilter}
              options={[
                { value: 'all', label: '全部状态' },
                { value: 'ready', label: '材料齐全' },
                { value: 'blocked_by_materials', label: '材料未齐' },
                { value: 'rules_not_configured', label: '细则待配置' },
              ]}
            />
          </div>
          <div className="case-bonus-list-head">
            <span>案件</span>
            <span>{filteredRows.length} 起</span>
          </div>
          <div className="case-bonus-rows">
            {casesLoading ? <Spin /> : filteredRows.length > 0 ? filteredRows.map(renderRow) : <Empty description="暂无匹配案件" />}
          </div>
        </aside>

        <main className="card case-bonus-detail">
          {renderAssessment()}
        </main>
      </section>
    </div>
  )
}

export default CaseBonusAccounting
