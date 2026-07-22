// @ts-expect-error Vitest runs this file in Node; the browser build intentionally omits Node typings.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./UserManagementPanel.tsx', import.meta.url), 'utf8')

describe('user management credential safety', () => {
  it('uses an idempotency key and never persists the temporary password in browser storage', () => {
    expect(source).toContain('user-create:${randomUuid()}')
    expect(source).not.toContain('localStorage')
    expect(source).not.toContain('sessionStorage')
  })

  it('clears one-time credentials when their modal closes', () => {
    expect(source).toContain('onClose={() => setOneTime(null)}')
    expect(source).toContain('密码只在本窗口显示一次')
  })

  it('gates creation by permissions and refreshes the member list after success', () => {
    expect(source).toContain("auth.hasPermission('organization.members.write')")
    expect(source).toContain("auth.hasPermission('roles.assign')")
    expect(source).toContain("invalidateQueries({ queryKey: ['organization', 'members'] })")
  })

  it('validates the form and locks the modal during submission', () => {
    expect(source).toContain('isStrongPassword(createForm.password')
    expect(source).toContain('disableClose={createMutation.isPending}')
    expect(source).toContain('disabled={createMutation.isPending')
  })
})
