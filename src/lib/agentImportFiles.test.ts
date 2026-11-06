import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { zipSync, unzip, Zip, ZipPassThrough, strToU8 } from 'fflate'
import type { Zippable } from 'fflate'
import { collectDroppedFiles, prepareImportFiles } from './agentImportFiles'
import type { ImportFile, ImportSource } from './agentImportFiles'

vi.mock('fflate', async importOriginal => {
  const actual = await importOriginal<typeof import('fflate')>()
  return { ...actual, unzip: vi.fn(actual.unzip) }
})

// Blob/arrayBuffer are available in Node; don't require jsdom or a new dependency.
class TestFile extends Blob {
  readonly name: string
  readonly lastModified: number
  readonly webkitRelativePath = ''
  constructor(parts: BlobPart[], name: string, options: FilePropertyBag = {}) {
    super(parts, options)
    this.name = name
    this.lastModified = options.lastModified ?? 1
  }
  async arrayBuffer(): Promise<ArrayBuffer> { return super.arrayBuffer() }
}
beforeAll(() => vi.stubGlobal('File', TestFile))
afterAll(() => vi.unstubAllGlobals())
beforeEach(() => { vi.mocked(unzip).mockClear() })

const MiB = 1024 * 1024
const image = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3])
function file(name: string, bytes: Uint8Array = image, path = ''): File {
  const output = new File([Uint8Array.from(bytes)], name, { type: 'application/octet-stream', lastModified: 123 })
  if (path) Object.defineProperty(output, 'webkitRelativePath', { value: path })
  return output
}
const archive = (entries: Zippable, name = '款式.zip', level: 0 | 1 | 6 | 9 = 0) => file(name, zipSync(entries, { level }))
const view = (bytes: Uint8Array) => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
function centralOffsets(bytes: Uint8Array): number[] {
  const data = view(bytes), end = bytes.length - 22
  let offset = data.getUint32(end + 16, true)
  return Array.from({ length: data.getUint16(end + 10, true) }, () => {
    const result = offset
    offset += 46 + data.getUint16(offset + 28, true) + data.getUint16(offset + 30, true) + data.getUint16(offset + 32, true)
    return result
  })
}
function mutateZip(change: (bytes: Uint8Array, data: DataView, central: number[]) => void, entries: Zippable = { 'a.png': image }, level: 0 | 6 = 0): File {
  const bytes = zipSync(entries, { level })
  change(bytes, view(bytes), centralOffsets(bytes))
  return file('test.zip', bytes)
}
function setSize(bytes: Uint8Array, data: DataView, central: number, size: number): void {
  data.setUint32(central + 24, size, true)
  data.setUint32(data.getUint32(central + 42, true) + 22, size, true)
}
function fakeSize(name: string, size: number): File {
  const output = file(name)
  Object.defineProperty(output, 'size', { value: size })
  vi.spyOn(output, 'arrayBuffer')
  return output
}

describe('prepareImportFiles plain images', () => {
  it('exports the source union and result shape', async () => {
    const source: ImportSource = 'auto'
    const result: ImportFile[] = (await prepareImportFiles([])).files
    expect(source).toBe('auto')
    expect(result).toEqual([])
  })

  it('accepts multiple JPEG/PNG/WebP files, corrects MIME, preserves bytes and dates', async () => {
    const result = await prepareImportFiles(['A.JPEG', 'b.jpg', 'c.PNG', 'd.WebP'].map(name => file(name)))
    expect(result.skipped).toEqual([])
    expect(result.files.map(item => item.file.type)).toEqual(['image/jpeg', 'image/jpeg', 'image/png', 'image/webp'])
    for (const item of result.files) {
      expect(new Uint8Array(await item.file.arrayBuffer())).toEqual(image)
      expect(item.file.lastModified).toBe(123)
      expect(item.file.name).toBe(item.relativePath)
    }
  })

  it('preserves webkitRelativePath and normalizes relative Windows separators', async () => {
    const result = await prepareImportFiles([file('正面.png', image, '衣服\\中文\\正面.png')])
    expect(result.files[0].relativePath).toBe('衣服/中文/正面.png')
    expect(result.files[0].file.name).toBe('正面.png')
  })

  it('reports all nonimages, including unsupported RAR/7z, without reading them', async () => {
    const inputs = ['readme.txt', 'a.rar', 'b.7z', 'a.gif', 'README', 'constructor', 'a.constructor'].map(name => file(name))
    const reads = inputs.map(input => vi.spyOn(input, 'arrayBuffer'))
    expect(await prepareImportFiles(inputs)).toEqual({ files: [], skipped: inputs.map(input => input.name) })
    for (const read of reads) expect(read).not.toHaveBeenCalled()
  })

  it.each(['/abs.png', 'C:/a.png', 'C:a.png', '\\\\host\\share\\a.png', '../a.png', './a.png', 'a/../b.png', 'a/./b.png',
    'a//b.png', 'a\u0000.png', 'a\u001f.png', 'a\u0085.png', 'a\u202e.png', 'a\u2066.png', 'a\u061c.png', 'a:b.png'])('rejects unsafe path %j', async path => {
    await expect(prepareImportFiles([file('a.png', image, path)])).rejects.toThrow(/unsafe path/)
  })

  it('rejects long and deeply nested paths, accepting exact path/depth limits', async () => {
    const prefix = `${'a'.repeat(250)}/`.repeat(3)
    await expect(prepareImportFiles([file('a.png', image, `${prefix}${'b'.repeat(244)}.png`)])).rejects.toThrow(/unsafe path/)
    await expect(prepareImportFiles([file('a.png', image, `${'a/'.repeat(16)}a.png`)])).rejects.toThrow(/depth/)
    expect((await prepareImportFiles([file('a.png', image, `${prefix}${'b'.repeat(243)}.png`), file('b.png', image, `${'a/'.repeat(15)}b.png`)])).files).toHaveLength(2)
  })

  it('reports loose macOS metadata without reading it, even with image/ZIP extensions', async () => {
    const inputs = [file('._front.png'), file('._bundle.zip'), file('back.webp', image, 'folder/__MACOSX/back.webp')]
    const reads = inputs.map(input => vi.spyOn(input, 'arrayBuffer'))
    const result = await prepareImportFiles([...inputs, file('front.png')], 1)
    expect(result.files.map(item => item.relativePath)).toEqual(['front.png'])
    expect(result.skipped).toEqual(['._front.png', '._bundle.zip', 'folder/__MACOSX/back.webp'])
    for (const read of reads) expect(read).not.toHaveBeenCalled()
    expect(unzip).not.toHaveBeenCalled()
  })

  it('does not treat similar normal filenames as macOS metadata', async () => {
    const names = ['.front.png', '_front.png', '__MACOSX-front.png', 'folder/__MACOSX-copy/front.png']
    const result = await prepareImportFiles(names.map(path => file(path.split('/').pop()!, image, path)))
    expect(result.files.map(item => item.relativePath)).toEqual(names)
    expect(result.skipped).toEqual([])
  })

  it('normalizes plain folder paths and filenames to NFC without changing bytes', async () => {
    const result = await prepareImportFiles([file('cafe\u0301.png', image, 're\u0301fe\u0301rences/cafe\u0301.png')])
    expect(result.files[0].relativePath).toBe('références/café.png')
    expect(result.files[0].file.name).toBe('café.png')
    expect(new Uint8Array(await result.files[0].file.arrayBuffer())).toEqual(image)
    await expect(prepareImportFiles([file('café.png'), file('cafe\u0301.png')])).rejects.toThrow(/duplicate file path/)
  })

  it('limits every path segment to 255 normalized Unicode characters', async () => {
    const exactName = `${'é'.repeat(251)}.png`
    const result = await prepareImportFiles([file(exactName.normalize('NFD')), file('front.png', image, `${'衣'.repeat(255)}/front.png`),
      file(`${'😀'.repeat(251)}.png`)])
    expect(result.files[0].file.name).toBe(exactName)
    expect(result.files).toHaveLength(3)
    await expect(prepareImportFiles([file(`${'a'.repeat(252)}.png`)])).rejects.toThrow(/segment exceeds 255/)
    await expect(prepareImportFiles([file('front.png', image, `${'衣'.repeat(256)}/front.png`)])).rejects.toThrow(/segment exceeds 255/)
  })

  it('rejects duplicate plain paths', async () => {
    await expect(prepareImportFiles([file('a.png'), file('a.png')])).rejects.toThrow(/duplicate file path/)
  })

  it('checks size before reading, including the ZIP input limit', async () => {
    for (const input of [fakeSize('a.png', 20 * MiB + 1), fakeSize('a.zip', 100 * MiB + 1)]) {
      await expect(prepareImportFiles([input])).rejects.toThrow(/size limit|exceeds 20/)
      expect(input.arrayBuffer).not.toHaveBeenCalled()
    }
  })

  it('rejects arrayBuffer/file.size mismatch and read failures', async () => {
    await expect(prepareImportFiles([fakeSize('a.png', 12)])).rejects.toThrow(/size mismatch/)
    const input = file('a.png')
    vi.spyOn(input, 'arrayBuffer').mockRejectedValue(new Error('read failed'))
    await expect(prepareImportFiles([input])).rejects.toThrow('read failed')
  })

  it.each([0, -1, 1.5, 501, NaN, Infinity])('rejects invalid maxFiles %s', async max => {
    await expect(prepareImportFiles([], max)).rejects.toThrow(/maxFiles/)
  })

  it('enforces the default 500-image cap and caller smaller cap', async () => {
    await expect(prepareImportFiles([file('a.png'), file('b.png')], 1)).rejects.toThrow(/count exceeds 1/)
    const inputs = Array.from({ length: 500 }, (_, i) => file(`${i}.png`))
    expect((await prepareImportFiles(inputs)).files).toHaveLength(500)
    await expect(prepareImportFiles([...inputs, file('last.png')])).rejects.toThrow(/count exceeds 500/)
  })
})

describe('ZIP preflight and byte verification', () => {
  it('reports all macOS metadata files instead of uploading sidecars as images', async () => {
    const result = await prepareImportFiles([archive({
      '__MACOSX/': new Uint8Array(),
      '__MACOSX/衣服/._front.png': strToU8('AppleDouble resource fork'),
      '__MACOSX/preview.webp': strToU8('metadata'),
      '衣服/._back.jpeg': strToU8('AppleDouble resource fork'),
      '._notes.txt': strToU8('metadata'),
      '衣服/front.png': image,
      '衣服/back.webp': image,
    })], 2)
    expect(result.files.map(item => item.relativePath)).toEqual(['款式/衣服/front.png', '款式/衣服/back.webp'])
    expect(result.skipped).toEqual(['款式/__MACOSX/衣服/._front.png', '款式/__MACOSX/preview.webp', '款式/衣服/._back.jpeg', '款式/._notes.txt'])
  })

  it('skips metadata ZIP sidecars without mistaking them for nested archives', async () => {
    const result = await prepareImportFiles([archive({ '._source.zip': strToU8('AppleDouble'), '__MACOSX/source.zip': strToU8('metadata'), 'front.png': image })], 1)
    expect(result.files.map(item => item.relativePath)).toEqual(['款式/front.png'])
    expect(result.skipped).toEqual(['款式/._source.zip', '款式/__MACOSX/source.zip'])
  })

  it('reports metadata-only ZIP files without using an image slot', async () => {
    const result = await prepareImportFiles([file('front.png'), archive({ '._front.png': image, '__MACOSX/preview.png': image })], 1)
    expect(result.files.map(item => item.relativePath)).toEqual(['front.png'])
    expect(result.skipped).toEqual(['款式/._front.png', '款式/__MACOSX/preview.png'])
  })

  it('keeps metadata subject to traversal, CRC and size security checks', async () => {
    await expect(prepareImportFiles([archive({ '__MACOSX/../._front.png': image })])).rejects.toThrow(/unsafe path/)
    const corrupt = mutateZip((bytes, data) => { bytes[30 + data.getUint16(26, true)] ^= 1 }, { '._front.png': image })
    await expect(prepareImportFiles([corrupt])).rejects.toThrow(/CRC/)
    const oversized = mutateZip((bytes, data, [central]) => setSize(bytes, data, central, 20 * MiB + 1), { '._front.png': image }, 6)
    await expect(prepareImportFiles([oversized])).rejects.toThrow(/20 MiB/)
  })

  it('normalizes ZIP roots and entry paths while retaining raw keys for byte/CRC lookup', async () => {
    const result = await prepareImportFiles([archive({ 're\u0301fe\u0301rences/cafe\u0301.png': image, '._cafe\u0301.png': image }, 'mode\u0300les.zip', 6)])
    expect(result.files[0].relativePath).toBe('modèles/références/café.png')
    expect(result.files[0].file.name).toBe('café.png')
    expect(new Uint8Array(await result.files[0].file.arrayBuffer())).toEqual(image)
    expect(result.skipped).toEqual(['modèles/._café.png'])
  })

  it('rejects canonical-equivalent ZIP paths before unzip', async () => {
    await expect(prepareImportFiles([archive({ 'café.png': image, 'cafe\u0301.png': image })])).rejects.toThrow(/duplicate ZIP path/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('disambiguates canonically equivalent archive roots', async () => {
    const result = await prepareImportFiles([archive({ 'a.png': image }, 'café.zip'), archive({ 'a.png': image }, 'cafe\u0301.zip')])
    expect(result.files.map(item => item.relativePath)).toEqual(['café/a.png', 'café-2/a.png'])
  })

  it('enforces normalized ZIP filename and directory segment limits before unzip', async () => {
    const exactName = `${'é'.repeat(251)}.png`
    expect((await prepareImportFiles([archive({ [exactName.normalize('NFD')]: image })])).files[0].file.name).toBe(exactName)
    vi.mocked(unzip).mockClear()
    for (const path of [`${'a'.repeat(252)}.png`, `${'衣'.repeat(256)}/front.png`]) {
      await expect(prepareImportFiles([archive({ [path]: image })])).rejects.toThrow(/segment exceeds 255/)
    }
    expect(unzip).not.toHaveBeenCalled()
  })

  it.each([0, 1, 6, 9] as const)('imports Chinese front/back folders with compression level %s', async level => {
    const result = await prepareImportFiles([archive({ '中文/': new Uint8Array(), '中文/front.PNG': image, '中文/back.webp': image, '说明.txt': strToU8('说明') }, '款式.zip', level)])
    expect(result.files.map(item => item.relativePath)).toEqual(['款式/中文/front.PNG', '款式/中文/back.webp'])
    expect(result.skipped).toEqual(['款式/说明.txt'])
    expect(new Uint8Array(await result.files[0].file.arrayBuffer())).toEqual(image)
    expect(result.files.map(item => item.file.type)).toEqual(['image/png', 'image/webp'])
    expect(unzip).toHaveBeenCalledOnce()
  })

  it('supports dynamic Huffman blocks, long back-references, and asynchronous worker unzip', async () => {
    const bytes = new Uint8Array(600000)
    for (let i = 0; i < bytes.length; i++) bytes[i] = i % 73
    const result = await prepareImportFiles([archive({ 'large.png': bytes }, 'dynamic.zip', 6)])
    expect(new Uint8Array(await result.files[0].file.arrayBuffer())).toEqual(bytes)
  })

  it('accepts empty ZIP, zero-byte images, and ZIP comments', async () => {
    expect(await prepareImportFiles([archive({})])).toEqual({ files: [], skipped: [] })
    const bytes = zipSync({ 'empty.png': new Uint8Array() }, { comment: '中文 comment' })
    expect((await prepareImportFiles([file('empty.zip', bytes)])).files[0].file.size).toBe(0)
  })

  it('preserves separate archive roots, disambiguates equal stems and plain folder collisions', async () => {
    const result = await prepareImportFiles([archive({ 'front.png': image }, 'one.zip'), archive({ 'front.png': image }, 'two.zip'),
      archive({ 'front.png': image }, 'one.zip'), file('back.png', image, 'one-3/back.png'), archive({ 'front.png': image }, 'one.zip')])
    expect(result.files.map(item => item.relativePath)).toEqual(['one/front.png', 'two/front.png', 'one-2/front.png', 'one-3/back.png', 'one-4/front.png'])
  })

  it('terminates namespace resolution when an ancestor is already occupied', async () => {
    const nested = archive({ 'front.png': image }, 'b.zip')
    Object.defineProperty(nested, 'webkitRelativePath', { value: 'a/b.zip' })
    const result = await prepareImportFiles([archive({ 'front.png': image }, 'a.zip'), nested])
    expect(result.files.map(item => item.relativePath)).toEqual(['a/front.png', 'a-2/b/front.png'])
    const conflicting = archive({ 'front.png': image }, 'b.zip')
    Object.defineProperty(conflicting, 'webkitRelativePath', { value: 'plain.png/b.zip' })
    expect((await prepareImportFiles([file('plain.png'), conflicting])).files[1].relativePath).toBe('plain.png-2/b/front.png')
  })

  it('keeps archive input folders in its namespace and checks the prefixed path limit', async () => {
    const input = archive({ 'a.png': image })
    Object.defineProperty(input, 'webkitRelativePath', { value: 'drop/款式.zip' })
    expect((await prepareImportFiles([input])).files[0].relativePath).toBe('drop/款式/a.png')
    await expect(prepareImportFiles([archive({ [`${'a/'.repeat(15)}a.png`]: image })])).rejects.toThrow(/depth/)
  })

  it.each(['../a.png', '/a.png', 'C:\\a.png', '\\\\server\\a.png', './a.png', 'a/../b.png', 'a\u202e.png', 'a:b.png'])('rejects unsafe ZIP entry %j before unzip', async name => {
    await expect(prepareImportFiles([archive({ [name]: image })])).rejects.toThrow(/unsafe path/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects normalized duplicates within one archive', async () => {
    await expect(prepareImportFiles([archive({ 'a/b.png': image, 'a\\b.png': image })])).rejects.toThrow(/duplicate ZIP path/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects file/directory path collisions', async () => {
    await expect(prepareImportFiles([archive({ 'a.png': image, 'a.png/b.png': image })])).rejects.toThrow(/path collision/)
  })

  it.each(['inner.zip', 'inner.rar', 'inner.7z', 'inner.tar.gz'])('rejects nested archive %s without expansion', async name => {
    await expect(prepareImportFiles([archive({ [name]: image })])).rejects.toThrow(/nested archive/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it.each([1, 0x40, 0x2000])('rejects encrypted/unsupported flags %s before unzip', async flag => {
    const input = mutateZip((_, data, [central]) => {
      data.setUint16(central + 8, flag, true)
      data.setUint16(6, flag, true)
    })
    await expect(prepareImportFiles([input])).rejects.toThrow(/encrypted|flags/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects unsupported compression and Unix symlinks', async () => {
    const compression = mutateZip((_, data, [central]) => data.setUint16(central + 10, 12, true))
    await expect(prepareImportFiles([compression])).rejects.toThrow(/compression/)
    const link = archive({ 'link.png': [strToU8('target'), { os: 3, attrs: 0o120777 << 16 }] })
    await expect(prepareImportFiles([link])).rejects.toThrow(/symlink/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects ZIP64 and malformed extra fields', async () => {
    const zip64 = file('a.zip', zipSync({ 'a.png': [image, { extra: { 1: new Uint8Array(8) } }] }))
    await expect(prepareImportFiles([zip64])).rejects.toThrow(/ZIP64/)
    const malformed = mutateZip((_, data, [central]) => data.setUint16(central + 30, 65535, true))
    await expect(prepareImportFiles([malformed])).rejects.toThrow(/truncated/)
  })

  it('bounds central-directory entry count before iterating', async () => {
    const input = mutateZip((bytes, data) => {
      data.setUint16(bytes.length - 22 + 8, 10001, true)
      data.setUint16(bytes.length - 22 + 10, 10001, true)
    })
    await expect(prepareImportFiles([input])).rejects.toThrow(/entry count/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects oversized declared files before decompression', async () => {
    const input = mutateZip((bytes, data, [central]) => setSize(bytes, data, central, MAX_SAFE_SIZE), { 'a.png': image }, 6)
    await expect(prepareImportFiles([input])).rejects.toThrow(/20 MiB/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('includes ignored entries in the 500 MiB expanded total preflight', async () => {
    const entries = Object.fromEntries(Array.from({ length: 26 }, (_, i) => [`${i}.txt`, image]))
    const input = mutateZip((bytes, data, offsets) => offsets.forEach(central => setSize(bytes, data, central, 20 * MiB)), entries, 6)
    await expect(prepareImportFiles([input])).rejects.toThrow(/expanded total/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('checks ZIP and plain image count together before unzip', async () => {
    await expect(prepareImportFiles([file('a.png'), archive({ 'b.png': image, 'c.png': image })], 2)).rejects.toThrow(/count exceeds 2/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects forged small DEFLATE output size before fflate allocation', async () => {
    const input = mutateZip((bytes, data, [central]) => setSize(bytes, data, central, 1), { 'a.png': new Uint8Array(MiB) }, 6)
    await expect(prepareImportFiles([input])).rejects.toThrow(/expanded size/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects overstated DEFLATE output size', async () => {
    const input = mutateZip((bytes, data, [central]) => setSize(bytes, data, central, 100), { 'a.png': image }, 6)
    await expect(prepareImportFiles([input])).rejects.toThrow(/size mismatch/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('rejects damaged payload CRC, including skipped nonimages', async () => {
    for (const name of ['a.png', 'readme.txt']) {
      const input = mutateZip((bytes, data) => { bytes[30 + data.getUint16(26, true)] ^= 1 }, { [name]: image })
      await expect(prepareImportFiles([input])).rejects.toThrow(/CRC/)
    }
  })

  it('rejects a forged CRC in both headers', async () => {
    const input = mutateZip((_, data, [central]) => {
      data.setUint32(central + 16, 1, true)
      data.setUint32(14, 1, true)
    })
    await expect(prepareImportFiles([input])).rejects.toThrow(/CRC/)
  })

  it('checks actual fflate results for missing data, size mismatch and CRC mismatch', async () => {
    const outputs: Record<string, Uint8Array>[] = [{}, { 'a.png': new Uint8Array() }, { 'a.png': new Uint8Array(image.length) }]
    for (const output of outputs) {
      vi.mocked(unzip).mockImplementationOnce((...args: Parameters<typeof unzip>) => {
        const callback = args[args.length - 1] as (error: null, result: Record<string, Uint8Array>) => void
        callback(null, output)
        return () => {}
      })
      await expect(prepareImportFiles([archive({ 'a.png': image })])).rejects.toThrow(/size\/CRC/)
    }
  })

  it('rejects prototype-sensitive fflate output keys without accepting inherited data', async () => {
    const input = mutateZip((bytes, _, [central]) => {
      bytes.set(strToU8('__proto__'), 30)
      bytes.set(strToU8('__proto__'), central + 46)
    }, { '123456789': image })
    await expect(prepareImportFiles([input])).rejects.toThrow(/unsupported ZIP filename/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('validates a deterministic corpus of stored/fixed/dynamic DEFLATE blocks', async () => {
    let seed = 12345
    for (let round = 0; round < 12; round++) {
      const bytes = new Uint8Array(2000 + round * 3000)
      for (let i = 0; i < bytes.length; i++) {
        seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
        bytes[i] = round % 3 === 0 ? seed >>> 24 : round % 3 === 1 ? i % 251 : (seed >>> 24) & 3
      }
      const result = await prepareImportFiles([archive({ 'a.png': bytes }, 'corpus.zip', round % 2 ? 1 : 9)])
      expect(new Uint8Array(await result.files[0].file.arrayBuffer())).toEqual(bytes)
    }
  })

  it.each([0, 1, 10, 21])('rejects truncated ZIP with %s bytes', async size => {
    await expect(prepareImportFiles([file('a.zip', new Uint8Array(size))])).rejects.toThrow(/truncated|corrupt/)
  })

  it('rejects a truncated real ZIP and arbitrary data disguised as ZIP', async () => {
    const bytes = zipSync({ 'a.png': image })
    await expect(prepareImportFiles([file('a.zip', bytes.subarray(0, -4))])).rejects.toThrow(/truncated|corrupt/)
    await expect(prepareImportFiles([file('a.zip', new Uint8Array(100))])).rejects.toThrow(/truncated|corrupt/)
  })

  it.each(['central signature', 'local signature', 'name', 'size', 'offset', 'count', 'disk', 'trailing', 'overlap'] as const)('rejects ZIP %s corruption', async kind => {
    const input = mutateZip((bytes, data, offsets) => {
      const [central, second] = offsets, end = bytes.length - 22
      if (kind === 'central signature') data.setUint32(central, 0, true)
      if (kind === 'local signature') data.setUint32(0, 0, true)
      if (kind === 'name') bytes[30] ^= 1
      if (kind === 'size') data.setUint32(22, 100, true)
      if (kind === 'offset') data.setUint32(central + 42, central, true)
      if (kind === 'count') { data.setUint16(end + 8, 1, true); data.setUint16(end + 10, 1, true) }
      if (kind === 'disk') data.setUint16(end + 4, 1, true)
      if (kind === 'trailing') data.setUint16(end + 20, 1, true)
      if (kind === 'overlap') data.setUint32(second + 42, 0, true)
    }, { 'a.png': image, 'b.png': image })
    await expect(prepareImportFiles([input])).rejects.toThrow(/ZIP/)
    expect(unzip).not.toHaveBeenCalled()
  })

  it('accepts streamed ZIP data descriptors and rejects their corruption', async () => {
    const chunks: Uint8Array[] = []
    const zip = new Zip((error, chunk) => { if (error) throw error; chunks.push(chunk) })
    const entry = new ZipPassThrough('a.png')
    zip.add(entry)
    entry.push(image, true)
    zip.end()
    const bytes = new Uint8Array(chunks.reduce((sum, chunk) => sum + chunk.length, 0))
    let offset = 0
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
    expect((await prepareImportFiles([file('stream.zip', bytes)])).files[0].relativePath).toBe('stream/a.png')
    bytes[30 + strToU8('a.png').length + image.length + 4] ^= 1
    await expect(prepareImportFiles([file('stream.zip', bytes)])).rejects.toThrow(/descriptor/)
  })

  it('rejects invalid stored DEFLATE length complement', async () => {
    const bytes = zipSync({ 'a.png': image }, { level: 0 })
    // Replace stored ZIP payload with a valid-sized raw DEFLATE stored block,
    // then invalidate NLEN (which fflate by itself does not check).
    const raw = new Uint8Array([1, image.length, 0, 0, 0, ...image])
    const central = centralOffsets(bytes)[0], start = 35
    const changed = new Uint8Array(bytes.length + 5)
    changed.set(bytes.subarray(0, start))
    changed.set(raw, start)
    changed.set(bytes.subarray(start + image.length), start + raw.length)
    const data = view(changed), newCentral = central + 5, end = changed.length - 22
    data.setUint16(8, 8, true)
    data.setUint16(newCentral + 10, 8, true)
    data.setUint32(18, raw.length, true)
    data.setUint32(newCentral + 20, raw.length, true)
    data.setUint32(end + 16, newCentral, true)
    await expect(prepareImportFiles([file('a.zip', changed)])).rejects.toThrow(/stored block/)
    expect(unzip).not.toHaveBeenCalled()
  })
})
const MAX_SAFE_SIZE = 20 * MiB + 1

// Test fixtures are intentionally structural, like the production WebKit API.
function droppedFile(name: string, input = file(name)) {
  return { name, isFile: true, isDirectory: false, file: (success: (file: File) => void) => success(input) }
}
type TestEntry = ReturnType<typeof droppedFile> | { name: string; isFile: boolean; isDirectory: boolean; createReader: () => { readEntries: (success: (entries: TestEntry[]) => void) => void } }
function directory(name: string, batches: TestEntry[][]): TestEntry {
  return { name, isFile: false, isDirectory: true, createReader: () => {
    let i = 0
    return { readEntries: (success: (entries: TestEntry[]) => void) => success(batches[i++] ?? []) }
  } }
}
const transfer = (entries: TestEntry[]) => ({ items: entries.map(entry => ({ kind: 'file', webkitGetAsEntry: () => entry, getAsFile: () => null })), files: [] })

describe('collectDroppedFiles', () => {
  it('normalizes dragged folder paths to NFC and reports collected sidecars as skipped', async () => {
    const files = await collectDroppedFiles(transfer([directory('re\u0301fe\u0301rences', [[droppedFile('cafe\u0301.png'), droppedFile('._cafe\u0301.png')]])]))
    expect(files.map(input => input.webkitRelativePath)).toEqual(['références/café.png', 'références/._café.png'])
    const result = await prepareImportFiles(files, 1)
    expect(result.files.map(item => item.relativePath)).toEqual(['références/café.png'])
    expect(result.skipped).toEqual(['références/._café.png'])
  })

  it('rejects overlong dragged directory and filename segments', async () => {
    await expect(collectDroppedFiles(transfer([directory('a'.repeat(256), [])]))).rejects.toThrow(/segment exceeds 255/)
    await expect(collectDroppedFiles(transfer([droppedFile(`${'a'.repeat(252)}.png`) ]))).rejects.toThrow(/segment exceeds 255/)
  })

  it('recursively reads all directory batches and preserves relative paths and bytes', async () => {
    const input = file('front.png')
    const result = await collectDroppedFiles(transfer([directory('衣服', [[droppedFile('front.png', input)], [directory('背面', [[droppedFile('back.webp')]])]])]))
    expect(result.map(item => item.webkitRelativePath)).toEqual(['衣服/front.png', '衣服/背面/back.webp'])
    expect(input.webkitRelativePath).toBe('')
    expect(new Uint8Array(await result[0].arrayBuffer())).toEqual(image)
    expect((await prepareImportFiles(result)).files.map(item => item.relativePath)).toEqual(['衣服/front.png', '衣服/背面/back.webp'])
  })

  it('uses FileList fallback and mixed entry/non-entry items', async () => {
    const input = file('a.png')
    expect(await collectDroppedFiles({ files: [input] })).toEqual([input])
    expect(await collectDroppedFiles({ items: [{ kind: 'string', getAsFile: () => null }], files: [input] })).toEqual([input])
    const result = await collectDroppedFiles({ files: [], items: [
      { kind: 'file', webkitGetAsEntry: () => droppedFile('b.png'), getAsFile: () => null },
      { kind: 'file', getAsFile: () => input },
    ] })
    expect(result.map(item => item.name)).toEqual(['b.png', 'a.png'])
  })

  it('snapshots entries synchronously before asynchronous reads', async () => {
    let active = true
    const getEntry = vi.fn(() => { if (!active) throw new Error('expired'); return droppedFile('a.png') })
    const pending = collectDroppedFiles({ files: [], items: [{ kind: 'file', webkitGetAsEntry: getEntry, getAsFile: () => null }] })
    active = false
    expect(await pending).toHaveLength(1)
    expect(getEntry).toHaveBeenCalledOnce()
  })

  it('propagates readEntries and file callback errors', async () => {
    const error = new DOMException('denied')
    const badFile = { name: 'a.png', isFile: true, isDirectory: false, file: (_success: (file: File) => void, reject: (error: DOMException) => void) => reject(error) }
    const badDirectory = { name: 'folder', isFile: false, isDirectory: true, createReader: () => ({ readEntries: (_success: (entries: TestEntry[]) => void, reject: (error: DOMException) => void) => reject(error) }) }
    for (const entry of [badFile, badDirectory]) {
      await expect(collectDroppedFiles({ files: [], items: [{ kind: 'file', webkitGetAsEntry: () => entry, getAsFile: () => null }] })).rejects.toThrow('denied')
    }
  })

  it('rejects unsafe folder paths, excessive recursion, and unreadable files', async () => {
    await expect(collectDroppedFiles(transfer([directory('..', [])]))).rejects.toThrow(/unsafe/)
    let nested: TestEntry = droppedFile('a.png')
    for (let i = 0; i < 16; i++) nested = directory(`d${i}`, [[nested]])
    await expect(collectDroppedFiles(transfer([nested]))).rejects.toThrow(/depth/)
    await expect(collectDroppedFiles({ files: [], items: [{ kind: 'file', getAsFile: () => null }] })).rejects.toThrow(/unreadable/)
  })

  it('accepts a real DOM DataTransfer structurally', () => {
    const accept = (dataTransfer: DataTransfer) => collectDroppedFiles(dataTransfer)
    expect(accept).toBeTypeOf('function')
  })
})
