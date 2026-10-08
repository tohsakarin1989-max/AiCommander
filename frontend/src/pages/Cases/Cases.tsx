import { useCallback, useEffect, useState, useMemo, useRef } from 'react'
import {
  Button,
  Modal,
  Form,
  Input,
  DatePicker,
  InputNumber,
  message as messageFactory,
  Popconfirm,
  Upload,
  Alert,
  Select,
  Row,
  Col,
  Switch,
  Pagination,
} from 'antd'
import {
  EditOutlined,
  DeleteOutlined,
  ApiOutlined,
  EnvironmentOutlined,
  NodeIndexOutlined,
  DatabaseOutlined,
  SafetyCertificateOutlined,
  DownOutlined,
  UpOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { agentRunApi } from '../../services/agentRuns'
import { caseApi, type CaseImportOptions, type CaseImportResult } from '../../services/cases'
import CaseImportCorrections from './CaseImportCorrections'
import CaseImportConfiguration from './CaseImportConfiguration'
import CaseHistoryReferences from './CaseHistoryReferences'
import CaseSemanticProfile from './CaseSemanticProfile'
import { CaseEntryPrecheck } from './CaseEntryPrecheck'
import { CaseSourceCollections, CaseTimeFields, oilUnitOptions } from './CaseSourceFields'
import CaseSourceDetails from './CaseSourceDetails'
import CaseEntityDetails from './CaseEntityDetails'
import CaseEvidenceFiles from './CaseEvidenceFiles'
import { caseLocationDraft } from './caseLocationDraft'
import RecordIntake from './RecordIntake'
import { CaseDossierNavigation, CaseDossierPanel, CaseQualityStatus, caseDossierView } from './CaseDossier'
import { formatCaseTime, formatOilVolume, formCaseTime } from '../../utils/caseValues'
import CaseResultPanel from '../../components/CaseResult/CaseResultPanel'
import CaseResultMap from '../../components/CaseResult/CaseResultMap'
import { useCaseWorkspace, useCaseWorkspaceSection } from '../../services/useCaseWorkspace'
import { caseContextPath, parseCaseContextParams, writeCaseFilterParams } from '../../services/caseContext'
import type { ImportCorrectionResult } from '../../services/caseImports'
import { caseStewardApi } from '../../services/caseSteward'
import type { BatchReviewResult, BonusAssessment, Case, CaseCreate, CasePerson, CaseQualityPreview, CaseUpdatePayload, CaseVehicle } from '../../types'
import type { ChainLink } from '../../types'
import { chainPresentation } from './chainPresentation'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import MapPicker from '../../components/Map/MapPicker'
import { authApi } from '../../services/auth'
import { chainPositionMeta, getChainPosition } from '../../utils/chainType'
import { canAccessAgentLab } from '../../config/features'
import { useRuntimeFeatures } from '../../config/useRuntimeFeatures'
import { buildCaseEntrySubmitPayload } from './caseEntrySubmitPayload'
import { caseSaveFailure, prepareCaseSubmission, resolveCaseSubmission, type CaseSubmission } from './caseSubmission'
import { useCaseLeaveGuard } from './useCaseLeaveGuard'
import { summarizeBatchReview } from './batchReviewPresentation'
import { summarizeCaseQualityPreview } from './caseQualityPreview'
import { buildCaseSearchParams, parseCaseDeepLinkId, caseDetailKey, visibleCaseDetail, returnToCaseListParams } from './caseSearch'
import {
  buildCaseAiIntakeApplication,
  buildCaseAiIntakeEntryFlags,
  formatAiIntakeValue,
} from './caseAiIntake'
import './Cases.css'

const { TextArea } = Input
const { Option } = Select

// 状态映射
const statusTagClass: Record<string, string> = {
  pending:    't-p',
  processing: 't-r',
  completed:  't-d',
  resolved:   't-d',
  failed:     't-x',
}

const statusLabel: Record<string, string> = {
  pending:    '待处理',
  processing: '处理中',
  completed:  '已完成',
  resolved:   '已结案',
  failed:     '失败',
}

// 油品类型颜色
const oilTypeColor: Record<string, string> = {
  柴油:  'var(--oil)',
  汽油:  'oklch(0.74 0.13 55)',
  润滑油: 'oklch(0.74 0.13 140)',
  原油:  'oklch(0.65 0.05 250)',
}


const materialStatusLabel: Record<string, string> = {
  satisfied: '已齐',
  partial: '待附件',
  missing: '缺失',
  not_required: '未触发',
}

const bonusGateLabel: Record<string, string> = {
  ready: '可复核',
  blocked_by_materials: '材料未齐',
  rules_not_configured: '待配置细则',
}

const aiIntakeModeText: Record<string, string> = {
  llm_success: 'LLM 识别',
  llm_failed: '规则降级',
  deterministic_fallback: '规则降级',
}

const sourceTypeOptions = ['巡逻发现', '群众举报', '领导指派', '公安机关线索', '技防预警', '红色网格上报', '作业区反馈', '其他']
const oilNatureOptions = ['被盗原油', '落地原油', '收缴油品', '回收原油', '其他']
const stageOptions = [
  { value: 'reported', label: '已报送' },
  { value: 'filed', label: '已立案' },
  { value: 'investigating', label: '调查中' },
  { value: 'transferred', label: '已移交' },
  { value: 'closed', label: '已办结' },
  { value: 'archived', label: '已归档' },
]

function vehicleDraftFromRecord(vehicle: CaseVehicle): Record<string, unknown> {
  return {
    id: vehicle.id,
    vehicle_type: vehicle.vehicle_type,
    road_vehicle_kind: vehicle.road_vehicle_kind,
    height_m: vehicle.height_m,
    gross_weight_t: vehicle.gross_weight_t,
    plate_number: vehicle.plate_number,
    handling_status: vehicle.handling_status,
    oil_volume: vehicle.oil_volume,
    oil_volume_unit: vehicle.oil_volume_unit || 'unknown',
  }
}

function personDraftFromRecord(person: CasePerson): Record<string, unknown> {
  return {
    id: person.id,
    name: person.name,
    handling_status: person.handling_status,
    role: person.role,
  }
}

// 默认案件筛选状态（复选框）
interface FilterState {
  statuses: string[]
  caseTypes: string[]
  oilTypes: string[]
  startDate: string
  endDate: string
}

const defaultFilterState: FilterState = {
  statuses: ['pending', 'processing', 'completed', 'resolved', 'failed'],
  caseTypes: [],
  oilTypes: [],
  startDate: '',
  endDate: '',
}


const Cases: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const caseContext = parseCaseContextParams(searchParams)
  const dossierView = caseDossierView(searchParams.get('case_view'))
  const [form] = Form.useForm()
  const [evidenceForm] = Form.useForm()
  const [modal, modalContextHolder] = Modal.useModal()
  const [message, messageContextHolder] = messageFactory.useMessage()
  const [isModalVisible, setIsModalVisible] = useState(false)
  const [editingCase, setEditingCase] = useState<Case | null>(null)
  const [entryDirty, setEntryDirty] = useState(false)
  const [submission, setSubmission] = useState<CaseSubmission | null>(null)
  const submissionRef = useRef<CaseSubmission | null>(null)
  const [saveFailure, setSaveFailure] = useState('')
  const [saveConflict, setSaveConflict] = useState(false)
  const [savePreparing, setSavePreparing] = useState(false)
  const saveBusy = useRef(false)
  const [savedCaseId, setSavedCaseId] = useState<number | null>(null)
  useCaseLeaveGuard(entryDirty || Boolean(submission))
  const [importModalVisible, setImportModalVisible] = useState(false)
  const [selectedImportFile, setSelectedImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<CaseImportResult | null>(null)
  const [importOperationalAreaId, setImportOperationalAreaId] = useState<number | undefined>()
  const [importWorksheet, setImportWorksheet] = useState('')
  const [importHeaderRow, setImportHeaderRow] = useState(1)
  const [importTimeZone, setImportTimeZone] = useState<'UTC' | 'Asia/Shanghai'>('Asia/Shanghai')
  const [importFieldMapping, setImportFieldMapping] = useState<Record<string, string | null>>({})
  const [importCorrectionBusy, setImportCorrectionBusy] = useState(false)
  const applyImportConfiguration = useCallback((settings: CaseImportOptions) => {
    setImportWorksheet(settings.worksheet ?? '')
    setImportHeaderRow(settings.header_row ?? 1)
    setImportTimeZone(settings.time_zone ?? 'UTC')
    setImportFieldMapping(settings.field_mapping ?? {})
    setImportPreview(null)
  }, [])
  const applyImportReceipt = useCallback((result: ImportCorrectionResult) => {
    setImportPreview(previous => previous?.batch_id === result.batch_id
      ? { ...previous, created: result.batch_created_total, valid: Math.max(previous.valid ?? 0, result.batch_created_total), errors: result.errors, replayed: false }
      : previous)
  }, [])
  const [bonusDraftLoadState, setBonusDraftLoadState] = useState({ vehicles: true, persons: true })
  const [bonusDraftTouched, setBonusDraftTouched] = useState({ vehicles: false, persons: false })
  const [sourceCollectionsLoaded, setSourceCollectionsLoaded] = useState({ locations: true, measurements: true })
  const [hadIncidentLocations, setHadIncidentLocations] = useState(false)
  const [evidenceModalVisible, setEvidenceModalVisible] = useState(false)
  const [locationModalVisible, setLocationModalVisible] = useState(false)
  const [activeLocationCaseId, setActiveLocationCaseId] = useState<number | null>(null)
  const [locationDraft, setLocationDraft] = useState<{ latitude?: number; longitude?: number }>({})
  const [showAdvancedFields, setShowAdvancedFields] = useState(false)
  const [showMapPicker, setShowMapPicker] = useState(false)
  const [aiIntakeText, setAiIntakeText] = useState('')
  const [aiIntakeSourceText, setAiIntakeSourceText] = useState('')
  const filters = caseContext.filters
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [keyword, setKeyword] = useState(() => filters.keyword ?? '')
  const [sidebarFilter, setSidebarFilter] = useState<FilterState>(() => ({
    ...defaultFilterState, statuses: filters.statuses ?? [], caseTypes: filters.case_types ?? [], oilTypes: filters.oil_types ?? [],
    startDate: filters.start_date ? dayjs(filters.start_date).format('YYYY-MM-DD') : '',
    endDate: filters.end_date ? dayjs(filters.end_date).subtract(1, 'millisecond').format('YYYY-MM-DD') : '',
  }))
  const filterToken = writeCaseFilterParams(new URLSearchParams(), filters).toString()
  useEffect(() => {
    const current = parseCaseContextParams(new URLSearchParams(filterToken)).filters
    setKeyword(current.keyword ?? '')
    const day = (value: string | undefined, end = false) => value && Number.isFinite(Date.parse(value))
      ? new Date(Date.parse(value) + 8 * 3600000 - (end ? 1 : 0)).toISOString().slice(0, 10) : ''
    setSidebarFilter({ ...defaultFilterState, statuses: current.statuses ?? [], caseTypes: current.case_types ?? [],
      oilTypes: current.oil_types ?? [], startDate: day(current.start_date), endDate: day(current.end_date, true) })
    setPage(1)
  }, [filterToken])
  const queryClient = useQueryClient()
  const { user, sessionEpoch } = useAuth()
  const { bonusAccountingEnabled, agentLabEnabled } = useRuntimeFeatures()
  const navigate = useNavigate()
  const editRequestRef = useRef(0)
  const entryMounted = useRef(true)
  useEffect(() => {
    entryMounted.current = true
    return () => { entryMounted.current = false; editRequestRef.current += 1 }
  }, [])
  const [batchReviewResult, setBatchReviewResult] = useState<BatchReviewResult | null>(null)
  const areaScopesQuery = useQuery({
    queryKey: ['my-area-scopes'],
    queryFn: authApi.myAreaScopes,
    staleTime: 5 * 60_000,
  })
  const defaultOperationalAreaId = (
    areaScopesQuery.data?.find(scope => scope.is_default)
    ?? areaScopesQuery.data?.[0]
  )?.operational_area_id
  const writableAreaScopes = useMemo(
    () => (areaScopesQuery.data ?? []).filter(
      scope => scope.access_level === 'write' || scope.access_level === 'manage',
    ),
    [areaScopesQuery.data],
  )
  const defaultWritableOperationalAreaId = (
    writableAreaScopes.find(scope => scope.is_default)
    ?? writableAreaScopes[0]
  )?.operational_area_id

  useEffect(() => {
    if (
      isModalVisible
      && !editingCase
      && defaultWritableOperationalAreaId != null
      && form.getFieldValue('operational_area_id') == null
    ) {
      form.setFieldValue('operational_area_id', defaultWritableOperationalAreaId)
    }
  }, [defaultWritableOperationalAreaId, editingCase, form, isModalVisible])

  useEffect(() => {
    if (importOperationalAreaId == null && defaultWritableOperationalAreaId != null) {
      setImportOperationalAreaId(defaultWritableOperationalAreaId)
    }
  }, [defaultWritableOperationalAreaId, importOperationalAreaId])

  const casesQuery = useQuery({
    queryKey: ['cases', 'page', user?.id, sessionEpoch, filters, page, pageSize],
    queryFn: ({ signal }) => caseApi.getCasePage({ ...filters, page, page_size: pageSize }, signal),
    enabled: !caseContext.error,
  })
  const { data: casePage, isLoading, isError: caseSearchError } = casesQuery
  const filteredCases = caseSearchError ? [] : casePage?.items ?? []
  const totalCases = casePage?.total ?? 0

  useEffect(() => {
    if (casePage && page > 1 && casePage.items.length === 0) {
      setPage(Math.max(1, Math.ceil(casePage.total / pageSize)))
    }
  }, [casePage, page, pageSize])

  const { data: caseStewardStatus } = useQuery({
    queryKey: ['agent-case-steward-status'],
    queryFn: caseStewardApi.status,
    enabled: canAccessAgentLab(user?.role, agentLabEnabled),
    retry: false,
  })

  const renderQualityBadge = (caseItem: Case) => {
    if (!caseItem.quality_issues?.validation) {
      return <span style={{ color: 'var(--ink-3)' }}>—</span>
    }
    return (
      <span
        className="tag"
        style={{ '--tag-c': caseItem.quality_issues.validation.can_save ? 'var(--ok)' : 'var(--warn)' } as React.CSSProperties}
        title="仅表示字段格式，不代表案件完成度"
      >
        {caseItem.quality_issues.validation.can_save ? '格式有效' : '格式待修正'}
      </span>
    )
  }

  const caseTypes = Object.keys(casePage?.facets.case_types ?? {})
  const oilTypes = Object.keys(casePage?.facets.oil_types ?? {})

  const batchReviewSummary = useMemo(
    () => batchReviewResult ? summarizeBatchReview(batchReviewResult) : null,
    [batchReviewResult],
  )

  const linkedCaseId = parseCaseDeepLinkId(searchParams.get('caseId'))
  const linkedCaseQuery = useQuery({
    queryKey: caseDetailKey(user?.id, sessionEpoch, linkedCaseId),
    queryFn: ({ signal }) => caseApi.getCase(linkedCaseId!, signal),
    enabled: linkedCaseId != null,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const selectedCase = linkedCaseId == null ? null : visibleCaseDetail(linkedCaseQuery)

  const { data: preprocessStatus } = useQuery({
    queryKey: ['preprocess-status'],
    queryFn: () => caseApi.getPreprocessStatus(),
    enabled: user?.role === 'admin',
    refetchInterval: 5000,
  })

  const { workspace, isPending: resultLoading, error: resultError, refetch: reloadWorkspace } = useCaseWorkspace(selectedCase?.id)
  const unifiedResult = workspace?.result.data ?? undefined
  const automationWorkbench = workspace?.automation_workbench?.data ?? undefined
  const bonusAssessment = bonusAccountingEnabled ? automationWorkbench?.bonus_assessment ?? undefined : undefined
  const caseProfile = workspace?.detail_profile?.data ?? undefined
  const caseDiagram = workspace?.diagram?.data ?? undefined
  const profileQuery = { isError: !!resultError || workspace?.detail_profile?.status === 'unavailable' }
  const processingQuery = { isError: !!resultError || workspace?.processing_card?.status === 'unavailable' }
  const diagramQuery = { isError: !!resultError || workspace?.diagram?.status === 'unavailable' }
  const automationQuery = { isError: !!resultError || workspace?.automation_workbench?.status === 'unavailable' }
  const { data: caseEvidence } = useCaseWorkspaceSection(
    'case-evidence', selectedCase?.id, () => caseApi.getCaseEvidence(selectedCase!.id))
  const { data: chainLinks } = useCaseWorkspaceSection(
    'case-chain-links', selectedCase?.id, () => caseApi.getChainLinks(selectedCase!.id))

  const { data: missingLocationCases, isLoading: missingLocationLoading } = useQuery({
    queryKey: ['cases-missing-location'],
    queryFn: () => caseApi.getCases({ missing_location: true, limit: 500 }),
    enabled: locationModalVisible,
  })

  useEffect(() => {
    if (!locationModalVisible || !missingLocationCases?.length || activeLocationCaseId) return
    setActiveLocationCaseId(missingLocationCases[0].id)
  }, [locationModalVisible, missingLocationCases, activeLocationCaseId])

  const qualityPreviewMutation = useMutation<CaseQualityPreview, Error, CaseCreate>({
    mutationFn: caseApi.previewCaseQuality,
  })

  const completeSave = (id: number) => {
    if (!entryMounted.current) return
    message.success('保存已确认，正在打开本案')
    submissionRef.current = null; editRequestRef.current += 1
    setSubmission(null); setEntryDirty(false); setSaveFailure(''); setSaveConflict(false)
    setIsModalVisible(false); setEditingCase(null); form.resetFields(); setSavedCaseId(id)
    for (const key of ['case-chain-links', 'chain-map-data', 'case-unified-result', 'cases', 'case-sources', 'case-source-revision', 'case-locations', 'case-measurements', 'case-bonus-assessment', 'case-automation-workbench', 'case-profile', 'case-processing-card', 'case-diagram', 'case-pipeline-status', 'case-analysis-profile', 'case-automatic-insights']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
  // Navigate after the saved render has disabled the leave guard.
  useEffect(() => {
    if (savedCaseId === null) return
    setSearchParams(previous => { const next = new URLSearchParams(previous); next.set('caseId', String(savedCaseId)); next.set('case_view', 'overview'); next.delete('create'); return next })
    setSavedCaseId(null)
  }, [savedCaseId, setSearchParams])
  const saveMutation = useMutation({
    mutationFn: async ({ attempt, retry = false, checkOnly = false }: { attempt: CaseSubmission; retry?: boolean; checkOnly?: boolean }) => {
      if (retry || checkOnly) return resolveCaseSubmission(attempt, caseApi, retry)
      return attempt.caseId !== undefined
        ? (await caseApi.updateCase(attempt.caseId, attempt.payload as CaseUpdatePayload)).id
        : (await caseApi.createCase(attempt.payload as CaseCreate, attempt.key)).id
    },
    onSuccess: id => {
      if (!entryMounted.current) return
      if (id !== null) completeSave(id)
      else setSaveFailure('暂未查到可确认的保存结果（也可能是权限发生变化）。原输入和凭证仍保留，不能据此认定未保存；可使用原请求安全重试或联系管理员核对。')
    },
    onError: (error, variables) => {
      if (!entryMounted.current) return
      const failure = caseSaveFailure(error)
      setSaveFailure(failure.state === 'rejected' && (variables.retry || variables.checkOnly)
        ? `${failure.message} 但原提交结果仍未确认，原凭证与输入继续锁定；请联系管理员核对，不能另建。` : failure.message)
      // A receipt lookup failure says nothing about the original write.
      if (failure.state === 'rejected' && !variables.checkOnly && !variables.retry) {
        submissionRef.current = null; setSubmission(null)
      }
      setSaveConflict(previous => previous || failure.state === 'conflict')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: caseApi.deleteCase,
    onSuccess: (_data, deletedId) => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['case-chain-links'] })
      queryClient.invalidateQueries({ queryKey: ['chain-map-data'] })
      if (linkedCaseId === deletedId) {
        setSearchParams(previous => { const next = new URLSearchParams(previous); next.delete('caseId'); return next }, { replace: true })
      }
      queryClient.removeQueries({ queryKey: caseDetailKey(user?.id, sessionEpoch, deletedId), exact: true })
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  const preprocessMutation = useMutation({
    mutationFn: caseApi.preprocessCase,
    onSuccess: (data) => {
      message.success(data.message || '预处理任务已提交')
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['case-profile'] })
      queryClient.invalidateQueries({ queryKey: ['case-processing-card'] })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`预处理失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const batchReviewMutation = useMutation({
    mutationFn: caseApi.batchReviewCases,
    onSuccess: async (result) => {
      const summary = summarizeBatchReview(result)
      setBatchReviewResult(result)
      message.open({
        type: summary.severity,
        content: `${summary.message}；${summary.description}`,
      })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
      await queryClient.invalidateQueries({ queryKey: ['preprocess-status'] })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`批量复核失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const caseStewardMutation = useMutation({
    mutationFn: (caseIds: number[]) => agentRunApi.create({
      task_type: 'case_data_quality',
      query: '对当前筛选范围内的案件执行只读质量复核，输出缺项、异常、疑似重复和证据索引',
      case_ids: caseIds,
      asset_ids: [],
    }),
    onSuccess: run => {
      message.success(`案件数据管家任务 ${run.id.slice(0, 8)} 已进入独立队列`)
      navigate(`/agent-lab?runId=${encodeURIComponent(run.id)}`)
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`案件数据管家启动失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const structureMutation = useMutation({
    mutationFn: ({ text }: { text: string; requestId: number }) => caseApi.structureCaseText(text),
    onSuccess: (data, { text: sourceText, requestId }) => {
      if (requestId !== editRequestRef.current || submissionRef.current || saveBusy.current) return
      const application = buildCaseAiIntakeApplication(data, sourceText)
      const patch = {
        ...application.patch,
        ...buildCaseAiIntakeEntryFlags(data, application.patch),
      } as Record<string, unknown>
      ;(['occurred_time', 'occurred_from', 'occurred_to', 'discovered_at', 'report_time'] as const).forEach(field => {
        if (typeof patch[field] === 'string') {
          patch[field] = formCaseTime(patch[field] as string, String(patch.time_timezone || form.getFieldValue('time_timezone') || 'Asia/Shanghai'))
        }
      })
      form.setFieldsValue(patch)
      setEntryDirty(true)
      setAiIntakeSourceText(sourceText)
      if (application.shouldOpenAdvancedFields) {
        setShowAdvancedFields(true)
      }
      if (patch.latitude != null || patch.longitude != null) {
        setShowMapPicker(true)
      }
      message.success(`AI 录入辅助员已写入 ${Object.keys(application.patch).length} 个可编辑字段`)
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`自动提取失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const aiIntakeApplication = useMemo(
    () => structureMutation.data
      ? buildCaseAiIntakeApplication(structureMutation.data, aiIntakeSourceText || aiIntakeText)
      : null,
    [aiIntakeSourceText, aiIntakeText, structureMutation.data],
  )

  const createEvidenceMutation = useMutation({
    mutationFn: (data: { title?: string; file_path?: string; notes?: string }) =>
      caseApi.createCaseEvidence(selectedCase!.id, data),
    onSuccess: async () => {
      message.success('材料已归档')
      queryClient.invalidateQueries({ queryKey: ['case-chain-links'] })
      queryClient.invalidateQueries({ queryKey: ['chain-map-data'] })
      queryClient.invalidateQueries({ queryKey: ['case-unified-result', selectedCase?.id] })
      setEvidenceModalVisible(false)
      evidenceForm.resetFields()
      await queryClient.invalidateQueries({ queryKey: ['case-evidence', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-bonus-assessment', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-automation-workbench', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-profile', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-processing-card', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-diagram', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-pipeline-status', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-analysis-profile', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-automatic-insights', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`材料归档失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const updateLocationMutation = useMutation({
    mutationFn: (data: { id: number; latitude: number; longitude: number }) =>
      caseApi.updateCaseLocation(data.id, { latitude: data.latitude, longitude: data.longitude }),
    onSuccess: async (_, variables) => {
      message.success('坐标已补录')
      queryClient.invalidateQueries({ queryKey: ['case-unified-result', variables.id] })
      const remaining = (missingLocationCases || []).filter(item => item.id !== variables.id)
      const nextCase = remaining[0]
      setActiveLocationCaseId(nextCase?.id ?? null)
      setLocationDraft({})
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
      await queryClient.invalidateQueries({ queryKey: ['cases-missing-location'] })
      await queryClient.invalidateQueries({ queryKey: ['chain-map-data'] })
      await queryClient.invalidateQueries({ queryKey: ['case-chain-links'] })
      await queryClient.invalidateQueries({ queryKey: ['case-pipeline-status', variables.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-analysis-profile', variables.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-automatic-insights', variables.id] })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`坐标保存失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const confirmChainMutation = useMutation({
    mutationFn: (linkId: number) => caseApi.confirmChainLink(linkId),
    onSuccess: async () => {
      message.success('链条关联已确认')
      await queryClient.invalidateQueries({ queryKey: ['case-chain-links', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['chain-map-data'] })
    },
  })

  const rejectChainMutation = useMutation({
    mutationFn: (linkId: number) => caseApi.rejectChainLink(linkId),
    onSuccess: async () => {
      message.success('链条推断已驳回')
      await queryClient.invalidateQueries({ queryKey: ['case-chain-links', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['chain-map-data'] })
    },
  })

  const previewImportMutation = useMutation({
    mutationFn: ({ file, operationalAreaId }: { file: File; operationalAreaId?: number }) => (
      caseApi.previewImportCases(file, operationalAreaId, { worksheet: importWorksheet, header_row: importHeaderRow, time_zone: importTimeZone, field_mapping: importFieldMapping })
    ),
    onSuccess: (data) => {
      setImportPreview(data)
      if (data.errors?.length) {
        message.warning(`预览完成：有效 ${data.valid ?? 0} 条，发现 ${data.errors.length} 条错误`)
      } else {
        message.success(`预览完成：可导入 ${data.valid ?? data.total} 条`)
      }
    },
    onError: (error: Error) => {
      setImportPreview(null)
      message.error(`预览失败：${error.message}`)
    },
  })

  const importMutation = useMutation({
    mutationFn: ({ file, operationalAreaId }: { file: File; operationalAreaId?: number }) => (
      caseApi.importCases(file, false, operationalAreaId, { worksheet: importWorksheet, header_row: importHeaderRow, time_zone: importTimeZone, field_mapping: importFieldMapping })
    ),
    onSuccess: async (data) => {
      if (data.replayed) {
        message.info('这份文件已处理，已恢复原批次回执，没有重复建案')
      } else if (data.errors && data.errors.length) {
        message.warning(`导入结束：成功 ${data.created} 条，失败 ${data.errors.length} 条，请查看下方行级原因`)
      } else {
        message.success(`导入成功：共 ${data.created} 条`)
      }
      setSelectedImportFile(null)
      setImportPreview(data)
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: Error) => {
      message.error(`导入失败：${error.message}`)
    },
  })

  const resetImportState = () => {
    if (importCorrectionBusy) return
    setImportModalVisible(false)
    setSelectedImportFile(null)
    setImportPreview(null)
    setImportWorksheet('')
    setImportHeaderRow(1)
    setImportTimeZone('Asia/Shanghai')
    setImportFieldMapping({})
    setImportOperationalAreaId(defaultWritableOperationalAreaId)
    previewImportMutation.reset()
    importMutation.reset()
  }

  const handleCreate = () => {
    if (submissionRef.current) { setIsModalVisible(true); return }
    editRequestRef.current += 1
    setEntryDirty(false); setSaveFailure(''); setSaveConflict(false)
    setEditingCase(null)
    form.resetFields()
    qualityPreviewMutation.reset()
    form.setFieldsValue({
      operational_area_id: defaultWritableOperationalAreaId,
      time_precision: 'unknown',
      time_timezone: 'Asia/Shanghai',
      oil_volume_unit: 'unknown',
      initial_locations: [],
      initial_measurements: [],
      bonus_has_vehicle: false,
      bonus_has_person: false,
      bonus_has_oil: false,
      bonus_has_police: false,
      initial_vehicles: [],
      initial_persons: [],
    })
    setBonusDraftLoadState({ vehicles: true, persons: true })
    setSourceCollectionsLoaded({ locations: true, measurements: true })
    setHadIncidentLocations(false)
    setBonusDraftTouched({ vehicles: false, persons: false })
    setShowAdvancedFields(false)
    setShowMapPicker(false)
    setAiIntakeText('')
    setAiIntakeSourceText('')
    structureMutation.reset()
    setIsModalVisible(true)
  }

  useEffect(() => {
    if (searchParams.get('create') !== '1' || areaScopesQuery.isPending) return
    setSearchParams(previous => { const next = new URLSearchParams(previous); next.delete('create'); return next }, { replace: true })
    if (user?.role === 'admin' || user?.role === 'analyst') handleCreate()
  }, [searchParams, areaScopesQuery.isPending])

  const handleEdit = async (caseItem: Case) => {
    if (submissionRef.current) { setIsModalVisible(true); message.warning('请先核对上一笔提交，不能覆盖未确认的输入。'); return }
    setEntryDirty(false); setSaveFailure(''); setSaveConflict(false)
    const requestId = editRequestRef.current + 1
    editRequestRef.current = requestId
    setEditingCase(caseItem)
    qualityPreviewMutation.reset()
    form.resetFields()
    let vehicles: CaseVehicle[] = []
    let persons: CasePerson[] = []
    const [vehicleResult, personResult, locationResult, measurementResult] = await Promise.allSettled([
      caseApi.getCaseVehicles(caseItem.id),
      caseApi.getCasePersons(caseItem.id),
      caseApi.getCaseLocations(caseItem.id),
      caseApi.getCaseMeasurements(caseItem.id),
    ])
    if (editRequestRef.current !== requestId) return
    const vehiclesLoaded = vehicleResult.status === 'fulfilled'
    const personsLoaded = personResult.status === 'fulfilled'
    if (vehiclesLoaded) {
      vehicles = vehicleResult.value
    } else {
      message.warning('涉案车辆台账加载失败，本次保存不会覆盖车辆台账')
    }
    if (personsLoaded) {
      persons = personResult.value
    } else {
      message.warning('涉案人员台账加载失败，本次保存不会覆盖人员台账')
    }
    setBonusDraftLoadState({ vehicles: vehiclesLoaded, persons: personsLoaded })
    setSourceCollectionsLoaded({ locations: locationResult.status === 'fulfilled', measurements: measurementResult.status === 'fulfilled' })
    setHadIncidentLocations(locationResult.status === 'fulfilled' && locationResult.value.some(item => item.role === 'incident'))
    setBonusDraftTouched({ vehicles: false, persons: false })
    setAiIntakeText(caseItem.description || '')
    setAiIntakeSourceText('')
    structureMutation.reset()
    const vehicleDrafts = vehicles.map(vehicleDraftFromRecord)
    const personDrafts = persons.map(personDraftFromRecord)
    const hasVehicleBonus = vehicleDrafts.length > 0 || Boolean(caseItem.vehicle_handling)
    const hasPersonBonus = personDrafts.length > 0 || Boolean(caseItem.person_handling)
    const hasOilBonus = Boolean(caseItem.oil_volume != null || caseItem.water_cut != null || caseItem.oil_handling || caseItem.oil_nature)
    const hasPoliceBonus = Boolean(caseItem.police_reported || caseItem.case_filed || caseItem.police_officer || caseItem.police_phone)
    form.setFieldsValue({
      ...caseItem,
      occurred_time: formCaseTime(caseItem.occurred_time, caseItem.time_timezone || 'Asia/Shanghai'),
      occurred_from: formCaseTime(caseItem.occurred_from, caseItem.time_timezone || 'Asia/Shanghai'),
      occurred_to: formCaseTime(caseItem.occurred_to, caseItem.time_timezone || 'Asia/Shanghai'),
      time_precision: caseItem.time_precision || (caseItem.occurred_time ? 'exact' : 'unknown'),
      time_timezone: caseItem.time_timezone || 'Asia/Shanghai',
      discovered_at: formCaseTime(caseItem.discovered_at, caseItem.time_timezone || 'Asia/Shanghai'),
      oil_volume_unit: caseItem.oil_volume_unit || 'unknown',
      initial_locations: locationResult.status === 'fulfilled' ? locationResult.value.map(caseLocationDraft) : undefined,
      initial_measurements: measurementResult.status === 'fulfilled' ? measurementResult.value.map(item => ({ ...item, measured_at: formCaseTime(item.measured_at, caseItem.time_timezone || 'Asia/Shanghai') })) : undefined,
      report_time: formCaseTime(caseItem.report_time, caseItem.time_timezone || 'Asia/Shanghai'),
      bonus_has_vehicle: hasVehicleBonus,
      bonus_has_person: hasPersonBonus,
      bonus_has_oil: hasOilBonus,
      bonus_has_police: hasPoliceBonus,
      initial_vehicles: hasVehicleBonus ? (vehicleDrafts.length ? vehicleDrafts : [{}]) : [],
      initial_persons: hasPersonBonus ? (personDrafts.length ? personDrafts : [{}]) : [],
    })
    setShowMapPicker(caseItem.latitude != null && caseItem.longitude != null)
    setIsModalVisible(true)
  }

  const handleBonusVehicleScopeChange = (checked: boolean) => {
    setEntryDirty(true)
    setBonusDraftTouched(prev => ({ ...prev, vehicles: true }))
    const rows = form.getFieldValue('initial_vehicles')
    form.setFieldsValue({
      bonus_has_vehicle: checked,
      initial_vehicles: checked ? (Array.isArray(rows) && rows.length ? rows : [{}]) : [],
    })
  }

  const handleBonusPersonScopeChange = (checked: boolean) => {
    setEntryDirty(true)
    setBonusDraftTouched(prev => ({ ...prev, persons: true }))
    const rows = form.getFieldValue('initial_persons')
    form.setFieldsValue({
      bonus_has_person: checked,
      initial_persons: checked ? (Array.isArray(rows) && rows.length ? rows : [{}]) : [],
    })
  }

  const handleSubmit = async () => {
    if (saveBusy.current || submissionRef.current || !entryMounted.current) return
    let values: Record<string, unknown>
    try {
      values = await form.validateFields()
    } catch (error) {
      setSaveFailure('请检查表单中标出的必填或格式问题，输入已保留。')
      return
    }
    // Two clicks can await field validation together; only the first may prepare a write.
    if (saveBusy.current || submissionRef.current || !entryMounted.current) return
    const payload = buildCaseEntrySubmitPayload(values, {
      mode: editingCase ? 'edit' : 'create',
      includeVehicleDrafts: !editingCase || bonusDraftLoadState.vehicles || bonusDraftTouched.vehicles,
      includePersonDrafts: !editingCase || bonusDraftLoadState.persons || bonusDraftTouched.persons,
      includeLocations: sourceCollectionsLoaded.locations,
      includeMeasurements: sourceCollectionsLoaded.measurements,
      hadIncidentLocations,
    })
    saveBusy.current = true; setSavePreparing(true); setSaveFailure('')
    let confirmed = false
    try {
      try {
        const preview = await qualityPreviewMutation.mutateAsync(payload as CaseCreate)
        if (!entryMounted.current) return
        const summary = summarizeCaseQualityPreview(preview)
        if (!summary.canSave) { setSaveFailure(summary.description); return }
        confirmed = !summary.requiresConfirmation || await modal.confirm({
          title: summary.title,
          content: <div><p>{summary.description}</p><p style={{ color: 'var(--ink-3)' }}>{preview.boundary}</p></div>,
          okText: '已核对，继续保存', cancelText: '返回补充',
        })
      } catch {
        if (!entryMounted.current) return
        confirmed = await modal.confirm({
          title: '服务端预检暂不可用', content: '核心案件保存不依赖智能体。可返回稍后重试，也可由人工确认后继续保存。',
          okText: '人工确认，继续保存', cancelText: '返回检查',
        })
      }
      if (!confirmed || !entryMounted.current) return
      const attempt = prepareCaseSubmission(payload, editingCase?.id)
      submissionRef.current = attempt; setSubmission(attempt)
      await saveMutation.mutateAsync({ attempt })
    } catch {
      // onError explains the write outcome without clearing the form.
    } finally {
      saveBusy.current = false; setSavePreparing(false)
    }
  }

  const confirmSubmission = async (retry: boolean) => {
    const attempt = submissionRef.current
    if (!attempt || saveBusy.current || (retry && saveConflict)) return
    saveBusy.current = true
    try {
      if (retry && attempt.caseId !== undefined && !await modal.confirm({
        title: '把本次原输入重新保存到同一案件？',
        content: '上一笔编辑可能已经生效。重试不会新增案件，但会重新提交本次原输入；如有其他人同时修改，请先人工核对。',
        okText: '已核对，重新保存本案', cancelText: '先不重试',
      })) return
      if (!entryMounted.current) return
      await saveMutation.mutateAsync({ attempt, retry, checkOnly: !retry })
    }
    catch { /* Preserve the original attempt; onError supplies an inline explanation. */ }
    finally { saveBusy.current = false }
  }

  const cancelEntry = async () => {
    if (saveBusy.current) return
    if (submissionRef.current) {
      if (await modal.confirm({ title: '保存结果尚未确认', content: '关闭窗口不会撤销服务器上的提交。本页会继续保留输入和原凭证，点击录入可继续核对；不要刷新页面或另建案件。', okText: '暂时收起，保留本页输入', cancelText: '继续核对' })) setIsModalVisible(false)
      return
    }
    if (entryDirty && !await modal.confirm({ title: '放弃本次未保存输入？', content: '取消后这些输入会清除；返回填写可继续保留。', okText: '放弃输入', cancelText: '返回填写' })) return
    editRequestRef.current += 1; setIsModalVisible(false); setEditingCase(null); setEntryDirty(false); setSaveFailure(''); form.resetFields()
  }

  // 侧边栏状态复选框切换
  const toggleStatus = (status: string) => {
    setSidebarFilter(prev => {
      const has = prev.statuses.includes(status)
      return {
        ...prev,
        statuses: has ? prev.statuses.filter(s => s !== status) : [...prev.statuses, status],
      }
    })
  }

  // 侧边栏油品筛选切换
  const toggleOilType = (oilType: string) => {
    setSidebarFilter(prev => {
      const has = prev.oilTypes.includes(oilType)
      return {
        ...prev,
        oilTypes: has ? prev.oilTypes.filter(t => t !== oilType) : [...prev.oilTypes, oilType],
      }
    })
  }

  // 应用侧边栏日期筛选
  const applyFilters = () => {
    if (sidebarFilter.startDate && sidebarFilter.endDate && sidebarFilter.startDate > sidebarFilter.endDate) {
      message.warning('开始日期不能晚于结束日期')
      return
    }
    setSearchParams(previous => writeCaseFilterParams(previous, {
      ...filters, ...buildCaseSearchParams({ ...sidebarFilter, keyword }),
      keyword: keyword.trim() || undefined, statuses: sidebarFilter.statuses,
      case_types: sidebarFilter.caseTypes, oil_types: sidebarFilter.oilTypes,
      start_date: buildCaseSearchParams(sidebarFilter).start_date,
      end_date: buildCaseSearchParams(sidebarFilter).end_date,
    }))
    setPage(1)
  }

  const resetFilters = () => {
    setSidebarFilter(defaultFilterState)
    setKeyword('')
    setSearchParams(previous => writeCaseFilterParams(previous, {}))
    setPage(1)
  }

  const statusCount = casePage?.facets.statuses ?? {}
  const caseTypeCount = casePage?.facets.case_types ?? {}
  const oilTypeCount = casePage?.facets.oil_types ?? {}

  // 发起圆桌分析
  const handleStartRoundtable = () => {
    if (!selectedCase) return
    navigate(`/meetings?caseId=${selectedCase.id}`)
  }


  const handleRunAiIntake = () => {
    const text = aiIntakeText || form.getFieldValue('description')
    if (!text || !String(text).trim()) {
      message.warning('请先粘贴案情文本')
      return
    }
    structureMutation.mutate({ text: String(text), requestId: editRequestRef.current })
  }

  const handleBatchReview = () => {
    if (!filteredCases.length) {
      message.warning('当前页没有可复核案件')
      return
    }
    batchReviewMutation.mutate({
      case_ids: filteredCases.map(caseItem => caseItem.id),
      limit: filteredCases.length,
      use_llm: false,
    })
  }

  const handleCaseStewardReview = () => {
    if (!caseStewardStatus?.can_start) {
      message.warning('当前账号不在案件数据管家指定试用名单内')
      return
    }
    if (!filteredCases.length) {
      message.warning('当前页没有可质检案件')
      return
    }
    const maxCases = caseStewardStatus.max_cases_per_run
    const caseIds = filteredCases.slice(0, maxCases).map(item => item.id)
    if (filteredCases.length > maxCases) {
      message.info(`本次按当前排序检查前 ${maxCases} 起案件，其余案件可调整筛选后分批执行`)
    }
    caseStewardMutation.mutate(caseIds)
  }

  const handleEvidenceSubmit = async () => {
    if (!selectedCase) return
    const values = await evidenceForm.validateFields()
    createEvidenceMutation.mutate(values)
  }

  const activeLocationCase = useMemo(() => {
    return (missingLocationCases || []).find(item => item.id === activeLocationCaseId) || null
  }, [missingLocationCases, activeLocationCaseId])

  const handleLocationSave = () => {
    if (!activeLocationCase || locationDraft.latitude == null || locationDraft.longitude == null) {
      message.warning('请先在地图上选择坐标')
      return
    }
    updateLocationMutation.mutate({
      id: activeLocationCase.id,
      latitude: locationDraft.latitude,
      longitude: locationDraft.longitude,
    })
  }

  const renderChainPositionTag = (caseItem: Case) => {
    const position = getChainPosition(caseItem)
    const meta = chainPositionMeta[position]
    return (
      <span
        className={`chain-tag chain-tag--${position}`}
        style={{ '--chain-c': meta.color } as React.CSSProperties}
      >
        {meta.label}
      </span>
    )
  }

  const renderChainLinkItem = (link: ChainLink, direction: 'upstream' | 'downstream') => {
    const related = direction === 'upstream' ? link.from_case : link.to_case
    const chainView = chainPresentation(link)
    return (
      <div key={link.id} className={`chain-link-card chain-link-card--${link.status}`}>
        <div className="chain-link-card__main">
          <b>{related?.case_number || `案件 ${direction === 'upstream' ? link.case_id_a : link.case_id_b}`}</b>
          <span>{related?.chain_label || '未知环节'} · {related?.location || '未标注地点'}</span>
          <small>
            直线距离 {link.distance_km.toFixed(1)} km · 时间差 {link.time_diff_days} 天 · 规则支持度 {Math.round(link.confidence * 100)} / 100
          </small>
          {link.reasoning && <p>{link.reasoning}</p>}
          {chainView.warning && <Alert type="warning" showIcon message={chainView.warning} />}
        </div>
        <div className="chain-link-card__side">
          <span>{chainView.statusLabel}</span>
          {link.status === 'inferred' && (
            <div>
              <Button
                size="small"
                type="primary"
                loading={confirmChainMutation.isPending}
                disabled={!chainView.canConfirm}
                onClick={() => confirmChainMutation.mutate(link.id)}
              >
                确认
              </Button>
              <Button
                size="small"
                danger
                loading={rejectChainMutation.isPending}
                onClick={() => rejectChainMutation.mutate(link.id)}
              >
                驳回
              </Button>
            </div>
          )}
        </div>
      </div>
    )
  }

  const renderChainPanel = (links?: ChainLink[]) => {
    if (!selectedCase) return null
    const upstreamLinks = (links || []).filter(item => item.case_id_b === selectedCase.id)
    const downstreamLinks = (links || []).filter(item => item.case_id_a === selectedCase.id)
    const hasLinks = upstreamLinks.length > 0 || downstreamLinks.length > 0
    const currentCount = [...upstreamLinks, ...downstreamLinks].filter(item => item.freshness === 'current').length
    const historyCount = upstreamLinks.length + downstreamLinks.length - currentCount
    return (
      <div className="chain-panel">
        <div className="chain-panel__summary">
          {renderChainPositionTag(selectedCase)}
          <span>{hasLinks ? `当前辅助关联 ${currentCount} 条 · 历史判断 ${historyCount} 条` : '暂无当前链条推断'}</span>
        </div>
        <p className="chain-panel__boundary">仅基于环节、直线距离和时间的辅助假设，不证明实际运输路径或正式串并案；历史判断不计入当前有效关联。</p>
        {upstreamLinks.length > 0 && (
          <div className="chain-panel__group">
            <b>上游关联</b>
            {upstreamLinks.map(link => renderChainLinkItem(link, 'upstream'))}
          </div>
        )}
        {downstreamLinks.length > 0 && (
          <div className="chain-panel__group">
            <b>下游关联</b>
            {downstreamLinks.map(link => renderChainLinkItem(link, 'downstream'))}
          </div>
        )}
      </div>
    )
  }

  const renderBonusAssessment = (assessment?: BonusAssessment) => {
    if (!assessment) {
      return <p className="narr">正在读取考核材料状态...</p>
    }
    const requiredChecks = assessment.material_checks.filter(item => item.required)
    const activeItems = assessment.bonus_items.filter(item => item.status !== 'not_applicable')
    const distribution = assessment.distribution || []
    const warnings = assessment.warnings || []
    return (
      <div className="bonus-panel">
        <div className="bonus-summary">
          <span className={`bonus-gate bonus-gate--${assessment.material_gate.status}`}>
            {bonusGateLabel[assessment.material_gate.status] || assessment.material_gate.status}
          </span>
          <span>
            材料 {assessment.material_gate.satisfied_count}/{assessment.material_gate.required_count}
          </span>
          <span>
            测算 ¥{assessment.total_suggested_amount.toLocaleString()}
          </span>
        </div>
        {assessment.primary_squad && (
          <div className="bonus-meta">
            <span>主控 {assessment.primary_squad}</span>
            <span>{assessment.rules_version}</span>
          </div>
        )}
        <div className="bonus-materials">
          {requiredChecks.slice(0, 5).map(item => (
            <div key={item.requirement_key} className={`bonus-row bonus-row--${item.status}`}>
              <span>{item.label}</span>
              <b>{materialStatusLabel[item.status] || item.status}</b>
            </div>
          ))}
        </div>
        <div className="bonus-items">
          {activeItems.slice(0, 4).map(item => (
            <div key={item.key} className="bonus-item">
              <span>{item.label}</span>
              <small>{item.basis}</small>
              <b>{item.status === 'calculated' ? `¥${item.suggested_amount.toLocaleString()}` : '暂不计入'}</b>
            </div>
          ))}
        </div>
        {distribution.length > 0 && (
          <div className="bonus-distribution">
            {distribution.slice(0, 4).map(item => (
              <div key={item.squad} className="bonus-item">
                <span>{item.squad}</span>
                <small>出警 {item.count} 人</small>
                <b>{item.amount === null ? '待分配' : `¥${item.amount.toLocaleString()}`}</b>
              </div>
            ))}
          </div>
        )}
        {assessment.material_gate.missing_materials.length > 0 && (
          <p className="narr" style={{ color: 'var(--warn)' }}>
            待补：{assessment.material_gate.missing_materials.slice(0, 4).join('、')}
          </p>
        )}
        {warnings.length > 0 && (
          <p className="narr" style={{ color: 'var(--warn)' }}>
            提醒：{warnings.slice(0, 2).join('；')}
          </p>
        )}
      </div>
    )
  }


  return (
    <div className={`page page-cases${selectedCase ? ' has-dossier' : ''}`}>
      {modalContextHolder}
      {messageContextHolder}
      {submission && !isModalVisible && <Alert type="warning" showIcon message="还有一笔保存结果未确认，原输入和凭证仅保留在本页。" action={<Button onClick={() => setIsModalVisible(true)}>继续核对本次提交</Button>} />}
      {/* 预处理状态提醒 */}
      {user?.role === 'admin' && preprocessStatus && (
        <Alert
          type="info"
          showIcon
          className="cases-preprocess-alert"
          message={`预处理队列：排队 ${preprocessStatus.pending}，处理中 ${
            preprocessStatus.processing
          }，平均耗时 ${
            preprocessStatus.avg_duration_seconds != null
              ? `${Math.round(preprocessStatus.avg_duration_seconds)} 秒`
              : '暂无数据'
          }`}
        />
      )}

      {batchReviewSummary && (
        <Alert
          type={batchReviewSummary.severity}
          showIcon
          closable
          className="cases-preprocess-alert"
          message={batchReviewSummary.message}
          description={batchReviewSummary.description}
          onClose={() => setBatchReviewResult(null)}
        />
      )}

      <div className="cases-layout">
        {/* ── 左侧筛选栏 ── */}
        <aside className="filters">
          {/* 案件状态 */}
          <div className="filter-group">
            <div className="gh">案件状态</div>
            {[
              { value: 'pending',    label: '待处理' },
              { value: 'processing', label: '处理中' },
              { value: 'completed',  label: '已完成' },
              { value: 'resolved',   label: '已结案' },
              { value: 'failed',     label: '失败' },
            ].map(({ value, label }) => (
              <label key={value} className="chk">
                <input
                  type="checkbox"
                  checked={sidebarFilter.statuses.includes(value)}
                  onChange={() => toggleStatus(value)}
                />
                <span>{label}</span>
                <span className="ct">{statusCount[value] || 0}</span>
              </label>
            ))}
          </div>

          {/* 案件类型 */}
          {caseTypes.length > 0 && (
            <div className="filter-group">
              <div className="gh">案件类型</div>
              {caseTypes.map(type => (
                <label key={type} className="chk">
                  <input
                    type="checkbox"
                    checked={sidebarFilter.caseTypes.includes(type)}
                    onChange={() => setSidebarFilter(prev => {
                      const has = prev.caseTypes.includes(type)
                      return {
                        ...prev,
                        caseTypes: has ? prev.caseTypes.filter(t => t !== type) : [...prev.caseTypes, type],
                      }
                    })}
                  />
                  <span>{type}</span>
                  <span className="ct">{caseTypeCount[type] || 0}</span>
                </label>
              ))}
            </div>
          )}

          {/* 油品类型 */}
          {oilTypes.length > 0 && (
            <div className="filter-group">
              <div className="gh">油品</div>
              <div className="chip-row">
                {oilTypes.map(oilType => (
                  <span
                    key={oilType}
                    className={`chip-sm${sidebarFilter.oilTypes.length === 0 || sidebarFilter.oilTypes.includes(oilType) ? ' on' : ''}`}
                    style={{ '--c': oilTypeColor[oilType] || 'var(--oil)' } as React.CSSProperties}
                    onClick={() => toggleOilType(oilType)}
                  >
                    {oilType} {oilTypeCount[oilType] || 0}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 日期范围 */}
          <div className="filter-group">
            <div className="gh">日期范围</div>
            <div className="date-range">
              <input
                type="date"
                value={sidebarFilter.startDate}
                onChange={e => setSidebarFilter(prev => ({ ...prev, startDate: e.target.value }))}
              />
              <span>→</span>
              <input
                type="date"
                value={sidebarFilter.endDate}
                onChange={e => setSidebarFilter(prev => ({ ...prev, endDate: e.target.value }))}
              />
            </div>
          </div>

          <button className="btn-primary" onClick={applyFilters}>
            应用筛选
          </button>
          <button className="btn-ghost" onClick={resetFilters}>重置</button>
          <small>分类计数为授权范围内符合关键词和日期的全部案件，不受分页影响。</small>
        </aside>

        {/* ── 右侧主内容区 ── */}
        <section className="cases-main">
          {/* 工具栏 */}
          <div className="tools-bar">
            <div className="search">
              <span className="ico">⌕</span>
              <input
                placeholder="搜索案件编号、地点、描述..."
                value={keyword}
                onChange={e => setKeyword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && applyFilters()}
              />
              <span className="kbd">⌘K</span>
            </div>
            <div className="tools-bar-right">
              {user?.role === 'admin' && caseStewardStatus?.can_start && (
                <button
                  className="btn-ghost"
                  disabled={caseStewardMutation.isPending || filteredCases.length === 0}
                  onClick={handleCaseStewardReview}
                  title="只生成质量问题和证据索引，不修改案件字段"
                >
                  <SafetyCertificateOutlined /> {caseStewardMutation.isPending ? '提交中' : '本页质检'}
                </button>
              )}
              {user?.role === 'admin' && <button
                className="btn-ghost"
                disabled={batchReviewMutation.isPending || filteredCases.length === 0}
                onClick={handleBatchReview}
              >
                <ApiOutlined /> {batchReviewMutation.isPending ? '复核中' : '本页批量复核'}
              </button>}
              <button className="btn-ghost" onClick={() => setLocationModalVisible(true)}>
                <EnvironmentOutlined /> 坐标补录
              </button>
              {bonusAccountingEnabled && (
                <button
                  className="btn-ghost"
                  onClick={() => navigate(selectedCase ? `/cases/bonus?caseId=${selectedCase.id}` : '/cases/bonus')}
                >
                  <DatabaseOutlined /> 奖金核算
                </button>
              )}
              <button className="btn-ghost" onClick={() => setImportModalVisible(true)}>导入 ▾</button>
              {user?.role !== 'viewer' && <RecordIntake onCase={handleCreate} areaId={defaultWritableOperationalAreaId} scopes={writableAreaScopes} />}
            </div>
          </div>

          {caseContext.error && <Alert type="error" showIcon message={caseContext.error} />}
          {linkedCaseQuery.isError && <Alert type="warning" showIcon message="链接中的案件不存在或当前无权访问。" />}

          {/* 案件列表 + 详情分栏 */}
          <div className="cases-split">
            {/* 案件表格 */}
            <div className="card cases-table-card">
              {caseSearchError ? (
                <Alert type="error" showIcon message="案件查询失败，不能将其视为没有案件。" action={<Button onClick={() => casesQuery.refetch()}>重试</Button>} />
              ) : isLoading ? (
                <div className="empty-state">
                  <div className="icon">⌛</div>
                  <span>加载中...</span>
                </div>
              ) : (
                <table className="data cases-table">
                  <thead>
                    <tr>
                      <th style={{ width: 140 }}>案件编号</th>
                      <th style={{ width: 130 }}>案发时间</th>
                      <th>案发地点</th>
                      <th style={{ width: 110 }}>类型</th>
                      <th style={{ width: 90 }}>油品</th>
                      <th style={{ width: 120 }}>信息质量</th>
                      <th style={{ width: 110 }}>状态</th>
                      <th style={{ width: 100 }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCases.length === 0 ? (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', color: 'var(--ink-3)', padding: '32px 0' }}>
                          暂无案件数据
                        </td>
                      </tr>
                    ) : (
                      filteredCases.map(caseItem => (
                        <tr
                          key={caseItem.id}
                          className={selectedCase?.id === caseItem.id ? 'selected' : ''}
                          onClick={() => setSearchParams(previous => {
                            const next = new URLSearchParams(previous)
                            next.set('caseId', String(caseItem.id))
                            return next
                          }, { replace: true })}
                        >
                          <td>
                            <span className="cno">{caseItem.case_number || `#${caseItem.id}`}</span>
                          </td>
                          <td className="time">
                            {formatCaseTime(caseItem, 'MM-DD HH:mm')}
                          </td>
                          <td>
                            <span style={{ fontSize: 12, color: 'var(--ink-1)' }}>
                              {caseItem.location || '—'}
                            </span>
                          </td>
                          <td>
                            {caseItem.case_type ? (
                              <span className="tag" style={{ '--tag-c': 'var(--accent)' } as React.CSSProperties}>
                                {caseItem.case_type}
                              </span>
                            ) : <span style={{ color: 'var(--ink-3)' }}>—</span>}
                          </td>
                          <td>
                            {caseItem.oil_type ? (
                              <span
                                className="tag"
                                style={{ '--tag-c': oilTypeColor[caseItem.oil_type] || 'var(--oil)' } as React.CSSProperties}
                              >
                                {caseItem.oil_type}
                              </span>
                            ) : <span style={{ color: 'var(--ink-3)' }}>—</span>}
                          </td>
                          <td>{renderQualityBadge(caseItem)}</td>
                          <td>
                            <span className={`tag ${statusTagClass[caseItem.status] || ''}`}>
                              {statusLabel[caseItem.status] || caseItem.status}
                            </span>
                          </td>
                          <td>
                            <div className="cases-row-actions" onClick={e => e.stopPropagation()}>
                              <button
                                className="cases-act-btn"
                                title="编辑"
                                onClick={() => handleEdit(caseItem)}
                              >
                                <EditOutlined />
                              </button>
                              {user?.role === 'admin' && <button
                                className="cases-act-btn"
                                title="预处理"
                                onClick={() => preprocessMutation.mutate(caseItem.id)}
                              >
                                <ApiOutlined />
                              </button>}
                              <button
                                className="cases-act-btn"
                                title="案件研判"
                                onClick={() => navigate(`/case-intelligence?caseId=${caseItem.id}`)}
                              >
                                <NodeIndexOutlined />
                              </button>
                              {caseItem.latitude != null && caseItem.longitude != null && (
                                <button
                                  className="cases-act-btn"
                                  title="地图"
                                  onClick={() => navigate(`/cases/map?caseId=${caseItem.id}`)}
                                >
                                  <EnvironmentOutlined />
                                </button>
                              )}
                              <Popconfirm
                                title="确认删除此案件？"
                                onConfirm={() => deleteMutation.mutate(caseItem.id)}
                                okText="删除"
                                cancelText="取消"
                              >
                                <button className="cases-act-btn cases-act-btn--danger" title="删除">
                                  <DeleteOutlined />
                                </button>
                              </Popconfirm>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              )}
              {!caseSearchError && !isLoading && (
                <div className="cases-pagination">
                  <Pagination
                    current={page}
                    pageSize={pageSize}
                    total={totalCases}
                    showSizeChanger
                    pageSizeOptions={[20, 50, 100, 200]}
                    showTotal={total => `共 ${total} 起 · 当前页 ${filteredCases.length} 起`}
                    onChange={(nextPage, size) => { setPage(size !== pageSize ? 1 : nextPage); setPageSize(size) }}
                  />
                </div>
              )}
            </div>

            {/* 案件详情面板 */}
            <aside className="case-detail">
              {selectedCase ? (
                <>
                  <div className="case-dossier-return">
                    <button type="button" className="btn-ghost" onClick={() => setSearchParams(returnToCaseListParams, { replace: true })}>← 返回案件列表</button>
                    <span>筛选条件与当前页保留</span>
                  </div>
                  {/* 详情头 */}
                  <div className="detail-head">
                    <div>
                      <div className="cno-big">{selectedCase.case_number || `#${selectedCase.id}`}</div>
                      <div className="cno-sub">
                        {selectedCase.location || '—'}
                        {selectedCase.case_type ? `  ·  ${selectedCase.case_type}` : ''}
                      </div>
                      <div className="chain-tag-row">
                        {renderChainPositionTag(selectedCase)}
                      </div>
                    </div>
                    <span className={`tag ${statusTagClass[selectedCase.status] || ''}`}>
                      {statusLabel[selectedCase.status] || selectedCase.status}
                    </span>
                  </div>

                  <CaseDossierNavigation />
                  <CaseDossierPanel view="relations" active={dossierView}>
                  <nav className="case-context-links detail-section" aria-label="当前案件关联视图">
                    <Link to={caseContextPath(`/case-intelligence?caseId=${selectedCase.id}`, searchParams)}>历史关联与研判</Link>
                    <Link to={caseContextPath(`/cases/map?caseId=${selectedCase.id}`, searchParams)}>案件地图</Link>
                    <Link to={caseContextPath(`/graphs/evidence?caseId=${selectedCase.id}`, searchParams)}>证据图谱</Link>
                    <Link to={caseContextPath(`/assistant?caseId=${selectedCase.id}`, searchParams)}>带条件询问助手</Link>
                    <Link to={`/topics?source=case&sourceId=${selectedCase.id}`}>持续关注资料变化</Link>
                    {unifiedResult && <Link to={caseContextPath(`/reports?resultId=${encodeURIComponent(unifiedResult.id)}`, searchParams)}>同版报告</Link>}
                  </nav>
                  {unifiedResult && <CaseResultMap result={unifiedResult} operationalAreaId={selectedCase.operational_area_id ?? undefined} />}
                  </CaseDossierPanel>
                  {(profileQuery.isError || processingQuery.isError || diagramQuery.isError || automationQuery.isError) && <Alert type="warning" showIcon
                    message="部分案件资料暂不可读，不能将其视为没有缺项。原始记录和可读成果仍可使用。" />}

                  <CaseDossierPanel view="overview" active={dossierView}>
                  <div className="detail-section">
                    <div className="ds-head">资料状态与报送</div>
                    <CaseQualityStatus quality={selectedCase.quality_issues} />
                    <div className="detail-grid">
                      <div className="kv">
                        <span className="k">录入有效性</span>
                        <span className="v">{renderQualityBadge(selectedCase)}</span>
                      </div>
                      {selectedCase.report_time && (
                        <div className="kv">
                          <span className="k">报送时间</span>
                          <span className="v">{dayjs(selectedCase.report_time).format('YYYY-MM-DD HH:mm')}</span>
                        </div>
                      )}
                      {selectedCase.report_unit && (
                        <div className="kv">
                          <span className="k">责任单位</span>
                          <span className="v">{selectedCase.report_unit}</span>
                        </div>
                      )}
                      {selectedCase.source_type && (
                        <div className="kv">
                          <span className="k">线索来源</span>
                          <span className="v">{selectedCase.source_type}</span>
                        </div>
                      )}
                      {selectedCase.current_stage && (
                        <div className="kv">
                          <span className="k">办理阶段</span>
                          <span className="v">{stageOptions.find(s => s.value === selectedCase.current_stage)?.label || selectedCase.current_stage}</span>
                        </div>
                      )}
                      <div className="kv">
                        <span className="k">报案/立案</span>
                        <span className="v">
                          {selectedCase.police_reported ? '已报案' : '未标注报案'}
                          {selectedCase.case_filed ? ' · 已立案' : ''}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="detail-section">
                    <div className="ds-head">案件画像底座</div>
                    <div className="detail-grid">
                      <div className="kv">
                        <span className="k">证据</span>
                        <span className="v">{caseProfile ? `${caseProfile.related.evidence.length} 项`
                          : caseEvidence ? `${caseEvidence.length} 项` : profileQuery.isError ? '暂不可读' : '加载中…'}</span>
                      </div>
                      <div className="kv">
                        <span className="k">车辆/人员</span>
                        <span className="v">
                          {caseProfile ? `${caseProfile.related.vehicles.length}/${caseProfile.related.persons.length}`
                            : profileQuery.isError ? '暂不可读' : '加载中…'}
                        </span>
                      </div>
                      <div className="kv">
                        <span className="k">AI 特征</span>
                        <span className="v">{caseProfile ? (caseProfile.availability.has_ai_features ? '已沉淀' : '待提取')
                          : profileQuery.isError ? '暂不可读' : '加载中…'}</span>
                      </div>
                      <div className="kv">
                        <span className="k">一案一图</span>
                        <span className="v">{caseDiagram ? `${caseDiagram.nodes.length} 节点`
                          : diagramQuery.isError ? '暂不可读' : '加载中…'}</span>
                      </div>
                    </div>
                    <p className="narr">
                      {caseProfile?.ai_summary.summary || selectedCase.description || '画像会聚合案件事实、材料、质量缺口和经验卡状态。'}
                    </p>
                  </div>

                  <p className="detail-section">发生记录：{formatCaseTime(selectedCase)}。油量记录：{formatOilVolume(selectedCase.oil_volume, selectedCase.oil_volume_unit)}。</p>
                  </CaseDossierPanel>

                  <CaseDossierPanel view="results" active={dossierView}>
                  <Button size="small" onClick={() => void reloadWorkspace()}>刷新已有成果</Button>
                  <CaseResultPanel
                    key={selectedCase.id}
                    caseId={selectedCase.id}
                    result={unifiedResult}
                    loading={resultLoading}
                    error={!!resultError}
                    errorStatus={(resultError as { status?: number } | null)?.status}
                    map={unifiedResult && <CaseResultMap result={unifiedResult} operationalAreaId={selectedCase.operational_area_id ?? undefined} />}
                    footer={unifiedResult && <Link to={caseContextPath(`/reports?resultId=${encodeURIComponent(unifiedResult.id)}`, searchParams)}>在报告中心查看此版本</Link>}
                  />
                  </CaseDossierPanel>
                  <CaseDossierPanel view="relations" active={dossierView}>
                  <CaseSemanticProfile semantics={workspace?.profile.data?.payload.semantics}
                    loading={resultLoading} error={!!resultError}
                    updating={workspace?.profile.status === 'updating'} />
                  <CaseHistoryReferences caseId={selectedCase.id} revision={selectedCase.updated_at || workspace?.profile.data?.source_hash} />
                  </CaseDossierPanel>

                  <CaseDossierPanel view="materials" active={dossierView}>
                  <Link to={`/reports?subject=case&subjectId=${selectedCase.id}`}>查看本案已有成果与材料</Link>
                  <CaseEvidenceFiles key={selectedCase.id} caseId={selectedCase.id} />
                  {bonusAccountingEnabled && (
                    <div className="detail-section">
                      <div className="ds-head">奖金考核测算</div>
                      {renderBonusAssessment(bonusAssessment)}
                    </div>
                  )}

                  {automationWorkbench && (
                    <div className="detail-section">
                      <div className="ds-head">已有成果与经验状态</div>
                      <div className="automation-456-list">
                        <div>
                          <b>结论分层</b>
                          <span>
                            事实 {automationWorkbench.conclusion_layering.facts.length}，推断 {automationWorkbench.conclusion_layering.inferences.length}，建议 {automationWorkbench.conclusion_layering.suggestions.length}
                          </span>
                        </div>
                        <div>
                          <b>经验卡</b>
                          <span>{automationWorkbench.experience_card.reusable_lessons[0] || automationWorkbench.experience_card.why_it_matters[0] || '尚无已保存经验，按需沉淀，不影响案件办理'}</span>
                        </div>
                        <div>
                          <b>缺口闭环</b>
                          <span>{automationWorkbench.gap_closure.actions[0]?.title || '暂无待补缺口'}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  </CaseDossierPanel>
                  <CaseDossierPanel view="relations" active={dossierView}>
                  <div className="detail-section">
                    <div className="ds-head">链条关联</div>
                    {renderChainPanel(chainLinks)}
                  </div>
                  </CaseDossierPanel>

                  <CaseDossierPanel view="materials" active={dossierView}>
                  <div className="detail-section">
                    <div className="ds-head ds-head--split">
                      <span>佐证材料</span>
                      <Button size="small" onClick={() => setEvidenceModalVisible(true)}>
                        登记材料
                      </Button>
                    </div>
                    {caseEvidence?.length ? (
                      <div className="evidence-list">
                        {caseEvidence.slice(0, 6).map(item => {
                          const auto = item.meta?.auto_classification as { label?: string; confidence?: number } | undefined
                          return (
                            <div key={item.id} className="evidence-mini">
                              <span>{item.title || item.file_path || `材料 ${item.id}`}</span>
                              <b>{auto?.label || item.requirement_key || item.evidence_type || '其他材料'}</b>
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="narr">暂无材料目录</p>
                    )}
                  </div>
                  </CaseDossierPanel>

                  <CaseDossierPanel view="sources" active={dossierView}>
                  <CaseSourceDetails key={selectedCase.id} caseId={selectedCase.id} revision={selectedCase.updated_at} />
                  <CaseEntityDetails profile={caseProfile} />
                  {/* 关键信息 */}
                  <div className="detail-grid">
                    <div className="kv">
                      <span className="k">案发时间</span>
                      <span className="v">{formatCaseTime(selectedCase)}</span>
                    </div>
                    {selectedCase.location && (
                      <div className="kv">
                        <span className="k">案发地点</span>
                        <span className="v">{selectedCase.location}</span>
                      </div>
                    )}
                    {selectedCase.case_type && (
                      <div className="kv">
                        <span className="k">案件类型</span>
                        <span className="v">
                          <span className="tag" style={{ '--tag-c': 'var(--accent)' } as React.CSSProperties}>
                            {selectedCase.case_type}
                          </span>
                        </span>
                      </div>
                    )}
                    {selectedCase.oil_type && (
                      <div className="kv">
                        <span className="k">油品</span>
                        <span className="v">
                          <span
                            className="tag"
                            style={{ '--tag-c': oilTypeColor[selectedCase.oil_type] || 'var(--oil)' } as React.CSSProperties}
                          >
                            {selectedCase.oil_type}
                          </span>
                        </span>
                      </div>
                    )}
                    {selectedCase.oil_nature && (
                      <div className="kv">
                        <span className="k">原油性质</span>
                        <span className="v">{selectedCase.oil_nature}</span>
                      </div>
                    )}
                    {selectedCase.oil_volume != null && (
                      <div className="kv">
                        <span className="k">涉案油量</span>
                        <span className="v" style={{ fontFamily: 'var(--mono)' }}>
                          {formatOilVolume(selectedCase.oil_volume, selectedCase.oil_volume_unit)}
                        </span>
                      </div>
                    )}
                    {selectedCase.water_cut != null && (
                      <div className="kv">
                        <span className="k">检斤含水</span>
                        <span className="v" style={{ fontFamily: 'var(--mono)' }}>
                          {selectedCase.water_cut}%
                        </span>
                      </div>
                    )}
                    {selectedCase.oil_value != null && (
                      <div className="kv">
                        <span className="k">涉案价值</span>
                        <span className="v" style={{ fontFamily: 'var(--mono)', color: 'var(--accent)' }}>
                          ¥ {(selectedCase.oil_value / 10000).toFixed(1)} 万
                        </span>
                      </div>
                    )}
                    {selectedCase.loss_amount != null && (
                      <div className="kv">
                        <span className="k">损失金额</span>
                        <span className="v" style={{ fontFamily: 'var(--mono)', color: 'var(--accent)' }}>
                          ¥ {(selectedCase.loss_amount / 10000).toFixed(2)} 万
                        </span>
                      </div>
                    )}
                    {selectedCase.facility_type && (
                      <div className="kv">
                        <span className="k">设施类型</span>
                        <span className="v">
                          {selectedCase.facility_type} {renderChainPositionTag(selectedCase)}
                        </span>
                      </div>
                    )}
                    {selectedCase.modus_operandi && (
                      <div className="kv">
                        <span className="k">作案手法</span>
                        <span className="v">{selectedCase.modus_operandi}</span>
                      </div>
                    )}
                    {selectedCase.latitude != null && selectedCase.longitude != null && (
                      <div className="kv">
                        <span className="k">坐标</span>
                        <span className="v" style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                          {selectedCase.latitude.toFixed(5)}, {selectedCase.longitude.toFixed(5)}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* 案情描述 */}
                  {selectedCase.description && (
                    <div className="detail-section">
                      <div className="ds-head">案情描述</div>
                      <p className="narr">{selectedCase.description}</p>
                    </div>
                  )}
                  </CaseDossierPanel>

                  {/* 底部操作 */}
                  <div className="detail-actions">
                    <button className="btn-primary" onClick={handleStartRoundtable}>
                      发起圆桌研判
                    </button>
                    <button className="btn-ghost" onClick={() => handleEdit(selectedCase)}>
                      编辑案件
                    </button>
                    <Popconfirm
                      title="确认删除此案件？"
                      onConfirm={() => deleteMutation.mutate(selectedCase.id)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <button className="btn-ghost cases-del-btn">删除</button>
                    </Popconfirm>
                  </div>
                </>
              ) : (
                <div className="empty-state">
                  <div className="icon">
                    <DatabaseOutlined />
                  </div>
                  <span>{bonusAccountingEnabled ? '选择案件后查看材料门禁和奖金测算' : '选择案件后查看研判、材料和缺口闭环'}</span>
                </div>
              )}
            </aside>
          </div>
        </section>
      </div>

      {/* ── 新建/编辑案件 Modal ── */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <DatabaseOutlined style={{ color: 'var(--accent)' }} />
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-0)', fontSize: 14, letterSpacing: '0.06em' }}>
              {editingCase ? '编辑案件' : '新建案件'}
            </span>
          </div>
        }
        open={isModalVisible}
        forceRender
        onOk={handleSubmit}
        onCancel={() => void cancelEntry()}
        width={760}
        confirmLoading={savePreparing || saveMutation.isPending}
        okButtonProps={{ disabled: Boolean(submission) }}
        cancelButtonProps={{ disabled: savePreparing || saveMutation.isPending }}
        closable={!savePreparing && !saveMutation.isPending}
        maskClosable={false}
        okText="保存案件"
        cancelText="取消"
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
          footer:  { borderTop: '1px solid var(--line)' },
        }}
      >
        {saveFailure && <Alert type={submission ? 'warning' : 'error'} showIcon role="alert" message={saveFailure} />}
        {submission && <div style={{ marginTop: 12 }}>
          <p>本次输入已锁定，核对前不改写提交内容。{submission.caseId === undefined ? `提交凭证：${submission.key}` : `编辑案件 #${submission.caseId}`}</p>
          {submission.caseId === undefined && <Button loading={saveMutation.isPending} onClick={() => void confirmSubmission(false)}>核对保存结果</Button>}
          <Button disabled={saveConflict || saveMutation.isPending} onClick={() => void confirmSubmission(true)}>{submission.caseId === undefined ? '使用原请求安全重试' : '将原输入重新保存到本案'}</Button>
        </div>}
        <Form form={form} layout="vertical" style={{ marginTop: 8 }} disabled={Boolean(submission) || savePreparing} onValuesChange={() => setEntryDirty(true)}>
          <div className="cases-ai-assistant">
            <div className="cases-ai-assistant__head">
              <div>
                <span><ApiOutlined /> AI 录入辅助员</span>
                <small>{structureMutation.data?.ai_intake_boundary || '先粘贴原始案情，系统只生成候选字段，提交前仍由人工确认。'}</small>
              </div>
              <b>
                {structureMutation.data
                  ? `${aiIntakeModeText[structureMutation.data.model_status || ''] || '候选识别'} · ${Math.round((structureMutation.data.confidence || 0) * 100)}%`
                  : '候选录入'}
              </b>
            </div>
            <TextArea
              rows={4}
              value={aiIntakeText}
              onChange={event => { setAiIntakeText(event.target.value); setEntryDirty(true) }}
              placeholder="粘贴原始案情：时间、地点、发现方式、涉油数量、车辆/人员处置、报案立案等。点击后自动填入下方可编辑字段。"
            />
            <div className="cases-ai-assistant__actions">
              <Button
                type="primary"
                icon={<ApiOutlined />}
                loading={structureMutation.isPending}
                onClick={handleRunAiIntake}
              >
                AI 辅助录入
              </Button>
              <Form.Item
                noStyle
                shouldUpdate={(previous, current) => previous.description !== current.description}
              >
                {({ getFieldValue }) => {
                  const description = String(getFieldValue('description') || '')
                  return (
                    <Button
                      onClick={() => setAiIntakeText(description)}
                      disabled={!description}
                    >
                      读取案情描述
                    </Button>
                  )
                }}
              </Form.Item>
              <span>结果已写入表单，可继续人工修改。</span>
            </div>

            {aiIntakeApplication && (
              <div className="cases-ai-intake">
                <div className="cases-ai-intake__head">
                  <span>已识别字段</span>
                  <b>{aiIntakeApplication.writableCandidates.length} 项可写入</b>
                </div>
                <div className="cases-ai-intake__list">
                  {aiIntakeApplication.writableCandidates.slice(0, 8).map(item => (
                    <div key={`${item.field}-${String(item.value)}`} className="cases-ai-intake__item">
                      <span>{item.label}</span>
                      <b>{formatAiIntakeValue(item.value)}</b>
                      <small>{item.source}</small>
                    </div>
                  ))}
                  {aiIntakeApplication.referenceCandidates.slice(0, 2).map(item => (
                    <div key={`${item.field}-${String(item.value)}`} className="cases-ai-intake__item cases-ai-intake__item--reference">
                      <span>{item.label}</span>
                      <b>{formatAiIntakeValue(item.value)}</b>
                      <small>仅供参考 · {item.source}</small>
                    </div>
                  ))}
                </div>
                {structureMutation.data?.material_recommendations?.length ? (
                  <div className="cases-ai-intake__chips">
                    {structureMutation.data.material_recommendations.slice(0, 4).map(item => (
                      <span key={item.requirement_key}>{item.label}</span>
                    ))}
                  </div>
                ) : null}
                {structureMutation.data?.follow_up_questions?.length ? (
                  <p className="narr" style={{ color: 'var(--warn)' }}>
                    待人工确认：{structureMutation.data.follow_up_questions.slice(0, 2).join('；')}
                  </p>
                ) : null}
              </div>
            )}
          </div>

          {writableAreaScopes.length > 1 && !editingCase ? (
            <Form.Item
              name="operational_area_id"
              label="所属厂区"
              rules={[{ required: true, message: '请选择所属厂区' }]}
            >
              <Select placeholder="请选择本案所属厂区">
                {writableAreaScopes.map(scope => (
                  <Option key={scope.operational_area_id} value={scope.operational_area_id}>
                    {scope.area_name}
                  </Option>
                ))}
              </Select>
            </Form.Item>
          ) : null}

          <CaseTimeFields form={form} />

          <Form.Item name="location" label="地点">
            <Input placeholder="如：××路××小区南门" />
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(previous, current) => (
              previous.latitude !== current.latitude
              || previous.longitude !== current.longitude
              || previous.operational_area_id !== current.operational_area_id
            )}
          >
            {({ getFieldValue, setFieldsValue }) => {
              const latitude = getFieldValue('latitude')
              const longitude = getFieldValue('longitude')
              const selectedOperationalAreaId = editingCase?.operational_area_id
                ?? getFieldValue('operational_area_id')
                ?? defaultWritableOperationalAreaId
                ?? defaultOperationalAreaId
              return (
                <>
                  <div
                    className="cases-map-toggle"
                    onClick={() => setShowMapPicker(!showMapPicker)}
                  >
                    {showMapPicker ? <UpOutlined style={{ fontSize: 12 }} /> : <DownOutlined style={{ fontSize: 12 }} />}
                    地图坐标（可选，用于地图与空间分析）
                    {latitude != null && longitude != null && (
                      <span>{Number(latitude).toFixed(5)}, {Number(longitude).toFixed(5)}</span>
                    )}
                  </div>

                  {showMapPicker && (
                    <div className="cases-map-entry">
                      <Form.Item label="经纬度" style={{ marginBottom: 0 }}>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <Form.Item name="latitude" style={{ flex: 1, marginBottom: 8 }}>
                            <InputNumber
                              style={{ width: '100%' }}
                              placeholder="纬度，例如 31.2304"
                              min={-90}
                              max={90}
                              step={0.000001}
                            />
                          </Form.Item>
                          <Form.Item name="longitude" style={{ flex: 1, marginBottom: 8 }}>
                            <InputNumber
                              style={{ width: '100%' }}
                              placeholder="经度，例如 121.4737"
                              min={-180}
                              max={180}
                              step={0.000001}
                            />
                          </Form.Item>
                        </div>
                      </Form.Item>

                      <Form.Item label="地图选点">
                        <MapPicker
                          key={selectedOperationalAreaId ?? 'default-area'}
                          lat={latitude}
                          lng={longitude}
                          operationalAreaId={selectedOperationalAreaId}
                          onChange={(lat, lng) => {
                            if (!submissionRef.current && !saveBusy.current) { setFieldsValue({ latitude: lat, longitude: lng }); setEntryDirty(true) }
                          }}
                        />
                      </Form.Item>
                    </div>
                  )}
                </>
              )
            }}
          </Form.Item>

          <Form.Item name="case_type" label="类型（可选）">
            <Input placeholder="如：管线开孔、油库入侵、罐车劫持等" />
          </Form.Item>

          <Form.Item
            name="description"
            label="案情原文（未知内容可后补）"
          >
            <TextArea rows={4} placeholder="请尽可能详细描述案情，其余结构化分析将由系统自动完成" />
          </Form.Item>

          <CaseEntryPrecheck
            form={form}
            onBonusVehicleScopeChange={handleBonusVehicleScopeChange}
            onBonusPersonScopeChange={handleBonusPersonScopeChange}
          />
          <CaseSourceCollections locationsEnabled={sourceCollectionsLoaded.locations} measurementsEnabled={sourceCollectionsLoaded.measurements} />
          {qualityPreviewMutation.data && <CaseQualityStatus quality={qualityPreviewMutation.data} />}

          <div className="cases-advanced-toggle" style={{ cursor: 'default' }}>
            业务管理字段（按需用于报送与后续研判）
          </div>

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="report_time" label="报送时间">
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="report_unit" label="报送/责任单位">
                <Input placeholder="如：××保卫班、××作业区" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="source_type" label="线索来源">
                <Select allowClear placeholder="请选择线索来源">
                  {sourceTypeOptions.map(option => (
                    <Option key={option} value={option}>{option}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="current_stage" label="办理阶段">
                <Select allowClear placeholder="请选择办理阶段">
                  {stageOptions.map(option => (
                    <Option key={option.value} value={option.value}>{option.label}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="source_detail" label="线索补充说明">
            <TextArea rows={2} placeholder="如举报内容、技防预警来源、公安线索编号等" />
          </Form.Item>

          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="police_reported" label="是否报案" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="case_filed" label="是否立案" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="operation_role" label="联合行动角色">
                <Select allowClear placeholder="主导/联合/配合/协助">
                  {['主导', '联合', '配合', '协助'].map(option => (
                    <Option key={option} value={option}>{option}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="police_officer" label="公安出警人">
                <Input placeholder="姓名或警号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="police_phone" label="公安联系电话">
                <Input placeholder="联系电话" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="security_officers" label="保卫班出警人">
            <Select mode="tags" placeholder="输入姓名后回车，可填写多人" />
          </Form.Item>

          <Form.Item name="loss_amount" label="损失金额（元，可选）">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>

          {/* 高级涉油特征折叠区域 */}
          <div
            className="cases-advanced-toggle"
            onClick={() => setShowAdvancedFields(!showAdvancedFields)}
          >
            {showAdvancedFields ? <UpOutlined style={{ fontSize: 12 }} /> : <DownOutlined style={{ fontSize: 12 }} />}
            涉油案件特征（高级，可选）
          </div>

          {showAdvancedFields && (
            <div className="cases-advanced-body">
              <Form.Item name="oil_type" label="油品类型">
                <Input placeholder="如：汽油、柴油、原油、润滑油" />
              </Form.Item>

              <Form.Item name="oil_nature" label="原油性质">
                <Select allowClear placeholder="请选择原油性质">
                  {oilNatureOptions.map(option => (
                    <Option key={option} value={option}>{option}</Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item name="oil_volume" label="涉油数量记录（不明可留空）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="oil_volume_unit" label="数量单位" initialValue="unknown"><Select options={oilUnitOptions} /></Form.Item>

              <Form.Item name="water_cut" label="检斤含水率（%）">
                <InputNumber style={{ width: '100%' }} min={0} max={100} />
              </Form.Item>

              <Form.Item name="oil_value" label="估算价值（元）">
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name="facility_type" label="目标设施类型">
                <Input placeholder="如：输油管线、加油站、油库、油罐车" />
              </Form.Item>

              <Form.Item name="facility_owner" label="设施所属单位">
                <Input placeholder="如：某石油公司、某物流企业" />
              </Form.Item>

              <Form.Item name="security_level" label="安防情况">
                <Input placeholder="如：监控盲区、周界薄弱、安防良好" />
              </Form.Item>

              <Form.Item name="modus_operandi" label="主要作案手法">
                <Input placeholder="如：打孔盗油、私接管线、计量作弊" />
              </Form.Item>

              <Form.Item name="upstream_source" label="上游油品来源">
                <Input placeholder="如：某段管线某号桩、某站某枪" />
              </Form.Item>

              <Form.Item name="downstream_destination" label="疑似销赃去向">
                <Input placeholder="如：黑加油点、工地、车队等" />
              </Form.Item>

              <Form.Item name="vehicle_handling" label="涉案车辆处理方式">
                <Input placeholder="如：扣押停放、移交公安、待处理" />
              </Form.Item>

              <Form.Item name="person_handling" label="抓获人员处理方式">
                <Input placeholder="如：移交公安、教育放行、待核查" />
              </Form.Item>

              <Form.Item name="oil_handling" label="涉案原油处理方式">
                <Input placeholder="如：检斤入库、移交、暂存" />
              </Form.Item>
            </div>
          )}
        </Form>
      </Modal>

      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-0)', fontSize: 14, letterSpacing: '0.06em' }}>
            批量补录坐标
          </span>
        }
        open={locationModalVisible}
        onCancel={() => {
          setLocationModalVisible(false)
          setActiveLocationCaseId(null)
          setLocationDraft({})
        }}
        width={860}
        footer={[
          <Button
            key="close"
            onClick={() => {
              setLocationModalVisible(false)
              setActiveLocationCaseId(null)
              setLocationDraft({})
            }}
          >
            关闭
          </Button>,
          <Button
            key="save"
            type="primary"
            loading={updateLocationMutation.isPending}
            disabled={!activeLocationCase || locationDraft.latitude == null || locationDraft.longitude == null}
            onClick={handleLocationSave}
          >
            保存并下一条
          </Button>,
        ]}
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
          footer:  { borderTop: '1px solid var(--line)' },
        }}
      >
        <div className="location-backfill">
          <div className="location-backfill__list">
            <div className="location-backfill__summary">
              <span>待补录</span>
              <b>{missingLocationCases?.length ?? 0}</b>
            </div>
            {missingLocationLoading ? (
              <p className="narr">正在读取缺坐标案件...</p>
            ) : (missingLocationCases || []).length === 0 ? (
              <p className="narr">当前没有缺坐标案件。</p>
            ) : (
              (missingLocationCases || []).map(item => (
                <button
                  key={item.id}
                  className={`location-backfill__item${activeLocationCaseId === item.id ? ' is-active' : ''}`}
                  onClick={() => {
                    setActiveLocationCaseId(item.id)
                    setLocationDraft({})
                  }}
                >
                  <b>{item.case_number}</b>
                  <span>{item.location || '未标注地点'}</span>
                  <small>{formatCaseTime(item, 'YYYY-MM-DD')}</small>
                </button>
              ))
            )}
          </div>
          <div className="location-backfill__map">
            {activeLocationCase ? (
              <>
                <div className="location-backfill__active">
                  <b>{activeLocationCase.case_number}</b>
                  <span>{activeLocationCase.location || '未标注地点'} · {activeLocationCase.case_type || '未分类'}</span>
                </div>
                <MapPicker
                  key={activeLocationCase.operational_area_id ?? 'default-area'}
                  height={330}
                  lat={locationDraft.latitude ?? activeLocationCase.latitude}
                  lng={locationDraft.longitude ?? activeLocationCase.longitude}
                  operationalAreaId={activeLocationCase.operational_area_id ?? undefined}
                  onChange={(latitude, longitude) => setLocationDraft({ latitude, longitude })}
                />
                <div className="location-backfill__coord">
                  {locationDraft.latitude != null && locationDraft.longitude != null
                    ? `${locationDraft.latitude.toFixed(6)}, ${locationDraft.longitude.toFixed(6)}`
                    : '点击地图选择坐标'}
                </div>
              </>
            ) : (
              <div className="empty-state">
                <div className="icon"><EnvironmentOutlined /></div>
                <span>选择左侧案件后补录坐标</span>
              </div>
            )}
          </div>
        </div>
      </Modal>

      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-0)', fontSize: 14, letterSpacing: '0.06em' }}>
            登记佐证材料
          </span>
        }
        open={evidenceModalVisible}
        forceRender
        onOk={handleEvidenceSubmit}
        onCancel={() => {
          setEvidenceModalVisible(false)
          evidenceForm.resetFields()
        }}
        okText="归档"
        cancelText="取消"
        confirmLoading={createEvidenceMutation.isPending}
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
        }}
      >
        <Form form={evidenceForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="title" label="材料名称" rules={[{ required: true, message: '请输入材料名称' }]}>
            <Input placeholder="如：检斤含水单据、车辆移交单据" />
          </Form.Item>
          <Form.Item name="file_path" label="文件路径或编号">
            <Input placeholder="本地路径、档案号或纸质材料编号" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <TextArea rows={3} placeholder="补充说明" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── 导入 Modal ── */}
      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-0)', fontSize: 14, letterSpacing: '0.06em' }}>
            导入历史案件（CSV / Excel）
          </span>
        }
        open={importModalVisible}
        onCancel={resetImportState}
        closable={!previewImportMutation.isPending && !importMutation.isPending && !importCorrectionBusy}
        maskClosable={!previewImportMutation.isPending && !importMutation.isPending && !importCorrectionBusy}
        keyboard={!previewImportMutation.isPending && !importMutation.isPending && !importCorrectionBusy}
        footer={[
          <Button key="cancel" disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy} onClick={resetImportState}>
            关闭
          </Button>,
          <Button key="preview" disabled={!selectedImportFile || previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
            onClick={() => selectedImportFile && previewImportMutation.mutate({ file: selectedImportFile, operationalAreaId: importOperationalAreaId })}>
            重新预览
          </Button>,
          <Button
            key="confirm"
            type="primary"
            loading={importMutation.isPending}
            disabled={
              importCorrectionBusy || !selectedImportFile ||
              importOperationalAreaId == null ||
              !importPreview ||
              (importPreview.valid ?? importPreview.total) === 0 ||
              previewImportMutation.isPending
            }
            onClick={() => selectedImportFile && importMutation.mutate({
              file: selectedImportFile,
              operationalAreaId: importOperationalAreaId,
            })}
          >
            确认导入
          </Button>,
        ]}
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
          body: { maxHeight: '65vh', overflowY: 'auto' },
        }}
      >
        <p className="cases-import-hint">
          支持中文表头：<strong>案发时间</strong>、<strong>案情描述</strong>；也兼容 occurred_time、description。
        </p>
        <p className="cases-import-hint">
          可选：案发地点、经度、纬度、案件类型等。单次最多 1000 条；无法识别的列会列出提示。
        </p>
        <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
          <label style={{ flex: 1 }}>工作表名称
            <Input aria-label="导入工作表名称" value={importWorksheet} maxLength={31}
              placeholder="留空使用文件当前工作表（CSV 留空）"
              disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
              onChange={event => { setImportWorksheet(event.target.value); setImportPreview(null) }} />
          </label>
          <label>表头行
            <InputNumber aria-label="导入表头行" min={1} max={100} precision={0} value={importHeaderRow}
              disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
              onChange={value => { setImportHeaderRow(value ?? 1); setImportPreview(null) }} />
          </label>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label htmlFor="case-import-time-zone">文件中未标时区的时间</label>
          <Select id="case-import-time-zone" aria-label="导入时间解释" style={{ width: '100%' }}
            value={importTimeZone} disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
            options={[{ value: 'Asia/Shanghai', label: '单位业务时间：北京时间（UTC+8）' }, { value: 'UTC', label: 'UTC 世界协调时（仅适用于原表确用 UTC 或旧模板）' }]}
            onChange={value => { setImportTimeZone(value); setImportPreview(null) }} />
          <p className="cases-import-hint">新文件默认按单位业务时间解释，请先核对。已有 Z 或时区偏移的时间保持原义；模板沿用其原设置，旧模板未标时区时仍按旧版 UTC 解释。更改后须重新预览，不批量改写已入库时间。</p>
        </div>
        {writableAreaScopes.length > 1 ? (
          <div style={{ marginBottom: 14 }}>
            <div className="cases-import-hint">本批案件所属厂区</div>
            <Select
              style={{ width: '100%' }}
              value={importOperationalAreaId}
              disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
              onChange={(value: number) => {
                setImportOperationalAreaId(value)
                setImportPreview(null)
                if (selectedImportFile) previewImportMutation.mutate({
                  file: selectedImportFile,
                  operationalAreaId: value,
                })
              }}
              options={writableAreaScopes.map(scope => ({
                value: scope.operational_area_id,
                label: scope.area_name,
              }))}
            />
          </div>
        ) : null}
        {importModalVisible && importPreview?.dry_run !== false && <CaseImportConfiguration
          file={selectedImportFile} areaId={importOperationalAreaId}
          settings={{ worksheet: importWorksheet, header_row: importHeaderRow, time_zone: importTimeZone, field_mapping: importFieldMapping }}
          disabled={previewImportMutation.isPending || importMutation.isPending}
          onChange={applyImportConfiguration} onBusyChange={setImportCorrectionBusy} />}
        <Upload.Dragger
          name="file"
          multiple={false}
          showUploadList={false}
          disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
          beforeUpload={(file) => {
            setSelectedImportFile(file)
            setImportPreview(null)
            previewImportMutation.mutate({
              file,
              operationalAreaId: importOperationalAreaId,
            })
            return false
          }}
          style={{
            background: 'var(--bg-2)',
            border: '1px dashed var(--line)',
            borderRadius: 0,
          }}
        >
          <p className="ant-upload-drag-icon" style={{ color: 'var(--accent)' }}>
            将文件拖到此处，或点击选择文件
          </p>
          <p className="ant-upload-text" style={{ color: 'var(--ink-2)' }}>
            {selectedImportFile ? selectedImportFile.name : '支持 CSV / Excel（.xlsx）文件'}
          </p>
        </Upload.Dragger>
        {previewImportMutation.isPending && (
          <div className="cases-import-status">正在解析并校验文件...</div>
        )}
        {importPreview && (
          <div className="cases-import-preview">
            {importPreview.dry_run === false && (
              <Alert type={importPreview.errors.length ? 'warning' : 'success'} showIcon
                message={importPreview.replayed ? `已恢复原批次回执，本次新增 0 条` : `本批已写入 ${importPreview.created} 条案件`}
                description={`批次 ${importPreview.batch_id ?? '—'}。相同文件和设置重传不会重复建案；可直接修正下面的失败行。`} />
            )}
            {!!importPreview.table?.ignored_headers.length && (
              <Alert type="warning" showIcon message="以下列未导入"
                description={importPreview.table.ignored_headers.join('、')} />
            )}
            <div className="cases-import-summary">
              <span>总行数 <b>{importPreview.total}</b></span>
              <span>有效 <b>{importPreview.valid ?? importPreview.total}</b></span>
              <span>错误 <b>{importPreview.errors?.length ?? 0}</b></span>
            </div>
            {importPreview.errors?.length > 0 && (
              <div className="cases-import-errors" style={{ maxHeight: 240, overflowY: 'auto' }}>
                {importPreview.errors.map((err) => (
                  <div key={`${err.row}-${err.error}`}>
                    第 {err.row} 行：{err.error}
                  </div>
                ))}
              </div>
            )}
            {importPreview.dry_run === false && importPreview.batch_id && <CaseImportCorrections
              key={importPreview.batch_id} batchId={importPreview.batch_id} onBusyChange={setImportCorrectionBusy}
              onCorrected={applyImportReceipt} />}
            {(importPreview.preview?.length ?? 0) > 0 && (
              <div className="cases-import-rows">
                {importPreview.preview!.slice(0, 5).map((row, idx) => (
                  <div key={idx} className="cases-import-row">
                    {Object.entries(row).slice(0, 5).map(([key, value]) => (
                      <span key={key}>
                        <b>{key}</b>{String(value ?? '—')}
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>

    </div>
  )
}

export default Cases
