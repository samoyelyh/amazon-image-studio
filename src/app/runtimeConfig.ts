import { z } from 'zod'

const runtimeEnvSchema = z.object({
  VITE_DEPLOYMENT_MODE: z.enum(['standalone', 'multiuser']).default('standalone'),
  VITE_API_BASE_URL: z.string().trim().optional().default(''),
})

const parsedRuntimeEnv = runtimeEnvSchema.parse({
  VITE_DEPLOYMENT_MODE: import.meta.env.VITE_DEPLOYMENT_MODE || undefined,
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL || undefined,
})

export const runtimeConfig = {
  deploymentMode: parsedRuntimeEnv.VITE_DEPLOYMENT_MODE,
  apiBaseUrl: parsedRuntimeEnv.VITE_API_BASE_URL.replace(/\/$/, ''),
  isStandalone: parsedRuntimeEnv.VITE_DEPLOYMENT_MODE === 'standalone',
} as const

export function normalizeBrowserBasename(baseUrl: string) {
  if (!baseUrl || baseUrl === './' || baseUrl === '/') return '/'
  return `/${baseUrl.replace(/^\/+|\/+$/g, '')}`
}
