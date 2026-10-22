import type { TrainingKnowledge } from './training-knowledge'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type CurrentTrainingItem = {
  exercise_name: string
  sets: number
  repetitions: string
  load_guidance: string
  rest_seconds: number
  position: number
  equipment_requirement?: string | null
  equipment_model_id?: string | null
}

export type CurrentTrainingPlan = TrainingKnowledge & {
  plan_id: string
  version_number: number
  status: 'current'
  name: string
  objective: string
  responsible_instructor_name: string | null
  approved_at: string | null
  items: CurrentTrainingItem[]
}

export type TrainingPlanDraft = Omit<CurrentTrainingPlan, 'status'> & {
  id: string
  revision: number
  submitted_for_review_at: string | null
  preview?: string | null
  validation_error?: string | null
  status: 'proposal'
  origin: 'ai' | 'instructor'
}

export async function submitTrainingDraft(accessToken: string, id: string, revision: number): Promise<TrainingPlanDraft> {
  const response = await fetch(`${apiBaseUrl}/training/drafts/${encodeURIComponent(id)}/submit`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision }),
  })
  if (response.status === 401) throw new Error('Sua sessão expirou. Entre novamente para continuar.')
  if (response.status === 403 || response.status === 404) throw new Error('Você não tem permissão para enviar este rascunho.')
  if (response.status === 409) throw new Error('O rascunho mudou. Recarregue a página e confira a versão atual antes de enviar.')
  if (response.status === 422) throw new Error('Este rascunho contém exercícios inválidos. Gere uma nova ficha antes de enviar para revisão.')
  if (!response.ok) throw new Error('Não foi possível enviar o treino para revisão. Tente novamente.')
  return response.json() as Promise<TrainingPlanDraft>
}

export async function createInitialTrainingProposal(accessToken: string): Promise<TrainingPlanDraft> {
  const response = await fetch(`${apiBaseUrl}/training/initial-proposal`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (response.status === 401) throw new Error('Sua sessão expirou. Entre novamente para continuar.')
  if (response.status === 403) throw new Error('Você não tem permissão para gerar seu rascunho de treino.')
  if (response.status === 502) throw new Error('A ficha gerada não passou pela validação automática. Tente gerar novamente; seu treino atual não foi alterado.')
  if (response.status === 422) {
    let detail: unknown
    try { detail = (await response.json() as { detail?: unknown }).detail } catch { /* Use the validation message when no structured detail is available. */ }
    if (detail === 'Completed onboarding is required before generating a training proposal') throw new Error('Conclua seu onboarding antes de gerar seu rascunho de treino.')
    throw new Error('A ficha gerada não passou pela validação automática. Tente gerar novamente; seu treino atual não foi alterado.')
  }
  if (response.status === 503) throw new Error('A geração por IA está indisponível no momento. Tente novamente.')
  if (!response.ok) throw new Error('Não foi possível gerar seu rascunho de treino. Tente novamente.')
  return response.json() as Promise<TrainingPlanDraft>
}

export async function getCurrentTrainingPlan(accessToken: string): Promise<CurrentTrainingPlan | null> {
  const response = await fetch(`${apiBaseUrl}/training/current`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (response.status === 401) throw new Error('Sua sessão expirou. Entre novamente para continuar.')
  if (response.status === 403) throw new Error('Você não tem permissão para acessar seu treino.')
  if (!response.ok) throw new Error('Não foi possível carregar seu treino. Tente novamente.')
  const payload = await response.json() as { plan: CurrentTrainingPlan | null }
  return payload.plan
}

export async function getOwnTrainingDrafts(accessToken: string): Promise<TrainingPlanDraft[]> {
  const response = await fetch(`${apiBaseUrl}/training/drafts`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (response.status === 401) throw new Error('Sua sessão expirou. Entre novamente para continuar.')
  if (response.status === 403) throw new Error('Você não tem permissão para acessar seus rascunhos.')
  if (!response.ok) throw new Error('Não foi possível carregar seus rascunhos de treino. Tente novamente.')
  return response.json() as Promise<TrainingPlanDraft[]>
}
