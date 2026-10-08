import type { MapLedgerClaim, MapLedgerPreview, MapLedgerRun } from '../../services/mapLedgerImports'

// Complete synthetic contracts shared only by the batch-correction tests.
export function ledgerBatchRun(id = 'batch'): MapLedgerRun {
  return { id, source_id: 1, template_id: 4, status: 'completed', filename: '合成台账.csv', source_revision: 'test-1',
    file_hash: 'test-hash', total_rows: 2, valid_rows: 0, quarantined_rows: 2, created_assets: 0, updated_assets: 0,
    errors: [], idempotent_replay: false, parent_run_id: null, original_evidence_object_id: null,
    table_metadata: { headers: ['编号', '产量', '单位', '空白'], sheet_name: null, header_row: 1 },
    counts: { new: 0, updated: 0, unchanged: 0, identity_pending: 0, conflict: 0, failed: 2 },
    template_snapshot: { id: 4, source_id: 1, name: '合成模板', header_row: 1, field_mapping: { production_output: '产量' },
      coordinate_system: 'wgs84', axis_order: 'lon_lat', coordinate_unit: 'degree', version: 1, is_active: true },
  }
}
export function ledgerBatchClaim(id = 1, runId = 'batch'): MapLedgerClaim {
  return { id, run_id: runId, row_number: id + 2, status: 'quarantined', retry_superseded: false, source_record_id: `F${id}`,
    raw_payload: { 编号: `F${id}`, 产量: `　${id}．５　`, 单位: '吨', 空白: null }, normalized_payload: null,
    parent_claim_id: null, correction_note: null, source_identity_id: null, identity_decision_id: null,
    plan: { row_number: id + 2, classification: 'failed', asset_id: null, asset_version: null, changes: [], groups: [],
      errors: [{ code: 'invalid_production_output', field: 'production_output', message: '不是有效数字' }] },
  }
}
export function ledgerBatchPreview(claims: MapLedgerClaim[]): MapLedgerPreview {
  return { plan_token: 'batch-plan', source_id: 1, template_id: 4, publishable: true, total_rows: claims.length,
    valid_rows: claims.length, quarantined_rows: 0, errors: [], sample: [], drift: [], rows_complete: true,
    structure: { headers: ['编号', '产量', '单位', '空白'], sheet_name: null, header_row: 1 },
    counts: { new: claims.length, updated: 0, unchanged: 0, identity_pending: 0, conflict: 0, failed: 0 },
    rows: claims.map(row => ({ row_number: row.row_number, classification: 'new', asset_id: null, asset_version: null,
      changes: [], groups: [], errors: [] })),
  }
}
