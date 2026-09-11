import { Alert, Button, Input, Space } from 'antd'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { governanceApi } from '../../services/governance'
import type { CaseResult } from '../../types/caseResult'

export default function CaseEvaluationArchive({ result, refreshing = false }: { result: CaseResult; refreshing?: boolean }) {
  const cache = useQueryClient()
  const [name, setName] = useState(`案件${result.content.case_id}固定评测`)
  const [version, setVersion] = useState(`画像${result.content.versions.profile_version}-${result.content_sha256.slice(0, 8)}`)
  const archive = useMutation({ mutationFn: () => governanceApi.archiveResult(result.id, result.content_sha256, name.trim(), version.trim()),
    retry: false, onSuccess: () => { void cache.invalidateQueries({ queryKey: ['fixed-datasets'] }) } })
  return <details className="case-result__evaluation-archive"><summary>管理员：纳入固定评测</summary>
    <p>固定当前案件画像、该成果的地图版本与归档时的关联检索结果。不会改写案件，也不会将现有候选当作正确标签。</p>
    <Space direction="vertical" style={{ width: '100%' }}>
      <label>评测集名称<Input aria-label="评测集名称" maxLength={200} value={name} disabled={archive.isPending || archive.isSuccess} onChange={event => setName(event.target.value)} /></label>
      <label>归档版本<Input aria-label="归档版本" maxLength={80} value={version} disabled={archive.isPending || archive.isSuccess} onChange={event => setVersion(event.target.value)} /></label>
      <Button loading={archive.isPending} disabled={!name.trim() || !version.trim() || archive.isSuccess || refreshing} onClick={() => archive.mutate()}>冻结评测输入</Button>
      {archive.isError && <Alert type="warning" message="未能归档，请刷新成果并核对版本；旧成果或缺少地图的画像不能冒充当前完整输入。" />}
      {archive.isSuccess && <Alert type="success" message="评测输入已冻结，尚未标注正确性。"
        description={<Link to="/agents">进入运维中心运行或比较评测</Link>} />}
    </Space>
  </details>
}
