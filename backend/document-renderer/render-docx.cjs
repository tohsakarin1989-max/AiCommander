'use strict'

// Fixed stdin/stdout protocol. No paths, URLs, shell commands or network requests from input.
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Footer, PageNumber, HeadingLevel, WidthType, ShadingType, AlignmentType,
  ImageRun,
} = require('docx')

const MAX_BYTES = 8 * 1024 * 1024
const FONT = { ascii: 'Arial', hAnsi: 'Arial', eastAsia: 'Noto Sans CJK SC' }
const widths = [2400, 6960]

function paragraphs(text, options = {}) {
  if (typeof text !== 'string') throw new Error('invalid_document_text')
  // Reject invalid XML characters instead of silently deleting source evidence.
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/u.test(text)) throw new Error('invalid_document_character')
  return text.split(/\r\n|\r|\n/u).map(line => new Paragraph({
    spacing: { after: 100 }, ...options, children: [new TextRun({ text: line, font: FONT })],
  }))
}

function table(rows) {
  if (!Array.isArray(rows) || rows.some(row => !Array.isArray(row) || row.length !== 2)) {
    throw new Error('invalid_document_table')
  }
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: widths,
    margins: { top: 80, bottom: 80, left: 100, right: 100 },
    rows: [['项目', '内容'], ...rows].map((row, index) => new TableRow({
      tableHeader: index === 0,
      cantSplit: true,
      children: row.map((text, column) => new TableCell({
        width: { size: widths[column], type: WidthType.DXA },
        shading: index === 0 ? { type: ShadingType.CLEAR, fill: 'E8EDF0' } : undefined,
        children: paragraphs(text),
      })),
    })),
  })
}

function frozenMapImage(input, map) {
  const image = input.map_image
  if (!image) throw new Error('frozen_map_renderer_required')
  if (!input.result_id || !input.content_sha256 || image.result_id !== input.result_id
      || image.content_sha256 !== input.content_sha256 || image.map_snapshot_id !== map.map_snapshot_id
      || typeof image.png_base64 !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(image.png_base64)) {
    throw new Error('invalid_frozen_map_image')
  }
  const data = Buffer.from(image.png_base64, 'base64')
  if (data.toString('base64') !== image.png_base64 || data.length < 33
      || !data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      || data.toString('ascii', 12, 16) !== 'IHDR') throw new Error('invalid_frozen_map_image')
  const width = data.readUInt32BE(16), height = data.readUInt32BE(20)
  if (width !== 960 || height < 500 || height > 1500) throw new Error('invalid_frozen_map_image')
  const scale = Math.min(624 / width, 700 / height)
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 },
    children: [new ImageRun({ type: 'png', data,
      transformation: { width: width * scale, height: height * scale },
      altText: { title: '冻结版本案件地图', name: 'case-result-map',
        description: `成果 ${input.result_id}，地图快照 ${map.map_snapshot_id}；候选范围待核验。` },
    })],
  })
}

async function render(input) {
  if (input.schema !== 'case-result-document-4.1.0-1' || !Array.isArray(input.blocks)) {
    throw new Error('unsupported_document_schema')
  }
  const children = []
  for (const [index, block] of input.blocks.entries()) {
    if (block.kind === 'heading') {
      children.push(...paragraphs(block.text, {
        heading: index === 0 ? HeadingLevel.TITLE : HeadingLevel.HEADING_1,
        keepNext: true, spacing: { before: 220, after: 120 },
      }))
    } else if (block.kind === 'table') {
      children.push(...paragraphs(block.text, { keepNext: true }))
      if (Array.isArray(block.rows) && block.rows.length === 0) children.push(...paragraphs('未记录'))
      else children.push(table(block.rows))
    } else if (block.kind === 'paragraph' || block.kind === 'source') {
      children.push(...paragraphs(block.text))
      if (block.rows?.length) children.push(table(block.rows))
    } else if (block.kind === 'map') {
      const map = JSON.parse(block.text)
      if (map.map_snapshot_id || map.candidates?.length || map.case_marker) {
        const image = frozenMapImage(input, map)
        children.push(...paragraphs('冻结版本地图', { heading: HeadingLevel.HEADING_1,
          pageBreakBefore: true, keepNext: true }))
        children.push(image)
        children.push(...paragraphs(`地图快照：${map.map_snapshot_id}。候选范围仅供核验，不代表实际路线或已确认事实。`))
      } else children.push(...paragraphs('地图：本成果尚未结合地图，不生成或推测地图位置。'))
    } else throw new Error('unsupported_document_block')
  }
  const document = new Document({
    creator: 'AiCommander', title: '案件统一研判成果',
    styles: {
      default: { document: { run: { font: FONT, size: 22 }, paragraph: { spacing: { line: 320 } } } },
      paragraphStyles: [
        { id: 'Title', name: 'Title', basedOn: 'Normal', run: { font: FONT, size: 36, bold: true }, paragraph: { alignment: AlignmentType.CENTER } },
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', run: { font: FONT, size: 28, bold: true }, paragraph: { outlineLevel: 0 } },
      ],
    },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1200, bottom: 1200, left: 1273, right: 1273 } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: '第 ', font: FONT }), new TextRun({ children: [PageNumber.CURRENT], font: FONT }),
          new TextRun({ text: ' 页', font: FONT })] })] }) },
      children,
    }],
  })
  return Packer.toBuffer(document)
}

async function main() {
  const chunks = []
  let size = 0
  for await (const chunk of process.stdin) {
    size += chunk.length
    if (size > MAX_BYTES) throw new Error('document_input_too_large')
    chunks.push(chunk)
  }
  const data = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  process.stdout.write(await render(data))
}

main().catch(error => {
  const allowed = new Set(['invalid_document_text', 'invalid_document_character', 'invalid_document_table',
    'unsupported_document_schema', 'frozen_map_renderer_required', 'invalid_frozen_map_image',
    'unsupported_document_block', 'document_input_too_large'])
  process.stderr.write(allowed.has(error.message) ? error.message : 'document_render_failed')
  process.exitCode = 1
})
