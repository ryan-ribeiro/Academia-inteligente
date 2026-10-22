import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import { CurrentTrainingPage } from './current-training-page'
import { InstructorPendingPlansPage } from './instructor-pending-plans-page'
import { InstructorPlanCollectionsPage } from './instructor-plan-collections-page'
import { expectReviewSessions } from './test/training-session-assertions'
import { sessionCurrentItems, sessionItemIndexes, sessionNames, sessionReviewItems } from './test/training-session-fixture'

vi.mock('./occupancy', () => ({ getOccupancy: async () => ({ occupancy: 0 }) }))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('explicit instructor approval preserves the same A/B/C sheet for the owner and both collections after reload', async () => {
  const pending = {
    id: 'version-abc', plan_id: 'plan-abc', version_number: 2, revision: 4,
    name: 'Três sessões', objective: 'Ganhar força', client_name: 'Ana Sintética', source: 'instructor',
    created_at: '2026-10-20T12:00:00Z', updated_at: '2026-10-21T12:00:00Z',
    current_responsible_instructor_name: null, items: sessionReviewItems,
  }
  const ownerDraft = { ...pending, status: 'proposal', origin: 'instructor', submitted_for_review_at: null, responsible_instructor_name: null, approved_at: null, items: sessionCurrentItems }
  const approved = { ...pending, status: 'current', revision: 5, responsible_instructor_name: 'Maria Instrutora', approved_at: '2026-10-21T12:00:00Z' }
  const ownerCurrent = { ...approved, items: sessionCurrentItems }
  const before = structuredClone({ pending, ownerDraft, approved, ownerCurrent })
  let isApproved = false
  const ok = (body: unknown) => ({ ok: true, json: async () => body })
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/approve')) {
      expect(JSON.parse(init!.body as string)).toEqual({ expected_revision: 4 })
      isApproved = true
      return ok(approved)
    }
    if (url.endsWith('/training/current')) return ok({ plan: isApproved ? ownerCurrent : null })
    if (url.endsWith('/training/drafts')) return ok(isApproved ? [] : [ownerDraft])
    if (url.includes('/pending?')) return ok({ items: isApproved ? [] : [pending], next_offset: null })
    if (url.endsWith('/pending/version-abc')) return ok(pending)
    if (url.includes('/responsible')) return ok({ items: [], next_cursor: null })
    if (url.includes('/collections?') || url.includes('/history?')) return ok({ items: isApproved ? [approved] : [], next_cursor: null })
    if (url.endsWith('/collections/version-abc')) return ok(approved)
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  let mounted = render(<CurrentTrainingPage accessToken="owner" onSignOut={vi.fn()} />)
  await screen.findByText('Rascunho — ainda não aprovado')
  expect(screen.queryByText('Plano atual')).not.toBeInTheDocument()
  for (const [index, label] of ['A', 'B', 'C'].entries()) {
    const section = within(screen.getByRole('region', { name: `Treino ${label}` }))
    const rows = within(section.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    rows.forEach((row, order) => {
      const item = sessionCurrentItems[sessionItemIndexes[index][order]]
      expect(within(row).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([sessionNames[index][order], String(item.sets), item.repetitions, item.load_guidance, `${item.rest_seconds} s`])
    })
  }
  mounted.unmount()
  mounted = render(<MemoryRouter><InstructorPendingPlansPage accessToken="instructor" onSignOut={vi.fn()} /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Revisar plano de Ana Sintética' }))
  expectReviewSessions(await screen.findByRole('region', { name: 'Revisão do plano' }))
  expect(isApproved).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
  await screen.findByText('Plano aprovado e definido como treino atual.')
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/approve'))).toHaveLength(1)
  expect(fetchMock.mock.calls.find(([url]) => url.endsWith('/approve'))?.[0]).toBe('http://localhost:8000/training/plans/plan-abc/versions/2/approve')
  mounted.unmount()
  for (let reload = 0; reload < 2; reload++) {
    mounted = render(<CurrentTrainingPage accessToken="owner" onSignOut={vi.fn()} />)
    await screen.findByText('Plano atual')
    expect(screen.queryByText('Rascunho — ainda não aprovado')).not.toBeInTheDocument()
    expect(screen.getByText('Instrutor responsável: Maria Instrutora')).toBeInTheDocument()
    expect(screen.getByText('Data de aprovação: 21/10/2026')).toBeInTheDocument()
    for (const [index, label] of ['A', 'B', 'C'].entries()) {
      const exercises = within(screen.getByRole('region', { name: `Treino ${label}` })).getAllByRole('article')
      expect(exercises).toHaveLength(2)
      exercises.forEach((exercise, order) => {
        const item = sessionCurrentItems[sessionItemIndexes[index][order]]
        const view = within(exercise)
        expect(view.getByRole('heading', { name: sessionNames[index][order] })).toBeInTheDocument()
        for (const text of [`Exercício ${order + 1}`, `${item.sets} séries`, `${item.repetitions} repetições`, item.rest_seconds ? `Descanso: ${item.rest_seconds} s` : 'Sem descanso programado', item.load_guidance, `Equipamento registrado: ${item.equipment_requirement}`]) expect(view.getByText(text)).toBeInTheDocument()
      })
    }
    mounted.unmount()
  }
  for (const mine of [true, false]) {
    mounted = render(<MemoryRouter><InstructorPlanCollectionsPage accessToken="instructor" onSignOut={vi.fn()} mine={mine} /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Ver plano e histórico de Ana Sintética' }))
    const detail = await screen.findByRole('region', { name: 'Detalhes do plano' })
    expectReviewSessions(detail)
    expect(within(detail).getByText('Plano atual')).toBeInTheDocument()
    expect(within(detail).getByText('Maria Instrutora')).toBeInTheDocument()
    mounted.unmount()
  }
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST' || init?.method === 'PATCH')).toHaveLength(1)
  expect({ pending, ownerDraft, approved, ownerCurrent }).toEqual(before)
})
