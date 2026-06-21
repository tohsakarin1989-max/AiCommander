type FeatureEnv = {
  VITE_ENABLE_BONUS_ACCOUNTING?: string | boolean
}

function isTruthyFlag(value: string | boolean | undefined): boolean {
  if (typeof value === 'boolean') return value
  return String(value ?? '').trim().toLowerCase() === 'true'
}

export function isBonusAccountingEnabled(env: FeatureEnv = import.meta.env): boolean {
  return isTruthyFlag(env.VITE_ENABLE_BONUS_ACCOUNTING)
}

export const bonusAccountingEnabled = isBonusAccountingEnabled()
