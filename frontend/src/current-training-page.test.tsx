import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { CurrentTrainingPage } from './current-training-page'

vi.mock('./occupancy', () => ({ getOccupancy: async () => ({ occupancy: 0 }) }))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const currentPlan = {
  plan_id: 'plan-1',
  version_number: 1,
  status: 'current' as const,
  name: 'Força inicial',
  objective: 'Ganhar força com consistência',
  responsible_instructor_name: 'Maria Silva',
  approved_at: '2026-09-27T12:00:00Z',
  items: [
    {
      exercise_name: 'Agachamento',
      sets: 3,
      repetitions: '8',
      load_guidance: 'Carga confortável e técnica controlada',
      rest_seconds: 90,
      position: 1,
      equipment_requirement: "Máquina histórica",
      equipment_model_id: "retained",
    },
  ],
}

test('renders the current training plan in workout order', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: currentPlan }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
  vi.stubGlobal('fetch', fetchMock)

  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Meu treino' })).toBeInTheDocument()
  expect(screen.getByText('Força inicial')).toBeInTheDocument()
  expect(screen.getByText('Agachamento')).toBeInTheDocument()
  expect(screen.getByText('Equipamento registrado: Máquina histórica')).toBeInTheDocument()
  expect(screen.getByText('3 séries')).toBeInTheDocument()
  expect(screen.getByText('8 repetições')).toBeInTheDocument()
  expect(screen.getByText('Descanso: 90 s')).toBeInTheDocument()
  expect(screen.getByText('Instrutor responsável: Maria Silva')).toBeInTheDocument()
  expect(screen.getByText('Data de aprovação: 27/09/2026')).toBeInTheDocument()
  expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/training/current')
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { Authorization: 'Bearer access-token' } })
})

test('shows an own draft as pending instructor approval, not as the current plan', async () => {
  const draft = { ...currentPlan, status: 'proposal', origin: 'ai', name: 'Rascunho de força' }
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [draft] }))

  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Treino A — Rascunho de força' })).toBeInTheDocument()
  expect(screen.getByText('Rascunho — ainda não aprovado')).toBeInTheDocument()
  expect(screen.getByText(/Seu instrutor precisa revisar, aprovar e ativar/)).toBeInTheDocument()
})

test('renders a clear empty state when the client has no current plan', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] }))

  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)

  expect(await screen.findByText('Seu treino ainda não está disponível')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Gerar rascunho inicial com IA' })).toBeInTheDocument()
})

test('generates and displays a single initial AI draft for the client', async () => {
  const draft = { ...currentPlan, status: 'proposal' as const, origin: 'ai' as const, name: 'Rascunho inicial de força' }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => draft })
  vi.stubGlobal('fetch', fetchMock)

  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Gerar rascunho inicial com IA' }))

  expect(await screen.findByRole('heading', { name: 'Treino A — Rascunho inicial de força' })).toBeInTheDocument()
  expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8000/training/initial-proposal')
  expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST', headers: { Authorization: 'Bearer access-token' } })
  expect(screen.queryByRole('button', { name: 'Gerar rascunho inicial com IA' })).not.toBeInTheDocument()
})

test('renders a controlled error when the current-plan query fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)

  expect(await screen.findByText('Não foi possível carregar seu treino. Tente novamente.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument()
})

test('shows a structured draft and only sends the displayed revision after client confirmation', async () => {
  const draft = {
    ...currentPlan, id: 'draft-1', revision: 3, status: 'proposal', origin: 'ai',
    submitted_for_review_at: null, name: 'Corpo inteiro',
    citations: [], knowledge_status: 'unavailable', knowledge_limitations: 'Consulta às fontes indisponível.',
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [draft] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...draft, revision: 4, submitted_for_review_at: '2026-10-17T20:00:00Z' }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)
  expect(await screen.findByRole('heading', { name: 'Treino A — Corpo inteiro' })).toBeInTheDocument()
  expect(screen.getByText('Objetivo: Ganhar força com consistência')).toBeInTheDocument()
  expect(screen.getByRole('table', { name: 'Ficha de exercícios' })).toBeInTheDocument()
  for (const column of ['Ordem', 'Exercício', 'Séries', 'Repetições ou duração', 'Carga', 'Descanso']) expect(screen.getByRole('columnheader', { name: column })).toBeInTheDocument()
  expect(screen.getByText('90 s')).toBeInTheDocument()
  expect(screen.getByText('Consulta às fontes indisponível.')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' }))
  expect(await screen.findByText(/Enviado para revisão do instrutor/)).toBeInTheDocument()
  expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8000/training/drafts/draft-1/submit')
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ expected_revision: 3 })
  expect(screen.queryByRole('button', { name: 'Enviar rascunho para minha revisão' })).not.toBeInTheDocument()
})

test('keeps an unsubmitted draft visible and explains a stale submission', async () => {
  const draft = { ...currentPlan, id: 'draft-1', revision: 1, status: 'proposal', origin: 'ai', submitted_for_review_at: null }
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [draft] })
    .mockResolvedValueOnce({ ok: false, status: 409 }))
  render(<CurrentTrainingPage accessToken="access-token" onSignOut={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Enviar rascunho para minha revisão' }))
  expect(await screen.findByText(/O rascunho mudou/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' })).toBeEnabled()
  expect(screen.queryByText(/Enviado para revisão do instrutor/)).not.toBeInTheDocument()
})
