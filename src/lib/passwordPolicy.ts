const UPPER = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
const LOWER = 'abcdefghijkmnopqrstuvwxyz'
const DIGITS = '23456789'
const SPECIAL = '!@#$%^&*_-+'
const ALL = UPPER + LOWER + DIGITS + SPECIAL

function randomIndex(max: number) {
  const values = new Uint32Array(1)
  crypto.getRandomValues(values)
  return values[0] % max
}

function pick(source: string) {
  return source[randomIndex(source.length)]
}

export function generateSecurePassword(length = 16) {
  const targetLength = Math.max(12, length)
  const characters = [pick(UPPER), pick(LOWER), pick(DIGITS), pick(SPECIAL)]
  while (characters.length < targetLength) characters.push(pick(ALL))
  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swap = randomIndex(index + 1)
    ;[characters[index], characters[swap]] = [characters[swap], characters[index]]
  }
  return characters.join('')
}

export interface PasswordRule {
  label: string
  passed: boolean
}

export function passwordRules(password: string, email = '', displayName = ''): PasswordRule[] {
  const compact = password.toLowerCase().replace(/[^a-z0-9]/g, '')
  const commonWeakParts = ['password', 'passwd', 'qwerty', 'admin', 'welcome', 'letmein', '123456', '111111', 'abc123', 'iloveyou']
  const identityParts = [email.split('@')[0], displayName]
    .map((value) => value.toLowerCase().replace(/[^a-z0-9]/g, ''))
    .filter((value) => value.length >= 4)
  return [
    { label: '至少 12 位', passed: password.length >= 12 },
    { label: '包含大写字母', passed: /[A-Z]/.test(password) },
    { label: '包含小写字母', passed: /[a-z]/.test(password) },
    { label: '包含数字', passed: /\d/.test(password) },
    { label: '包含特殊字符', passed: /[^A-Za-z0-9]/.test(password) },
    { label: '不包含常见弱密码', passed: !commonWeakParts.some((part) => compact.includes(part)) },
    { label: '不包含邮箱或姓名的主要部分', passed: !identityParts.some((part) => compact.includes(part)) },
  ]
}

export function isStrongPassword(password: string, email = '', displayName = '') {
  return passwordRules(password, email, displayName).every((rule) => rule.passed)
}
