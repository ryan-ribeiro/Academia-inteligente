import { ApiRequestError } from './clients'
import type { CurrentTrainingItem } from './training-plan'
import type { TrainingKnowledge } from './training-knowledge'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
export type ReviewItem = Omit<CurrentTrainingItem, 'position'> & {
  equipment_requirement: string | null
  equipment_model_id: string | null
}
export type ReviewContent = { name: string; objective: string; items: ReviewItem[] }
export type PendingPlan = ReviewContent & TrainingKnowledge & {
  id: string; plan_id: string; version_number: number; revision: number
  client_name: string; source: 'ai' | 'instructor' | 'adaptation'
  created_at: string; updated_at: string
  current_responsible_instructor_name: string | null
  append_target?: (ReviewContent & { id: string; revision: number }) | null
}
export type PendingPage = { items: PendingPlan[]; next_offset: number | null }

async function request<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}/training${path}`, {
    ...init, cache: 'no-store', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    const message = response.status === 409 ? 'Este rascunho mudou. Recarregue e revise antes de continuar.'
      : response.status === 404 ? 'Este rascunho não está mais pendente. Recarregue a lista.'
      : response.status === 422 ? 'Verifique os campos. Itens novos ou alterados exigem equipamento com unidade ativa e operacional. Recarregue as opções de equipamento.'
      : response.status === 401 ? 'Sua sessão expirou. Entre novamente.'
      : response.status === 403 ? 'Você não tem permissão para revisar planos.'
      : 'Não foi possível concluir a revisão. Tente novamente.'
    throw new ApiRequestError(message, response.status)
  }
  return response.json() as Promise<T>
}
export const getPendingPlans = (token: string, offset = 0) => request<PendingPage>(token, `/pending?limit=20&offset=${offset}`)
export const getPendingPlan = (token: string, id: string) => request<PendingPlan>(token, `/pending/${id}`)
export const savePendingPlan = (token: string, plan: PendingPlan, content: ReviewContent) => request<PendingPlan>(token, `/plans/${plan.plan_id}/versions/${plan.version_number}`, { method: 'PATCH', body: JSON.stringify({ ...content, expected_revision: plan.revision }) })
export const approvePendingPlan = (token: string, plan: PendingPlan) => request<PendingPlan>(token, `/plans/${plan.plan_id}/versions/${plan.version_number}/approve`, { method: 'POST', body: JSON.stringify({ expected_revision: plan.revision }) })
export const appendPendingToCurrent = (token: string, plan: PendingPlan, selectedPositions: number[]) => request<PendingPlan>(token, `/pending/${plan.id}/append-to-current`, { method: 'POST', body: JSON.stringify({ expected_revision: plan.revision, current_version_id: plan.append_target?.id, expected_current_revision: plan.append_target?.revision, selected_positions: selectedPositions }) })
