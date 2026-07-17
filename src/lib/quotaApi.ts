import { authenticatedFetch } from './authApi'

export interface QuotaAccount {
  id: string
  organization_id: string
  balance: number
  reserved_balance: number
  available_balance: number
  version: number
  updated_at: string
}

export interface QuotaRule {
  id: string
  organization_id: string | null
  operation_code: string
  name: string
  base_cost: number
  model_multipliers: Record<string, unknown>
  quality_multipliers: Record<string, unknown>
  resolution_multipliers: Record<string, unknown>
  resource_pool_multipliers: Record<string, unknown>
  effective_from: string
  effective_to: string | null
}

export interface CostEstimate {
  operation_code: string
  rule_id: string
  quantity: number
  base_cost: number
  unit_cost: number
  estimated_cost: number
  multipliers: Record<string, string>
  available_balance: number
  sufficient: boolean
}

export interface QuotaTransaction {
  id: string
  reservation_id: string | null
  transaction_type: string
  amount: number
  balance_delta: number
  reserved_delta: number
  balance_after: number
  reserved_after: number
  operation_code: string | null
  reference_type: string | null
  reference_id: string | null
  metadata_json: Record<string, unknown> | null
  created_by: string | null
  created_at: string
}

export interface QuotaReservation {
  id: string
  operation_code: string
  quantity: number
  actual_quantity: number | null
  unit_cost: number
  reserved_amount: number
  consumed_amount: number
  released_amount: number
  refunded_amount: number
  status: string
  factors_json: Record<string, unknown>
  reference_type: string | null
  reference_id: string | null
  expires_at: string
  settled_at: string | null
  created_at: string
  updated_at: string
}

export interface QuotaPackage { id: string; code: string; name: string; quota_amount: number; price: string; currency: string; valid_days: number | null }
export interface QuotaTransactionPage { items: QuotaTransaction[]; total: number; limit: number; offset: number }
export interface QuotaReservationPage { items: QuotaReservation[]; total: number; limit: number; offset: number }

export const getQuotaAccount = () => authenticatedFetch<QuotaAccount>('/quota/account')
export const getQuotaRules = () => authenticatedFetch<QuotaRule[]>('/quota/rules')
export const getQuotaPackages = () => authenticatedFetch<QuotaPackage[]>('/quota/packages')
export const getQuotaTransactions = () => authenticatedFetch<QuotaTransactionPage>('/quota/transactions')
export const getQuotaReservations = () => authenticatedFetch<QuotaReservationPage>('/quota/reservations')

export function estimateQuota(input: { operation_code: string; quantity: number; quality?: string; resolution?: string; resource_pool?: string }) {
  return authenticatedFetch<CostEstimate>('/quota/estimate', { method: 'POST', body: JSON.stringify(input) })
}

export function adjustQuota(input: { transaction_type: 'grant' | 'recharge' | 'adjust' | 'expire'; amount: number; idempotency_key: string; reason: string }) {
  return authenticatedFetch<{ account: QuotaAccount; transaction: QuotaTransaction }>('/quota/adjustments', {
    method: 'POST', body: JSON.stringify(input),
  })
}
