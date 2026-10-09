import { useCallback, useEffect, useRef, useState } from 'react'

/** Only acknowledged server drafts survive navigation; never persist case text in browser storage. */
export function useCaseIntakeSession() {
  const [entryDirty, updateDirty] = useState(false)
  const [changeVersion, setChangeVersion] = useState(0)
  const manualFields = useRef(new Set<string>())
  const setEntryDirty = useCallback((dirty: boolean) => {
    updateDirty(dirty)
    if (dirty) setChangeVersion(version => version + 1)
  }, [])
  const onManualChange = useCallback((changes: Record<string, unknown>) => {
    Object.keys(changes).forEach(field => manualFields.current.add(field))
    setEntryDirty(true)
  }, [setEntryDirty])
  return { entryDirty, changeVersion, setEntryDirty, manualFields, onManualChange }
}

export function useCaseDraftAutosave({ enabled, blocked, changeVersion, save, delay = 1500 }: {
  enabled: boolean; blocked: boolean; changeVersion: number; save: () => Promise<unknown>; delay?: number
}) {
  const latestSave = useRef(save)
  latestSave.current = save
  useEffect(() => {
    if (!enabled || blocked) return
    const timer = setTimeout(() => { void latestSave.current() }, delay)
    return () => clearTimeout(timer)
  }, [enabled, blocked, changeVersion, delay])
}
