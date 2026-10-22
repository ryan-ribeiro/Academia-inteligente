import { Button, Stack } from '@mui/material'
import { useState } from 'react'

import { createInitialTrainingProposal, submitTrainingDraft, type TrainingPlanDraft } from '../training-plan'
import { StatusNotice } from './ui'

type Props = { accessToken: string; draft: TrainingPlanDraft; onSubmitted: (draft: TrainingPlanDraft) => void; disabled?: boolean }

export function TrainingDraftReviewActions({ accessToken, draft, onSubmitted, disabled = false }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(regenerate = false) {
    if (submitting || disabled) return
    setSubmitting(true); setError(null)
    try { onSubmitted(await (regenerate ? createInitialTrainingProposal(accessToken) : submitTrainingDraft(accessToken, draft.id, draft.revision))) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível enviar o treino para revisão.') }
    finally { setSubmitting(false) }
  }

  return <Stack spacing={1.5} aria-busy={submitting}>
    {draft.validation_error
      ? <>
        <StatusNotice severity="error">{draft.validation_error}</StatusNotice>
        <Button disabled={submitting || disabled} onClick={() => void submit(true)} variant="contained">{submitting ? 'Gerando nova ficha…' : 'Gerar nova ficha'}</Button>
      </>
      : draft.submitted_for_review_at
      ? <StatusNotice severity="success">Enviado para revisão do instrutor. A ficha ainda não está aprovada nem ativa.</StatusNotice>
      : <>
        <StatusNotice severity="info">Confira os exercícios e peça ajustes ao assistente se precisar. O botão abaixo envia esta ficha diretamente ao instrutor para revisão.</StatusNotice>
        <Button disabled={submitting || disabled} onClick={() => void submit()} variant="contained">{submitting ? 'Enviando para revisão…' : 'Enviar rascunho para minha revisão'}</Button>
      </>}
    {error && <StatusNotice severity="error">{error}</StatusNotice>}
  </Stack>
}
