import type { TrainingKnowledge } from './training-knowledge'
import type { TrainingPlanDraft } from './training-plan'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type TrainingChatMessage = TrainingKnowledge & {
  role: 'user' | 'assistant'
  content: string
  created_at: string
  client_request_id?: string | null
  reply_to_client_request_id?: string | null
  adaptation_suggested?: boolean
  adaptation_reason?: string | null
}

export type TrainingChat = { messages: TrainingChatMessage[]; draft?: TrainingPlanDraft | null }

async function chatError(response: Response, fallback: string): Promise<never> {
  if (response.status === 401) throw new Error('Sua sessão expirou. Entre novamente para continuar.')
  if (response.status === 403) throw new Error('Você não tem permissão para acessar o assistente de treino.')
  if (response.status === 409) throw new Error('Seu rascunho mudou durante a resposta. Recarregue o treino e revise antes de tentar novamente.')
  if (response.status === 422) throw new Error('A resposta da IA não pôde ser validada. Tente novamente; seu treino não foi alterado.')
  if (response.status === 503) throw new Error('O assistente de treino está indisponível no momento. Tente novamente.')
  throw new Error(fallback)
}

export async function getOwnTrainingChat(accessToken: string): Promise<TrainingChat> {
  const response = await fetch(`${apiBaseUrl}/training/chat`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (!response.ok) return chatError(response, 'Não foi possível carregar sua conversa. Tente novamente.')
  return response.json() as Promise<TrainingChat>
}

export async function sendTrainingChatMessage(
  accessToken: string,
  message: string,
  clientRequestId: string,
): Promise<TrainingChat> {
  const response = await fetch(`${apiBaseUrl}/training/chat/messages`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, client_request_id: clientRequestId }),
  })
  if (!response.ok) return chatError(response, 'Não foi possível enviar sua mensagem. Tente novamente.')
  return response.json() as Promise<TrainingChat>
}
