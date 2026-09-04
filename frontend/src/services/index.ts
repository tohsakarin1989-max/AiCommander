/**
 * =============================================================================
 * AiCommander 前端 API 服务层 - 统一入口
 * =============================================================================
 *
 * 使用示例：
 *
 * import { caseApi, aiApi, eventApi, configApi } from '@/services'
 *
 * // 获取案件列表
 * const cases = await caseApi.getCases()
 *
 * // 创建圆桌会议
 * const meeting = await aiApi.meeting.create({ ... })
 *
 * // 获取事件列表
 * const events = await eventApi.list()
 *
 * // 获取 AI 模型列表
 * const models = await configApi.models.list()
 *
 * =============================================================================
 * 类型说明：所有类型请从 @/types 导入，services 不再导出类型
 * =============================================================================
 */

// 基础 API 实例
export { default as api } from './api'
export { apiCall, withContext, ApiError } from './api'

// 案件数据
export { caseApi } from './cases'

// 事件数据（新风格命名空间 + 向后兼容函数导出）
export { eventApi } from './events'
// 向后兼容：保留旧函数导出
export {
  getEventTypes,
  createEvent,
  listEvents,
  getEvent,
  updateEvent,
  deleteEvent,
  convertEventToCase,
  analyzeArea,
  getAreaRiskRanking,
  getHotspots,
  listAreaProfiles,
  getAreaProfile,
  refreshAreaProfile,
  analyzeCorrelations,
  listCorrelations,
  confirmCorrelation,
  getEventStatistics,
  getMapData,
} from './events'

// AI 功能（圆桌会议、助手、智能体、结论、模板）
export { aiApi } from './ai'

// 分析报告（部署建议、图谱）
export { analysisApi } from './analysis'
export { reportApi } from './reports'
export type { ReportListItem } from './reports'
export { knowledgeApi } from './knowledge'
export type { CitationAssistResponse, ExperienceKnowledgeResponse } from './knowledge'

// 系统配置（模型、参数）
export { configApi } from './config'

// 地图服务
export { mapMCPApi } from './mapMCP'

// 巡逻服务
export { patrolApi } from './patrols'

// 团伙分析
export { gangApi } from './gangs'

// 保卫人员管理
export { personnelApi } from './personnel'

// 重要部位管理
export { keyLocationApi } from './key_locations'

// 辖区风险底座
export { jurisdictionApi } from './jurisdiction'
export type {
  AssetRiskProfile,
  AssetTableImportResult,
  CaseRiskContext,
  CaseExperienceCard,
  DataQualitySummary,
  EffectivenessSummary,
  JurisdictionFeedback,
  JurisdictionAsset,
  JurisdictionAssetCreate,
  JurisdictionAssetSummary,
  JurisdictionDistance,
  MaterializedPatrolPlan,
  MaterializedPatrolRecord,
  PatrolPlan,
  RoundtableBriefing,
  SimilarTarget,
  SimilarTargetsResponse,
  PreventionWorkbench,
} from './jurisdiction'

// 案件研判工作台
export { caseIntelligenceApi } from './caseIntelligence'

// 数智自动化告警
export { automationAlertApi } from './automationAlerts'
export type { AutomationAlert } from './automationAlerts'

// 工作建议
export { suggestionsApi } from './suggestions'
export type { WorkSuggestion, SuggestionsResponse } from './suggestions'
