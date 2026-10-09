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
import { caseApi, type CaseEditSnapshot, type CaseImportOptions, type CaseImportResult } from '../../services/cases'
import { caseDraftsApi, type CaseDraft, type CaseDraftSave } from '../../services/caseDrafts'
import CaseDraftLibrary from './CaseDraftLibrary'
import CaseEditConflict from './CaseEditConflict'
import { intakeSessionState, mergeIntakeCandidates, restoreIntakeDescription, type IntakeConflict } from './caseIntakeSession'
import { useCaseDraftAutosave, useCaseIntakeSession } from './useCaseIntakeSession'
import { editSnapshotValues, entryDifferenceFields, entryFormValues, restoreEntryValues, serializeEntryValues } from './caseDraftSnapshot'
import CaseImportCorrections from './CaseImportCorrections'
import CaseRecentImports from './CaseRecentImports'
import CaseExportMenu from './CaseExportMenu'
import CaseImportConfiguration from './CaseImportConfiguration'
import CaseClipboardImport from './CaseClipboardImport'
import CaseFacilityPicker from './CaseFacilityPicker'
import { intakeCapabilityLabel, intakeEvidenceLabel } from './caseEntryAssistance'
import CaseHistoryReferences from './CaseHistoryReferences'
import CaseSemanticProfile from './CaseSemanticProfile'
import { importPreviewCells } from './importCorrection'
import { CaseEntryPrecheck } from './CaseEntryPrecheck'
import { CaseSourceCollections, CaseTimeFields, locationRoleLabels, oilUnitOptions } from './CaseSourceFields'
import CaseFeedbackFields from './CaseFeedbackFields'
import { changedFeedbackFields, feedbackDescription, feedbackFields } from './caseFeedback'
import CaseAnalysisApplicability, { type AnalysisApplicability } from './CaseAnalysisApplicability'
import CaseSourceDetails from './CaseSourceDetails'
import CaseEntityDetails from './CaseEntityDetails'
import CaseEvidenceFiles from './CaseEvidenceFiles'
import RecordIntake from './RecordIntake'
import { CaseDossierNavigation, CaseDossierPanel, CaseQualityStatus, caseDossierView, hasCurrentCaseQuality } from './CaseDossier'
import { formatCaseTime, formatOilVolume, formatStoredTime, formCaseTime } from '../../utils/caseValues'
import CaseResultPanel from '../../components/CaseResult/CaseResultPanel'
import CaseResultMap from '../../components/CaseResult/CaseResultMap'
import { useCaseWorkspace, useCaseWorkspaceSection } from '../../services/useCaseWorkspace'
import { parseCaseContextParams, parseCaseListPosition, writeCaseFilterParams, writeCaseListPosition } from '../../services/caseContext'
import { businessContextPath } from '../../services/businessNavigation'
import BusinessReturnLink from '../../components/BusinessReturnLink'
import { caseImportsApi, type ImportCorrectionResult, type RecentImportBatch } from '../../services/caseImports'
import { caseStewardApi } from '../../services/caseSteward'
import type { BatchReviewResult, BonusAssessment, Case, CaseCreate, CaseQuality, CaseQualityPreview, CaseUpdatePayload } from '../../types'
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
import { buildCaseSearchParams, parseCaseDeepLinkId, caseDetailKey, visibleCaseDetail, visibleCasePage, returnToCaseListParams } from './caseSearch'
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

// 默认案件筛选状态（复选框）
interface FilterState {
  statuses: string[]
  caseTypes: string[]
  oilTypes: string[]
  startDate: string
  endDate: string
  timeBasis: 'discovery' | 'incident' | 'entry'
}

const defaultFilterState: FilterState = {
  statuses: ['pending', 'processing', 'completed', 'resolved', 'failed'],
  caseTypes: [],
  oilTypes: [],
  startDate: '',
  endDate: '',
  timeBasis: 'discovery',
}


const CaseWorkspace: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const caseContext = parseCaseContextParams(searchParams)
  const listPosition = parseCaseListPosition(searchParams)
  const contextError = caseContext.error || listPosition.error
  const caseContextPath = (target: string, params: URLSearchParams) => businessContextPath(target, params, '/cases')
  const dossierView = caseDossierView(searchParams.get('case_view'))
  const [form] = Form.useForm()
  const [evidenceForm] = Form.useForm()
  const [modal, modalContextHolder] = Modal.useModal()
  const [message, messageContextHolder] = messageFactory.useMessage()
  const [isModalVisible, setIsModalVisible] = useState(false)
  const [editingCase, setEditingCase] = useState<Case | null>(null)
  const [editRevision, setEditRevision] = useState<number | null>(null)
  const [editConflict, setEditConflict] = useState<CaseEditSnapshot | null>(null)
  const [activeDraft, setActiveDraft] = useState<CaseDraft | null>(null)
  const [draftLibraryOpen, setDraftLibraryOpen] = useState(false)
  const [draftBusy, setDraftBusy] = useState(false)
  const [draftNotice, setDraftNotice] = useState('')
  const [draftFailure, setDraftFailure] = useState('')
  const draftSaveRef = useRef<{ id: string; payload: CaseDraftSave } | null>(null)
  const [draftSavePending, setDraftSavePending] = useState(false)
  const [draftConflict, setDraftConflict] = useState<CaseDraft | null>(null)
  const [draftSubmissionConflictId, setDraftSubmissionConflictId] = useState<string | null>(null)
  const [consumedDraftCaseId, setConsumedDraftCaseId] = useState<number | null>(null)
  const { entryDirty, changeVersion, setEntryDirty, manualFields, onManualChange } = useCaseIntakeSession()
  const [submission, setSubmission] = useState<CaseSubmission | null>(null)
  const submissionRef = useRef<CaseSubmission | null>(null)
  const [saveFailure, setSaveFailure] = useState('')
  const [saveConflict, setSaveConflict] = useState(false)
  const [savePreparing, setSavePreparing] = useState(false)
  const saveBusy = useRef(false)
  const [savedCaseId, setSavedCaseId] = useState<number | null>(null)
  const [importCorrectionDirty, setImportCorrectionDirty] = useState(false)
  useCaseLeaveGuard(entryDirty || Boolean(submission) || draftSavePending || importCorrectionDirty)
  const [importModalVisible, setImportModalVisible] = useState(false)
  const [selectedImportFile, setSelectedImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<CaseImportResult | null>(null)
  const [importOperationalAreaId, setImportOperationalAreaId] = useState<number | undefined>()
  const [importWorksheet, setImportWorksheet] = useState('')
  const [importHeaderRow, setImportHeaderRow] = useState(1)
  const [importPreset, setImportPreset] = useState<CaseImportOptions['import_preset']>(null)
  const [importTimeZone, setImportTimeZone] = useState<'UTC' | 'Asia/Shanghai'>('Asia/Shanghai')
  const [importFieldMapping, setImportFieldMapping] = useState<Record<string, string | null>>({})
  const [importSourceKey, setImportSourceKey] = useState('')
  const [importSourceRevision, setImportSourceRevision] = useState('')
  const [importCorrectionBusy, setImportCorrectionBusy] = useState(false)
  const [recentImportsOpen, setRecentImportsOpen] = useState(false)
  const applyImportConfiguration = useCallback((settings: CaseImportOptions) => {
    setImportWorksheet(settings.worksheet ?? '')
    setImportHeaderRow(settings.header_row ?? 1)
    setImportPreset(settings.import_preset ?? null)
    setImportTimeZone(settings.time_zone ?? 'UTC')
    setImportFieldMapping(settings.field_mapping ?? {})
    setImportSourceKey(settings.source_key ?? '')
    setImportSourceRevision(settings.source_revision ?? '')
    setImportPreview(null)
  }, [])
  const applyImportReceipt = useCallback((result: ImportCorrectionResult) => {
    setImportPreview(previous => previous?.batch_id === result.batch_id
      ? { ...previous, created: result.batch_created_total, valid: Math.max(previous.valid ?? 0, result.batch_created_total), errors: result.errors, replayed: false }
      : previous)
    void queryClient.invalidateQueries({ queryKey: ['case-recent-imports'] })
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
  const [aiIntakeSourceText, setAiIntakeSourceText] = useState('')
  const [intakeConflicts, setIntakeConflicts] = useState<IntakeConflict[]>([])
  const [legacyAssistantText, setLegacyAssistantText] = useState('')
  const filters = caseContext.filters
  const { page, pageSize } = listPosition
  const setPage = useCallback((value: number) => setSearchParams(previous => writeCaseListPosition(previous, value, pageSize)), [pageSize, setSearchParams])
  const [keyword, setKeyword] = useState(() => filters.keyword ?? '')
  const [sidebarFilter, setSidebarFilter] = useState<FilterState>(() => ({
    ...defaultFilterState, statuses: filters.statuses ?? [], caseTypes: filters.case_types ?? [], oilTypes: filters.oil_types ?? [],
    startDate: filters.start_date ? dayjs(filters.start_date).format('YYYY-MM-DD') : '',
    endDate: filters.end_date ? dayjs(filters.end_date).subtract(1, 'millisecond').format('YYYY-MM-DD') : '',
    timeBasis: filters.time_basis ?? (filters.start_date || filters.end_date ? 'incident' : 'discovery'),
  }))
  const filterToken = writeCaseFilterParams(new URLSearchParams(), filters).toString()
  useEffect(() => {
    const current = parseCaseContextParams(new URLSearchParams(filterToken)).filters
    setKeyword(current.keyword ?? '')
    const day = (value: string | undefined, end = false) => value && Number.isFinite(Date.parse(value))
      ? new Date(Date.parse(value) + 8 * 3600000 - (end ? 1 : 0)).toISOString().slice(0, 10) : ''
    setSidebarFilter({ ...defaultFilterState, statuses: current.statuses ?? [], caseTypes: current.case_types ?? [],
      oilTypes: current.oil_types ?? [], startDate: day(current.start_date), endDate: day(current.end_date, true),
      timeBasis: current.time_basis ?? (current.start_date || current.end_date ? 'incident' : 'discovery') })
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
    queryFn: ({ signal }) => caseApi.getCasePage({ ...filters, time_basis: filters.time_basis ?? (filters.start_date || filters.end_date ? 'incident' : 'discovery'), page, page_size: pageSize }, signal),
    enabled: !contextError,
  })
  const { data: rawCasePage, isLoading, isError: caseSearchError } = casesQuery
  const casePage = visibleCasePage(rawCasePage, !!contextError || caseSearchError)
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

  const renderQualityBadge = (quality?: Partial<CaseQuality> | null) => {
    if (!hasCurrentCaseQuality(quality)) {
      return <span style={{ color: 'var(--ink-3)' }}>—</span>
    }
    return (
      <span
        className="tag"
        style={{ '--tag-c': quality.validation.can_save ? 'var(--ok)' : 'var(--warn)' } as React.CSSProperties}
        title="仅表示字段格式，不代表案件完成度"
      >
        {quality.validation.can_save ? '格式有效' : '格式待修正'}
      </span>
    )
  }

  const caseTypes = Object.keys(casePage?.facets.case_types ?? {})
  const oilTypes = Object.keys(casePage?.facets.oil_types ?? {})

  const batchReviewSummary = useMemo(
    () => !contextError && batchReviewResult ? summarizeBatchReview(batchReviewResult) : null,
    [batchReviewResult, contextError],
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
    setIsModalVisible(false); setEditingCase(null); setEditRevision(null); setEditConflict(null)
    setActiveDraft(null); setDraftNotice(''); setDraftFailure(''); setDraftConflict(null); setDraftSubmissionConflictId(null)
    setConsumedDraftCaseId(null)
    draftSaveRef.current = null; setDraftSavePending(false)
    form.resetFields(); setSavedCaseId(id)
    void queryClient.invalidateQueries({ queryKey: ['case-private-drafts'] })
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
      if (retry || checkOnly) return resolveCaseSubmission(attempt, { ...caseApi, getDraft: caseDraftsApi.get, submitDraft: caseDraftsApi.submit }, retry)
      if (attempt.draftId && attempt.draftRevision !== undefined) return (await caseDraftsApi.submit(attempt.draftId, attempt.draftRevision, attempt.payload)).case_id
      return attempt.caseId !== undefined
        ? (await caseApi.updateEditSnapshot(attempt.caseId, attempt.sourceRevision!, attempt.payload as CaseUpdatePayload)).case.id
        : (await caseApi.createCase(attempt.payload as CaseCreate, attempt.key)).id
    },
    onSuccess: id => {
      if (!entryMounted.current) return
      if (id !== null) completeSave(id)
      else setSaveFailure('暂未查到可确认的保存结果（也可能是权限发生变化）。原输入和凭证仍保留，不能据此认定未保存；可使用原请求安全重试或联系管理员核对。')
    },
    onError: (error, variables) => {
      if (!entryMounted.current) return
      const detail = (error as { detail?: { detail?: { code?: string } } }).detail?.detail
      if (variables.attempt.caseId !== undefined && detail?.code === 'case_revision_conflict') {
        setSaveFailure('案件来源版本已变化。当前输入仍保留，请读取服务器最新记录逐项比较。')
        setSaveConflict(true)
        void readEditConflict(variables.attempt.caseId)
        return
      }
      if (variables.attempt.draftId && detail?.code === 'draft_revision_conflict') {
        setSaveFailure('草稿已被其他页面修改。原输入与提交请求继续保留，请读取最新草稿进行比较。')
        setSaveConflict(true); setDraftSubmissionConflictId(variables.attempt.draftId)
        void readSubmissionDraftConflict(variables.attempt.draftId)
        return
      }
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

  const readEditConflict = async (id: number) => {
    const requestId = editRequestRef.current
    try {
      const latest = await caseApi.getEditSnapshot(id)
      if (!entryMounted.current || editRequestRef.current !== requestId) return
      setEditConflict(latest)
    } catch {
      if (entryMounted.current && editRequestRef.current === requestId) setSaveFailure('最新版本读取失败或权限已变化。我的输入仍保留，不能跳过比较覆盖。')
    }
  }

  const readSubmissionDraftConflict = async (id: string) => {
    const requestId = editRequestRef.current
    try {
      const latest = await caseDraftsApi.get(id)
      if (!entryMounted.current || editRequestRef.current !== requestId) return
      if (latest.status === 'submitted' && latest.submitted_case_id) await compareConsumedDraft(latest.submitted_case_id)
      else setDraftConflict(latest)
    } catch {
      if (entryMounted.current && editRequestRef.current === requestId) setSaveFailure('最新草稿读取失败或当前不可访问。原请求仍保留，不能据此另建案件。')
    }
  }

  const compareConsumedDraft = async (caseId: number) => {
    setConsumedDraftCaseId(caseId)
    setDraftNotice('')
    setDraftFailure(`该草稿已由其他页面转为案件 #${caseId}，不能据此确认本页内容已保存。本页输入仍保留；请与该案最新记录逐项比较，之后只能明确编辑该案，不会另建案件。`)
    await readEditConflict(caseId)
  }

  const intakeSnapshot = () => ({ values: serializeEntryValues(form.getFieldsValue(true)),
    assistant_source_text: aiIntakeSourceText, had_incident_locations: hadIncidentLocations,
    manual_fields: [...manualFields.current].sort(), ...(legacyAssistantText ? { assistant_text: legacyAssistantText } : {}) })

  const acceptSavedDraft = (draft: CaseDraft, checkCurrent = false) => {
    setActiveDraft(draft); draftSaveRef.current = null; setDraftSavePending(false); setDraftFailure(''); setDraftConflict(null)
    // A user can keep typing during automatic save. Its receipt acknowledges only that snapshot.
    setEntryDirty(checkCurrent && entryDifferenceFields(intakeSnapshot(), draft.form_snapshot).length > 0)
    setDraftNotice(`私有草稿已暂存于 ${formatStoredTime(draft.updated_at, 'YYYY-MM-DD HH:mm:ss')}。到期时间：${formatStoredTime(draft.expires_at, 'YYYY-MM-DD HH:mm')}；到期后不可找回。`)
    void queryClient.invalidateQueries({ queryKey: ['case-private-drafts'] })
  }

  const persistDraft = async (): Promise<CaseDraft | null> => {
    if (submissionRef.current || draftConflict || editConflict) return null
    const areaId = editingCase?.operational_area_id ?? form.getFieldValue('operational_area_id')
    if (!areaId) { setDraftFailure('请选择可写厂区后保存私有草稿。'); return null }
    const requestId = editRequestRef.current
    // Changing a new record's area starts a new private draft; never move an existing snapshot across scopes.
    const sameAreaDraft = activeDraft?.operational_area_id === areaId ? activeDraft : null
    const attempt = draftSaveRef.current ?? { id: sameAreaDraft?.id || crypto.randomUUID(), payload: {
      expected_revision: sameAreaDraft?.revision || 0, operational_area_id: areaId,
      target_case_id: editingCase?.id ?? null, base_case_revision: editingCase ? editRevision : null,
      schema_version: 1 as const, form_snapshot: intakeSnapshot(),
    } }
    draftSaveRef.current = attempt; setDraftSavePending(true); setDraftBusy(true); setDraftFailure('')
    try {
      const draft = await caseDraftsApi.save(attempt.id, attempt.payload)
      if (!entryMounted.current || editRequestRef.current !== requestId) return null
      acceptSavedDraft(draft, true)
      return draft
    } catch (error) {
      if (!entryMounted.current || editRequestRef.current !== requestId) return null
      const status = (error as { status?: number }).status
      if (status && status >= 400 && status < 500 && status !== 408 && status !== 409) {
        draftSaveRef.current = null; setDraftSavePending(false)
        setDraftFailure(`草稿未保存：${error instanceof Error ? error.message : '请检查权限或输入'}。本页输入仍保留。`)
      } else setDraftFailure('草稿保存未确认或版本已变化。输入已冻结；请核对草稿或重试原保存，不要新建另一份。')
      return null
    } finally { if (entryMounted.current && editRequestRef.current === requestId) setDraftBusy(false) }
  }

  const entryState = intakeSessionState({ dirty: entryDirty, savedAt: activeDraft?.updated_at,
    savingDraft: draftBusy, submitting: savePreparing || saveMutation.isPending,
    outcomeUnknown: Boolean(submission) || (draftSavePending && !draftBusy), conflict: Boolean(editConflict || draftConflict || saveConflict) })

  const checkDraftSave = async () => {
    const attempt = draftSaveRef.current
    if (!attempt || draftBusy) return
    const requestId = editRequestRef.current
    setDraftBusy(true)
    try {
      const latest = await caseDraftsApi.get(attempt.id)
      if (!entryMounted.current || editRequestRef.current !== requestId) return
      if (latest.status === 'submitted' && latest.submitted_case_id) { await compareConsumedDraft(latest.submitted_case_id); return }
      if (!entryDifferenceFields(attempt.payload.form_snapshot, latest.form_snapshot).length
          && latest.revision > attempt.payload.expected_revision && latest.base_case_revision === attempt.payload.base_case_revision) acceptSavedDraft(latest, true)
      else { setDraftConflict(latest); setDraftFailure('服务器已有不同草稿版本，请比较后再保存；本页输入未被覆盖。') }
    } catch {
      if (entryMounted.current && editRequestRef.current === requestId) setDraftFailure('暂未读到可确认的草稿（也可能是撤权或到期）。原输入和保存请求继续保留，可用原请求重试。')
    } finally { if (entryMounted.current && editRequestRef.current === requestId) setDraftBusy(false) }
  }

  const restoreDraft = async (id: string) => {
    if (submissionRef.current || draftSaveRef.current || draftBusy || saveBusy.current) { message.warning('请先核对当前尚未确认的保存。'); return }
    if (entryDirty && !window.confirm('找回其他草稿会替换本页未保存输入。请确认已保存需要保留的草稿，仍要继续吗？')) return
    const requestId = ++editRequestRef.current
    setDraftBusy(true)
    try {
      const draft = await caseDraftsApi.get(id, undefined, 'resume')
      if (!entryMounted.current || editRequestRef.current !== requestId) return
      if (draft.status === 'submitted' && draft.submitted_case_id) { setDraftLibraryOpen(false); completeSave(draft.submitted_case_id); return }
      if (draft.schema_version !== 1 || !draft.form_snapshot.values || typeof draft.form_snapshot.values !== 'object') throw new Error('草稿格式不支持')
      const current = draft.target_case_id ? await caseApi.getEditSnapshot(draft.target_case_id) : null
      if (!entryMounted.current || editRequestRef.current !== requestId) return
      form.resetFields(); form.setFieldsValue(restoreEntryValues(restoreIntakeDescription(draft.form_snapshot)))
      setEditingCase(current?.case ?? null); setEditRevision(draft.base_case_revision); setEditConflict(null)
      setBonusDraftLoadState({ vehicles: true, persons: true }); setSourceCollectionsLoaded({ locations: true, measurements: true })
      setBonusDraftTouched({ vehicles: false, persons: false }); setHadIncidentLocations(Boolean(draft.form_snapshot.had_incident_locations))
      setLegacyAssistantText(String(draft.form_snapshot.assistant_text || '')); setAiIntakeSourceText(String(draft.form_snapshot.assistant_source_text || ''))
      manualFields.current = new Set(Array.isArray(draft.form_snapshot.manual_fields) ? draft.form_snapshot.manual_fields as string[] : [])
      setIntakeConflicts([])
      structureMutation.reset(); qualityPreviewMutation.reset(); setSaveFailure(''); setSaveConflict(false)
      acceptSavedDraft(draft); setShowAdvancedFields(false); setShowMapPicker(false); setDraftLibraryOpen(false); setIsModalVisible(true)
      if (current && current.source_revision !== draft.base_case_revision) { setEditConflict(current); setSaveFailure('草稿基于较早的案件版本，请比较后再保存正式记录。') }
    } catch (error) {
      if (entryMounted.current && editRequestRef.current === requestId) message.error(`草稿无法找回：${error instanceof Error ? error.message : '请核对权限与到期时间'}。未用旧缓存代替。`)
    } finally { if (entryMounted.current && editRequestRef.current === requestId) setDraftBusy(false) }
  }

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
      if (!entryMounted.current || requestId !== editRequestRef.current || submissionRef.current || draftSaveRef.current || saveBusy.current) return
      if (form.getFieldValue('description') !== sourceText) {
        message.info('原始记录在提取期间已修改，本次候选未写入。请根据最新原文重新提取。')
        return
      }
      const application = buildCaseAiIntakeApplication(data, sourceText)
      const candidates = {
        ...application.patch,
        ...buildCaseAiIntakeEntryFlags(data, application.patch),
      } as Record<string, unknown>
      ;(['occurred_time', 'occurred_from', 'occurred_to', 'discovered_at', 'report_time'] as const).forEach(field => {
        if (typeof candidates[field] === 'string') {
          candidates[field] = formCaseTime(candidates[field] as string, String(candidates.time_timezone || form.getFieldValue('time_timezone') || 'Asia/Shanghai'))
        }
      })
      const { patch, conflicts } = mergeIntakeCandidates(form.getFieldsValue(true), candidates, manualFields.current)
      setIntakeConflicts(conflicts)
      let changedFeedback = form.getFieldValue('feedback_changed_fields')
      for (const field of feedbackFields) if (typeof patch[field] === 'boolean') changedFeedback = changedFeedbackFields(changedFeedback, field)
      if (changedFeedback) patch.feedback_changed_fields = changedFeedback
      form.setFieldsValue(patch)
      setEntryDirty(true)
      setAiIntakeSourceText(sourceText)
      if (application.shouldOpenAdvancedFields) {
        setShowAdvancedFields(true)
      }
      if (patch.latitude != null || patch.longitude != null) {
        setShowMapPicker(true)
      }
      message.success(`已补齐 ${Object.keys(patch).filter(field => !field.startsWith('feedback_')).length} 个空白字段；保留人工内容，${conflicts.length} 项差异供核对`)
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`自动提取失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const aiIntakeApplication = useMemo(
    () => structureMutation.data
      ? buildCaseAiIntakeApplication(structureMutation.data, aiIntakeSourceText)
      : null,
    [aiIntakeSourceText, structureMutation.data],
  )

  useCaseDraftAutosave({ enabled: isModalVisible && entryDirty && Boolean(editingCase?.operational_area_id ?? form.getFieldValue('operational_area_id')),
    blocked: Boolean(submission) || draftBusy || draftSavePending || savePreparing || structureMutation.isPending || Boolean(draftConflict) || Boolean(editConflict) || Boolean(draftFailure),
    changeVersion, save: persistDraft })

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
      caseApi.previewImportCases(file, operationalAreaId, { import_preset: importPreset, worksheet: importWorksheet, header_row: importHeaderRow, time_zone: importTimeZone, field_mapping: importFieldMapping, source_key: importSourceKey.trim() || undefined, source_revision: importSourceRevision.trim() || undefined })
    ),
    onSuccess: (data) => {
      setImportPreview(data)
      void queryClient.invalidateQueries({ queryKey: ['case-recent-imports'] })
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
      caseApi.importCases(file, false, operationalAreaId, { import_preset: importPreset, worksheet: importWorksheet, header_row: importHeaderRow, time_zone: importTimeZone, field_mapping: importFieldMapping, source_key: importSourceKey.trim() || undefined, source_revision: importSourceRevision.trim() || undefined })
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
    if (importCorrectionDirty && !window.confirm('当前失败行有尚未提交的修正。关闭后这些输入会丢失，已保存批次仍可找回。仍要关闭吗？')) return
    setImportModalVisible(false)
    setSelectedImportFile(null)
    setImportPreview(null)
    setImportWorksheet('')
    setImportHeaderRow(1)
    setImportPreset(null)
    setImportTimeZone('Asia/Shanghai')
    setImportFieldMapping({})
    setImportOperationalAreaId(defaultWritableOperationalAreaId)
    previewImportMutation.reset()
    importMutation.reset()
  }

  const openRecentImport = async (batch: RecentImportBatch) => {
    if (importCorrectionBusy) return
    if (selectedImportFile && !window.confirm('找回批次会收起当前文件预览，尚未导入的文件不会保存。继续吗？')) return
    if (importCorrectionDirty && !window.confirm('切换批次会放弃当前失败行未提交的修正，仍要继续吗？')) return
    setImportCorrectionBusy(true)
    try {
      const receipt = await caseImportsApi.getRows(batch.batch_id)
      if (!entryMounted.current) return
      setSelectedImportFile(null); setImportOperationalAreaId(batch.operational_area_id ?? undefined)
      setImportPreview({ total: batch.total ?? receipt.created_total + receipt.rows.length, created: receipt.created_total, updated: 0,
        valid: receipt.created_total, dry_run: false, batch_id: batch.batch_id, replayed: true,
        errors: receipt.rows.map(row => ({ row: row.row, error: row.error || '待核对' })) })
      setRecentImportsOpen(false)
    } catch { if (entryMounted.current) message.error('批次找回失败或权限已变化，没有使用旧回执。') }
    finally { if (entryMounted.current) setImportCorrectionBusy(false) }
  }

  const handleCreate = () => {
    if (submissionRef.current || draftSaveRef.current) { setIsModalVisible(true); return }
    editRequestRef.current += 1
    setEntryDirty(false); setSaveFailure(''); setSaveConflict(false)
    setEditingCase(null)
    setEditRevision(null); setEditConflict(null); setActiveDraft(null); setDraftConflict(null); setDraftNotice(''); setDraftFailure('')
    form.resetFields()
    qualityPreviewMutation.reset()
    form.setFieldsValue({
      operational_area_id: defaultWritableOperationalAreaId,
      time_precision: 'unknown',
      time_timezone: 'Asia/Shanghai',
      oil_volume_unit: 'unknown',
      entry_location_role: 'unknown',
      police_reported: null,
      case_filed: null,
      feedback_changed_fields: [],
      feedback_initial_known_fields: [],
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
    manualFields.current.clear(); setIntakeConflicts([]); setLegacyAssistantText('')
    setAiIntakeSourceText('')
    structureMutation.reset()
    setIsModalVisible(true)
  }

  useEffect(() => {
    if (searchParams.get('create') !== '1' || areaScopesQuery.isPending) return
    setSearchParams(previous => { const next = new URLSearchParams(previous); next.delete('create'); return next }, { replace: true })
    if (user?.role === 'admin' || user?.role === 'analyst') handleCreate()
  }, [searchParams, areaScopesQuery.isPending])

  useEffect(() => {
    if (searchParams.get('drafts') !== '1' && searchParams.get('imports') !== '1') return
    if (user?.role === 'admin' || user?.role === 'analyst') {
      if (searchParams.get('drafts') === '1') setDraftLibraryOpen(true)
      if (searchParams.get('imports') === '1') { setImportModalVisible(true); setRecentImportsOpen(true) }
    }
    setSearchParams(previous => { const next = new URLSearchParams(previous); next.delete('drafts'); next.delete('imports'); return next }, { replace: true })
  }, [searchParams, user?.role, setSearchParams])

  const handleEdit = async (caseItem: Case) => {
    if (submissionRef.current || draftSaveRef.current) { setIsModalVisible(true); message.warning('请先核对上一笔提交或草稿保存，不能覆盖未确认的输入。'); return }
    setEntryDirty(false); setSaveFailure(''); setSaveConflict(false)
    const requestId = editRequestRef.current + 1
    editRequestRef.current = requestId
    qualityPreviewMutation.reset()
    try {
      const snapshot = await caseApi.getEditSnapshot(caseItem.id)
      if (!entryMounted.current || editRequestRef.current !== requestId) return
      setEditingCase(snapshot.case); setEditRevision(snapshot.source_revision); setEditConflict(null)
      setActiveDraft(null); setDraftNotice(''); setDraftFailure(''); setDraftConflict(null)
      form.resetFields(); form.setFieldsValue(editSnapshotValues(snapshot))
      setBonusDraftLoadState({ vehicles: true, persons: true }); setSourceCollectionsLoaded({ locations: true, measurements: true })
      setHadIncidentLocations(snapshot.initial_locations.some(item => item.role === 'incident')); setBonusDraftTouched({ vehicles: false, persons: false })
      manualFields.current.clear(); setIntakeConflicts([]); setLegacyAssistantText(''); setAiIntakeSourceText(''); structureMutation.reset()
      setShowAdvancedFields(false); setShowMapPicker(snapshot.case.latitude != null && snapshot.case.longitude != null)
      setIsModalVisible(true)
    } catch {
      if (entryMounted.current && editRequestRef.current === requestId) message.error('当前案件及明细版本读取失败，未打开可覆盖旧记录的编辑表单。请重试。')
    }
  }

  const handleBonusVehicleScopeChange = (checked: boolean) => {
    manualFields.current.add('bonus_has_vehicle'); manualFields.current.add('initial_vehicles')
    setEntryDirty(true)
    setBonusDraftTouched(prev => ({ ...prev, vehicles: true }))
    const rows = form.getFieldValue('initial_vehicles')
    form.setFieldsValue({
      bonus_has_vehicle: checked,
      initial_vehicles: checked ? (Array.isArray(rows) && rows.length ? rows : [{}]) : [],
    })
  }

  const handleBonusPersonScopeChange = (checked: boolean) => {
    manualFields.current.add('bonus_has_person'); manualFields.current.add('initial_persons')
    setEntryDirty(true)
    setBonusDraftTouched(prev => ({ ...prev, persons: true }))
    const rows = form.getFieldValue('initial_persons')
    form.setFieldsValue({
      bonus_has_person: checked,
      initial_persons: checked ? (Array.isArray(rows) && rows.length ? rows : [{}]) : [],
    })
  }

  const handleSubmit = async () => {
    if (saveBusy.current || submissionRef.current || draftSaveRef.current || draftBusy || editConflict || draftConflict || !entryMounted.current) return
    if (editingCase && editRevision === null) { setSaveFailure('尚未读取可确认的案件版本，不能保存编辑。'); return }
    let values: Record<string, unknown>
    try {
      await form.validateFields()
      values = entryFormValues(form.getFieldsValue(true))
    } catch (error) {
      const fields = (error as { errorFields?: Array<{ errors: string[] }> }).errorFields
      setSaveFailure(`请检查表单中标出的必填或格式问题，输入已保留。${fields?.flatMap(field => field.errors).join('；') || ''}`)
      setShowAdvancedFields(true)
      return
    }
    // Two clicks can await field validation together; only the first may prepare a write.
    if (saveBusy.current || submissionRef.current || draftSaveRef.current || draftBusy || !entryMounted.current) return
    const payload = buildCaseEntrySubmitPayload(values, {
      mode: editingCase ? 'edit' : 'create',
      includeVehicleDrafts: !editingCase || bonusDraftLoadState.vehicles || bonusDraftTouched.vehicles,
      includePersonDrafts: !editingCase || bonusDraftLoadState.persons || bonusDraftTouched.persons,
      includeLocations: sourceCollectionsLoaded.locations,
      includeMeasurements: sourceCollectionsLoaded.measurements,
      hadIncidentLocations,
      legacyCoordinates: editingCase ?? undefined,
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
      // Persist every submission's identity before sending it, including one-click manual entries.
      const savedDraft = await persistDraft()
      if (!savedDraft || !entryMounted.current) return
      const attempt = prepareCaseSubmission(payload, editingCase?.id, { sourceRevision: editingCase ? editRevision! : undefined,
        ...(savedDraft ? { key: savedDraft.submission_key, draftId: savedDraft.id, draftRevision: savedDraft.revision } : {}) })
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
      if (retry && attempt.caseId !== undefined && !attempt.draftId && !await modal.confirm({
        title: '把本次原输入重新保存到同一案件？',
        content: '上一笔编辑可能已经生效。重试仍带原来源版本；记录已变化时会停止并要求比较，不会静默覆盖。',
        okText: '已核对，重新保存本案', cancelText: '先不重试',
      })) return
      if (!entryMounted.current) return
      await saveMutation.mutateAsync({ attempt, retry, checkOnly: !retry })
    }
    catch { /* Preserve the original attempt; onError supplies an inline explanation. */ }
    finally { saveBusy.current = false }
  }

  const cancelEntry = async () => {
    if (saveBusy.current || draftBusy) return
    if (draftSaveRef.current) { setDraftFailure('草稿保存结果尚未确认，输入继续保留。请先核对草稿或使用原请求重试。'); return }
    if (submissionRef.current) {
      if (await modal.confirm({ title: '保存结果尚未确认', content: '关闭窗口不会撤销服务器上的提交。原输入已暂存；可从“我的草稿”读取当前服务器结果继续核对，不要另建案件。', okText: '暂时收起', cancelText: '继续核对' })) setIsModalVisible(false)
      return
    }
    if (entryDirty && !await modal.confirm({ title: '放弃尚未暂存的修改？', content: '服务器只保留最后确认暂存的版本，当前未保存修改关闭后会清除。可返回等待自动暂存或立即暂存后再离开。', okText: '放弃未保存修改', cancelText: '返回填写' })) return
    editRequestRef.current += 1; setIsModalVisible(false); setEditingCase(null); setEntryDirty(false); setSaveFailure('')
    setEditRevision(null); setEditConflict(null); setDraftConflict(null); setActiveDraft(null); setDraftNotice(''); setDraftFailure(''); form.resetFields()
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
  }

  const resetFilters = () => {
    setSidebarFilter(defaultFilterState)
    setKeyword('')
    setSearchParams(previous => writeCaseFilterParams(previous, {}))
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
    const text = form.getFieldValue('description')
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
            <Select aria-label="案件列表时间口径" value={sidebarFilter.timeBasis} style={{ width: '100%', marginBottom: 8 }}
              options={[{ value: 'discovery', label: '发现／查获时间' }, { value: 'incident', label: '实际案发时间' }, { value: 'entry', label: '录入时间' }]}
              onChange={value => setSidebarFilter(previous => ({ ...previous, timeBasis: value }))} />
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
          <small>时间未知的记录不以录入时间替代。旧链接未声明口径时，有日期筛选继续采用原案发口径。</small>
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
              {!contextError && <CaseExportMenu params={{ ...filters, time_basis: filters.time_basis ?? (filters.start_date || filters.end_date ? 'incident' : 'discovery') }} />}
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
              {user?.role !== 'viewer' && <button className="btn-ghost" onClick={() => setDraftLibraryOpen(true)}>我的草稿</button>}
              {user?.role !== 'viewer' && <RecordIntake onCase={handleCreate} areaId={defaultWritableOperationalAreaId} scopes={writableAreaScopes} />}
            </div>
          </div>

          {contextError && <Alert type="error" showIcon message={contextError} />}
          {linkedCaseQuery.isError && <Alert type="warning" showIcon message="链接中的案件不存在或当前无权访问。" />}

          {/* 案件列表 + 详情分栏 */}
          <div className="cases-split">
            {/* 案件表格 */}
            <div className="card cases-table-card">
              {contextError ? <p role="status">筛选条件无效，已隐藏上次列表和计数；请修正条件后再查询。</p> : caseSearchError ? (
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
                      <th style={{ width: 150 }}>发现／案发时间</th>
                      <th>地点原文（角色见详情）</th>
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
                            <div>发现：{caseItem.discovered_at ? formatStoredTime(caseItem.discovered_at, 'MM-DD HH:mm', caseItem.time_timezone || 'Asia/Shanghai') : '未知'}</div>
                            <small>案发：{formatCaseTime(caseItem, 'MM-DD HH:mm')}</small>
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
                          <td>{renderQualityBadge(caseItem.quality_issues)}</td>
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
              {!contextError && !caseSearchError && !isLoading && (
                <div className="cases-pagination">
                  <Pagination
                    current={page}
                    pageSize={pageSize}
                    total={totalCases}
                    showSizeChanger
                    pageSizeOptions={[20, 50, 100, 200]}
                    showTotal={total => `共 ${total} 起 · 当前页 ${filteredCases.length} 起`}
                    onChange={(nextPage, size) => setSearchParams(previous => writeCaseListPosition(previous, size !== pageSize ? 1 : nextPage, size))}
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
                  <BusinessReturnLink />
                  <Link className="btn-ghost" to={`/assistant?caseId=${selectedCase.id}`}>以本条记录查历史参考（全部授权历史）</Link>
                  <CaseDossierPanel view="relations" active={dossierView}>
                  <nav className="case-context-links detail-section" aria-label="当前案件关联视图">
                    <Link to={caseContextPath(`/case-intelligence?caseId=${selectedCase.id}`, searchParams)}>历史关联与研判</Link>
                    <Link to={caseContextPath(`/cases/map?caseId=${selectedCase.id}`, searchParams)}>案件地图</Link>
                    <Link to={caseContextPath(`/graphs/evidence?caseId=${selectedCase.id}`, searchParams)}>证据图谱</Link>
                    <Link to={caseContextPath(`/assistant?caseId=${selectedCase.id}`, searchParams)}>带条件询问助手</Link>
                    <Link to={caseContextPath(`/topics?source=case&sourceId=${selectedCase.id}`, searchParams)}>持续关注资料变化</Link>
                    {unifiedResult && <Link to={caseContextPath(`/reports?resultId=${encodeURIComponent(unifiedResult.id)}`, searchParams)}>同版报告</Link>}
                  </nav>
                  {unifiedResult && <CaseResultMap result={unifiedResult} operationalAreaId={selectedCase.operational_area_id ?? undefined} />}
                  </CaseDossierPanel>
                  {(profileQuery.isError || processingQuery.isError || diagramQuery.isError || automationQuery.isError) && <Alert type="warning" showIcon
                    message="部分案件资料暂不可读，不能将其视为没有缺项。原始记录和可读成果仍可使用。" />}

                  <CaseDossierPanel view="overview" active={dossierView}>
                  <div className="detail-section">
                    <div className="ds-head">资料状态与报送</div>
                    <CaseQualityStatus quality={caseProfile?.quality}
                      readState={profileQuery.isError ? 'unavailable' : resultLoading ? 'loading' : 'ready'} />
                    <div className="detail-grid">
                      <div className="kv">
                        <span className="k">录入有效性</span>
                        <span className="v">{renderQualityBadge(profileQuery.isError || resultLoading ? undefined : caseProfile?.quality)}</span>
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
                          {feedbackDescription(selectedCase, 'police_reported')} · {feedbackDescription(selectedCase, 'case_filed')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <CaseAnalysisApplicability
                    value={workspace?.profile.data?.payload.analysis_applicability as AnalysisApplicability | undefined}
                    loading={resultLoading} error={!!resultError || workspace?.profile.status === 'unavailable'}
                    updating={workspace?.profile.status === 'updating'} />

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

                  <p className="detail-section">发现／查获：{selectedCase.discovered_at ? formatStoredTime(selectedCase.discovered_at, 'YYYY-MM-DD HH:mm', selectedCase.time_timezone || 'Asia/Shanghai') : '尚未掌握'}。实际案发：{formatCaseTime(selectedCase)}。油量记录：{formatOilVolume(selectedCase.oil_volume, selectedCase.oil_volume_unit)}。</p>
                  <CaseHistoryReferences caseId={selectedCase.id} revision={selectedCase.updated_at || workspace?.profile.data?.source_hash} compact />
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
                  <Link to={caseContextPath(`/reports?subject=case&subjectId=${selectedCase.id}`, searchParams)}>查看本案已有成果与材料</Link>
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
                        <span className="k">地点原文</span>
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
                    <button className="btn-primary" onClick={() => handleEdit(selectedCase)}>
                      编辑案件
                    </button>
                    <details><summary>高级研判</summary><button className="btn-ghost" onClick={handleStartRoundtable}>发起圆桌研判</button></details>
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
      <Modal title="我的私有草稿" open={draftLibraryOpen} onCancel={() => setDraftLibraryOpen(false)} footer={null} width={760} destroyOnClose>
        {draftLibraryOpen && <CaseDraftLibrary disabled={draftBusy || Boolean(submission) || draftSavePending} onRestore={id => void restoreDraft(id)} />}
      </Modal>
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
        okButtonProps={{ disabled: Boolean(submission) || draftBusy || draftSavePending || Boolean(editConflict) || Boolean(draftConflict) }}
        cancelButtonProps={{ disabled: savePreparing || saveMutation.isPending || draftBusy }}
        closable={!savePreparing && !saveMutation.isPending && !draftBusy}
        maskClosable={false}
        okText="保存案件"
        cancelText="取消"
        footer={origin => <><Button loading={draftBusy} disabled={Boolean(submission) || draftSavePending || savePreparing || Boolean(editConflict) || Boolean(draftConflict)}
          onClick={() => void persistDraft()}>立即暂存</Button>{origin}</>}
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
          footer:  { borderTop: '1px solid var(--line)' },
        }}
      >
        <p role="status" data-intake-state={entryState}>{({ editing: entryDirty ? '有新修改，正在等待自动暂存；未显示确认前请勿关闭页面。' : '填写后自动暂存到本人私有草稿。', saving_draft: '正在暂存，可继续填写…', submitting: '正在核对并保存正式记录…', outcome_unknown: '保存结果未确认，请核对原请求。', saved: '当前输入已暂存，尚未修改正式案件。', conflict: '存在版本差异，当前输入保留，请核对。' })[entryState]}</p>
        {saveFailure && <Alert type={submission ? 'warning' : 'error'} showIcon role="alert" message={saveFailure} />}
        {draftNotice && <Alert type="info" showIcon message={draftNotice} description={entryDirty ? '本次新修改尚未保存到草稿。' : '已保存内容可从“我的草稿”找回；尚未创建或修改正式案件。'} />}
        {draftFailure && <Alert type="warning" showIcon message={draftFailure} />}
        {draftSavePending && <div className="case-entry-actions">
          <Button loading={draftBusy} onClick={() => void checkDraftSave()}>核对草稿保存</Button>
          <Button disabled={draftBusy || Boolean(draftConflict)} onClick={() => void persistDraft()}>重试原草稿保存</Button>
        </div>}
        {editConflict && <CaseEditConflict key={`case:${editConflict.case.id}:${editConflict.source_revision}`}
          mine={serializeEntryValues(form.getFieldsValue(true))} latest={serializeEntryValues(editSnapshotValues(editConflict))} revision={editConflict.source_revision}
          onResolve={resolved => {
            form.resetFields(); form.setFieldsValue(restoreEntryValues(resolved)); setEditingCase(editConflict.case); setEditRevision(editConflict.source_revision)
            setHadIncidentLocations(editConflict.initial_locations.some(item => item.role === 'incident'))
            if (consumedDraftCaseId !== null) {
              setActiveDraft(null); setConsumedDraftCaseId(null); setDraftFailure(''); setDraftNotice('')
              draftSaveRef.current = null; setDraftSavePending(false); setDraftSubmissionConflictId(null)
            }
            setEditConflict(null); submissionRef.current = null; setSubmission(null); setSaveConflict(false); setSaveFailure('比较结果已写入表单，请核对后再保存。'); setEntryDirty(true)
          }} />}
        {saveConflict && !editConflict && submission?.caseId !== undefined && <Button onClick={() => void readEditConflict(submission.caseId!)}>读取最新案件进行比较</Button>}
        {draftSubmissionConflictId && !draftConflict && <Button onClick={() => void readSubmissionDraftConflict(draftSubmissionConflictId)}>读取最新草稿进行比较</Button>}
        {draftConflict && <CaseEditConflict key={`draft:${draftConflict.id}:${draftConflict.revision}`} kind="draft"
          mine={draftSaveRef.current?.payload.form_snapshot ?? intakeSnapshot()} latest={draftConflict.form_snapshot} revision={draftConflict.revision}
          onResolve={resolved => {
            form.resetFields(); form.setFieldsValue(restoreEntryValues(restoreIntakeDescription(resolved)))
            setLegacyAssistantText(String(resolved.assistant_text || '')); setAiIntakeSourceText(String(resolved.assistant_source_text || ''))
            manualFields.current = new Set(Array.isArray(resolved.manual_fields) ? resolved.manual_fields as string[] : [])
            setHadIncidentLocations(Boolean(resolved.had_incident_locations)); setEditRevision(draftConflict.base_case_revision)
            setActiveDraft(draftConflict); setDraftConflict(null); draftSaveRef.current = null; setDraftSavePending(false)
            if (draftSubmissionConflictId) { submissionRef.current = null; setSubmission(null); setSaveConflict(false); setSaveFailure(''); setDraftSubmissionConflictId(null) }
            setDraftFailure('比较结果仅在本页，核对后请再次保存草稿。'); setEntryDirty(true)
          }} />}
        {submission && <div style={{ marginTop: 12 }}>
          <p>本次输入已锁定，核对前不改写提交内容。{submission.caseId === undefined ? `提交凭证：${submission.key}` : `编辑案件 #${submission.caseId}`}</p>
          {(submission.caseId === undefined || submission.draftId) && <Button loading={saveMutation.isPending} onClick={() => void confirmSubmission(false)}>核对保存结果</Button>}
          <Button disabled={saveConflict || saveMutation.isPending} onClick={() => void confirmSubmission(true)}>{submission.caseId === undefined ? '使用原请求安全重试' : '将原输入重新保存到本案'}</Button>
        </div>}
        <Form form={form} layout="vertical" style={{ marginTop: 8 }} disabled={Boolean(submission) || savePreparing || (draftSavePending && !draftBusy) || Boolean(editConflict) || Boolean(draftConflict)} onValuesChange={changes => { onManualChange(changes); if (!draftSaveRef.current) setDraftFailure('') }}>
          <div className="cases-ai-assistant">
            <div className="cases-ai-assistant__head">
              <div>
                <span><ApiOutlined /> 文字辅助录入</span>
                <small>{structureMutation.data?.ai_intake_boundary || '先粘贴原始案情，系统只生成候选字段，提交前仍由人工确认。'}</small>
              </div>
              <b>
                {structureMutation.data
                  ? intakeCapabilityLabel(structureMutation.data.model_status)
                  : '规则可用，模型状态以实际提取结果为准'}
              </b>
            </div>
            <Form.Item name="description" label="简要经过／原始记录（只写已掌握内容）">
              <TextArea rows={5} placeholder="填写或粘贴已掌握的时间、地点、简要经过和本单位处置。一份原文用于正式记录和辅助提取，未知情况不用补造。" />
            </Form.Item>
            {legacyAssistantText && legacyAssistantText !== form.getFieldValue('description') && <details><summary>旧草稿保留的辅助原文</summary><p style={{ whiteSpace: 'pre-wrap' }}>{legacyAssistantText}</p><small>保留历史输入，不替换上方原始记录；需要时自行核对合并。</small></details>}
            <div className="cases-ai-assistant__actions">
              <Button
                type="primary"
                icon={<ApiOutlined />}
                loading={structureMutation.isPending}
                disabled={draftBusy || draftSavePending}
                onClick={handleRunAiIntake}
              >
                从原文提取候选字段
              </Button>
              <span>{structureMutation.isSuccess ? '仅补齐空白；已有内容和人工清空项保持不变。' : '提取不保存正式案件，手工录入无需模型。'}</span>
            </div>

            {intakeConflicts.length > 0 && <section aria-label="提取差异"><Alert type="info" showIcon message={`${intakeConflicts.length} 项候选与当前填写不同，已保留当前内容`} />
              <ul>{intakeConflicts.map(item => <li key={item.field}>
                <strong>{structureMutation.data?.candidates?.find(candidate => candidate.field === item.field)?.label || item.field}</strong>：当前 {formatAiIntakeValue(item.current)}；候选 {formatAiIntakeValue(item.proposed)}。
              </li>)}</ul><small>如原文支持候选，可直接修改对应字段；不会自动覆盖。</small></section>}

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
                      <small>{intakeEvidenceLabel(structureMutation.data!, item.field)}</small>
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

          <Form.Item name="location" label="本次记录的地点原文">
            <Input placeholder="如：××道路附近；角色或精确位置不明可保留原文" />
          </Form.Item>
          <Form.Item name="entry_location_role" label="这处地点在本次记录中的角色" initialValue="unknown" dependencies={['latitude', 'longitude']}
            rules={[({ getFieldValue }) => ({ validator(_, role) {
              const latitude = getFieldValue('latitude'); const longitude = getFieldValue('longitude')
              const hasLatitude = latitude !== undefined && latitude !== null; const hasLongitude = longitude !== undefined && longitude !== null
              if (hasLatitude !== hasLongitude) return Promise.reject(new Error('已填写坐标时，请同时核对经纬度；未知可都留空'))
              if (!editingCase && hasLatitude && (!role || role === 'unknown')) return Promise.reject(new Error('已填写坐标，请明确地点角色后保存，不能默认为案发地点'))
              return Promise.resolve()
            } })]}
            extra={editingCase ? '原有地点明细保持原样。明确选择角色后新增对应地点记录；不会将旧地图点自动解释为案发点。' : '未明确时保留为原文提及；发现地点不会自动作为盗取地点。'}>
            <Select options={[{ value: 'unknown', label: '尚不明确' }, ...Object.entries(locationRoleLabels).map(([value, label]) => ({ value, label }))]} />
          </Form.Item>

          <Form.Item noStyle shouldUpdate={(before, after) => before.operational_area_id !== after.operational_area_id}>
            {({ getFieldValue }) => <CaseFacilityPicker key={`${user?.id}:${sessionEpoch}:${getFieldValue('operational_area_id')}`}
              areaId={editingCase?.operational_area_id ?? getFieldValue('operational_area_id') ?? defaultWritableOperationalAreaId}
              disabled={Boolean(submission) || savePreparing || draftBusy || draftSavePending || Boolean(editConflict) || Boolean(draftConflict)}
              onApply={patch => {
                if (submissionRef.current || saveBusy.current || draftSaveRef.current || draftBusy || editConflict || draftConflict) return
                if (patch.latitude !== undefined && form.getFieldValue('entry_location_role') !== 'discovery' && (form.getFieldValue('initial_locations') || []).some((row: { role?: string }) => row.role === 'incident')) {
                  message.warning('本案已有案发地点明细，主地图点由明细决定。请在“补充地点角色”中核对修改，本次未替换地点或坐标。')
                  return
                }
                const conflicts = Object.entries(patch).some(([field, value]) => { const current = form.getFieldValue(field); return current !== undefined && current !== null && current !== '' && current !== value })
                if (conflicts && !window.confirm('这将替换表单中的地点或坐标，请确认与本案原文一致。继续复用吗？')) return
                form.setFieldsValue(patch); setEntryDirty(true)
                if (patch.latitude !== undefined) setShowMapPicker(true)
              }} />}
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
                    核对地点坐标（可选，不代表盗取来源）
                    {latitude != null && longitude != null && (
                      <span>{Number(latitude).toFixed(5)}, {Number(longitude).toFixed(5)}</span>
                    )}
                  </div>

                  {showMapPicker && (
                    <div className="cases-map-entry">
                      <p>请先核对上方地点角色。角色未知的新地点只保留文字，不发布为精确点；编辑旧记录不会自动重解释原坐标。</p>
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
                            if (!submissionRef.current && !saveBusy.current && !draftSaveRef.current && !draftBusy && !editConflict && !draftConflict) { setFieldsValue({ latitude: lat, longitude: lng }); setEntryDirty(true) }
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

          <section aria-label="本单位已知处置">
            <h4>本单位处置与移交（按已掌握情况填写）</h4>
            <Form.Item name="vehicle_handling" label="车辆处置"><Input placeholder="如：移交公安、扣押停放；未掌握可留空" /></Form.Item>
            <Form.Item name="person_handling" label="人员处置"><Input placeholder="如：移交公安、教育放行；不等同于公安后续处理" /></Form.Item>
            <Form.Item name="oil_handling" label="油品处置"><Input placeholder="如：移交公安、检斤入库、暂存；与查获量分别记录" /></Form.Item>
          </section>

          <details className="case-entry-section"><summary>已掌握的人员、车辆及处置资料（按需）</summary><CaseEntryPrecheck
            form={form}
            onBonusVehicleScopeChange={handleBonusVehicleScopeChange}
            onBonusPersonScopeChange={handleBonusPersonScopeChange}
          /></details>
          <CaseSourceCollections locationsEnabled={sourceCollectionsLoaded.locations} measurementsEnabled={sourceCollectionsLoaded.measurements} />
          {qualityPreviewMutation.data && <CaseQualityStatus quality={qualityPreviewMutation.data} />}

          <details className="case-entry-section"><summary>报送、办理与业务管理字段（按需）</summary>

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

          <CaseFeedbackFields form={form} />
          <Row gutter={12}>
            <Col xs={24} sm={12}>
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
          </details>

          {/* 高级涉油特征折叠区域 */}
          <details className="case-entry-section" open={showAdvancedFields} onToggle={event => setShowAdvancedFields(event.currentTarget.open)}>
            <summary>涉油案件特征（高级，可选）</summary>
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

            </div>
          </details>
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
        <details className="case-entry-section" open={recentImportsOpen} onToggle={event => setRecentImportsOpen(event.currentTarget.open)}>
          <summary>最近导入批次，找回并续做</summary>
          {recentImportsOpen && <CaseRecentImports disabled={importCorrectionBusy || importMutation.isPending || previewImportMutation.isPending}
            onOpen={batch => void openRecentImport(batch)} />}
        </details>
        <p className="cases-import-hint">
          案情描述必填；时间、地点和其他信息不知道可以留空。支持中文表头和英文字段名。
        </p>
        <p className="cases-import-hint">
          可选：案发地点、经度、纬度、案件类型等。单次最多 1000 条；无法识别的列会列出提示。
        </p>
        <label style={{ display: 'block', marginBottom: 14 }}>台账格式
          <Select aria-label="案件台账格式" style={{ width: '100%' }} value={importPreset ?? 'general'}
            disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
            options={[{ value: 'general', label: '通用案件表' }, { value: 'security_ledger', label: '保卫案件年度台账（标题、年月日、两列备注）' }]}
            onChange={value => {
              setImportPreset(value === 'security_ledger' ? value : null)
              setImportHeaderRow(value === 'security_ledger' ? 3 : 1)
              setImportFieldMapping({}); setImportSourceKey(''); setImportSourceRevision(''); setImportPreview(null)
            }} />
        </label>
        {importPreset === 'security_ledger' && <Alert type="info" showIcon message="保留原始台账，不替来源作判断"
          description="首列备注作为案情原文；其余备注、无表头补充及统计列逐行留作来源。系统案件类型与联动方式分开，回收量不当损失量，台账年月日不自动认作案发时间。.et 请先在 WPS 中另存为 .xlsx。" />}
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
          settings={{ import_preset: importPreset, worksheet: importWorksheet, header_row: importHeaderRow, time_zone: importTimeZone, field_mapping: importFieldMapping, source_key: importSourceKey, source_revision: importSourceRevision }}
          disabled={previewImportMutation.isPending || importMutation.isPending}
          onChange={applyImportConfiguration} onBusyChange={setImportCorrectionBusy} />}
        <CaseClipboardImport disabled={previewImportMutation.isPending || importMutation.isPending || importCorrectionBusy}
          onSelect={file => { setSelectedImportFile(file); setImportWorksheet(''); setImportHeaderRow(1); setImportPreset(null); setImportFieldMapping({}); setImportPreview(null) }} />
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
                message={importPreview.replayed ? `已恢复原批次回执，本次新增 0 条` : `本批新增 ${importPreview.created} 条、更正 ${importPreview.updated ?? 0} 条案件`}
                description={`批次 ${importPreview.batch_id ?? '—'}。相同文件和设置重传不会重复建案；可直接修正下面的失败行。`} />
            )}
            {!!importPreview.table?.ignored_headers.length && (
              <Alert type="warning" showIcon message={importPreview.table.import_preset === 'security_ledger' ? '以下列仅保留来源原值，不映射为案件事实' : '以下列未映射业务字段'}
                description={importPreview.table.ignored_headers.join('、')} />
            )}
            {!!importPreview.table?.warnings?.length && <Alert type="info" showIcon message="导入口径提示"
              description={<ul>{importPreview.table.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>} />}
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
              onCorrected={applyImportReceipt} onDirtyChange={setImportCorrectionDirty} />}
            {(importPreview.preview?.length ?? 0) > 0 && (
              <div className="cases-import-rows">
                {importPreview.preview!.slice(0, 20).map((row, idx) => (
                  <div key={idx} className="cases-import-row">
                    {typeof row.action === 'string' && <strong>{({ created: '新增', unchanged: '未变化', update: '来源更正', updated: '来源更正', failed: '格式待修', conflict: '冲突待核' } as Record<string, string>)[row.action] || row.action}</strong>}
                    {importPreviewCells(row).map(({ key, label, value }) => (
                      <span key={key}>
                        <b>{label}</b>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '未知')}
                      </span>
                    ))}
                    {Array.isArray(row.warnings) && row.warnings.length > 0 && <ul>{row.warnings.filter((warning): warning is string => typeof warning === 'string')
                      .map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
                    {row.differences != null && <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(row.differences, null, 2)}</pre>}
                  </div>
                ))}
                {importPreview.preview!.length > 20 && <p>这里只展示前 20 条预览，全部行仍按来源和权限校验，失败行见完整错误回执。</p>}
              </div>
            )}
          </div>
        )}
      </Modal>

    </div>
  )
}

export default function Cases() {
  const { user, sessionEpoch } = useAuth()
  // A changed principal/session must never inherit another user's form or late requests.
  return <CaseWorkspace key={`${user?.id ?? 'anonymous'}:${sessionEpoch}`} />
}
