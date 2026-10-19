import { Box, Button, Card, CardContent, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Divider, FormControlLabel, FormGroup, Stack, Tab, Tabs, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ApiRequestError } from './clients'
import { EmptyState, LoadingState, PageHeader, StatusNotice } from './components/ui'
import { TrainingPlanContent } from './components/training-plan-content'
import { TrainingKnowledgeSources } from './components/training-knowledge-sources'
import { TrainingDraftFields } from './training-draft-fields'
import { InstructorShell } from './instructor-shell'
import { appendPendingToCurrent, approvePendingPlan, getPendingPlan, getPendingPlans, savePendingPlan, type PendingPlan, type ReviewContent } from './training-review'

const sources = { ai: 'IA', instructor: 'Instrutor', adaptation: 'Adaptação aceita pelo cliente' }
const date = (value: string) => new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'medium', timeStyle: 'short' })
const content = (plan: PendingPlan): ReviewContent => ({ name: plan.name, objective: plan.objective, items: plan.items.map((item) => ({ exercise_name: item.exercise_name, sets: item.sets, repetitions: item.repetitions, load_guidance: item.load_guidance, rest_seconds: item.rest_seconds, equipment_requirement: item.equipment_requirement ?? null, equipment_model_id: item.equipment_model_id ?? null })) })

export function InstructorPendingPlansPage({ accessToken, onSignOut }: { accessToken: string; onSignOut: () => void }) {
  const [searchParams] = useSearchParams()
  const requestedDraft = searchParams.get('rascunho')
  const [editing, setEditing] = useState(false)
  const [discardAction, setDiscardAction] = useState<(() => void) | null>(null)
  const listButtons = useRef(new Map<string, HTMLButtonElement>())
  const listHeading = useRef<HTMLHeadingElement>(null)
  const [plans, setPlans] = useState<PendingPlan[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<PendingPlan | null>(null)
  const [draft, setDraft] = useState<ReviewContent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selectedPositions, setSelectedPositions] = useState<number[]>([])
  const dirty = Boolean(selected && draft && JSON.stringify(content(selected)) !== JSON.stringify(draft))
  const working = useRef(false)
  const generation = useRef(0)
  function afterDiscard(action: () => void) {
    if (dirty) setDiscardAction(() => action)
    else action()
  }
  function closeReview() {
    const id = selected?.id
    setSelected(null); setDraft(null); setEditing(false)
    requestAnimationFrame(() => { if (id) listButtons.current.get(id)?.focus() })
  }
  const editorHeading = useRef<HTMLHeadingElement>(null)
  const detailSection = useRef<HTMLElement>(null)
  useEffect(() => {
    if (selected) {
      editorHeading.current?.focus({ preventScroll: true })
      detailSection.current?.scrollIntoView?.({ block: 'start' })
    }
  }, [selected?.id])

  function failure(reason: unknown) {
    setError(reason instanceof ApiRequestError ? reason.message : 'Não foi possível carregar ou salvar os planos. Tente novamente.')
    if (reason instanceof ApiRequestError && [404, 409].includes(reason.status)) setStale(true)
  }
  async function load(offset = 0) {
    const request = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const page = await getPendingPlans(accessToken, offset)
      if (request !== generation.current) return
      setPlans((previous) => offset === 0 ? page.items : [...previous, ...page.items.filter((item) => !previous.some((old) => old.id === item.id))])
      setNextOffset(page.next_offset)
    } catch (reason) { if (request === generation.current) failure(reason) }
    finally { if (request === generation.current) setLoading(false) }
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [accessToken])
  useEffect(() => {
    if (requestedDraft) void open({ id: requestedDraft })
  }, [accessToken, requestedDraft])

  async function open(plan: Pick<PendingPlan, 'id'>) {
    if (working.current) return
    working.current = true; setBusy(true); setError(null); setNotice(null)
    try {
      const latest = await getPendingPlan(accessToken, plan.id)
      setSelected(latest); setDraft(content(latest)); setStale(false); setEditing(false); setSelectedPositions([])
    } catch (reason) { failure(reason) }
    finally { working.current = false; setBusy(false) }
  }
  async function submit(plan: PendingPlan, approve: boolean, changes?: ReviewContent) {
    if (working.current || stale) return
    working.current = true; setBusy(true); setError(null); setNotice(null)
    try {
      let latest = plan
      if (changes) {
        const saved = await savePendingPlan(accessToken, plan, changes)
        latest = { ...plan, ...saved }
        setSelected(latest); setDraft(content(latest))
        setPlans((items) => items.map((item) => item.id === plan.id ? latest : item))
      }
      if (approve) {
        await approvePendingPlan(accessToken, latest)
        setSelected(null); setDraft(null)
        await load()
        requestAnimationFrame(() => listHeading.current?.focus())
      }
      setNotice(approve ? 'Plano aprovado e definido como treino atual.' : 'Rascunho salvo. O treino atual não foi alterado.')
    } catch (reason) { failure(reason) }
    finally { working.current = false; setBusy(false) }
  }
  async function append() {
    if (!selected?.append_target || !draft || !selectedPositions.length || working.current || stale) return
    working.current = true; setBusy(true); setError(null); setNotice(null)
    try {
      let latest = selected
      if (dirty) {
        latest = { ...latest, ...await savePendingPlan(accessToken, latest, draft) }
        setSelected(latest); setDraft(content(latest))
        setPlans((items) => items.map((item) => item.id === latest.id ? latest : item))
      }
      // A save response omits review-only metadata; retain the displayed target.
      const merged = await appendPendingToCurrent(accessToken, latest, selectedPositions)
      setSelected(merged); setDraft(content(merged)); setEditing(false); setSelectedPositions([])
      setPlans((items) => items.map((item) => item.id === merged.id ? merged : item))
      setNotice('Nova versão preparada com os exercícios selecionados. Confira a ficha combinada e aprove para ativá-la.')
    } catch (reason) { failure(reason) }
    finally { working.current = false; setBusy(false) }
  }
  return <InstructorShell onSignOut={onSignOut} contentMaxWidth="lg"><Stack spacing={3}>
    <PageHeader eyebrow="Revisão profissional" title="Planos pendentes" description="Confira os exercícios e as orientações antes de aprovar. Cada aprovação define o treino atual do cliente." />
    {error && <StatusNotice severity="error">{error}</StatusNotice>}
    {notice && <StatusNotice severity="success">{notice}</StatusNotice>}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(260px, 0.8fr) minmax(0, 1.8fr)' }, gap: 3, alignItems: 'start' }}>
      <Stack component="section" aria-label="Lista de planos pendentes" spacing={2} sx={{ minWidth: 0, display: { xs: selected ? 'none' : 'flex', lg: 'flex' }, position: { lg: 'sticky' }, top: 24 }}>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
          <Typography component="h2" variant="h3" ref={listHeading} tabIndex={-1} sx={{ scrollMarginTop: { xs: 88, md: 24 } }}>Aguardando revisão</Typography>
          <Button disabled={busy || loading} onClick={() => afterDiscard(() => { closeReview(); setStale(false); void load() })}>Recarregar lista</Button>
        </Stack>
        <Typography variant="body2" color="text.secondary" aria-live="polite">{plans.length} {plans.length === 1 ? 'rascunho carregado' : 'rascunhos carregados'}{nextOffset !== null ? ' · Há mais resultados' : ''}</Typography>
        {loading && <LoadingState label="Carregando planos pendentes" />}
        {!loading && !error && plans.length === 0 && <EmptyState title="Nenhum plano pendente" description="Os rascunhos aguardando aprovação aparecerão aqui." />}
        <Stack spacing={1.5} sx={(theme) => ({ maxHeight: { lg: '70vh' }, overflowY: { lg: 'auto' }, scrollbarWidth: 'thin', scrollbarColor: `${theme.palette.divider} transparent`, p: 0.5 })}>
          {plans.map((plan) => <Button key={plan.id} color="inherit" disabled={busy}
            ref={(element) => { if (element) listButtons.current.set(plan.id, element); else listButtons.current.delete(plan.id) }}
            aria-label={`Revisar plano de ${plan.client_name}`} aria-pressed={selected?.id === plan.id}
            onClick={() => afterDiscard(() => void open(plan))}
            sx={{ display: 'block', flexShrink: 0, textAlign: 'left', p: 2.5, borderRadius: 3, width: '100%', border: '1px solid', borderColor: selected?.id === plan.id ? 'primary.main' : 'divider', bgcolor: selected?.id === plan.id ? 'rgba(255,133,100,0.08)' : 'background.paper' }}>
            <Stack spacing={1}>
              <Typography component="span" sx={{ fontWeight: 800, overflowWrap: 'anywhere' }}>{plan.name}</Typography>
              <Typography component="span" variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere', color: 'primary.main' }}>Cliente: {plan.client_name}</Typography>
              <Box component="span" sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
                <Chip component="span" size="small" variant="outlined" color="warning" label={sources[plan.source]} sx={{ height: 'auto', minHeight: 24, '& .MuiChip-label': { whiteSpace: 'normal', py: 0.5 } }} />
                <Chip component="span" size="small" label={`${plan.items.length} ${plan.items.length === 1 ? 'exercício' : 'exercícios'}`} />
              </Box>
              <Typography component="span" variant="caption" color="text.secondary">Criado em {date(plan.created_at)}</Typography>
              <Typography component="span" variant="caption" color="text.secondary">Atualizado em {date(plan.updated_at)} · Revisão {plan.revision}</Typography>
              <Typography component="span" variant="caption" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>Instrutor responsável pelo treino atual: {plan.current_responsible_instructor_name ?? 'Não informado'}</Typography>
              <Typography component="span" variant="body2" color="primary.main" sx={{ fontWeight: 750 }}>Revisar plano →</Typography>
            </Stack>
          </Button>)}
        </Stack>
        {nextOffset !== null && <Button disabled={loading || busy} onClick={() => void load(nextOffset)}>Carregar mais planos</Button>}
      </Stack>
      <Box sx={{ minWidth: 0, display: { xs: selected || busy ? 'block' : 'none', lg: 'block' } }}>
        {busy && <LoadingState label="Processando revisão" />}
        {!selected && !busy && <Card variant="outlined" sx={{ bgcolor: 'rgba(245,247,244,0.025)' }}><CardContent sx={{ py: 7 }}><Stack spacing={1.5} sx={{ maxWidth: 380, mx: 'auto' }}>
          <Typography variant="overline" color="primary.main">Revisão do treino</Typography>
          <Typography component="h2" variant="h3">Escolha um rascunho para revisar</Typography>
          <Typography color="text.secondary">Leia o treino completo, ajuste o que for necessário e aprove quando estiver pronto. Salvar um rascunho não altera o treino atual.</Typography>
        </Stack></CardContent></Card>}
        {selected && draft && <Card component="section" ref={detailSection} aria-label="Revisão do plano" sx={{ scrollMarginTop: { xs: 80, md: 24 }, borderTop: '3px solid', borderTopColor: 'primary.main' }}><CardContent sx={{ p: { xs: 2, sm: 3 } }}><Stack spacing={3}>
          <Box><Button disabled={busy} onClick={() => afterDiscard(closeReview)}>← Voltar à lista</Button></Box>
          <Stack spacing={1.5}>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Chip size="small" color="warning" variant="outlined" label="Aguardando aprovação" />
              <Chip size="small" label={`Origem: ${sources[selected.source]}`} sx={{ height: 'auto', minHeight: 24, '& .MuiChip-label': { whiteSpace: 'normal', py: 0.5 } }} />
            </Stack>
            <Typography component="h2" ref={editorHeading} tabIndex={-1} variant="h3" sx={{ fontSize: { xs: '1.35rem', sm: '1.6rem' }, overflowWrap: 'anywhere', scrollMarginTop: { xs: 88, md: 24 } }}>{draft.name}</Typography>
            <Typography sx={{ fontWeight: 700, overflowWrap: 'anywhere', color: 'primary.main', bgcolor: 'rgba(255,133,100,0.06)', p: 1.5, borderRadius: 2 }}>Cliente: {selected.client_name}</Typography>
            <Typography variant="body2" color="text.secondary">Atualizado em {date(selected.updated_at)} · Revisão {selected.revision}</Typography>
            {dirty && <Typography role="status" variant="body2" color="warning.main">Alterações não salvas</Typography>}
            {stale && <Button disabled={busy} onClick={() => afterDiscard(() => void open(selected))}>Recarregar rascunho</Button>}
          </Stack>
          <Divider />
          {(selected.source !== 'instructor' || Boolean(selected.citations?.length) || Boolean(selected.knowledge_limitations?.trim())) && <Stack spacing={1}>
            <TrainingKnowledgeSources {...selected} knowledge_status={selected.knowledge_status ?? 'unavailable'} title="Fundamentação bibliográfica" />
            <Typography variant="body2" color="text.secondary">A fundamentação exibida corresponde à versão salva. Confira sua aplicabilidade aos ajustes e às restrições do cliente antes de aprovar.</Typography>
          </Stack>}
          <Tabs value={editing ? 'edit' : 'preview'} onChange={(_, value) => setEditing(value === 'edit')} aria-label="Modo de revisão" variant="fullWidth">
            <Tab id="aba-visualizar" aria-controls="painel-visualizar" value="preview" label="Visualizar treino" />
            <Tab id="aba-editar" aria-controls="painel-editar" value="edit" label="Editar rascunho" />
          </Tabs>
          <Box role="tabpanel" id="painel-visualizar" aria-labelledby="aba-visualizar" hidden={editing}>{!editing && <TrainingPlanContent plan={draft} />}</Box>
          <Box role="tabpanel" id="painel-editar" aria-labelledby="aba-editar" hidden={!editing}>
            {editing && <Box component="fieldset" disabled={busy || stale} sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}>
              <TrainingDraftFields accessToken={accessToken} draft={draft} onChange={(value) => { setDraft(value); setSelectedPositions([]) }} />
            </Box>}
          </Box>
          {selected.append_target && <Stack spacing={2}>
            <Typography component="h3" variant="h4">Ficha atual do cliente</Typography>
            <TrainingPlanContent plan={selected.append_target} />
            <Typography component="h3" variant="h4">Escolha os exercícios da IA para a nova versão</Typography>
            <Typography variant="body2" color="text.secondary">A nova versão manterá os exercícios da ficha atual e incluirá apenas os exercícios marcados abaixo. Confira a ficha combinada antes de aprovar.</Typography>
            <FormGroup aria-label="Exercícios sugeridos para acrescentar">{draft.items.map((item, index) => <FormControlLabel key={index} label={`Adicionar exercício ${index + 1}: ${item.exercise_name}`} control={<Checkbox disabled={busy || stale} checked={selectedPositions.includes(index + 1)} onChange={(_, checked) => setSelectedPositions((positions) => checked ? [...positions, index + 1] : positions.filter((position) => position !== index + 1))} />} />)}</FormGroup>
            <Button disabled={busy || stale || selectedPositions.length === 0} variant="outlined" onClick={() => void append()}>Preparar nova versão com selecionados</Button>
          </Stack>}
          <Box sx={{ position: { lg: 'sticky' }, bottom: 16, bgcolor: 'background.paper', borderTop: '1px solid', borderColor: 'divider', pt: 2 }}>
            <Stack spacing={1.5}>
              <Typography variant="body2" color="text.secondary">Aprovar torna esta versão o treino atual e registra você como instrutor responsável.</Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} sx={{ flexWrap: 'wrap', gap: 1 }}>
                {(editing || dirty) && <Button disabled={busy || stale} variant="outlined" onClick={() => void submit(selected, false, draft)}>Salvar rascunho</Button>}
                <Button disabled={busy || stale} variant="contained" onClick={() => void submit(selected, true, editing || dirty ? draft : undefined)}>{editing || dirty ? 'Aprovar alterações' : selected.append_target ? 'Aprovar como nova ficha' : 'Aprovar'}</Button>
                <Button disabled={busy} onClick={() => afterDiscard(closeReview)}>Fechar revisão</Button>
              </Stack>
            </Stack>
          </Box>
        </Stack></CardContent></Card>}
      </Box>
    </Box>
    <Dialog open={discardAction !== null} onClose={() => setDiscardAction(null)} aria-labelledby="descartar-edicao-titulo" aria-describedby="descartar-edicao-descricao">
      <DialogTitle id="descartar-edicao-titulo">Descartar alterações não salvas?</DialogTitle>
      <DialogContent><DialogContentText id="descartar-edicao-descricao">As alterações feitas nesta revisão ainda não foram salvas. O rascunho salvo e o treino atual permanecem como estão.</DialogContentText></DialogContent>
      <DialogActions><Button autoFocus onClick={() => setDiscardAction(null)}>Continuar editando</Button><Button color="error" onClick={() => { discardAction?.(); setDiscardAction(null) }}>Descartar alterações</Button></DialogActions>
    </Dialog>
  </Stack></InstructorShell>
}
