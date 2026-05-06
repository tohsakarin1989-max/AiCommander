import api from './api'
import type { SecurityPersonnel, SecurityPersonnelCreate } from '../types'

export const personnelApi = {
  list: (params?: { status?: string; department?: string }) =>
    api.get<SecurityPersonnel[]>('/personnel', { params }).then(r => r.data),

  create: (data: SecurityPersonnelCreate) =>
    api.post<SecurityPersonnel>('/personnel', data).then(r => r.data),

  update: (id: number, data: Partial<SecurityPersonnelCreate>) =>
    api.put<SecurityPersonnel>(`/personnel/${id}`, data).then(r => r.data),

  delete: (id: number) =>
    api.delete(`/personnel/${id}`).then(r => r.data),
}
