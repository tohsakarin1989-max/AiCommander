// Offline adapter for the hash-pinned official MapLibre Font Maker WASM build.
// Only hash-pinned public Noto fonts are accepted by this reproducible build.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const hashes = {
  js: '2d5cce9e20511e3e1798a696b496cfb4fb9c55cd9cceaa73fd77849e1c3d7a64',
  wasm: 'de2986e66201499de76f21bb3a649e1f27d7d68af21cb2616dc3a7b25bade691',
  font: '2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b',
};
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function readVerified(filename, expected) {
  const fd = fs.openSync(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > 32 * 1024 * 1024) throw new Error('invalid input size/type');
    const bytes = fs.readFileSync(fd);
    if (digest(bytes) !== expected) throw new Error('input checksum mismatch');
    return bytes;
  } finally { fs.closeSync(fd); }
}

async function main() {
  const [toolDirectory, fontPath, outputDirectory, mongolianPath, emojiPath] = process.argv.slice(2);
  if (![5, 7].includes(process.argv.length)) {
    throw new Error('Usage: node generate-map-glyphs.cjs TOOL_DIR FONT_OTF NEW_OUTPUT_DIR [MONGOLIAN_TTF EMOJI_TTF]');
  }
  const composite = process.argv.length === 7;
  const expectedName = composite
    ? 'Noto Sans CJK SC Regular,Noto Sans Mongolian Regular,Noto Emoji Regular'
    : 'Noto Sans CJK SC Regular';
  if (fs.existsSync(outputDirectory)) throw new Error('output already exists');
  const js = readVerified(path.join(toolDirectory, 'sdfglyph.js'), hashes.js);
  const wasm = readVerified(path.join(toolDirectory, 'sdfglyph.wasm'), hashes.wasm);
  const font = readVerified(fontPath, hashes.font);
  const fontBytes = [font];
  const pinned = {...hashes};
  if (composite) {
    pinned.mongolian = 'e458bbdef2ac9579315293070b8f72abc290a42a0279a99b50a9829a7ccd8245';
    pinned.emoji = 'de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551';
    fontBytes.push(readVerified(mongolianPath, pinned.mongolian), readVerified(emojiPath, pinned.emoji));
  }
  let ready, fail;
  const initialized = new Promise((resolve, reject) => { ready = resolve; fail = reject; });
  const Module = {wasmBinary: new Uint8Array(wasm), onRuntimeInitialized: () => ready(),
    onAbort: () => fail(new Error('WASM initialization failed')), print: () => {}, printErr: () => {}};
  // No Node process, require, fetch or filesystem hooks are passed to the fixed
  // Emscripten runtime. VM is not claimed as a hostile-code security sandbox.
  const context = vm.createContext({Module, setTimeout, clearTimeout, console});
  vm.runInContext(js.toString('utf8'), context, {timeout: 10000});
  await initialized;
  fs.mkdirSync(outputDirectory, {mode: 0o700});
  const stack = Module.ccall('create_fontstack', 'number', ['number'], [0]);
  if (!stack) throw new Error('WASM allocation failed');
  const pointers = [];
  try {
    for (const bytes of fontBytes) {
      const pointer = Module._malloc(bytes.length);
      if (!pointer) throw new Error('WASM allocation failed');
      pointers.push(pointer);
      Module.HEAPU8.set(bytes, pointer);
      Module.ccall('fontstack_add_face', null, ['number', 'number', 'number'], [stack, pointer, bytes.length]);
    }
    const namePointer = Module.ccall('fontstack_name', 'number', ['number'], [stack]);
    const fontstack = context.UTF8ToString(namePointer);
    if (fontstack !== expectedName) throw new Error('unexpected fontstack');
    const glyphDirectory = path.join(outputDirectory, fontstack);
    fs.mkdirSync(glyphDirectory);
    const files = [];
    const starts = Array.from({length: 256}, (_, i) => i * 256);
    if (composite) starts.push(127744);
    for (const start of starts) {
      const glyph = Module.ccall('generate_glyph_buffer', 'number', ['number', 'number'], [stack, start]);
      try {
        const data = Module.ccall('glyph_buffer_data', 'number', ['number'], [glyph]);
        const size = Module.ccall('glyph_buffer_size', 'number', ['number'], [glyph]);
        if (!size || size > 2 * 1024 * 1024) throw new Error('invalid glyph range size');
        const bytes = Buffer.from(Module.HEAPU8.subarray(data, data + size));
        const name = `${start}-${start + 255}.pbf`;
        fs.writeFileSync(path.join(glyphDirectory, name), bytes, {flag: 'wx'});
        files.push({name, size_bytes: bytes.length, sha256: digest(bytes)});
      } finally { Module.ccall('free_glyph_buffer', null, ['number'], [glyph]); }
    }
    const report = {status: 'generated_not_render_verified', fontstack, hashes: pinned,
      unicode_range: [0, 65535], files, publish_ready: false};
    if (composite) {
      report.font_profile = 'cjk-mongolian-emoji-v1';
      report.additional_unicode_ranges = [[127744, 127999]];
    }
    fs.writeFileSync(path.join(outputDirectory, 'glyph-manifest.json'), JSON.stringify(report, null, 2), {flag: 'wx'});
    console.log(JSON.stringify({status: report.status, fontstack, ranges: files.length,
      bytes: files.reduce((total, file) => total + file.size_bytes, 0)}));
  } finally {
    Module.ccall('free_fontstack', null, ['number'], [stack]);
    for (const pointer of pointers) Module._free(pointer);
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
