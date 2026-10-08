import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'

export const caseLeaveMessage = '本页还有未保存输入或未确认的提交。离开后本页输入和提交凭证将丢失；请先核对保存结果。仍要离开吗？'

export function useCaseLeaveGuard(active: boolean) {
  const blocker = useBlocker(active)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm(caseLeaveMessage)) blocker.proceed()
    else blocker.reset()
  }, [blocker])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!active) return
      event.preventDefault(); event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [active])
}
