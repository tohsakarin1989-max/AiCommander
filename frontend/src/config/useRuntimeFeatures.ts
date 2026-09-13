import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { runtimeApi, type RuntimeFeatures } from '../services/runtime'
import { agentLabEnabled, bonusAccountingEnabled } from './features'

export type FeatureAvailability = 'loading' | 'unavailable' | 'disabled' | 'enabled'

export function useRuntimeFeatures() {
  const { phase } = useAuth()
  const query = useQuery({
    queryKey: ['runtime-status'],
    queryFn: runtimeApi.status,
    enabled: phase === 'authenticated',
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  })
  const features = query.isError ? undefined : query.data?.features
  const featureState = (name: keyof RuntimeFeatures, compiled = true): FeatureAvailability => {
    if (!compiled) return 'disabled'
    if (phase !== 'authenticated' || query.isPending) return 'loading'
    if (query.isError || typeof features?.[name] !== 'boolean') return 'unavailable'
    return features[name] ? 'enabled' : 'disabled'
  }
  const availability = {
    legacy_operations: featureState('legacy_operations'),
    bonus_accounting: featureState('bonus_accounting', bonusAccountingEnabled),
    agent_lab: featureState('agent_lab', agentLabEnabled),
    showcase: featureState('showcase'),
  }
  return {
    query,
    availability,
    legacyOperationsEnabled: availability.legacy_operations === 'enabled',
    bonusAccountingEnabled: availability.bonus_accounting === 'enabled',
    agentLabEnabled: availability.agent_lab === 'enabled',
  }
}
