import { afterEach, expect, it, vi } from 'vitest'
import { agentRequestId, canConfirmAgentRun, confirmAgentRun, sendAgentMessage, sendAgentChatMessage, type AgentRun, type AgentStatus } from './agentControlApi'
import { authenticatedFetch } from './authApi'
vi.mock('./authApi', () => ({ authenticatedFetch: vi.fn() }))
afterEach(() => vi.restoreAllMocks())
const status: AgentStatus = { enabled: true, writes_enabled: false, model_calls_enabled: false, planner_mode: 'mock', checkpoint_configured: true }
export const fixture: AgentRun = { id: 'run', conversation_id: 'conversation', status: 'awaiting_confirmation', revision: 1, planner_mode: 'mock',
  plan: { schema_version: 1, summary: '生成套图', actions: [{ tool: 'submit_tryon_batch', arguments: {} }], image_count: 4, may_charge: true, cost_note: '需要确认费用' },
  result: {}, error_code: null, state_signature: 'a'.repeat(64), confirmation_token: 'b'.repeat(64), events: [], jobs: [], workspace_url: null }
it('never treats a mock planner as free image execution', () => {
  expect(canConfirmAgentRun(fixture, status)).toBe(false)
  expect(canConfirmAgentRun(fixture, { ...status, writes_enabled: true })).toBe(false)
  expect(canConfirmAgentRun(fixture, { ...status, writes_enabled: true, model_calls_enabled: true })).toBe(true)
})
it('uses server credentials and stable plan fields rather than sending arbitrary action arguments', async () => {
  vi.mocked(authenticatedFetch).mockResolvedValue(fixture)
  await confirmAgentRun(fixture)
  const calls = vi.mocked(authenticatedFetch).mock.calls
  const [, init] = calls[calls.length - 1]
  expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 1, state_signature: fixture.state_signature, confirmation_token: fixture.confirmation_token })
})
it('rejects a missing confirmation capability before any request', async () => {
  await expect(confirmAgentRun({ ...fixture, confirmation_token: null })).rejects.toThrow()
})
it('creates IDs without secure-context-only randomUUID', () => {
  vi.stubGlobal('crypto', { getRandomValues: (a: Uint8Array) => { a.fill(17); return a } })
  expect(agentRequestId()).toMatch(/^[0-9a-f-]{36}$/)
  vi.unstubAllGlobals()
})
it('sends an explicit suggestion-only mode and versioned clarification reference without arbitrary action arguments', async()=>{
  vi.mocked(authenticatedFetch).mockResolvedValue(fixture)
  await sendAgentChatMessage('conversation',{content:'给我建议',client_request_id:'key',attachment_ids:[],request_mode:'suggest',reply_to_run_id:'r',reply_to_revision:2})
  const calls=vi.mocked(authenticatedFetch).mock.calls
  const body=JSON.parse(String(calls[calls.length-1][1]?.body))
  expect(body).toEqual({content:'给我建议',client_request_id:'key',attachment_ids:[],request_mode:'suggest',reply_to_run_id:'r',reply_to_revision:2,chat_mode:true,auto_execute:true})
  expect(body).not.toHaveProperty('actions');expect(body).not.toHaveProperty('preset_id')
})
it('keeps the ordinary message payload compatible when assistance fields are absent',async()=>{
  vi.mocked(authenticatedFetch).mockResolvedValue(fixture)
  await sendAgentChatMessage('conversation',{content:'生成图片',client_request_id:'key',attachment_ids:[]})
  const calls=vi.mocked(authenticatedFetch).mock.calls
  const body=JSON.parse(String(calls[calls.length-1][1]?.body))
  expect(body).not.toHaveProperty('request_mode');expect(body).not.toHaveProperty('reply_to_run_id')
})
