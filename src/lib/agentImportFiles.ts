import { unzip, strFromU8 } from 'fflate'

export type ImportSource = 'template' | 'garment' | 'auto'
export type ImportFile = { file: File; relativePath: string }

const MiB = 1024 * 1024
const MAX_FILE = 20 * MiB
const MAX_ZIP = 100 * MiB
const MAX_TOTAL = 500 * MiB
const MAX_IMAGES = 500
const MAX_ENTRIES = 10000
const mimeTypes: Readonly<Record<string, string>> = Object.assign(Object.create(null), {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
})
const archiveExtension = /\.(zip|rar|7z|tar|gz|bz2|xz|tgz|zst)$/i
const extension = (path: string) => path.split('.').pop()!.toLowerCase()
function isMacMetadata(path: string): boolean {
  const parts = path.split('/')
  return parts.includes('__MACOSX') || parts[parts.length - 1].startsWith('._')
}
function fail(message: string): never { throw new Error(`Import: ${message}`) }

function safePath(raw: string, directory = false): string {
  let path = raw.replace(/\\/g, '/').normalize('NFC')
  if (directory && path.endsWith('/')) path = path.slice(0, -1)
  if (!path || path.length > 1000 || raw.length > 1000 || path.startsWith('/')
    || /[:\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/.test(path)) {
    return fail(`unsafe path: ${JSON.stringify(raw)}`)
  }
  const parts = path.split('/')
  if (parts.length > 16 || parts.some(part => !part || part === '.' || part === '..')) {
    return fail(`unsafe path or depth exceeds 16: ${JSON.stringify(raw)}`)
  }
  // Count Unicode characters, not UTF-16 code units, after canonical composition.
  if (parts.some(part => Array.from(part).length > 255)) fail(`path segment exceeds 255 characters: ${JSON.stringify(raw)}`)
  return path
}

const crcTable = Uint32Array.from({ length: 256 }, (_, value) => {
  for (let i = 0; i < 8; i++) value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0)
  return value >>> 0
})
function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

// Validate DEFLATE's real output length without allocating its output. fflate's
// fixed-size unzip buffers alone cannot detect an under-declared expansion bomb.
class Bits {
  position = 0
  constructor(readonly bytes: Uint8Array) {}
  peek(count: number): number {
    const offset = this.position >>> 3
    return (((this.bytes[offset] ?? 0) | ((this.bytes[offset + 1] ?? 0) << 8)
      | ((this.bytes[offset + 2] ?? 0) << 16)) >>> (this.position & 7)) & ((1 << count) - 1)
  }
  take(count: number): number {
    if (this.position + count > this.bytes.length * 8) fail('truncated DEFLATE stream')
    const value = this.peek(count)
    this.position += count
    return value
  }
}
type Huffman = { table: Uint32Array; width: number }
function huffman(lengths: number[], allowEmpty = false): Huffman | null {
  const width = Math.max(...lengths)
  if (!width) return allowEmpty ? null : fail('empty DEFLATE Huffman tree')
  const counts = new Uint16Array(16)
  for (const length of lengths) {
    if (length < 0 || length > 15) fail('invalid DEFLATE code length')
    if (length) counts[length]++
  }
  let left = 1
  for (let i = 1; i <= width; i++) {
    left = left * 2 - counts[i]
    if (left < 0) fail('oversubscribed DEFLATE Huffman tree')
  }
  if (left && !(width === 1 && counts[1] === 1)) fail('incomplete DEFLATE Huffman tree')
  const next = new Uint16Array(16)
  let code = 0
  for (let i = 1; i <= width; i++) next[i] = code = (code + counts[i - 1]) * 2
  const table = new Uint32Array(1 << width)
  lengths.forEach((length, symbol) => {
    if (!length) return
    let value = next[length]++, reversed = 0
    for (let i = 0; i < length; i++, value >>>= 1) reversed = (reversed << 1) | (value & 1)
    for (let i = reversed; i < table.length; i += 1 << length) table[i] = (symbol << 5) | length
  })
  return { table, width }
}
function symbol(bits: Bits, tree: Huffman | null): number {
  if (!tree) return fail('missing DEFLATE distance tree')
  const value = tree.table[bits.peek(tree.width)]
  if (!value) return fail('invalid DEFLATE Huffman code')
  bits.take(value & 31)
  return value >>> 5
}
const fixedLiteral = huffman(Array.from({ length: 288 }, (_, i) => i < 144 ? 8 : i < 256 ? 9 : i < 280 ? 7 : 8))!
const fixedDistance = huffman(Array(32).fill(5))!
const lengthBase = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
const lengthExtra = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0]
const distanceBase = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]

function checkDeflate(bytes: Uint8Array, expected: number): void {
  const bits = new Bits(bytes)
  let output = 0, final = 0
  do {
    final = bits.take(1)
    const kind = bits.take(2)
    if (kind === 0) {
      bits.position = Math.ceil(bits.position / 8) * 8
      const size = bits.take(16)
      if ((size ^ bits.take(16)) !== 65535) fail('corrupt DEFLATE stored block')
      bits.position += size * 8
      if (bits.position > bytes.length * 8) fail('truncated DEFLATE stored block')
      output += size
    } else {
      if (kind === 3) fail('invalid DEFLATE block')
      let literal = fixedLiteral, distance: Huffman | null = fixedDistance
      if (kind === 2) {
        const literals = bits.take(5) + 257, distances = bits.take(5) + 1, codes = bits.take(4) + 4
        if (literals > 286) fail('invalid DEFLATE literal count')
        const order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
        const lengths = Array(19).fill(0)
        for (let i = 0; i < codes; i++) lengths[order[i]] = bits.take(3)
        const tree = huffman(lengths)
        const all: number[] = []
        while (all.length < literals + distances) {
          const value = symbol(bits, tree)
          if (value < 16) all.push(value)
          else {
            if (value === 16 && !all.length) fail('invalid DEFLATE repeat')
            const count = value === 16 ? bits.take(2) + 3 : value === 17 ? bits.take(3) + 3 : bits.take(7) + 11
            const repeated = value === 16 ? all[all.length - 1] : 0
            if (all.length + count > literals + distances) fail('invalid DEFLATE repeat length')
            for (let i = 0; i < count; i++) all.push(repeated)
          }
        }
        if (!all[256]) fail('missing DEFLATE end code')
        literal = huffman(all.slice(0, literals))!
        distance = huffman(all.slice(literals), true)
      }
      for (;;) {
        const value = symbol(bits, literal)
        if (value === 256) break
        if (value < 256) output++
        else {
          if (value > 285) fail('invalid DEFLATE length')
          const size = lengthBase[value - 257] + bits.take(lengthExtra[value - 257])
          const code = symbol(bits, distance)
          if (code > 29) fail('invalid DEFLATE distance')
          const back = distanceBase[code] + bits.take(code < 4 ? 0 : (code >>> 1) - 1)
          if (back > output) fail('invalid DEFLATE back-reference')
          output += size
        }
        if (output > expected) fail('DEFLATE expanded size exceeds declared size')
      }
    }
    if (output > expected) fail('DEFLATE expanded size exceeds declared size')
  } while (!final)
  if (output !== expected || Math.ceil(bits.position / 8) !== bytes.length) fail('DEFLATE size mismatch or trailing data')
}

type ZipEntry = { rawName: string; path: string; directory: boolean; size: number; compressed: number; crc: number; method: number; start: number; end: number; local: number }
function preflight(bytes: Uint8Array): ZipEntry[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const u16 = (p: number) => view.getUint16(p, true)
  const u32 = (p: number) => view.getUint32(p, true)
  const range = (p: number, n: number, end = bytes.length) => {
    if (p < 0 || n < 0 || p + n > end) fail('corrupt or truncated ZIP')
  }
  function extras(start: number, size: number) {
    const end = start + size
    range(start, size)
    while (start < end) {
      range(start, 4, end)
      const id = u16(start), size = u16(start + 2)
      if (id === 1 || id === 0x9901) fail('ZIP64/encrypted ZIP is unsupported')
      range(start + 4, size, end)
      start += size + 4
    }
  }
  let eocd = bytes.length - 22
  for (; eocd >= Math.max(0, bytes.length - 65557); eocd--) {
    if (u32(eocd) === 0x06054b50) break
  }
  if (eocd < Math.max(0, bytes.length - 65557)) return fail('corrupt or truncated ZIP end record')
  range(eocd, 22)
  if (eocd + 22 + u16(eocd + 20) !== bytes.length) fail('ZIP comment/trailing data mismatch')
  if (u16(eocd + 4) || u16(eocd + 6) || u16(eocd + 8) !== u16(eocd + 10)) fail('multi-disk ZIP is unsupported')
  const count = u16(eocd + 10), cdSize = u32(eocd + 12), cd = u32(eocd + 16)
  if (count === 65535 || cd === 0xffffffff || cdSize === 0xffffffff) fail('ZIP64 is unsupported')
  if (count > MAX_ENTRIES) fail('ZIP entry count exceeds 10000')
  if (cd + cdSize !== eocd) fail('corrupt ZIP central directory')
  range(cd, cdSize, eocd)
  const entries: ZipEntry[] = [], paths = new Set<string>()
  let cursor = cd
  for (let i = 0; i < count; i++) {
    range(cursor, 46, eocd)
    if (u32(cursor) !== 0x02014b50) fail('corrupt ZIP central entry')
    const flags = u16(cursor + 8), method = u16(cursor + 10)
    if (flags & ~0x080e) fail('encrypted or unsupported ZIP flags')
    if (method !== 0 && method !== 8) fail('unsupported ZIP compression')
    if (u16(cursor + 6) > 20) fail('unsupported ZIP version')
    const compressed = u32(cursor + 20), size = u32(cursor + 24), crc = u32(cursor + 16)
    if (size > MAX_FILE) fail('ZIP file exceeds 20 MiB')
    const nameSize = u16(cursor + 28), extraSize = u16(cursor + 30), commentSize = u16(cursor + 32)
    range(cursor + 46, nameSize + extraSize + commentSize, eocd)
    const nameBytes = bytes.subarray(cursor + 46, cursor + 46 + nameSize)
    let rawName: string
    try { rawName = flags & 0x800 ? new TextDecoder('utf-8', { fatal: true }).decode(nameBytes) : strFromU8(nameBytes, true) }
    catch { return fail('invalid ZIP filename encoding') }
    if (rawName === '__proto__') fail('unsupported ZIP filename: __proto__')
    const directory = /[/\\]$/.test(rawName), path = safePath(rawName, directory)
    if (paths.has(path)) fail(`duplicate ZIP path: ${path}`)
    paths.add(path)
    const mode = (u32(cursor + 38) >>> 16) & 0xf000
    if (mode && mode !== 0x8000 && mode !== 0x4000) fail(`symlink/special ZIP entry: ${path}`)
    if (u16(cursor + 34)) fail('multi-disk ZIP entry is unsupported')
    extras(cursor + 46 + nameSize, extraSize)
    const local = u32(cursor + 42)
    range(local, 30, cd)
    if (u32(local) !== 0x04034b50 || u16(local + 4) !== u16(cursor + 6)
      || u16(local + 6) !== flags || u16(local + 8) !== method) fail('ZIP local header mismatch')
    const localNameSize = u16(local + 26), localExtraSize = u16(local + 28)
    range(local + 30, localNameSize + localExtraSize, cd)
    if (localNameSize !== nameSize || nameBytes.some((byte, j) => byte !== bytes[local + 30 + j])) fail('ZIP local filename mismatch')
    extras(local + 30 + localNameSize, localExtraSize)
    const start = local + 30 + localNameSize + localExtraSize
    range(start, compressed, cd)
    let end = start + compressed
    if (flags & 8) {
      if ((u32(local + 14) && u32(local + 14) !== crc) || (u32(local + 18) && u32(local + 18) !== compressed)
        || (u32(local + 22) && u32(local + 22) !== size)) fail('ZIP local size/CRC mismatch')
      range(end, 12, cd)
      const descriptor = u32(end) === 0x08074b50 ? end + 4 : end
      range(descriptor, 12, cd)
      if (u32(descriptor) !== crc || u32(descriptor + 4) !== compressed || u32(descriptor + 8) !== size) fail('ZIP data descriptor mismatch')
      end = descriptor + 12
    } else if (u32(local + 14) !== crc || u32(local + 18) !== compressed || u32(local + 22) !== size) fail('ZIP local size/CRC mismatch')
    if (method === 0 && compressed !== size) fail('stored ZIP size mismatch')
    if (directory && size) fail('ZIP directory contains data')
    if (!directory && !isMacMetadata(path) && archiveExtension.test(path)) fail(`nested archive is unsupported: ${path}`)
    entries.push({ rawName, path, directory, size, compressed, crc, method, start, end, local })
    cursor += 46 + nameSize + extraSize + commentSize
  }
  if (cursor !== eocd) fail('ZIP central directory count/size mismatch')
  let end = 0
  for (const entry of [...entries].sort((a, b) => a.local - b.local)) {
    if (entry.local !== end) fail('overlapping ZIP entries or unindexed data')
    end = entry.end
  }
  if (end !== cd) fail('unindexed ZIP data')
  // Also reject a file used as another entry's directory.
  const files = new Set(entries.filter(entry => !entry.directory).map(entry => entry.path))
  for (const entry of entries) {
    const parts = entry.path.split('/')
    for (let i = 1; i < parts.length; i++) if (files.has(parts.slice(0, i).join('/'))) fail('ZIP file/directory path collision')
  }
  return entries
}

async function readFile(file: File, limit: number): Promise<Uint8Array> {
  if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > limit) fail(`file size limit exceeded: ${file.name}`)
  const bytes = new Uint8Array(await file.arrayBuffer())
  if (bytes.length !== file.size || bytes.length > limit) fail(`file size mismatch: ${file.name}`)
  return bytes
}

/** Reject unsafe/corrupt input atomically; report every unsupported plain/ZIP file. */
export async function prepareImportFiles(files: File[], maxFiles = MAX_IMAGES): Promise<{ files: ImportFile[]; skipped: string[] }> {
  if (!Number.isInteger(maxFiles) || maxFiles < 1 || maxFiles > MAX_IMAGES) fail('maxFiles must be between 1 and 500')
  const ready: ImportFile[] = [], skipped: string[] = []
  const inputs = files.map(file => ({ file, path: safePath(file.webkitRelativePath || file.name) }))
  const occupied = new Set(inputs.filter(({ path }) => extension(path) !== 'zip').map(({ path }) => path))
  const roots: string[] = []
  let total = 0
  function budget(size: number, images: number) {
    total += size
    if (total > MAX_TOTAL) fail('expanded total exceeds 500 MiB')
    if (ready.length + images > maxFiles) fail(`image count exceeds ${maxFiles}`)
  }
  function result(bytes: Uint8Array, path: string, original?: File): ImportFile {
    const name = path.split('/').pop()!
    // No image re-encoding or format sniffing: the server validates image content.
    return { file: new File([Uint8Array.from(bytes)], name, { type: mimeTypes[extension(path)], lastModified: original?.lastModified }), relativePath: path }
  }
  const seenPlain = new Set<string>()
  for (const { file, path } of inputs) {
    if (extension(path) !== 'zip' || isMacMetadata(path)) {
      if (file.size > MAX_FILE) fail(`file exceeds 20 MiB: ${path}`)
      if (isMacMetadata(path) || !mimeTypes[extension(path)]) { skipped.push(path); continue }
      if (seenPlain.has(path)) fail(`duplicate file path: ${path}`)
      seenPlain.add(path)
      budget(file.size, 1)
      ready.push(result(await readFile(file, MAX_FILE), path, file))
      continue
    }
    const bytes = await readFile(file, MAX_ZIP)
    const entries = preflight(bytes)
    const base = safePath(path.slice(0, -4))
    const components = base.split('/')
    const namespaces = [...roots, ...occupied]
    // Rename the conflicting ancestor, not only the last component: e.g. a.zip
    // plus a/b.zip becomes a/... and a-2/b/... instead of looping forever.
    let renameAt = components.length - 1
    for (const used of namespaces) {
      if (base.startsWith(`${used}/`)) renameAt = Math.min(renameAt, used.split('/').length - 1)
    }
    let root = base, suffix = 2
    while (namespaces.some(used => root === used || root.startsWith(`${used}/`) || used.startsWith(`${root}/`))) {
      const candidate = [...components]
      candidate[renameAt] += `-${suffix++}`
      root = safePath(candidate.join('/'))
    }
    roots.push(root)
    for (const entry of entries) safePath(`${root}/${entry.path}`)
    budget(entries.reduce((sum, entry) => sum + entry.size, 0), entries.filter(entry => !entry.directory
      && !isMacMetadata(`${root}/${entry.path}`) && mimeTypes[extension(entry.path)]).length)
    // Validate streams before unzip can allocate any expanded buffers, including
    // ignored non-images. Then verify their actual bytes and CRC as well.
    for (const entry of entries) if (entry.method === 8) checkDeflate(bytes.subarray(entry.start, entry.start + entry.compressed), entry.size)
    const expanded = await new Promise<Record<string, Uint8Array>>((resolve, reject) => {
      unzip(bytes, (error, output) => error ? reject(new Error(`Import: corrupt ZIP: ${error.message}`)) : resolve(output))
    })
    for (const entry of entries) {
      const data = Object.prototype.hasOwnProperty.call(expanded, entry.rawName) ? expanded[entry.rawName] : undefined
      if (!data || data.length !== entry.size || crc32(data) !== entry.crc) fail(`ZIP size/CRC mismatch: ${entry.path}`)
      if (entry.directory) continue
      const relativePath = `${root}/${entry.path}`
      // Finder sidecars can have image/ZIP extensions but are never upload images.
      if (isMacMetadata(relativePath) || !mimeTypes[extension(entry.path)]) { skipped.push(relativePath); continue }
      ready.push(result(data, relativePath))
    }
  }
  return { files: ready, skipped }
}

// Structural interfaces avoid depending on non-standard WebKit DOM declarations.
type DroppedEntry = {
  name: string
  isFile: boolean
  isDirectory: boolean
  file?: (success: (file: File) => void, error: (error: DOMException) => void) => void
  createReader?: () => { readEntries: (success: (entries: DroppedEntry[]) => void, error: (error: DOMException) => void) => void }
}
type DroppedItem = { kind: string; webkitGetAsEntry?: () => DroppedEntry | null; getAsFile: () => File | null }
type DroppedDataTransfer = { items?: ArrayLike<DroppedItem>; files: ArrayLike<File> }

/** Snapshot entries synchronously while the drop event's data store is readable. */
export async function collectDroppedFiles(dataTransfer: DroppedDataTransfer): Promise<File[]> {
  const items = Array.from(dataTransfer.items ?? []).filter(item => item.kind === 'file')
  const sources = items.map(item => ({ entry: item.webkitGetAsEntry?.(), file: item.getAsFile() }))
  const fallback = Array.from(dataTransfer.files)
  const files: File[] = []
  let entryCount = 0
  async function visit(entry: DroppedEntry, parent: string): Promise<void> {
    if (++entryCount > MAX_ENTRIES) fail('dropped entry count exceeds 10000')
    const path = safePath(parent ? `${parent}/${entry.name}` : entry.name)
    if (entry.isFile && !entry.isDirectory && entry.file) {
      const file = await new Promise<File>((resolve, reject) => entry.file!(resolve, reject))
      const copy = new File([file], file.name, { type: file.type, lastModified: file.lastModified })
      Object.defineProperty(copy, 'webkitRelativePath', { value: path })
      files.push(copy)
    } else if (entry.isDirectory && !entry.isFile && entry.createReader) {
      const reader = entry.createReader()
      for (;;) {
        const batch = await new Promise<DroppedEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
        if (!batch.length) break
        for (const child of batch) await visit(child, path)
      }
    } else fail(`unreadable dropped entry: ${path}`)
  }
  if (!sources.length) return fallback
  for (const source of sources) {
    if (source.entry) await visit(source.entry, '')
    else if (source.file) files.push(source.file)
    else fail('unreadable dropped file')
  }
  return files
}
