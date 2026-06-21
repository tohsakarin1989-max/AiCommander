import api from './api'
import type { KeyLocation, KeyLocationCreate } from '../types'

export const keyLocationApi = {
  list: (params?: { location_type?: string; status?: string }) =>
    api.get<KeyLocation[]>('/key-locations', { params }).then(r => r.data),

  create: (data: KeyLocationCreate) =>
    api.post<KeyLocation>('/key-locations', data).then(r => r.data),

  update: (id: number, data: Partial<KeyLocationCreate>) =>
    api.put<KeyLocation>(`/key-locations/${id}`, data).then(r => r.data),

  delete: (id: number) =>
    api.delete(`/key-locations/${id}`).then(r => r.data),
}
