import { Alert, Button, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapLedgerImportsApi, type MapLedgerComparison } from '../../services/mapLedgerImports'
import type { MapLedgerDeclaration } from '../../services/mapFoundation'

const reasons: Record<string, string> = {
  coverage_unknown: '未声明完整度，不比较缺席', incremental: '增量资料，不比较缺席',
  current_rows_incomplete: '本批次仍有失败、身份或冲突问题，不能作为完整台账比较',
  no_previous_comparable_ledger: '没有同来源、同范围的上期完整台账，暂不比较',
  overlapping_period: '有效期间与已有台账重叠，不能认定相邻批次', ambiguous_previous_period: '上期存在多份期间重叠的台账，无法唯一确定比较基准',
  period_gap: '业务期间不相邻，不比较缺席', previous_not_full: '上一相邻期间是增量资料，不比较缺席',
  intervening_coverage_unknown: '上期之后存在未声明范围的资料，不能确认完整台账接续',
  previous_rows_incomplete: '上期仍有失败或未确定身份的行，不能作为完整基准',
  identity_mapping_changed: '稳定来源编号的映射已变化，需先核对身份口径',
  data_restricted_or_unavailable: '相关资料受限或不可用，不展示缺席条目与数量',
  scope_changed: '来源厂区已变化，原比较不再适用', correction_subset: '这是部分行的修正批次，不代表完整台账',
}

export function LedgerComparisonView({ comparison, declaration }: { comparison: MapLedgerComparison; declaration?: MapLedgerDeclaration | null }) {
  return <section aria-label="台账完整度与缺席待核">
    {declaration && <p>管理员声明：{declaration.mode === 'full' ? '范围内完整台账' : '增量资料'} · {declaration.scope_key} · {declaration.scope_description}<br />
      业务期间 [{declaration.valid_from}，{declaration.valid_to})，来源 #{declaration.source_id} / 厂区 #{declaration.operational_area_id}。</p>}
    {comparison.phase === 'preview' && <Alert type="info" message="当前仅为候选预览，尚未执行；只有全行处理成功的完整台账才可作为后续基准。" />}
    {comparison.status !== 'comparable' ? <p>{reasons[comparison.reason] || '暂不能确认台账可比性，不比较缺席'}</p> : <>
      <p>上期批次 {comparison.baseline_run_id} · 来源修订 {comparison.baseline_source_revision}。上期 {comparison.previous_count} 行，本期 {comparison.current_count} 行，本期未出现 {comparison.missing_count} 项，均为待核。</p>
      <Table size="small" rowKey="claim_id" dataSource={comparison.missing || []} pagination={{ pageSize: 10, showSizeChanger: false }} columns={[
        { title: '来源稳定编号', dataIndex: 'source_record_id' }, { title: '上期原表行', dataIndex: 'row_number' },
        { title: '上期来源声明', dataIndex: 'claim_id', render: id => `#${id}` },
        { title: '处理含义', render: () => '本期未出现，待核；设施原状态不变' },
      ]} />
      {comparison.rows_complete === false && <p>当前显示前 200 项，数量覆盖全部；本页不提供批量停用或删除操作。</p>}
    </>}
    <p>{comparison.boundary}</p>
  </section>
}

export default function MapLedgerComparisonReceipt({ runId, declaration }: { runId: string; declaration?: MapLedgerDeclaration | null }) {
  const { user, sessionEpoch } = useAuth()
  const query = useQuery({ queryKey: ['map-ledger-comparison', user?.id, sessionEpoch, runId], gcTime: 0,
    queryFn: ({ signal }) => mapLedgerImportsApi.comparison(runId, signal) })
  if (query.isError) return <Alert type="warning" message="台账比较读取失败或权限、来源已变化，未展示旧比较及数量。"
    action={<Button onClick={() => void query.refetch()}>重新核对</Button>} />
  if (!query.isSuccess || query.isFetching) return <p>正在核对台账比较权限与来源…</p>
  return <LedgerComparisonView comparison={query.data} declaration={declaration} />
}
