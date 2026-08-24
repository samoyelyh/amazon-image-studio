import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearAccessToken } from './authApi'
import {
  applyHermesProposal,
  cancelHermesProposal,
  createHermesConversation,
  getHermesStatus,
  listHermesConversations,
  sendHermesMessage,
} from './hermesAgentApi'

afterEach(() => {
  clearAccessToken()
  vi.unstubAllGlobals()
})

function ok(body: unknown = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('Hermes attachment agent API', () => {
  it('keeps all Hermes calls behind the authenticated application backend', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok([])))
    vi.stubGlobal('fetch', fetchMock)

    await getHermesStatus('project-1')
    await listHermesConversations('project-1')
    await createHermesConversation('project-1')
    await sendHermesMessage('project-1', 'conversation-1', '先策划，不要生成')
    await applyHermesProposal('project-1', 'proposal-1')
    await cancelHermesProposal('project-1', 'proposal-2')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/attachment-workbench/projects/project-1/hermes/status',
      '/api/v1/attachment-workbench/projects/project-1/hermes/conversations',
      '/api/v1/attachment-workbench/projects/project-1/hermes/conversations',
      '/api/v1/attachment-workbench/projects/project-1/hermes/conversations/conversation-1/messages',
      '/api/v1/attachment-workbench/projects/project-1/hermes/proposals/proposal-1/apply',
      '/api/v1/attachment-workbench/projects/project-1/hermes/proposals/proposal-2/cancel',
    ])
    expect(fetchMock.mock.calls.every((call) => !String(call[0]).includes('8642'))).toBe(true)
    expect(JSON.parse((fetchMock.mock.calls[3][1] as RequestInit).body as string)).toEqual({
      content: '先策划，不要生成',
    })
  })
})
