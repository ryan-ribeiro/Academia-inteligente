import { Box, Button, Card, CardContent, Chip, Divider, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'

import { ClientShell } from './components/application-shell'
import { RouterButtonLink } from './components/router-button-link'
import { TrainingDraftReviewActions } from './components/training-draft-review-actions'
import { TrainingExerciseTable, trainingRows, trainingTitle } from './components/training-exercise-table'
import { TrainingKnowledgeSources } from './components/training-knowledge-sources'
import { EmptyState, LoadingState, PageHeader, StatusNotice } from './components/ui'
import { createInitialTrainingProposal, getCurrentTrainingPlan, getOwnTrainingDrafts, type CurrentTrainingPlan, type TrainingPlanDraft } from './training-plan'

type CurrentTrainingPageProps = { accessToken: string; onSignOut: () => void }

function restLabel(restSeconds: number) {
  return restSeconds === 0 ? 'Sem descanso programado' : `Descanso: ${restSeconds} s`
}

export function CurrentTrainingPage({ accessToken, onSignOut }: CurrentTrainingPageProps) {
  const [plan, setPlan] = useState<CurrentTrainingPlan | null | undefined>(undefined)
  const [drafts, setDrafts] = useState<TrainingPlanDraft[]>([])
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  async function loadPlan() {
    setError(null)
    setPlan(undefined)
    try {
      const [currentPlan, ownDrafts] = await Promise.all([
        getCurrentTrainingPlan(accessToken),
        getOwnTrainingDrafts(accessToken),
      ])
      setPlan(currentPlan)
      setDrafts(ownDrafts)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível carregar seu treino.')
      setPlan(null)
    }
  }

  useEffect(() => { void loadPlan() }, [accessToken])

  async function generateDraft() {
    setError(null)
    setGenerating(true)
    try {
      const draft = await createInitialTrainingProposal(accessToken)
      setDrafts((current) => [draft, ...current.filter((item) => item.plan_id !== draft.plan_id || item.version_number !== draft.version_number)])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível gerar seu rascunho de treino.')
    } finally {
      setGenerating(false)
    }
  }

  if (plan === undefined) {
    return <ClientShell onSignOut={onSignOut} showClientNavigation><LoadingState label="Carregando seu treino" /></ClientShell>
  }

  return (
    <ClientShell onSignOut={onSignOut} showClientNavigation>
      <Stack spacing={{ xs: 2.5, sm: 3 }} sx={{ maxWidth: 960, minWidth: 0, mx: 'auto' }}>
        <PageHeader
          action={<RouterButtonLink to="/assistente" variant="outlined">Assistente de treino</RouterButtonLink>}
          eyebrow="Treino atual"
          title="Meu treino"
          description="Use esta ficha durante o treino. Siga as orientações e ajuste a carga somente com acompanhamento profissional."
        />
        {error && (
          <Stack spacing={1.5} sx={{ alignItems: 'flex-start' }}>
            <StatusNotice severity="error">{error}</StatusNotice>
            <Button onClick={() => void loadPlan()} variant="outlined">Tentar novamente</Button>
          </Stack>
        )}
        {!error && !plan && (
          <Stack spacing={2} sx={{ alignItems: 'flex-start' }}>
            <EmptyState
              title="Seu treino ainda não está disponível"
              description="Gere um rascunho inicial com IA ou aguarde seu instrutor criar uma proposta. O treino só fica disponível após revisão, aprovação e ativação profissional."
            />
            {!drafts.some((draft) => draft.origin === 'ai') && (
              <Button disabled={generating} onClick={() => void generateDraft()} variant="contained">
                {generating ? 'Gerando rascunho…' : 'Gerar rascunho inicial com IA'}
              </Button>
            )}
          </Stack>
        )}
        {!error && plan && (
          <Card component="section" sx={{ borderTop: '3px solid', borderTopColor: 'primary.main' }}>
            <CardContent sx={{ p: { xs: 2.25, sm: 3 } }}>
              <Stack spacing={2.5}>
                <Stack spacing={1.25} sx={{ pb: 1 }}>
                  <Typography color="primary.main" variant="overline">Plano atual</Typography>
                  <Typography component="h2" variant="h3" sx={{ overflowWrap: 'anywhere' }}>{plan.name}</Typography>
                  <Typography color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>{plan.objective}</Typography>
                  <Typography variant="body2">Instrutor responsável: {plan.responsible_instructor_name ?? 'Não informado'}</Typography>
                  <Typography color="text.secondary" variant="body2">Data de aprovação: {plan.approved_at ? new Date(plan.approved_at).toLocaleDateString('pt-BR') : 'Não informada'}</Typography>
                </Stack>
                <Divider />
                <Stack spacing={2}>
                  {plan.items.map((item) => (
                    <Box component="article" key={item.position} sx={{ minWidth: 0, p: { xs: 2, sm: 2.5 }, border: '1px solid', borderColor: 'divider', borderRadius: 2.5, bgcolor: 'rgba(16,24,27,0.4)' }}>
                      <Stack spacing={1.5}>
                        <Typography color="primary.main" variant="overline">Exercício {item.position}</Typography>
                        <Typography component="h3" variant="h4" sx={{ overflowWrap: 'anywhere' }}>{item.exercise_name}</Typography>
                        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
                          <Chip label={`${item.sets} séries`} sx={{ fontSize: '0.95rem', px: 0.5, py: 0.5 }} />
                          <Chip label={`${item.repetitions} repetições`} sx={{ fontSize: '0.95rem', px: 0.5, py: 0.5 }} />
                          <Chip label={restLabel(item.rest_seconds)} variant="outlined" sx={{ py: 0.5 }} />
                        </Stack>
                        <Box sx={{ borderLeft: '3px solid', borderColor: 'divider', pl: 1.5 }}>
                          <Typography color="text.secondary" variant="body2">Orientação de carga</Typography>
                          <Typography sx={{ overflowWrap: 'anywhere' }}>{item.load_guidance}</Typography>
                          {item.equipment_requirement && <Typography>Equipamento registrado: {item.equipment_requirement}</Typography>}
                        </Box>
                      </Stack>
                    </Box>
                  ))}
                </Stack>
              </Stack>
            </CardContent>
          </Card>
        )}
        {!error && drafts.map((draft) => (
          <Card component="section" key={`${draft.plan_id}-${draft.version_number}`} variant="outlined" sx={{ borderTop: '3px solid', borderTopColor: 'warning.main' }}>
            <CardContent sx={{ p: { xs: 2.25, sm: 3 } }}>
              <Stack spacing={2}>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' }, justifyContent: 'space-between' }}>
                  <Typography color="warning.main" variant="overline">Rascunho — ainda não aprovado</Typography>
                  <Chip color="warning" label={draft.submitted_for_review_at ? 'Enviado ao instrutor' : 'Aguardando sua confirmação'} size="small" />
                </Stack>
                <Typography component="h2" sx={{ overflowWrap: 'anywhere' }} variant="h3">{trainingTitle(draft.name)}</Typography>
                <Typography color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>Objetivo: {draft.objective}</Typography>
                <Typography>Status: Aguardando revisão do instrutor</Typography>
                <StatusNotice severity="info">Este é apenas um rascunho. Seu instrutor precisa revisar, aprovar e ativar a ficha antes que ela se torne seu treino atual.</StatusNotice>
                <TrainingExerciseTable rows={trainingRows(draft.items)} />
                <TrainingKnowledgeSources {...draft} />
                <TrainingDraftReviewActions accessToken={accessToken} draft={draft} onSubmitted={(updated) => setDrafts((items) => items.map((item) => item.id === updated.id ? updated : item))} />
              </Stack>
            </CardContent>
          </Card>
        ))}
      </Stack>
    </ClientShell>
  )
}
