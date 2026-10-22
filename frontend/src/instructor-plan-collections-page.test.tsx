import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import { InstructorPlanCollectionsPage } from './instructor-plan-collections-page'
import { expectReviewSessions } from './test/training-session-assertions'
import { sessionNames, sessionReviewItems } from './test/training-session-fixture'

const plan = { id: 'current', name: 'Força', client_name: 'Ana Silva', status: 'current', revision: 2, approved_at: '2026-09-27T12:00:00Z', responsible_instructor_name: 'Maria Silva', objective: 'Ganhar força', items: [{ exercise_name: 'Agachamento', sets: 3, repetitions: '8', load_guidance: 'Confortável', rest_seconds: 90, equipment_model_id: null, equipment_requirement: null }] }
const past = { ...plan, id: 'past', status: 'superseded', name: 'Treino anterior', responsible_instructor_name: 'João Silva' }
const ok = (body: unknown) => ({ ok: true, json: async () => body })
function mockFetch(override?: (url: string, init?: RequestInit) => unknown) {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    const result = override?.(url, init)
    if (result) return result
    if (url.includes('/responsible')) return ok({ items: [{ reference: 'current', name: 'Maria Silva' }], next_cursor: null })
    if (url.includes('/history')) return ok({ items: [plan, past], next_cursor: null })
    if (url.includes('/collections?')) return ok({ items: [plan], next_cursor: null })
    if (url.endsWith('/past')) return ok(past)
    return ok(plan)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}
function mount(mine = false, entry = '/') { return render(<MemoryRouter initialEntries={[entry]}><InstructorPlanCollectionsPage accessToken="token" onSignOut={vi.fn()} mine={mine} /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('combines filters and opens immutable history with original responsibility', async () => {
  const fetchMock = mockFetch()
  mount()
  await screen.findByText('Cliente: Ana Silva')
  fireEvent.click(screen.getByRole('button', { name: 'Mais filtros' }))
  fireEvent.change(screen.getByLabelText('Nome do cliente'), { target: { value: ' Ana ' } })
  fireEvent.change(screen.getByLabelText('Aprovação a partir de'), { target: { value: '2026-09-27' } })
  fireEvent.change(screen.getByLabelText('Aprovação até'), { target: { value: '2026-09-27' } })
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Instrutor responsável' }))
  fireEvent.click(await screen.findByRole('option', { name: 'Maria Silva' }))
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.includes('search=Ana&responsible=current&start=2026-09-27&end=2026-09-27'))).toBe(true))
  fireEvent.click(screen.getByRole('button', { name: 'Ver plano e histórico de Ana Silva' }))
  await screen.findByRole('button', { name: 'Editar' })
  fireEvent.click(screen.getByRole('tab', { name: 'Histórico' }))
  const historical = screen.getByRole('button', { name: /Treino anterior/ })
  expect(within(historical).getByText('Cliente: Ana Silva')).toBeInTheDocument()
  fireEvent.click(historical)
  await screen.findByText('Histórico — somente leitura')
  expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Treino anterior' })).toHaveFocus()
})

test('cancel preserves draft and explicit confirmation sends the exact revision', async () => {
  const fetchMock = mockFetch((url, init) => {
    if (!url.endsWith('/draft')) return undefined
    const payload = JSON.parse(init!.body as string)
    return payload.discard_id ? { ok: false, status: 409, json: async () => ({ detail: 'stale' }) } : { ok: false, status: 409, json: async () => ({ detail: { code: 'existing_draft', draft: { id: 'existing', name: 'Rascunho de IA', revision: 4 } } }) }
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Ver plano e histórico de Ana Silva' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Editar' }))
  await screen.findByRole('dialog', { name: 'Substituir rascunho existente?' })
  fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/draft'))).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Descartar e criar rascunho' }))
  await screen.findByText('O plano ou rascunho mudou. Recarregue e revise antes de continuar.')
  const calls = fetchMock.mock.calls.filter(([url]) => url.endsWith('/draft'))
  expect(JSON.parse(calls[2][1]!.body as string)).toEqual({ expected_revision: 2, discard_id: 'existing', discard_revision: 4 })
})

test('my plans requests only own responsibility and supports empty and retry states', async () => {
  let fail = true
  const fetchMock = mockFetch((url) => url.includes('/collections?') ? fail ? { ok: false, status: 503, json: async () => ({}) } : ok({ items: [], next_cursor: null }) : undefined)
  mount(true)
  expect(screen.getByText('Carregando planos')).toBeInTheDocument()
  await screen.findByText('Não foi possível carregar ou editar o plano. Tente novamente.')
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Recarregar planos' }))
  await screen.findByText('Nenhum plano encontrado')
  expect(fetchMock.mock.calls.some(([url]) => url.includes('mine=true'))).toBe(true)
  expect(screen.queryByLabelText('Nome do cliente')).not.toBeInTheDocument()
})


test.each([false, true])('collection mine=%s identifies the client in cards and the reading view', async (mine) => {
  mockFetch()
  mount(mine)
  const open = await screen.findByRole('button', { name: 'Ver plano e histórico de Ana Silva' })
  expect(within(open).getByText('Cliente: Ana Silva')).toBeInTheDocument()
  fireEvent.click(open)
  const detail = await screen.findByRole('region', { name: 'Detalhes do plano' })
  expect(within(detail).getByRole('heading', { name: 'Força' })).toHaveFocus()
  expect(within(detail).getByText('Cliente: Ana Silva')).toBeInTheDocument()
  expect(within(detail).getByRole('heading', { name: 'Agachamento' })).toBeInTheDocument()
  for (const label of ['Séries', 'Repetições ou duração', 'Descanso', 'Orientação de carga', 'Confortável']) expect(within(detail).getByText(label)).toBeInTheDocument()
  expect(open).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(within(detail).getByRole('button', { name: /Voltar à lista/ }))
  await waitFor(() => expect(open).toHaveFocus())
  expect(screen.queryByRole('region', { name: 'Detalhes do plano' })).not.toBeInTheDocument()
})

test('clears every applied filter and returns to the complete collection', async () => {
  const fetchMock = mockFetch()
  mount()
  await screen.findByText('Cliente: Ana Silva')
  fireEvent.change(screen.getByLabelText('Nome do cliente'), { target: { value: 'Ana' } })
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
  await screen.findByText('Consulta filtrada')
  fireEvent.click(screen.getByRole('button', { name: 'Limpar filtros' }))
  await waitFor(() => expect(screen.queryByText('Consulta filtrada')).not.toBeInTheDocument())
  expect(screen.getByLabelText('Nome do cliente')).toHaveValue('')
  expect(fetchMock.mock.calls.filter(([url]) => url.includes('/collections?')).at(-1)?.[0]).toMatch(/mine=false&limit=20$/)
})

test.each([false, true])('collection mine=%s preserves sessions on reopening and shows historical prescriptions and attribution', async (mine) => {
  const current = { ...plan, items: sessionReviewItems }
  const historicalItems = sessionReviewItems.map((item) => ({ ...item, exercise_name: `Histórico ${item.exercise_name}`, sets: item.sets + 10, load_guidance: `Histórico ${item.load_guidance}` }))
  const historical = { ...past, approved_at: '2026-08-20T12:00:00Z', items: historicalItems }
  const before = structuredClone({ current, historical })
  const fetchMock = mockFetch((url) => {
    if (url.includes('/collections?')) return ok({ items: [current], next_cursor: null })
    if (url.includes('/history')) return ok({ items: [current, historical], next_cursor: null })
    if (url.endsWith('/current')) return ok(current)
    if (url.endsWith('/past')) return ok(historical)
    return undefined
  })
  const first = mount(mine)
  const open = await screen.findByRole('button', { name: 'Ver plano e histórico de Ana Silva' })
  fireEvent.click(open)
  let detail = await screen.findByRole('region', { name: 'Detalhes do plano' })
  expectReviewSessions(detail)
  expect(within(detail).getByText('Plano atual')).toBeInTheDocument()
  expect(within(detail).getByText('Cliente: Ana Silva')).toBeInTheDocument()
  expect(within(detail).getByText('Maria Silva')).toBeInTheDocument()
  expect(within(detail).getByText(/27 de set\. de 2026/)).toBeInTheDocument()
  fireEvent.click(within(detail).getByRole('tab', { name: 'Histórico' }))
  expect(within(detail).queryByRole('region', { name: 'Treino A' })).not.toBeInTheDocument()
  fireEvent.click(within(detail).getByRole('button', { name: /Treino anterior/ }))
  await screen.findByText('Histórico — somente leitura')
  expectReviewSessions(detail, historicalItems, sessionNames.map((names) => names.map((name) => `Histórico ${name}`)))
  expect(within(detail).getByText('João Silva')).toBeInTheDocument()
  expect(within(detail).getByText(/20 de ago\. de 2026/)).toBeInTheDocument()
  expect(within(detail).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument()
  fireEvent.click(within(detail).getByRole('button', { name: 'Voltar ao plano atual' }))
  await waitFor(() => expect(within(detail).getByText('Plano atual')).toBeInTheDocument())
  expectReviewSessions(detail)
  fireEvent.click(within(detail).getByRole('button', { name: /Voltar à lista/ }))
  await waitFor(() => expect(open).toHaveFocus())
  first.unmount()
  // The client workspace reaches this same reader through the existing deep link.
  mount(mine, '/instrutor/todos-os-planos?plano=current')
  detail = await screen.findByRole('region', { name: 'Detalhes do plano' })
  expectReviewSessions(detail)
  expect(within(detail).getByRole('heading', { name: 'Força' })).toHaveFocus()
  expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  expect({ current, historical }).toEqual(before)
})
