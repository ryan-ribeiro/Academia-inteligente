import type { TrainingKnowledge } from './training-knowledge'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type TrainingAdaptation = TrainingKnowledge & {
  id: string
  status: string
  source_client_request_id: string
  explanation: string
  preview: string
  reason: string
  base_items: Array<{ position: number; exercise_name: string; sets: number; repetitions: string; load_guidance: string; rest_seconds: number }>
  operations: Array<{
    operation_type: 'add' | 'remove' | 'replace' | 'adjust'
    target_position: number | null
    exercise_name: string | null
    sets?: number | null
    repetitions?: string | null
    load_guidance?: string | null
    rest_seconds?: number | null
    equipment_requirement?: string | null
    equipment_model_id?: string | null
    equipment_model_name?: string | null
    is_existing_exercise?: boolean | null
  }>
}

async function adaptationError(response: Response): Promise<never> {
  if (response.status === 401) throw new Error('Sua sessão expirou. Entre novamente para continuar.')
  if (response.status === 403) throw new Error('Você não tem permissão para esta alteração.')
  if (response.status === 409) throw new Error('Já existe um rascunho ou o treino mudou. Recarregue e revise antes de continuar.')
  if (response.status === 422) throw new Error('Você precisa ter um treino atual antes de solicitar uma alteração.')
  if (response.status === 503) throw new Error('A proposta de alteração está indisponível no momento. Tente novamente.')
  throw new Error('Não foi possível processar a proposta de alteração. Tente novamente.')
}

export async function getOwnAdaptations(accessToken: string): Promise<TrainingAdaptation[]> {
  const response = await fetch(`${apiBaseUrl}/training/adaptations`, { headers: { Authorization: `Bearer ${accessToken}` } })
  if (!response.ok) return adaptationError(response)
  return response.json() as Promise<TrainingAdaptation[]>
}

export async function createAdaptation(accessToken: string, reason: string, sourceRequestId: string, clientRequestId: string): Promise<TrainingAdaptation> {
  const response = await fetch(`${apiBaseUrl}/training/adaptations`, { method: 'POST', headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ reason, source_client_request_id: sourceRequestId, client_request_id: clientRequestId }) })
  if (!response.ok) return adaptationError(response)
  return response.json() as Promise<TrainingAdaptation>
}

export async function decideAdaptation(accessToken: string, id: string, accept: boolean): Promise<TrainingAdaptation> {
  const response = await fetch(`${apiBaseUrl}/training/adaptations/${id}/client-decision`, { method: 'POST', headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ accept }) })
  if (!response.ok) return adaptationError(response)
  return response.json() as Promise<TrainingAdaptation>
}
