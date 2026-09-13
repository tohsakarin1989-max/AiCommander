import { useState } from 'react'
import { Alert, Button, Input, Space } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { agentLabEnabled } from '../../config/features'
import { governanceApi } from '../../services/governance'

export default function FacilityEvaluationArchive({ artifactId, available }: { artifactId: string; available: boolean }) {
  const { user } = useAuth()
  if (user?.role !== 'admin' || !agentLabEnabled) return null
  return <details className="case-result__evaluation-archive"><summary>管理员：归档设施来源对照</summary>
    {available ? <ArchiveForm key={artifactId} artifactId={artifactId} />
      : <p>此历史附件未留存完整评分输入，不能从前三候选倒推评测集。原成果仍可查看。</p>}
  </details>
}

function ArchiveForm({ artifactId }: { artifactId: string }) {
  const cache = useQueryClient()
  const [name, setName] = useState(`设施来源对照-${artifactId.slice(0, 8)}`)
  const [version, setVersion] = useState('1')
  const archive = useMutation({ mutationFn: () => governanceApi.archiveFacility(artifactId, name.trim(), version.trim()),
    retry: false, onSuccess: () => { void cache.invalidateQueries({ queryKey: ['fixed-datasets'] }) } })
  const locked = archive.isPending || archive.isSuccess
  return <Space direction="vertical" style={{ width: '100%' }}>
    <p>固定本附件的全池评分、道路依据及同案件地图的旧来源规则输入。候选不当作正确标签，也不修改案件。</p>
    <label>设施评测名称<Input aria-label="设施评测名称" maxLength={200} value={name} disabled={locked} onChange={event => setName(event.target.value)} /></label>
    <label>设施评测版本<Input aria-label="设施评测版本" maxLength={80} value={version} disabled={locked} onChange={event => setVersion(event.target.value)} /></label>
    <Button loading={archive.isPending} disabled={locked || !name.trim() || !version.trim()} onClick={() => archive.mutate()}>归档此道路附件</Button>
    {archive.isError && <Alert type="warning" message="归档未完成，请核对当前来源、权限和评测版本。" />}
    {archive.isSuccess && <Alert type="success" message="已归档，尚未标注正确性。" description={<Link to="/agents">进入运维中心比较新旧规则</Link>} />}
  </Space>
}
