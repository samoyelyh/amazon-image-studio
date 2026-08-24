import { authenticatedFetch } from './authApi'

export interface HermesStatus {
  enabled: boolean
  available: boolean
  mode: 'suggest'
  model: string
  profile: string
  message: string
}

export interface HermesAction {
  tool: string
  arguments: Record<string, unknown>
}

export interface HermesProposal {
  id: string
  summary: string
  actions: HermesAction[]
  expected_state_signature: string
  status: 'pending' | 'applied' | 'cancelled' | 'stale' | 'failed' | string
  result: Record<string, unknown>
  error_message: string | null
  created_at: string
  applied_at: string | null
}

export interface HermesMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | string
  content: string
  metadata: Record<string, unknown>
  external_response_id: string | null
  created_at: string
  proposal: HermesProposal | null
}

export interface HermesConversation {
  id: string
  project_id: string
  title: string
  mode: string
  status: string
  created_at: string
  updated_at: string
  messages: HermesMessage[]
}

export function getHermesStatus(projectId: string) {
  return authenticatedFetch<HermesStatus>(`/attachment-workbench/projects/${projectId}/hermes/status`)
}

export function listHermesConversations(projectId: string) {
  return authenticatedFetch<HermesConversation[]>(`/attachment-workbench/projects/${projectId}/hermes/conversations`)
}

export function createHermesConversation(projectId: string) {
  return authenticatedFetch<HermesConversation>(`/attachment-workbench/projects/${projectId}/hermes/conversations`, {
    method: 'POST', body: JSON.stringify({ title: 'Hermes 智能助理' }),
  })
}

export function sendHermesMessage(projectId: string, conversationId: string, content: string) {
  return authenticatedFetch<HermesConversation>(`/attachment-workbench/projects/${projectId}/hermes/conversations/${conversationId}/messages`, {
    method: 'POST', body: JSON.stringify({ content }),
  })
}

export function applyHermesProposal(projectId: string, proposalId: string) {
  return authenticatedFetch(`/attachment-workbench/projects/${projectId}/hermes/proposals/${proposalId}/apply`, { method: 'POST' })
}

export function cancelHermesProposal(projectId: string, proposalId: string) {
  return authenticatedFetch<HermesProposal>(`/attachment-workbench/projects/${projectId}/hermes/proposals/${proposalId}/cancel`, { method: 'POST' })
}
