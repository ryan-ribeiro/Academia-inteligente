import { Box, Button, Card, CardContent, CircularProgress, Stack, TextField, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { WorkspaceIcon } from './components/workspace-presentation'
import { ClientShell } from './components/application-shell'
import { RouterButtonLink } from './components/router-button-link'
import { TrainingKnowledgeSources } from './components/training-knowledge-sources'
import { TrainingChatContent } from './components/training-chat-content'
import { TrainingDraftReviewActions } from './components/training-draft-review-actions'
import { TrainingExerciseTable, trainingRows, trainingTitle } from './components/training-exercise-table'
import { ChatMessage, EmptyState, LoadingState, PageHeader, StatusNotice } from './components/ui'
import { getOwnTrainingChat, sendTrainingChatMessage, type TrainingChat } from './training-chat'
import { createAdaptation, decideAdaptation, getOwnAdaptations, type TrainingAdaptation } from './training-adaptation'
import { getCurrentTrainingPlan } from './training-plan'
import { useChatAutoScroll } from './use-chat-auto-scroll'

type TrainingChatPageProps = { accessToken: string; onSignOut: () => void }

function requestId(): string { return crypto.randomUUID() }

const adaptationStatuses: Record<string, string> = {
  proposed: 'Aguardando sua revisão',
  pending_instructor_review: 'Aguardando revisão do instrutor',
  client_rejected: 'Você recusou esta proposta',
  instructor_rejected: 'Proposta recusada pelo instrutor',
  approved: 'Aprovada pelo instrutor',
  superseded: 'Substituída por uma nova solicitação ou versão',
}

export function TrainingChatPage({ accessToken, onSignOut }: TrainingChatPageProps) {
  const [chat, setChat] = useState<TrainingChat | null>(null)
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState<{ message: string; id: string } | null>(null)
  const [retry, setRetry] = useState<{ message: string; id: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adaptations, setAdaptations] = useState<TrainingAdaptation[]>([])
  const [hasCurrentPlan, setHasCurrentPlan] = useState<boolean | null>(null)
  const [creatingProposal, setCreatingProposal] = useState(false)
  const [reviewingProposal, setReviewingProposal] = useState<string | null>(null)
  const proposalRequestIds = useRef(new Map<string, string>())
  const chatEndRef = useChatAutoScroll(chat?.messages.length ?? 0, pending !== null)

  useEffect(() => {
    let active = true
    void Promise.all([getOwnTrainingChat(accessToken), getOwnAdaptations(accessToken), getCurrentTrainingPlan(accessToken)])
      .then(([state, proposals, plan]) => { if (active) { setChat(state); setAdaptations(proposals); setHasCurrentPlan(plan !== null) } })
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : 'Não foi possível carregar sua conversa.'))
    return () => { active = false }
  }, [accessToken])

  async function submit(nextMessage: string, id = requestId()) {
    if (!nextMessage.trim() || pending || creatingProposal || reviewingProposal) return
    setPending({ message: nextMessage, id })
    setError(null)
    try {
      const updated = await sendTrainingChatMessage(accessToken, nextMessage, id)
      setChat(updated)
      setMessage('')
      setRetry(null)
      if (updated.draft && updated.draft.revision !== chat?.draft?.revision && adaptations.some((proposal) => proposal.status === 'pending_instructor_review')) {
        await getOwnAdaptations(accessToken).then(setAdaptations).catch(() => setError('A ficha foi atualizada, mas não foi possível atualizar o histórico de adaptações. Recarregue a conversa para conferir.'))
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível enviar sua mensagem.')
      setRetry({ message: nextMessage, id })
    } finally { setPending(null) }
  }

  async function requestProposal(sourceRequestId: string, reason: string) {
    if (creatingProposal || reviewingProposal || pending) return
    setCreatingProposal(true); setError(null)
    try {
      const id = proposalRequestIds.current.get(sourceRequestId) ?? crypto.randomUUID()
      proposalRequestIds.current.set(sourceRequestId, id)
      const proposal = await createAdaptation(accessToken, reason, sourceRequestId, id)
      setAdaptations((items) => [proposal, ...items.filter((item) => item.id !== proposal.id)])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível gerar a proposta.') }
    finally { setCreatingProposal(false) }
  }

  async function reviewProposal(id: string, accept: boolean) {
    if (reviewingProposal || creatingProposal || pending) return
    setReviewingProposal(id); setError(null)
    try { const proposal = await decideAdaptation(accessToken, id, accept); setAdaptations((items) => items.map((item) => item.id === id ? proposal : item)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível revisar a proposta.') }
    finally { setReviewingProposal(null) }
  }

  if ((!chat || hasCurrentPlan === null) && error) return <ClientShell onSignOut={onSignOut} showClientNavigation contentMaxWidth="md"><StatusNotice severity="error">{error}</StatusNotice></ClientShell>

  if (!chat || hasCurrentPlan === null) return <ClientShell onSignOut={onSignOut} showClientNavigation contentMaxWidth="md"><LoadingState label="Carregando assistente de treino" /></ClientShell>

  const suggestions = chat.messages.filter((item) => item.role === 'assistant' && item.adaptation_suggested && item.reply_to_client_request_id && item.adaptation_reason)
  const draft = chat.draft
  const busy = pending !== null || creatingProposal || reviewingProposal !== null
  const previewInLastReply = !!draft?.preview && !!chat.messages.at(-1)?.content.includes(draft.preview)

  return (
    <ClientShell onSignOut={onSignOut} showClientNavigation contentMaxWidth="md">
      <Stack spacing={3} sx={{ maxWidth: 880, mx: 'auto', width: '100%', minWidth: 0 }}>
        <PageHeader
          action={<RouterButtonLink to="/treino" variant="outlined">Ver meu treino</RouterButtonLink>}
          description="Tire dúvidas sobre o seu plano atual e seus exercícios. Mudanças no treino precisam de revisão profissional."
          eyebrow="Assistente de treino"
          title="Como posso ajudar hoje?"
        />
        <Stack aria-live="polite" aria-relevant="additions" spacing={1.5} sx={{ minHeight: 280, p: { xs: 1, sm: 2 }, borderRadius: 3, bgcolor: 'rgba(16,24,27,0.35)' }}>
          {chat.messages.length === 0
            ? <EmptyState description="Pergunte sobre os exercícios, séries, repetições ou orientações do seu treino atual." title="Seu espaço para tirar dúvidas" />
            : chat.messages.map((item, index) => <ChatMessage key={`${item.created_at}-${index}`} role={item.role} footer={item.role === 'assistant' ? <TrainingKnowledgeSources {...item} /> : undefined}>{item.role === 'assistant' ? <TrainingChatContent content={item.content} /> : item.content}</ChatMessage>)}
          {pending && <>
            {!chat.messages.some((item) => item.client_request_id === pending.id) && <ChatMessage role="user">{pending.message}</ChatMessage>}
            <ChatMessage role="assistant"><Stack direction="row" spacing={1.5} role="status" sx={{ alignItems: 'center' }}><CircularProgress size={20} aria-label="Gerando resposta do assistente" /><Typography>Preparando sua resposta…</Typography></Stack></ChatMessage>
          </>}
        </Stack>
        {draft && <Card component="section"><CardContent><Stack spacing={2}>
          {!previewInLastReply && <>
            <Typography component="h2" variant="h3">{trainingTitle(draft.name)}</Typography>
            <Typography>Objetivo: {draft.objective}</Typography>
            <Typography>Status: {draft.validation_error ? 'Rascunho inválido' : 'Aguardando revisão do instrutor'}</Typography>
            {!draft.validation_error && <TrainingExerciseTable rows={trainingRows(draft.items)} />}
            <TrainingKnowledgeSources {...draft} />
          </>}
          <TrainingDraftReviewActions accessToken={accessToken} draft={draft} disabled={busy} onSubmitted={(updated) => setChat((previous) => previous && (!previous.draft || previous.draft.revision <= updated.revision) ? { ...previous, draft: updated } : previous)} />
        </Stack></CardContent></Card>}
        {error && <Stack spacing={1} sx={{ alignItems: 'flex-start' }}><StatusNotice severity="error">{error}</StatusNotice>{retry && <Button onClick={() => void submit(retry.message, retry.id)} variant="outlined">Tentar novamente</Button>}</Stack>}
        <Box aria-hidden="true" ref={chatEndRef} sx={{ height: 1, scrollMarginBottom: { xs: 184, sm: 132 } }} />
        <Card aria-busy={pending !== null} component="form" onSubmit={(event) => { event.preventDefault(); void submit(message) }} sx={{ bottom: 16, position: 'sticky', zIndex: 1, borderColor: 'rgba(255,133,100,0.35)', boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}>
          <CardContent>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <TextField autoComplete="off" fullWidth label="Escreva sua pergunta" multiline onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return; event.preventDefault(); void submit(message) }} disabled={busy} helperText="Enter para enviar · Shift + Enter para uma nova linha" placeholder="Conte o que precisa; você pode reunir dúvidas e corrigir informações." value={message} />
              <Button disabled={!message.trim() || busy} type="submit" variant="contained" startIcon={<WorkspaceIcon name="send" />}>{pending ? 'Enviando…' : 'Enviar'}</Button>
            </Stack>
          </CardContent>
        </Card>
        {hasCurrentPlan && !draft && suggestions.filter((suggestion) => !adaptations.some((proposal) => proposal.source_client_request_id === suggestion.reply_to_client_request_id)).map((suggestion, index) => <Card component="section" key={`${suggestion.created_at}-${index}`}>
          <CardContent>
            <Stack spacing={1.5}>
              <Typography component="h2" variant="h3">Sugestão de alteração</Typography>
              <Typography color="text.secondary">O assistente identificou uma possível melhoria: {suggestion.adaptation_reason}</Typography>
              <Typography>Primeiro gere a ficha para conferir os exercícios. Depois, envie para revisão do instrutor.</Typography>
              <Box><Button disabled={creatingProposal || reviewingProposal !== null || pending !== null} onClick={() => void requestProposal(suggestion.reply_to_client_request_id!, suggestion.adaptation_reason!)} variant="outlined">{creatingProposal ? 'Preparando rascunho…' : 'Gerar rascunho para conferir'}</Button></Box>
            </Stack>
          </CardContent>
        </Card>)}
        {adaptations.map((proposal) => <Card component="section" key={proposal.id}><CardContent><Stack spacing={1}>
          <Typography component="h2" variant="h3">Proposta de alteração</Typography>
          <Typography>{proposal.explanation}</Typography>
          {proposal.preview && <TrainingChatContent content={proposal.preview} />}
          <TrainingKnowledgeSources {...proposal} />
          <Typography color="text.secondary" variant="body2">Status: {adaptationStatuses[proposal.status] ?? 'Aguardando atualização'}</Typography>
          {proposal.status === 'pending_instructor_review' && <StatusNotice severity="success">Enviado para revisão do instrutor. Seu plano atual continua vigente até a aprovação.</StatusNotice>}
          {proposal.status === 'proposed' && <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}><Button disabled={reviewingProposal !== null || creatingProposal || pending !== null} onClick={() => void reviewProposal(proposal.id, true)} variant="contained">{reviewingProposal === proposal.id ? 'Enviando para revisão…' : 'Enviar rascunho para minha revisão'}</Button><Button disabled={reviewingProposal !== null || creatingProposal || pending !== null} onClick={() => void reviewProposal(proposal.id, false)} variant="outlined">Recusar</Button></Stack>}
        </Stack></CardContent></Card>)}
        <Box><StatusNotice severity="info">O assistente pode atualizar o rascunho em edição quando você pedir. Você pode reunir informações e corrigir apenas um dado, sem recomeçar a conversa. Seu plano atual só muda após revisão profissional. A conversa é mantida por 30 dias.</StatusNotice></Box>
      </Stack>
    </ClientShell>
  )
}
