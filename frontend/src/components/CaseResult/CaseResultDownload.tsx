import { useEffect, useRef, useState } from 'react'
import { Button } from 'antd'
import { caseResultsApi } from '../../services/caseResults'

export default function CaseResultDownload({ resultId, hash }: { resultId: string; hash: string }) {
  const request = useRef<AbortController | null>(null)
  const [busy, setBusy] = useState<'docx' | 'pdf' | null>(null)
  const [status, setStatus] = useState('')
  useEffect(() => () => { request.current?.abort(); request.current = null }, [])

  const download = async (format: 'docx' | 'pdf') => {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setBusy(format)
    setStatus('正在生成当前版本报告，请勿重复点击。')
    try {
      const blob = await caseResultsApi.download(resultId, hash, format, controller.signal)
      if (controller.signal.aborted || request.current !== controller) return
      const url = URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = `case-result-${hash.slice(0, 16)}.${format}`
        document.body.appendChild(link)
        link.click()
        link.remove()
      } finally { window.setTimeout(() => URL.revokeObjectURL(url), 1000) }
      setStatus('已交给浏览器下载，请在下载列表查看文件。')
    } catch (error) {
      if (request.current !== controller) return
      if (controller.signal.aborted) setStatus('已停止等待下载，后台正在执行的渲染可能仍会完成。')
      else {
        const code = (error as { status?: number }).status
        setStatus(code === 401 ? '登录已失效，请重新登录。'
          : code === 403 || code === 404 ? '成果或引用当前不可访问，请刷新页面。'
            : code === 413 ? '报告过大，暂不能交互式导出。'
              : '报告暂未生成成功，请稍后重试；地图或转换服务不可用时不会下载缺失内容的文件。')
      }
    } finally {
      if (request.current === controller) { request.current = null; setBusy(null) }
    }
  }
  return <div className="case-result__download" aria-label="下载当前成果">
    <div className="case-result__download-actions">
      <Button disabled={!!busy} onClick={() => void download('docx')}>下载 Word</Button>
      <Button disabled={!!busy} onClick={() => void download('pdf')}>下载 PDF</Button>
      {busy && <Button onClick={() => request.current?.abort()}>停止等待</Button>}
    </div>
    <small>导出当前展示的冻结版本，不触发新的案件研判。</small>
    {status && <p role="status" aria-live="polite">{status}</p>}
  </div>
}
