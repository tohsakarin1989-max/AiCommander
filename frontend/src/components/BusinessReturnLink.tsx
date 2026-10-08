import { Link, useSearchParams } from 'react-router-dom'
import { safeBusinessReturn } from '../services/businessNavigation'

export default function BusinessReturnLink() {
  const [params] = useSearchParams()
  const target = safeBusinessReturn(params.get('return_to'))
  return target ? <Link className="btn-ghost" to={target}>返回来源位置</Link> : null
}
