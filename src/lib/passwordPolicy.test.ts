import { describe, expect, it, vi } from 'vitest'
import { generateSecurePassword, isStrongPassword, passwordRules } from './passwordPolicy'

describe('password policy', () => {
  it('generates strong passwords without ambiguous characters', () => {
    vi.stubGlobal('crypto', { getRandomValues: (values: Uint32Array) => { values[0] = Math.floor(Math.random() * 2 ** 30); return values } })
    for (let index = 0; index < 25; index += 1) {
      const password = generateSecurePassword()
      expect(password).toHaveLength(16)
      expect(password).not.toMatch(/[O01lI]/)
      expect(isStrongPassword(password)).toBe(true)
    }
    vi.unstubAllGlobals()
  })

  it('rejects identity-derived and incomplete passwords', () => {
    expect(isStrongPassword('AliceStore9!x', 'alice@example.com', 'Alice Store')).toBe(false)
    const rules = passwordRules('lowercase-only', '', '')
    expect(rules.filter((rule) => !rule.passed).length).toBeGreaterThan(1)
  })
})
