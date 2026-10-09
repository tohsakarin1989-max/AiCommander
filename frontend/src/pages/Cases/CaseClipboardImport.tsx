import { useState } from 'react'
import { Button, Input } from 'antd'

export default function CaseClipboardImport({ disabled, onSelect }: {
  disabled: boolean; onSelect: (file: File) => void
}) {
  const [text, setText] = useState('')
  return <details style={{ margin: '12px 0' }}>
    <summary>少量记录：粘贴 Excel 选区</summary>
    <p>请连同表头一起复制。按人工粘贴来源保留原文，不当作已保全的原始 Excel 文件；仍需预览后确认。</p>
    <Input.TextArea aria-label="Excel选区内容" rows={5} value={text} disabled={disabled}
      maxLength={500000} onChange={event => setText(event.target.value)} />
    <Button disabled={disabled || !text.trim()} onClick={() => {
      onSelect(new File([text], '人工粘贴.tsv', { type: 'text/tab-separated-values' }))
      setText('')
    }}>送入同一导入预览</Button>
  </details>
}
