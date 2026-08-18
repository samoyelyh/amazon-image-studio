import { Navigate, useParams, useSearchParams } from 'react-router-dom'

export default function SmartImageVariationPage() {
  const { sessionId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const next = new URLSearchParams({ sourceSession: sessionId })
  const sourceAsset = searchParams.get('sourceAsset')
  const sourceGroup = searchParams.get('sourceGroup')
  if (sourceAsset) next.set('sourceAsset', sourceAsset)
  if (sourceGroup) next.set('sourceGroup', sourceGroup)
  return <Navigate to={`/workspaces/listing/variations?${next}`} replace />
}
