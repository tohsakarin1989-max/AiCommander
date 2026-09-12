import api from './api'

export type FixedScorerPolicy = 'captured' | 'current_candidate' | 'facility_captured' | 'facility_candidate'
export type FixedDataset = { id: number; name: string; version: string; kind: 'case' | 'road'; checksum: string; sample_count: number; evaluation_family?: 'all' | 'facility_source' }
export type EvaluationRecord = {
  id: string; dataset_id: number; status: string; started_at: string
  algorithm_manifest: { evaluation_schema?: string; scorer_policy?: string }
  metrics: Record<string, number | string | null>
}
export type EvaluationComparison = {
  mode: 'repeatability' | 'algorithm_comparison'; counts: Record<string, number>
  baseline_failed_cases: number; candidate_failed_cases: number; boundary: string
  baseline_top1_hit_rate?: number | null; candidate_top1_hit_rate?: number | null; evaluation_family?: string
}
export type RoadEvaluationJob = {
  event_id: string; status: string; result_status: string | null
  metrics: Record<string, number | string | null> | null
}
export type RoadEvaluationDirectory = { total: number; items: Array<{
  event_id: string; status: string; created_at: string; source_available: boolean; dataset_id: number | null
}> }
export type EvaluationLabel = { hypothesis_type: 'possible_source' | 'storage_area' | 'activity_area' | 'transfer_route'; expected_asset_ids: number[]; expected_region_grid?: string | null }
export type EvaluationLabels = { dataset_id: number; name: string; version: string; case_ids: number[];
  cases: Array<{ id: number; case_number: string }>; label_assets: Array<{ id: number; name: string }>;
  ground_truth: Record<string, EvaluationLabel[]>; negative_case_ids: number[]; checksum: string }
export type EvaluationDiagnostics = { run_id: string; case_count: number; problems: Record<string, number>;
  judged_candidates: number; unjudged_candidates: number; legacy_cases_without_observations: number;
  calibration_status: string; calibrated_probability: null; boundary: string;
  buckets: Array<{ lower: number | null; upper_exclusive: number | null; verified_correct: number; verified_incorrect: number; unjudged: number }> }
export type ScoreCalibration = { status: string; case_count: number; boundary: string; production_promotion_allowed: false;
  split: { train_case_ids: number[]; validation_case_ids: number[]; train_observations: number; validation_observations: number };
  validation: { baseline: number; calibrated: number; improvement: number } | null }

export type IntelligenceRuntimeOverview = {
  orchestrator: string
  business_agents: string[]
  versions: {
    algorithms: Array<{ component: string; version: string; checksum: string }>
    scope_policy: { version: string; checksum: string }
  }
  latest_evaluation?: {
    id: string
    status: string
    metrics: Record<string, number | string | null>
    completed_at?: string | null
  } | null
  formal_case_mutations_allowed: boolean
  execution_task_creation_allowed: boolean
  external_model_required: boolean
}

export const governanceApi = {
  getDiagnostics: async (id: string): Promise<EvaluationDiagnostics> => (await api.get(`/admin/evaluations/runs/${encodeURIComponent(id)}/diagnostics`)).data,
  getCalibration: async (id: string): Promise<ScoreCalibration> => (await api.get(`/admin/evaluations/runs/${encodeURIComponent(id)}/calibration`)).data,
  getLabels: async (id: number): Promise<EvaluationLabels> => (await api.get(`/admin/evaluations/fixed-datasets/${id}/labels`)).data,
  searchLabelAssets: async (id: number, caseId: number, q: string): Promise<{ items: Array<{ id: number; name: string; asset_type: string }>; has_more: boolean }> =>
    (await api.get(`/admin/evaluations/fixed-datasets/${id}/label-assets`, { params: { case_id: caseId, q } })).data,
  reviseLabels: async (id: number, value: { version: string; reason: string; ground_truth: Record<string, EvaluationLabel[]>; negative_case_ids: number[] }): Promise<{ id: number }> =>
    (await api.post(`/admin/evaluations/fixed-datasets/${id}/label-versions`, value)).data,
  archiveResult: async (resultId: string, hash: string, name: string, version: string): Promise<{ id: number; name: string; version: string }> =>
    (await api.post('/admin/evaluations/result-archives', { result_id: resultId, expected_checksum: hash, name, version })).data,
  archiveFacility: async (artifactId: string, name: string, version: string): Promise<{ id: number }> =>
    (await api.post('/admin/evaluations/facility-datasets', { artifact_ids: [artifactId], name, version })).data,
  getDatasets: async (beforeId?: number): Promise<{ items: FixedDataset[]; next_before_id: number | null }> =>
    (await api.get('/admin/evaluations/fixed-datasets', { params: { before_id: beforeId } })).data,
  getEvaluations: async (): Promise<EvaluationRecord[]> => (await api.get('/admin/evaluations/runs', { params: { limit: 100 } })).data,
  runFixed: async (datasetId: number, policy: FixedScorerPolicy): Promise<EvaluationRecord> =>
    (await api.post('/admin/evaluations/fixed-run', { dataset_id: datasetId, scorer_policy: policy })).data,
  compareFixed: async (baseline: string, candidate: string): Promise<EvaluationComparison> =>
    (await api.post('/admin/evaluations/fixed-compare', { baseline_run_id: baseline, candidate_run_id: candidate })).data,
  runRoad: async (datasetId: number, requestId: string): Promise<{ event_id: string }> =>
    (await api.post('/admin/evaluations/road-jobs', { dataset_id: datasetId, request_id: requestId })).data,
  getRoadJob: async (id: string): Promise<RoadEvaluationJob> => (await api.get(`/admin/evaluations/road-jobs/${encodeURIComponent(id)}`)).data,
  getRoadJobs: async (page: number): Promise<RoadEvaluationDirectory> =>
    (await api.get('/admin/evaluations/road-jobs', { params: { page, page_size: 10 } })).data,
  cancelRoadJob: async (id: string): Promise<{ event_id: string; status: string }> =>
    (await api.post(`/admin/evaluations/road-jobs/${encodeURIComponent(id)}/cancel`)).data,
  getRuntimeOverview: async (): Promise<IntelligenceRuntimeOverview> => {
    const response = await api.get<IntelligenceRuntimeOverview>('/admin/intelligence-runtime/overview')
    return response.data
  },
}
