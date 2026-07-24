import { authenticatedFetch, type AuthMembership } from './authApi'

export type OrganizationRole = 'organization_admin' | 'manager' | 'member' | 'viewer'

export const getCurrentOrganizationMembers = () =>
  authenticatedFetch<AuthMembership[]>('/organizations/current/members')

export const createOrganizationMember = (
  input: { email: string; display_name: string; temporary_password: string; role_code: OrganizationRole },
  idempotencyKey: string,
) => authenticatedFetch<AuthMembership>('/organizations/current/members', {
  method: 'POST',
  headers: { 'Idempotency-Key': idempotencyKey },
  body: JSON.stringify(input),
})

export const updateOrganizationMemberRole = (memberId: string, roleCode: OrganizationRole) =>
  authenticatedFetch<AuthMembership>(`/organizations/current/members/${memberId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role_code: roleCode }),
  })

export const updateOrganizationMemberStatus = (memberId: string, status: 'active' | 'disabled') =>
  authenticatedFetch<AuthMembership>(`/organizations/current/members/${memberId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })

export const resetOrganizationMemberPassword = (memberId: string, temporaryPassword: string) =>
  authenticatedFetch<{ user_id: string; must_change_password: boolean }>(
    `/organizations/current/members/${memberId}/reset-password`,
    {
      method: 'POST',
      body: JSON.stringify({ temporary_password: temporaryPassword, force_change_password: true }),
    },
  )

export const removeOrganizationMember = (memberId: string) =>
  authenticatedFetch<void>(`/organizations/current/members/${memberId}`, { method: 'DELETE' })
