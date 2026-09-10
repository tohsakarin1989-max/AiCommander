type FeatureEnv = {
  VITE_ENABLE_BONUS_ACCOUNTING?: string | boolean
  VITE_ENABLE_AGENT_LAB?: string | boolean
}

function isTruthyFlag(value: string | boolean | undefined): boolean {
  if (typeof value === 'boolean') return value
  return String(value ?? '').trim().toLowerCase() === 'true'
}

export function isBonusAccountingEnabled(env: FeatureEnv = import.meta.env): boolean {
  return isTruthyFlag(env.VITE_ENABLE_BONUS_ACCOUNTING)
}

export const bonusAccountingEnabled = isBonusAccountingEnabled()

export function isAgentLabEnabled(env: FeatureEnv = import.meta.env): boolean {
  return isTruthyFlag(env.VITE_ENABLE_AGENT_LAB)
}

export function canAccessAgentLab(
  role: 'admin' | 'analyst' | 'viewer' | undefined,
  enabled = isAgentLabEnabled(),
): boolean {
  return enabled && role === 'admin'
}

export const agentLabEnabled = isAgentLabEnabled()
