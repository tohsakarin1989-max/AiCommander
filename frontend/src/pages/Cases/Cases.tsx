import { useEffect, useState, useMemo } from 'react'
import {
  Button,
  Modal,
  Form,
  Input,
  DatePicker,
  InputNumber,
  message,
  Popconfirm,
  Upload,
  Alert,
  Select,
  Row,
  Col,
  Switch,
} from 'antd'
import {
  EditOutlined,
  DeleteOutlined,
  ApiOutlined,
  EnvironmentOutlined,
  NodeIndexOutlined,
  DatabaseOutlined,
  DownOutlined,
  UpOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { caseApi, type CaseImportResult } from '../../services/cases'
import type { BonusAssessment, Case, CaseAutomationWorkbench, CaseCreate } from '../../types'
import type { ChainLink } from '../../types'
import { useNavigate, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import MapPicker from '../../components/Map/MapPicker'
import { chainPositionMeta, getChainPosition } from '../../utils/chainType'
import { bonusAccountingEnabled } from '../../config/features'
import { buildCaseEntryReadiness } from './caseEntryReadiness'
import './Cases.css'

const { TextArea } = Input
const { RangePicker } = DatePicker
const { Option } = Select

// 搜索筛选参数接口
interface SearchFilters {
  keyword?: string
  status?: string
  case_type?: string
  oil_type?: string
  start_date?: string
  end_date?: string
  has_geo?: boolean
}

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

const qualityColor: Record<string, string> = {
  high: 'var(--ok)',
  medium: 'var(--warn)',
  low: 'var(--err)',
}

const qualityLabel: Record<string, string> = {
  high: '信息完整',
  medium: '需补充',
  low: '缺项较多',
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
}

const defaultFilterState: FilterState = {
  statuses: ['pending', 'processing', 'completed', 'resolved'],
  caseTypes: [],
  oilTypes: [],
  startDate: '',
  endDate: '',
}

const Cases: React.FC = () => {
  const [form] = Form.useForm()
  const [evidenceForm] = Form.useForm()
  const [searchForm] = Form.useForm()
  const watchedLat = Form.useWatch('latitude', form)
  const watchedLng = Form.useWatch('longitude', form)
  const watchedLocation = Form.useWatch('location', form)
  const watchedCaseType = Form.useWatch('case_type', form)
  const watchedDescription = Form.useWatch('description', form)
  const watchedVehicleHandling = Form.useWatch('vehicle_handling', form)
  const watchedPersonHandling = Form.useWatch('person_handling', form)
  const watchedInitialVehicles = Form.useWatch('initial_vehicles', form)
  const watchedInitialPersons = Form.useWatch('initial_persons', form)
  const watchedBonusHasVehicle = Form.useWatch('bonus_has_vehicle', form)
  const watchedBonusHasPerson = Form.useWatch('bonus_has_person', form)
  const watchedBonusHasOil = Form.useWatch('bonus_has_oil', form)
  const watchedBonusHasPolice = Form.useWatch('bonus_has_police', form)
  const watchedOilNature = Form.useWatch('oil_nature', form)
  const watchedOilVolume = Form.useWatch('oil_volume', form)
  const watchedWaterCut = Form.useWatch('water_cut', form)
  const watchedOilHandling = Form.useWatch('oil_handling', form)
  const watchedPoliceReported = Form.useWatch('police_reported', form)
  const watchedCaseFiled = Form.useWatch('case_filed', form)
  const watchedPoliceOfficer = Form.useWatch('police_officer', form)
  const watchedPolicePhone = Form.useWatch('police_phone', form)
  const [isModalVisible, setIsModalVisible] = useState(false)
  const [editingCase, setEditingCase] = useState<Case | null>(null)
  const [selectedCase, setSelectedCase] = useState<Case | null>(null)
  const [importModalVisible, setImportModalVisible] = useState(false)
  const [selectedImportFile, setSelectedImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<CaseImportResult | null>(null)
  const [evidenceModalVisible, setEvidenceModalVisible] = useState(false)
  const [locationModalVisible, setLocationModalVisible] = useState(false)
  const [activeLocationCaseId, setActiveLocationCaseId] = useState<number | null>(null)
  const [locationDraft, setLocationDraft] = useState<{ latitude?: number; longitude?: number }>({})
  const [showAdvancedFields, setShowAdvancedFields] = useState(false)
  const [filters, setFilters] = useState<SearchFilters>({})
  const [keyword, setKeyword] = useState('')
  const [sidebarFilter, setSidebarFilter] = useState<FilterState>(defaultFilterState)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 构建查询参数
  const queryParams = useMemo(() => {
    const params: Record<string, string | boolean> = {}
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.status) params.status = filters.status
    if (filters.case_type) params.case_type = filters.case_type
    if (filters.oil_type) params.oil_type = filters.oil_type
    if (filters.start_date) params.start_date = filters.start_date
    if (filters.end_date) params.end_date = filters.end_date
    if (filters.has_geo !== undefined) params.has_geo = filters.has_geo
    return params
  }, [filters])

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases', queryParams],
    queryFn: () => caseApi.getCases(queryParams),
  })

  const renderQualityBadge = (caseItem: Case) => {
    if (caseItem.quality_score == null) {
      return <span style={{ color: 'var(--ink-3)' }}>—</span>
    }
    const level = caseItem.quality_level || 'low'
    return (
      <span
        className="tag"
        style={{ '--tag-c': qualityColor[level] || 'var(--warn)' } as React.CSSProperties}
        title={caseItem.quality_issues?.recommendations?.[0]}
      >
        {Math.round(caseItem.quality_score)} · {qualityLabel[level] || level}
      </span>
    )
  }

  // 案件类型和油品类型（用于侧边栏过滤选项）
  const caseTypes = useMemo(() => {
    const types = new Set<string>()
    cases?.forEach(c => c.case_type && types.add(c.case_type))
    return Array.from(types)
  }, [cases])

  const oilTypes = useMemo(() => {
    const types = new Set<string>()
    cases?.forEach(c => c.oil_type && types.add(c.oil_type))
    return Array.from(types)
  }, [cases])

  const caseEntryReadiness = useMemo(() => buildCaseEntryReadiness({
    latitude: watchedLat,
    longitude: watchedLng,
    location: watchedLocation,
    case_type: watchedCaseType,
    bonus_has_vehicle: Boolean(watchedBonusHasVehicle),
    bonus_has_person: Boolean(watchedBonusHasPerson),
    bonus_has_oil: Boolean(watchedBonusHasOil),
    bonus_has_police: Boolean(watchedBonusHasPolice),
    description: watchedDescription,
    vehicle_handling: watchedVehicleHandling,
    person_handling: watchedPersonHandling,
    oil_nature: watchedOilNature,
    oil_volume: watchedOilVolume,
    water_cut: watchedWaterCut,
    oil_handling: watchedOilHandling,
    police_reported: watchedPoliceReported,
    case_filed: watchedCaseFiled,
    police_officer: watchedPoliceOfficer,
    police_phone: watchedPolicePhone,
    initial_vehicles: watchedInitialVehicles,
    initial_persons: watchedInitialPersons,
  }), [
    watchedLat,
    watchedLng,
    watchedLocation,
    watchedCaseType,
    watchedBonusHasVehicle,
    watchedBonusHasPerson,
    watchedBonusHasOil,
    watchedBonusHasPolice,
    watchedDescription,
    watchedVehicleHandling,
    watchedPersonHandling,
    watchedOilNature,
    watchedOilVolume,
    watchedWaterCut,
    watchedOilHandling,
    watchedPoliceReported,
    watchedCaseFiled,
    watchedPoliceOfficer,
    watchedPolicePhone,
    watchedInitialVehicles,
    watchedInitialPersons,
  ])

  const readinessAttentionCount = caseEntryReadiness.filter(item => item.status === 'attention').length
  const readinessReadyCount = caseEntryReadiness.filter(item => item.status === 'ready').length

  // 侧边栏过滤后的案件列表
  const filteredCases = useMemo(() => {
    if (!cases) return []
    return cases.filter(c => {
      // 状态过滤
      if (sidebarFilter.statuses.length > 0 && !sidebarFilter.statuses.includes(c.status)) return false
      // 案件类型过滤
      if (sidebarFilter.caseTypes.length > 0 && c.case_type && !sidebarFilter.caseTypes.includes(c.case_type)) return false
      // 油品类型过滤
      if (sidebarFilter.oilTypes.length > 0 && c.oil_type && !sidebarFilter.oilTypes.includes(c.oil_type)) return false
      // 关键词过滤
      if (keyword) {
        const kw = keyword.toLowerCase()
        const matchField = (val?: string | null) => val?.toLowerCase().includes(kw)
        if (!matchField(c.case_number) && !matchField(c.location) && !matchField(c.description) && !matchField(c.case_type)) return false
      }
      return true
    })
  }, [cases, sidebarFilter, keyword])

  useEffect(() => {
    const caseIdFromUrl = searchParams.get('caseId')
    if (!caseIdFromUrl || !cases) return
    const targetId = parseInt(caseIdFromUrl, 10)
    if (!Number.isNaN(targetId)) {
      const found = cases.find(c => c.id === targetId)
      if (found) setSelectedCase(found)
    }
  }, [searchParams, cases])

  const { data: preprocessStatus } = useQuery({
    queryKey: ['preprocess-status'],
    queryFn: () => caseApi.getPreprocessStatus(),
    refetchInterval: 5000,
  })

  const { data: bonusAssessment } = useQuery({
    queryKey: ['case-bonus-assessment', selectedCase?.id],
    queryFn: () => caseApi.getBonusAssessment(selectedCase!.id),
    enabled: bonusAccountingEnabled && !!selectedCase,
  })

  const { data: automationWorkbench } = useQuery({
    queryKey: ['case-automation-workbench', selectedCase?.id],
    queryFn: () => caseApi.getAutomationWorkbench(selectedCase!.id),
    enabled: !!selectedCase,
  })

  const { data: caseEvidence } = useQuery({
    queryKey: ['case-evidence', selectedCase?.id],
    queryFn: () => caseApi.getCaseEvidence(selectedCase!.id),
    enabled: !!selectedCase,
  })

  const { data: chainLinks } = useQuery({
    queryKey: ['case-chain-links', selectedCase?.id],
    queryFn: () => caseApi.getChainLinks(selectedCase!.id),
    enabled: !!selectedCase,
  })

  const { data: missingLocationCases, isLoading: missingLocationLoading } = useQuery({
    queryKey: ['cases-missing-location'],
    queryFn: () => caseApi.getCases({ missing_location: true, limit: 500 }),
    enabled: locationModalVisible,
  })

  useEffect(() => {
    if (!locationModalVisible || !missingLocationCases?.length || activeLocationCaseId) return
    setActiveLocationCaseId(missingLocationCases[0].id)
  }, [locationModalVisible, missingLocationCases, activeLocationCaseId])

  const createMutation = useMutation({
    mutationFn: caseApi.createCase,
    onSuccess: () => {
      message.success('创建成功')
      setIsModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Case> }) =>
      caseApi.updateCase(id, data),
    onSuccess: () => {
      message.success('更新成功')
      setIsModalVisible(false)
      setEditingCase(null)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['case-bonus-assessment'] })
      queryClient.invalidateQueries({ queryKey: ['case-automation-workbench'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: caseApi.deleteCase,
    onSuccess: () => {
      message.success('删除成功')
      setSelectedCase(null)
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  const preprocessMutation = useMutation({
    mutationFn: caseApi.preprocessCase,
    onSuccess: (data) => {
      message.success(data.message || '预处理任务已提交')
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`预处理失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const structureMutation = useMutation({
    mutationFn: (text: string) => caseApi.structureCaseText(text),
    onSuccess: (data) => {
      const patch = { ...data.case_fields } as Record<string, unknown>
      if (typeof patch.occurred_time === 'string') {
        patch.occurred_time = dayjs(patch.occurred_time)
      }
      form.setFieldsValue(patch)
      setShowAdvancedFields(true)
      message.success(`已提取 ${Object.keys(data.case_fields).length} 个字段`)
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`自动提取失败: ${err.response?.data?.detail || err.message}`)
    },
  })

  const createEvidenceMutation = useMutation({
    mutationFn: (data: { title?: string; file_path?: string; notes?: string }) =>
      caseApi.createCaseEvidence(selectedCase!.id, data),
    onSuccess: async () => {
      message.success('材料已归档')
      setEvidenceModalVisible(false)
      evidenceForm.resetFields()
      await queryClient.invalidateQueries({ queryKey: ['case-evidence', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-bonus-assessment', selectedCase?.id] })
      await queryClient.invalidateQueries({ queryKey: ['case-automation-workbench', selectedCase?.id] })
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
      const remaining = (missingLocationCases || []).filter(item => item.id !== variables.id)
      const nextCase = remaining[0]
      setActiveLocationCaseId(nextCase?.id ?? null)
      setLocationDraft({})
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
      await queryClient.invalidateQueries({ queryKey: ['cases-missing-location'] })
      await queryClient.invalidateQueries({ queryKey: ['chain-map-data'] })
      await queryClient.invalidateQueries({ queryKey: ['case-chain-links'] })
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
    mutationFn: (file: File) => caseApi.previewImportCases(file),
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
    mutationFn: (file: File) => caseApi.importCases(file),
    onSuccess: async (data) => {
      message.success(`导入成功：共 ${data.total} 条，成功 ${data.created} 条`)
      if (data.errors && data.errors.length) {
        message.warning('部分记录导入失败，详情请查看控制台')
        // eslint-disable-next-line no-console
        console.warn('导入错误详情：', data.errors)
      }
      setImportModalVisible(false)
      setSelectedImportFile(null)
      setImportPreview(null)
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: Error) => {
      message.error(`导入失败：${error.message}`)
    },
  })

  const resetImportState = () => {
    setImportModalVisible(false)
    setSelectedImportFile(null)
    setImportPreview(null)
    previewImportMutation.reset()
    importMutation.reset()
  }

  const handleCreate = () => {
    setEditingCase(null)
    form.resetFields()
    setShowAdvancedFields(false)
    setIsModalVisible(true)
  }

  const handleEdit = (caseItem: Case) => {
    setEditingCase(caseItem)
    form.setFieldsValue({
      ...caseItem,
      occurred_time: dayjs(caseItem.occurred_time),
      report_time: caseItem.report_time ? dayjs(caseItem.report_time) : undefined,
    })
    setIsModalVisible(true)
  }

  const handleBonusVehicleScopeChange = (checked: boolean) => {
    const rows = form.getFieldValue('initial_vehicles')
    form.setFieldsValue({
      bonus_has_vehicle: checked,
      initial_vehicles: checked ? (Array.isArray(rows) && rows.length ? rows : [{}]) : [],
    })
  }

  const handleBonusPersonScopeChange = (checked: boolean) => {
    const rows = form.getFieldValue('initial_persons')
    form.setFieldsValue({
      bonus_has_person: checked,
      initial_persons: checked ? (Array.isArray(rows) && rows.length ? rows : [{}]) : [],
    })
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingCase) {
        updateMutation.mutate({
          id: editingCase.id,
          data: {
            ...values,
            occurred_time: values.occurred_time?.toISOString(),
            report_time: values.report_time?.toISOString(),
          },
        })
      } else {
        createMutation.mutate({
          ...values,
          occurred_time: values.occurred_time?.toISOString(),
          report_time: values.report_time?.toISOString(),
        } as CaseCreate)
      }
    } catch (error) {
      console.error('Validation failed:', error)
    }
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
    const newFilters: SearchFilters = {}
    if (keyword) newFilters.keyword = keyword
    if (sidebarFilter.startDate) newFilters.start_date = sidebarFilter.startDate
    if (sidebarFilter.endDate) newFilters.end_date = sidebarFilter.endDate
    setFilters(newFilters)
  }

  const resetFilters = () => {
    setSidebarFilter(defaultFilterState)
    setKeyword('')
    setFilters({})
    searchForm.resetFields()
  }

  // 统计各状态数量
  const statusCount = useMemo(() => {
    const count: Record<string, number> = {}
    cases?.forEach(c => {
      count[c.status] = (count[c.status] || 0) + 1
    })
    return count
  }, [cases])

  const caseTypeCount = useMemo(() => {
    const count: Record<string, number> = {}
    cases?.forEach(c => {
      if (c.case_type) count[c.case_type] = (count[c.case_type] || 0) + 1
    })
    return count
  }, [cases])

  const oilTypeCount = useMemo(() => {
    const count: Record<string, number> = {}
    cases?.forEach(c => {
      if (c.oil_type) count[c.oil_type] = (count[c.oil_type] || 0) + 1
    })
    return count
  }, [cases])

  // 发起圆桌分析
  const handleStartRoundtable = () => {
    if (!selectedCase) return
    navigate(`/meetings/new?caseId=${selectedCase.id}`)
  }

  // 派遣巡逻
  const handleDispatchPatrol = () => {
    if (!selectedCase) return
    navigate(`/patrols?caseId=${selectedCase.id}`)
  }

  const handleStructureFromDescription = () => {
    const text = form.getFieldValue('description')
    if (!text || !String(text).trim()) {
      message.warning('请先填写案情描述')
      return
    }
    structureMutation.mutate(String(text))
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
    const statusLabel = link.status === 'confirmed' ? '已确认' : '待确认'
    return (
      <div key={link.id} className={`chain-link-card chain-link-card--${link.status}`}>
        <div className="chain-link-card__main">
          <b>{related?.case_number || `案件 ${direction === 'upstream' ? link.case_id_a : link.case_id_b}`}</b>
          <span>{related?.chain_label || '未知环节'} · {related?.location || '未标注地点'}</span>
          <small>
            距离 {link.distance_km.toFixed(1)} km · 时间差 {link.time_diff_days} 天 · 置信度 {Math.round(link.confidence * 100)}%
          </small>
          {link.reasoning && <p>{link.reasoning}</p>}
        </div>
        <div className="chain-link-card__side">
          <span>{statusLabel}</span>
          {link.status === 'inferred' && (
            <div>
              <Button
                size="small"
                type="primary"
                loading={confirmChainMutation.isPending}
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
    return (
      <div className="chain-panel">
        <div className="chain-panel__summary">
          {renderChainPositionTag(selectedCase)}
          <span>{hasLinks ? `发现 ${upstreamLinks.length + downstreamLinks.length} 条上下游关联` : '暂无链条推断'}</span>
        </div>
        <p className="chain-panel__boundary">链条关联是系统基于环节、距离和时间生成的辅助假设，确认前不作为定案依据。</p>
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

  const renderAutomationPanel = (workbench?: CaseAutomationWorkbench) => {
    const assessment = bonusAccountingEnabled ? (workbench?.bonus_assessment || bonusAssessment) : undefined
    const gate = assessment?.material_gate
    const total = assessment?.total_suggested_amount ?? 0
    const primarySquad = assessment?.primary_squad || selectedCase?.report_unit || '未选择'
    const moduleByKey = new Map((workbench?.modules || []).map(item => [item.key, item]))
    const conclusion = moduleByKey.get('conclusion_layering')
    const card = moduleByKey.get('experience_card')
    const gap = moduleByKey.get('gap_closure')
    const actions = workbench?.gap_closure.actions || []
    return (
      <div className="cases-automation-panel">
        <div className="cases-automation-head">
          <span>案件自动化</span>
          <b>{selectedCase ? selectedCase.case_number : '待选择案件'}</b>
        </div>
        <div className="cases-automation-metrics">
          <div>
            <span>主控班组</span>
            <b>{primarySquad}</b>
          </div>
          <div>
            <span>佐证材料</span>
            <b>{gate ? `${gate.satisfied_count}/${gate.required_count}` : `${workbench?.gap_closure.material_gaps.length || 0} 缺口`}</b>
          </div>
          <div>
            <span>{bonusAccountingEnabled ? '奖金测算' : '研判复核'}</span>
            <b>{bonusAccountingEnabled ? `¥${total.toLocaleString()}` : (workbench?.ready_for_human_review ? '可复核' : '需补充')}</b>
          </div>
        </div>
        <div className="cases-automation-actions">
          <Button size="small" icon={<ApiOutlined />} onClick={handleCreate}>
            录入提取
          </Button>
          <Button
            size="small"
            icon={<DatabaseOutlined />}
            disabled={!selectedCase}
            onClick={() => setEvidenceModalVisible(true)}
          >
            材料归档
          </Button>
          {bonusAccountingEnabled && (
            <Button
              size="small"
              icon={<NodeIndexOutlined />}
              disabled={!selectedCase}
              onClick={() => document.querySelector('.case-detail')?.scrollTo({ top: 0, behavior: 'smooth' })}
            >
              奖金测算
            </Button>
          )}
        </div>
        <div className="cases-automation-modules">
          <div className={`cases-automation-module cases-automation-module--${conclusion?.status || 'idle'}`}>
            <span>4 结论分层</span>
            <b>
              事实 {workbench?.conclusion_layering.facts.length || 0} · 推断 {workbench?.conclusion_layering.inferences.length || 0}
            </b>
            <small>建议 {workbench?.conclusion_layering.suggestions.length || 0} · 缺口 {workbench?.conclusion_layering.information_gaps.length || 0}</small>
          </div>
          <div className={`cases-automation-module cases-automation-module--${card?.status || 'idle'}`}>
            <span>5 经验卡</span>
            <b>经验 {workbench?.experience_card.reusable_lessons.length || 0}</b>
            <small>{workbench?.experience_card.how_it_was_found?.[0] || '选择案件后自动沉淀'}</small>
          </div>
          <div className={`cases-automation-module cases-automation-module--${gap?.status || 'idle'}`}>
            <span>6 缺口闭环</span>
            <b>待办 {actions.length}</b>
            <small>{actions[0]?.title || '材料和信息缺口会自动汇总'}</small>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page page-cases">
      {/* 预处理状态提醒 */}
      {preprocessStatus && (
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
            应用筛选 ({filteredCases.length})
          </button>
          <button className="btn-ghost" onClick={resetFilters}>重置</button>
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
              <button className="btn-primary" onClick={handleCreate}>
                ＋ 新建案件
              </button>
            </div>
          </div>

          {renderAutomationPanel(automationWorkbench)}

          {/* 案件列表 + 详情分栏 */}
          <div className="cases-split">
            {/* 案件表格 */}
            <div className="card cases-table-card">
              {isLoading ? (
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
                          onClick={() => setSelectedCase(caseItem)}
                        >
                          <td>
                            <span className="cno">{caseItem.case_number || `#${caseItem.id}`}</span>
                          </td>
                          <td className="time">
                            {dayjs(caseItem.occurred_time).format('MM-DD HH:mm')}
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
                              <button
                                className="cases-act-btn"
                                title="预处理"
                                onClick={() => preprocessMutation.mutate(caseItem.id)}
                              >
                                <ApiOutlined />
                              </button>
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
            </div>

            {/* 案件详情面板 */}
            <aside className="case-detail">
              {selectedCase ? (
                <>
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

                  <div className="detail-section">
                    <div className="ds-head">信息质量与报送</div>
                    <div className="detail-grid">
                      <div className="kv">
                        <span className="k">质量评分</span>
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
                    {selectedCase.quality_issues?.missing_required?.length ? (
                      <p className="narr" style={{ color: 'var(--warn)' }}>
                        缺项：{selectedCase.quality_issues.missing_required.slice(0, 4).map(i => i.label).join('、')}
                      </p>
                    ) : null}
                  </div>

                  {bonusAccountingEnabled && (
                    <div className="detail-section">
                      <div className="ds-head">奖金考核测算</div>
                      {renderBonusAssessment(bonusAssessment)}
                    </div>
                  )}

                  {automationWorkbench && (
                    <div className="detail-section">
                      <div className="ds-head">AI 自动化复盘</div>
                      <div className="automation-456-list">
                        <div>
                          <b>结论分层</b>
                          <span>
                            事实 {automationWorkbench.conclusion_layering.facts.length}，推断 {automationWorkbench.conclusion_layering.inferences.length}，建议 {automationWorkbench.conclusion_layering.suggestions.length}
                          </span>
                        </div>
                        <div>
                          <b>经验卡</b>
                          <span>{automationWorkbench.experience_card.reusable_lessons[0] || automationWorkbench.experience_card.why_it_matters[0] || '待补充更多案件信息'}</span>
                        </div>
                        <div>
                          <b>缺口闭环</b>
                          <span>{automationWorkbench.gap_closure.actions[0]?.title || '暂无待补缺口'}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="detail-section">
                    <div className="ds-head">链条关联</div>
                    {renderChainPanel(chainLinks)}
                  </div>

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

                  {/* 关键信息 */}
                  <div className="detail-grid">
                    <div className="kv">
                      <span className="k">案发时间</span>
                      <span className="v">{dayjs(selectedCase.occurred_time).format('YYYY-MM-DD HH:mm')}</span>
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
                          {selectedCase.oil_volume} 吨
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
                        <span className="v" style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
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

                  {/* 底部操作 */}
                  <div className="detail-actions">
                    <button className="btn-primary" onClick={handleStartRoundtable}>
                      发起圆桌研判
                    </button>
                    <button className="btn-ghost" onClick={() => handleEdit(selectedCase)}>
                      编辑案件
                    </button>
                    <button className="btn-ghost" onClick={handleDispatchPatrol}>
                      派遣巡逻
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
        onOk={handleSubmit}
        onCancel={() => {
          setIsModalVisible(false)
          setEditingCase(null)
          form.resetFields()
        }}
        width={620}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText="确认"
        cancelText="取消"
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
          footer:  { borderTop: '1px solid var(--line)' },
        }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="occurred_time"
            label="发生时间"
            rules={[{ required: true, message: '请选择发生时间' }]}
          >
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item name="location" label="地点">
            <Input placeholder="如：××路××小区南门" />
          </Form.Item>

          <Form.Item label="经纬度（可选，用于地图与空间分析）" style={{ marginBottom: 0 }}>
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

          <Form.Item label="地图选点（可选）">
            <MapPicker
              lat={watchedLat}
              lng={watchedLng}
              onChange={(lat, lng) => {
                form.setFieldsValue({ latitude: lat, longitude: lng })
              }}
            />
          </Form.Item>

          <Form.Item name="case_type" label="类型（可选）">
            <Input placeholder="如：管线开孔、油库入侵、罐车劫持等" />
          </Form.Item>

          <Form.Item
            name="description"
            label="案情描述"
            rules={[{ required: true, message: '请输入案情描述' }]}
          >
            <TextArea rows={4} placeholder="请尽可能详细描述案情，其余结构化分析将由系统自动完成" />
          </Form.Item>

          <div className="cases-auto-extract">
            <Button
              size="small"
              icon={<ApiOutlined />}
              loading={structureMutation.isPending}
              onClick={handleStructureFromDescription}
            >
              自动提取
            </Button>
          </div>

          <div className="case-entry-readiness">
            <div className="case-entry-readiness-head">
              <span>保存前预检</span>
              <b>{readinessReadyCount} 项就绪 · {readinessAttentionCount} 项需关注</b>
            </div>
            <div className="case-entry-readiness-grid">
              {caseEntryReadiness.map(item => (
                <div key={item.key} className={`case-readiness-card ${item.status}`}>
                  <strong>{item.label}</strong>
                  <span>{item.impact}</span>
                  <small>{item.action}</small>
                </div>
              ))}
            </div>
          </div>

          <div className="cases-bonus-scope-grid">
            <div>
              <Form.Item name="bonus_has_vehicle" valuePropName="checked" noStyle>
                <Switch size="small" onChange={handleBonusVehicleScopeChange} />
              </Form.Item>
              <b>涉案车辆奖励</b>
              <span>车辆类别、车牌和处置状态</span>
            </div>
            <div>
              <Form.Item name="bonus_has_person" valuePropName="checked" noStyle>
                <Switch size="small" onChange={handleBonusPersonScopeChange} />
              </Form.Item>
              <b>抓获人员奖励</b>
              <span>人员处理类型和角色</span>
            </div>
            <div>
              <Form.Item name="bonus_has_oil" valuePropName="checked" noStyle>
                <Switch size="small" />
              </Form.Item>
              <b>涉油检斤处置</b>
              <span>油量、含水率和入库/回收</span>
            </div>
            <div>
              <Form.Item name="bonus_has_police" valuePropName="checked" noStyle>
                <Switch size="small" />
              </Form.Item>
              <b>报案立案佐证</b>
              <span>报案、立案和公安联系人</span>
            </div>
          </div>

          {watchedBonusHasVehicle && (
            <Form.List name="initial_vehicles">
              {(fields, { add, remove }) => (
                <div className="cases-bonus-draft">
                  <div className="cases-bonus-draft-head">
                    <span>涉案车辆</span>
                    <Button size="small" onClick={() => add({})}>增加车辆</Button>
                  </div>
                  {fields.map(({ key, name, ...restField }) => (
                    <div key={key} className="cases-bonus-draft-row">
                      <Form.Item
                        {...restField}
                        name={[name, 'vehicle_type']}
                        label="车辆考核类别"
                      >
                        <Select allowClear placeholder="请选择车辆类别">
                          {['摩托车（电动车）', '5吨以下机动车', '5吨以上机动车', '重型挂车', '机动船', '3吨以下炼化油罐', '3吨以上炼化油罐'].map(option => (
                            <Option key={option} value={option}>{option}</Option>
                          ))}
                        </Select>
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'plate_number']}
                        label="车牌/编号"
                      >
                        <Input placeholder="可选" />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'handling_status']}
                        label="车辆处理"
                      >
                        <Select allowClear placeholder="请选择">
                          {['移交公安', '扣押停放', '待处理', '返还'].map(option => (
                            <Option key={option} value={option}>{option}</Option>
                          ))}
                        </Select>
                      </Form.Item>
                      <Button size="small" disabled={fields.length === 1} onClick={() => remove(name)}>
                        删除
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </Form.List>
          )}

          {watchedBonusHasPerson && (
            <Form.List name="initial_persons">
              {(fields, { add, remove }) => (
                <div className="cases-bonus-draft">
                  <div className="cases-bonus-draft-head">
                    <span>抓获/涉案人员</span>
                    <Button size="small" onClick={() => add({})}>增加人员</Button>
                  </div>
                  {fields.map(({ key, name, ...restField }) => (
                    <div key={key} className="cases-bonus-draft-row">
                      <Form.Item
                        {...restField}
                        name={[name, 'name']}
                        label="姓名/代称"
                      >
                        <Input placeholder="可选" />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'handling_status']}
                        label="人员处理类型"
                      >
                        <Select allowClear placeholder="请选择处理类型">
                          {['刑事拘留', '行政拘留', '治安拘留', '行政处罚', '教育放行', '待核查'].map(option => (
                            <Option key={option} value={option}>{option}</Option>
                          ))}
                        </Select>
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'role']}
                        label="人员角色"
                      >
                        <Input placeholder="如司机、协助人员" />
                      </Form.Item>
                      <Button size="small" disabled={fields.length === 1} onClick={() => remove(name)}>
                        删除
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </Form.List>
          )}

          <div className="cases-advanced-toggle" style={{ cursor: 'default' }}>
            业务管理字段（按细则用于报送、质量评分和后续研判）
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

          <Form.Item name="loss_amount" label="损失金额（元，可选）">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>

          {/* 高级涉油特征折叠区域 */}
          <div
            className="cases-advanced-toggle"
            onClick={() => setShowAdvancedFields(!showAdvancedFields)}
          >
            {showAdvancedFields ? <UpOutlined style={{ fontSize: 11 }} /> : <DownOutlined style={{ fontSize: 11 }} />}
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

              <Form.Item name="oil_volume" label="涉油数量（吨或升）">
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>

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
                  <small>{dayjs(item.occurred_time).format('YYYY-MM-DD')}</small>
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
                  height={330}
                  lat={locationDraft.latitude ?? activeLocationCase.latitude}
                  lng={locationDraft.longitude ?? activeLocationCase.longitude}
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
        footer={[
          <Button key="cancel" onClick={resetImportState}>
            取消
          </Button>,
          <Button
            key="confirm"
            type="primary"
            loading={importMutation.isPending}
            disabled={
              !selectedImportFile ||
              !importPreview ||
              (importPreview.valid ?? importPreview.total) === 0 ||
              previewImportMutation.isPending
            }
            onClick={() => selectedImportFile && importMutation.mutate(selectedImportFile)}
          >
            确认导入
          </Button>,
        ]}
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)' },
          header:  { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
        }}
      >
        <p className="cases-import-hint">
          请选择包含以下列的文件：<strong>occurred_time</strong>（发生时间）、<strong>description</strong>（案件描述）。
        </p>
        <p className="cases-import-hint">
          可选列：<strong>location</strong>、<strong>latitude</strong>、<strong>longitude</strong>。
        </p>
        <Upload.Dragger
          name="file"
          multiple={false}
          showUploadList={false}
          disabled={previewImportMutation.isPending || importMutation.isPending}
          beforeUpload={(file) => {
            setSelectedImportFile(file)
            setImportPreview(null)
            previewImportMutation.mutate(file)
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
            <div className="cases-import-summary">
              <span>总行数 <b>{importPreview.total}</b></span>
              <span>有效 <b>{importPreview.valid ?? importPreview.total}</b></span>
              <span>错误 <b>{importPreview.errors?.length ?? 0}</b></span>
            </div>
            {importPreview.errors?.length > 0 && (
              <div className="cases-import-errors">
                {importPreview.errors.slice(0, 5).map((err) => (
                  <div key={`${err.row}-${err.error}`}>
                    第 {err.row} 行：{err.error}
                  </div>
                ))}
                {importPreview.errors.length > 5 && (
                  <div>还有 {importPreview.errors.length - 5} 条错误未显示</div>
                )}
              </div>
            )}
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

      {/* 搜索表单（隐藏，保留逻辑） */}
      <Form form={searchForm} style={{ display: 'none' }}>
        <Form.Item name="keyword"><Input /></Form.Item>
        <Form.Item name="status"><Select><Option value="pending">待处理</Option></Select></Form.Item>
        <Form.Item name="case_type"><Input /></Form.Item>
        <Form.Item name="oil_type"><Input /></Form.Item>
        <Form.Item name="dateRange"><RangePicker /></Form.Item>
        <Form.Item name="has_geo" valuePropName="checked"><Switch /></Form.Item>
        <Row><Col span={6}></Col></Row>
      </Form>
    </div>
  )
}

export default Cases
