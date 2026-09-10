// Fixed local validator: JSON on stdin only, no caller paths, URLs or code.
const { validateStyleMin } = require('@maplibre/maplibre-gl-style-spec')
const { version } = require('@maplibre/maplibre-gl-style-spec/package.json')
const chunks = []
let size = 0
process.stdin.on('data', chunk => {
  size += chunk.length
  if (size > 1024 * 1024) process.exit(2)
  chunks.push(chunk)
})
process.stdin.on('end', () => {
  try {
    const style = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    if (validateStyleMin(style).length) process.exit(2)
    process.stdout.write(JSON.stringify({ status: 'style_syntax_validated',
      validator: '@maplibre/maplibre-gl-style-spec', version }))
  } catch {
    process.exit(2)
  }
})
