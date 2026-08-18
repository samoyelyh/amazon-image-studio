export async function resolveBatchTryOnAssetId(
  cache: Map<string, string>,
  localAssetKey: string,
  existingServerAssetId: string | undefined,
  upload: () => Promise<string>,
): Promise<string> {
  const existing = existingServerAssetId || cache.get(localAssetKey)
  if (existing) {
    cache.set(localAssetKey, existing)
    return existing
  }
  const uploaded = await upload()
  cache.set(localAssetKey, uploaded)
  return uploaded
}
