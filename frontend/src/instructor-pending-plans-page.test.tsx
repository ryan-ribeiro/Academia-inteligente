import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import { InstructorPendingPlansPage } from './instructor-pending-plans-page'
import { expectReviewSessions } from './test/training-session-assertions'
import { sessionReviewItems } from './test/training-session-fixture'

const plan = {
  id: 'draft', plan_id: 'plan', version_number: 1, revision: 1,
  client_name: 'Maria Silva', source: 'adaptation', name: 'Força', objective: 'Ganhar força',
  created_at: '2026-09-27T12:00:00Z', updated_at: '2026-09-27T12:00:00Z',
  current_responsible_instructor_name: 'João Silva',
  items: [{ exercise_name: 'Leg Press', sets: 3, repetitions: '8', load_guidance: 'Confortável', rest_seconds: 90, equipment_model_id: 'machine', equipment_requirement: 'Leg Press 45°' }],
}
const ok = (body: unknown) => ({ ok: true, json: async () => body })
const citation = {
  chunk_id: 'strength-1', source_id: 'nhs-strength', title: 'Strength exercises',
  url: 'https://www.nhs.uk/live-well/exercise/strength-exercises/', authors: ['NHS'],
  license: 'OGL v3.0', license_url: 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/',
  section: 'Sit-to-stand',
}
function mount() { render(<MemoryRouter><InstructorPendingPlansPage accessToken="token" onSignOut={vi.fn()} /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('session display numbering never changes the original global append selection or payload', async () => {
  const targetItems = sessionReviewItems.map((item) => ({ ...item, exercise_name: `Atual ${item.exercise_name}` }))
  const source = { ...plan, source: 'ai', items: sessionReviewItems, append_target: { id: 'target', revision: 8, name: 'Atual', objective: 'Força', items: targetItems } }
  const before = structuredClone(source)
  const combined = { ...source, revision: 2, append_target: null, items: [...targetItems, source.items[4]] }
  const fetchMock = mockFetch((url) => {
    if (url.endsWith('/append-to-current')) return ok(combined)
    if (url.includes('/pending?')) return ok({ items: [source], next_offset: null })
    if (url.endsWith('/pending/draft')) return ok(source)
    return undefined
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  const preview = await screen.findByRole('tabpanel', { name: 'Visualizar treino' })
  expectReviewSessions(preview)
  expect(screen.getAllByRole('region', { name: 'Treino A' })).toHaveLength(2)
  const currentA = screen.getAllByRole('region', { name: 'Treino A' })[1]
  expect(within(currentA).getByRole('heading', { name: 'Atual Agachamento (com apoio)' })).toBeInTheDocument()
  expect(within(currentA).getAllByRole('listitem')).toHaveLength(2)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Adicionar exercício 5: Agachamento (com apoio) (Dia B)' }))
  fireEvent.click(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' }))
  await screen.findByText(/Nova versão preparada/)
  const request = fetchMock.mock.calls.find(([url]) => url.endsWith('/append-to-current'))!
  expect(JSON.parse(request[1]!.body as string)).toEqual({ expected_revision: 1, current_version_id: 'target', expected_current_revision: 8, selected_positions: [5] })
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false)
  const sessionB = within(screen.getByRole('region', { name: 'Treino B' }))
  expect(sessionB.getAllByRole('listitem')).toHaveLength(3)
  expect(sessionB.getByRole('heading', { name: 'Agachamento (com apoio)' })).toBeInTheDocument()
  expect(sessionB.queryByRole('heading', { name: 'Remada' })).not.toBeInTheDocument()
  expect(source).toEqual(before)
})

function mockFetch(action?: (url: string, init?: RequestInit) => unknown) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/usable-models?')) return ok({ items: [{ id: 'machine', name: 'Leg Press 45°' }], next_cursor: null })
    const result = action?.(url, init)
    if (result) return result
    if (url.includes('/pending?')) return ok({ items: [plan], next_offset: null })
    return ok(plan)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('appends a submitted targeted sheet to the displayed current plan and approves only after previewing the combined version', async () => {
  const source = {
    ...plan, source: 'ai', name: 'Bíceps',
    items: ['Rosca direta', 'Rosca alternada'].map((name) => ({ ...plan.items[0], exercise_name: name, equipment_model_id: null, equipment_requirement: null })),
    append_target: { id: 'current-version', revision: 2, name: 'Treino atual', objective: 'Ganhar força', items: plan.items },
  }
  const combined = { ...source, name: 'Treino atual', plan_id: 'current-plan', version_number: 2, revision: 2, append_target: null, items: [...plan.items, source.items[1]] }
  let approved = false
  const fetchMock = mockFetch((url) => {
    if (url.endsWith('/append-to-current')) return ok(combined)
    if (url.endsWith('/approve')) { approved = true; return ok({ ...combined, status: 'current' }) }
    if (url.includes('/pending?')) return ok({ items: approved ? [] : [source], next_offset: null })
    if (url.endsWith('/pending/draft')) return ok(source)
    return undefined
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  expect(await screen.findByRole('heading', { name: 'Rosca direta' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Leg Press' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Escolha os exercícios da IA para a nova versão' })).toBeInTheDocument()
  const firstExercise = screen.getByRole('checkbox', { name: 'Adicionar exercício 1: Rosca direta' })
  expect(firstExercise).not.toBeChecked()
  fireEvent.click(firstExercise)
  expect(firstExercise).toBeChecked()
  fireEvent.click(firstExercise)
  expect(firstExercise).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Adicionar exercício 2: Rosca alternada' }))
  fireEvent.click(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' }))
  await screen.findByText(/Nova versão preparada com os exercícios selecionados/)
  expect(screen.queryByRole('button', { name: 'Preparar nova versão com selecionados' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Rosca direta' })).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Rosca alternada' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Leg Press' })).toBeInTheDocument()
  const appendRequest = fetchMock.mock.calls.find(([url]) => url.endsWith('/append-to-current'))!
  expect(JSON.parse(appendRequest[1]!.body as string)).toEqual({ expected_revision: 1, current_version_id: 'current-version', expected_current_revision: 2, selected_positions: [2] })
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
  await screen.findByText('Plano aprovado e definido como treino atual.')
  const approval = fetchMock.mock.calls.find(([url]) => url.endsWith('/approve'))!
  expect(approval[0]).toBe('http://localhost:8000/training/plans/current-plan/versions/2/approve')
  expect(JSON.parse(approval[1]!.body as string)).toEqual({ expected_revision: 2 })
})

test('a stale append preserves the displayed sheet and blocks approval until reload', async () => {
  const source = { ...plan, source: 'ai', append_target: { id: 'current-version', revision: 2, name: 'Atual', objective: 'Força', items: plan.items } }
  const fetchMock = mockFetch((url) => {
    if (url.endsWith('/append-to-current')) return { ok: false, status: 409 }
    if (url.includes('/pending?')) return ok({ items: [source], next_offset: null })
    return ok(source)
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Adicionar exercício 1: Leg Press' }))
  fireEvent.click(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' }))
  await screen.findByText('Este rascunho mudou. Recarregue e revise antes de continuar.')
  expect(screen.getByRole('button', { name: 'Aprovar como nova ficha' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' })).toBeDisabled()
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false)
})

test('retains a saved edit when appending fails and retries with its saved revision', async () => {
  const source = { ...plan, source: 'ai', append_target: { id: 'current-version', revision: 2, name: 'Atual', objective: 'Força', items: plan.items } }
  let attempts = 0
  const fetchMock = mockFetch((url, init) => {
    if (init?.method === 'PATCH') return ok({ ...source, ...JSON.parse(init.body as string), revision: 2 })
    if (url.endsWith('/append-to-current')) {
      attempts++
      return attempts === 1 ? { ok: false, status: 503 } : ok({ ...source, name: 'Atual', plan_id: 'current-plan', version_number: 2, revision: 3, append_target: null, items: [...plan.items, ...source.items] })
    }
    if (url.includes('/pending?')) return ok({ items: [source], next_offset: null })
    return url.endsWith('/pending/draft') ? ok(source) : undefined
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  await screen.findByRole('button', { name: 'Aprovar como nova ficha' })
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  fireEvent.change(screen.getByLabelText(/Nome do plano/), { target: { value: 'Sugestão revisada' } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'Adicionar exercício 1: Leg Press' }))
  fireEvent.click(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' }))
  await screen.findByText('Não foi possível concluir a revisão. Tente novamente.')
  expect(screen.queryByText('Alterações não salvas')).not.toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Revisão do plano' })).getByRole('heading', { name: 'Sugestão revisada' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Preparar nova versão com selecionados' }))
  await screen.findByText(/Nova versão preparada com os exercícios selecionados/)
  const writes = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH' || init?.method === 'POST')
  expect(writes.map(([, init]) => init?.method)).toEqual(['PATCH', 'POST', 'POST'])
  expect(writes.slice(1).map(([, init]) => JSON.parse(init!.body as string).expected_revision)).toEqual([2, 2])
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false)
})

test('lists minimized pending metadata and approves directly with the viewed revision', async () => {
  const fetchMock = mockFetch()
  mount()
  expect(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' })).toBeInTheDocument()
  expect(within(screen.getByRole('button', { name: 'Revisar plano de Maria Silva' })).getByText('Cliente: Maria Silva')).toBeInTheDocument()
  expect(screen.getByText(/Adaptação aceita pelo cliente/)).toBeInTheDocument()
  expect(screen.getByText(/Instrutor responsável pelo treino atual: João Silva/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Revisar plano de Maria Silva' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Aprovar' }))
  expect(await screen.findByText('Plano aprovado e definido como treino atual.')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Aguardando revisão' })).toHaveFocus())
  const request = fetchMock.mock.calls.find(([url]) => url.endsWith('/approve'))!
  expect(JSON.parse(request[1]!.body as string)).toEqual({ expected_revision: 1 })
  expect(fetchMock.mock.calls.some(([url]) => /instructor-decision|\/activate/.test(url))).toBe(false)
})

test('edits the whole draft, preserves equipment, and saving never activates', async () => {
  const fetchMock = mockFetch((_, init) => {
    if (init?.method !== 'PATCH') return undefined
    const input = JSON.parse(init.body as string)
    return ok({ ...plan, ...input, revision: input.expected_revision + 1 })
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  await screen.findByRole('heading', { name: 'Força' })
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  expect(screen.getByRole('combobox', { name: 'Equipamento do catálogo 1' })).toHaveTextContent('Leg Press 45°')
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Equipamento do catálogo 1' })).not.toHaveAttribute('aria-disabled', 'true'))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Equipamento do catálogo 1' }))
  expect(await screen.findByRole('option', { name: 'Leg Press 45°' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('option', { name: 'Leg Press 45°' }))
  fireEvent.change(screen.getByLabelText(/Nome do plano/), { target: { value: 'Força revisada' } })
  fireEvent.change(screen.getByLabelText(/Descanso em segundos 1/), { target: { value: '120' } })
  fireEvent.click(screen.getByRole('button', { name: 'Salvar rascunho' }))
  expect(await screen.findByText('Rascunho salvo. O treino atual não foi alterado.')).toBeInTheDocument()
  const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
  expect(JSON.parse(patch[1]!.body as string)).toMatchObject({ name: 'Força revisada', expected_revision: 1, items: [{ rest_seconds: 120, equipment_model_id: 'machine' }] })
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Aprovar alterações' }))
  await screen.findByText('Plano aprovado e definido como treino atual.')
  expect(JSON.parse(fetchMock.mock.calls.find(([url]) => url.endsWith('/approve'))![1]!.body as string)).toEqual({ expected_revision: 3 })
})

test('stale save blocks approval until the draft has been reloaded', async () => {
  const fetchMock = mockFetch((_, init) => init?.method === 'PATCH' ? { ok: false, status: 409 } : undefined)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  await screen.findByRole('heading', { name: 'Força' })
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  fireEvent.click(screen.getByRole('button', { name: 'Aprovar alterações' }))
  await screen.findByText('Este rascunho mudou. Recarregue e revise antes de continuar.')
  expect(screen.getByRole('button', { name: 'Aprovar alterações' })).toBeDisabled()
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Recarregar rascunho' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Aprovar' })).not.toBeDisabled())
})

test('loading failure is visible and retry can reach an empty state', async () => {
  let fail = true
  mockFetch((url) => url.includes('/pending?') ? (fail ? { ok: false, status: 503 } : ok({ items: [], next_offset: null })) : undefined)
  mount()
  expect(screen.getByText('Carregando planos pendentes')).toBeInTheDocument()
  await screen.findByText('Não foi possível concluir a revisão. Tente novamente.')
  expect(screen.queryByText('Carregando planos pendentes')).not.toBeInTheDocument()
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Recarregar lista' }))
  expect(await screen.findByText('Nenhum plano pendente')).toBeInTheDocument()
})

test('loads another bounded page without replacing the existing list', async () => {
  mockFetch((url) => url.includes('/pending?') ? ok(url.endsWith('offset=20') ? { items: [{ ...plan, id: 'other', client_name: 'Outro cliente' }], next_offset: null } : { items: [plan], next_offset: 20 }) : undefined)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Carregar mais planos' }))
  expect(await screen.findByRole('button', { name: 'Revisar plano de Outro cliente' })).toBeInTheDocument()
  expect(within(screen.getByRole('button', { name: 'Revisar plano de Maria Silva' })).getByText('Cliente: Maria Silva')).toBeInTheDocument()
  expect(within(screen.getByRole('button', { name: 'Revisar plano de Outro cliente' })).getByText('Cliente: Outro cliente')).toBeInTheDocument()
})


test('opens a readable preview before editing and preserves unsaved changes across preview', async () => {
  const fetchMock = mockFetch()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  expect(await screen.findByRole('heading', { name: 'Leg Press' })).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Revisão do plano' })).getByText('Cliente: Maria Silva')).toBeInTheDocument()
  expect(screen.queryByLabelText(/Nome do plano/)).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([url]) => url.includes('/usable-models'))).toBe(false)
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  fireEvent.change(screen.getByLabelText(/Nome do plano/), { target: { value: 'Treino ajustado' } })
  fireEvent.click(screen.getByRole('tab', { name: 'Visualizar treino' }))
  expect(screen.getByText('Treino ajustado')).toBeInTheDocument()
  expect(screen.getByText('Alterações não salvas')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Fechar revisão' }))
  await screen.findByRole('dialog', { name: 'Descartar alterações não salvas?' })
  fireEvent.click(screen.getByRole('button', { name: 'Continuar editando' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByText('Treino ajustado')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Fechar revisão' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Descartar alterações' }))
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Revisão do plano' })).not.toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH' || init?.method === 'POST')).toBe(false)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Revisar plano de Maria Silva' })).toHaveFocus())
})


test('approval from preview saves displayed unsaved edits before approving the new revision', async () => {
  const fetchMock = mockFetch((_, init) => {
    if (init?.method !== 'PATCH') return undefined
    return ok({ ...plan, ...JSON.parse(init.body as string), revision: 2 })
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  await screen.findByRole('heading', { name: 'Leg Press' })
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  fireEvent.change(screen.getByLabelText(/Nome do plano/), { target: { value: 'Treino revisado na prévia' } })
  fireEvent.click(screen.getByRole('tab', { name: 'Visualizar treino' }))
  fireEvent.click(screen.getByRole('button', { name: 'Aprovar alterações' }))
  await screen.findByText('Plano aprovado e definido como treino atual.')
  const writes = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH' || init?.method === 'POST')
  expect(writes.map(([, init]) => init?.method)).toEqual(['PATCH', 'POST'])
  expect(JSON.parse(writes[0][1]!.body as string)).toMatchObject({ name: 'Treino revisado na prévia', expected_revision: 1 })
  expect(JSON.parse(writes[1][1]!.body as string)).toEqual({ expected_revision: 2 })
})

test.each(['ai', 'adaptation', 'instructor'])('shows bibliographic grounding for an %s proposal throughout instructor review', async (source) => {
  mockFetch((url) => url.endsWith('/pending/draft') ? ok({ ...plan, source, citations: [citation], knowledge_status: 'supported', knowledge_limitations: 'As fontes não substituem a avaliação individual.' }) : undefined)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  const grounding = await screen.findByRole('region', { name: 'Fundamentação bibliográfica' })
  expect(within(grounding).getByRole('link', { name: 'Strength exercises (abre em nova aba)' })).toHaveAttribute('href', citation.url)
  expect(within(grounding).getByRole('alert')).toHaveTextContent('As fontes não substituem a avaliação individual.')
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  expect(grounding).toBeVisible()
  expect(screen.getByText(/Confira sua aplicabilidade aos ajustes e às restrições do cliente antes de aprovar/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Aprovar alterações' })).not.toBeDisabled()
})

test('makes insufficient bibliographic evidence explicit without inventing links', async () => {
  mockFetch((url) => url.endsWith('/pending/draft') ? ok({ ...plan, source: 'ai', citations: [], knowledge_status: 'insufficient_evidence', knowledge_limitations: 'Não há evidência suficiente para esta restrição.' }) : undefined)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  const grounding = await screen.findByRole('region', { name: 'Fundamentação bibliográfica' })
  expect(within(grounding).getByText('Evidência bibliográfica insuficiente')).toBeInTheDocument()
  expect(within(grounding).getByRole('alert')).toHaveTextContent('Não há evidência suficiente para esta restrição.')
  expect(within(grounding).queryByRole('link')).not.toBeInTheDocument()
})

test('replaces previous citations with the returned limitation after instructor edits', async () => {
  const groundedPlan = { ...plan, source: 'ai', citations: [citation], knowledge_status: 'supported', knowledge_limitations: '' }
  const fetchMock = mockFetch((url, init) => {
    if (init?.method === 'PATCH') return ok({ ...groundedPlan, ...JSON.parse(init.body as string), revision: 2, citations: [], knowledge_status: 'insufficient_evidence', knowledge_limitations: 'A fundamentação anterior não foi revalidada para esta versão.' })
    return url.endsWith('/pending/draft') ? ok(groundedPlan) : undefined
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Maria Silva' }))
  expect(await screen.findByRole('link', { name: 'Strength exercises (abre em nova aba)' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Editar rascunho' }))
  fireEvent.change(screen.getByLabelText(/Nome do plano/), { target: { value: 'Plano ajustado' } })
  fireEvent.click(screen.getByRole('button', { name: 'Salvar rascunho' }))
  await screen.findByText('Rascunho salvo. O treino atual não foi alterado.')
  const grounding = screen.getByRole('region', { name: 'Fundamentação bibliográfica' })
  expect(within(grounding).queryByRole('link')).not.toBeInTheDocument()
  expect(within(grounding).getByRole('alert')).toHaveTextContent('A fundamentação anterior não foi revalidada para esta versão.')
  const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
  expect(JSON.parse(patch[1]!.body as string)).not.toHaveProperty('citations')
})
