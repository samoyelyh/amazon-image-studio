import { afterEach, expect, it, vi } from 'vitest'
import { zipSync } from 'fflate'
import { downloadAuthenticatedFile, responseFilename, withPartialExportConfirmation, downloadErrorMessage } from './serverDownloads'
import { authenticatedFetchResponse, AuthApiError } from './authApi'

vi.mock('./authApi', async (importOriginal) => ({ ...await importOriginal<typeof import('./authApi')>(), authenticatedFetchResponse: vi.fn() }))
vi.mock('./contentApi', () => ({ fetchAssetBlob: vi.fn() }))

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks() })

it('uses the standard UTF-8 filename* response header', async () => {
  const link = { href: '', download: '', click: vi.fn(), remove: vi.fn() }
  vi.stubGlobal('document', { createElement: () => link, body: { appendChild: vi.fn() } })
  vi.stubGlobal('window', { setTimeout: vi.fn() })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fixture')
  vi.mocked(authenticatedFetchResponse).mockResolvedValue(new Response('fixture', { headers: {
    'Content-Disposition': `attachment; filename="fallback.zip"; filename*=UTF-8''${encodeURIComponent('礼品模板.zip')}`,
  } }))
  await downloadAuthenticatedFile('/fixture', 'local.zip')
  expect(link.download).toBe('礼品模板.zip')
})

it('rejects truncated ZIP before saving and retains the request ID', async () => {
  vi.mocked(authenticatedFetchResponse).mockResolvedValue(new Response('PKbroken', { headers: {
    'Content-Type': 'application/zip', 'X-Request-ID': 'test-download-123',
  } }))
  await expect(downloadAuthenticatedFile('/fixture')).rejects.toMatchObject({ code: 'download.interrupted', requestId: 'test-download-123' })
})

it('checks declared file length', async () => {
  vi.mocked(authenticatedFetchResponse).mockResolvedValue(new Response('image', { headers: { 'Content-Length': '900' } }))
  await expect(downloadAuthenticatedFile('/fixture')).rejects.toMatchObject({ code: 'download.interrupted' })
})

it('accepts an actual complete ZIP with unicode names', async () => {
  const link = { click: vi.fn(), remove: vi.fn() }
  vi.stubGlobal('document', { createElement: () => link, body: { appendChild: vi.fn() } })
  vi.stubGlobal('window', { setTimeout: vi.fn() })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fixture')
  vi.mocked(authenticatedFetchResponse).mockResolvedValue(new Response(zipSync({ '中文.png': new Uint8Array([1, 2]) }) as BodyInit,
    { headers: { 'Content-Type': 'application/zip', 'X-Batch-Try-On-Exported': '1' } }))
  expect((await downloadAuthenticatedFile('/fixture')).exported).toBe(1)
  expect(link.click).toHaveBeenCalledOnce()
})

it('never silently accepts partial export; asks before retrying', async () => {
  const confirm = vi.fn().mockReturnValue(true)
  vi.stubGlobal('window', { confirm })
  const download = vi.fn().mockRejectedValueOnce(new AuthApiError(409, 'batch_tryon.export_partial_confirmation_required', '2/3 completed'))
    .mockResolvedValue('archive')
  expect(await withPartialExportConfirmation(download)).toBe('archive')
  expect(download.mock.calls).toEqual([[false], [true]])
  confirm.mockReturnValue(false)
  download.mockRejectedValueOnce(new AuthApiError(409, 'batch_tryon.export_partial_confirmation_required', 'partial'))
  expect(await withPartialExportConfirmation(download)).toBeNull()
})

it('preserves server error details and displays correlation for support', async () => {
  const error = new AuthApiError(502, 'batch_tryon.export_asset_missing', '图片缺失', { stage: 'read_asset' }, 'rid-1')
  vi.mocked(authenticatedFetchResponse).mockRejectedValue(error)
  await expect(downloadAuthenticatedFile('/fixture')).rejects.toBe(error)
  expect(downloadErrorMessage(error)).toContain('rid-1')
  expect(responseFilename(new Response('', { headers: { 'Content-Disposition': 'attachment; filename="ascii.zip"' } }))).toBe('ascii.zip')
})
