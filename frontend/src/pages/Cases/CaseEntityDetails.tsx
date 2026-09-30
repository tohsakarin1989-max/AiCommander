import type { CaseProfile } from '../../types'
import { formatOilVolume, formatStoredTime } from '../../utils/caseValues'

export default function CaseEntityDetails({ profile }: { profile?: CaseProfile }) {
  if (!profile) return <p className="detail-section">人员、车辆与回收明细暂未加载，不据此认定没有记录。</p>
  return <div className="detail-section case-source-details">
    <h3>车辆与人员</h3>
    {profile.related.vehicles.length ? <ul>{profile.related.vehicles.map((item, i) => <li key={item.id ?? i}>
      {item.plate_number || '车牌未记录'} · {item.vehicle_type || '类型未记录'} · {item.handling_status || '处置未记录'}
      <small>载油：{formatOilVolume(item.oil_volume, item.oil_volume_unit)}；车辆总重：{item.gross_weight_t == null ? '未知' : `${item.gross_weight_t} 吨`}；车高：{item.height_m == null ? '未知' : `${item.height_m} 米`}</small>
    </li>)}</ul> : <p>尚无已录入车辆明细。</p>}
    {profile.related.persons.length ? <ul>{profile.related.persons.map((item, i) => <li key={item.id ?? i}>{item.name || '姓名未记录'} · {item.role || '角色未记录'} · {item.handling_status || '处置未记录'}<small>{item.notes}</small></li>)}</ul> : <p>尚无已录入人员明细。</p>}
    <h3>回收记录</h3>{profile.related.oil_recovery.length ? <ul>{profile.related.oil_recovery.map((item, i) => <li key={item.id ?? i}>
      {formatOilVolume(item.volume_tons, 'tonne')} · {item.receiver || '接收方未记录'}<small>{formatStoredTime(item.handled_at)} · {item.handling_method || '处置方式未记录'} · {item.notes}</small>
    </li>)}</ul> : <p>尚无独立回收记录。</p>}
    <h3>相关线索</h3>{profile.related.tips.length ? <ul>{profile.related.tips.map((item, i) => <li key={item.id ?? i}>{item.content || '内容未记录'}<small>{item.location || '地点未明确'} · {formatStoredTime(item.reported_at)} · {item.verification_status || '待核实'}</small></li>)}</ul> : <p>尚无关联线索。</p>}
  </div>
}
