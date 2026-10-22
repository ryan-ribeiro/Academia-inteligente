import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { TrainingChatPage } from './training-chat-page'

const citation = {
  chunk_id: 'strength-1', source_id: 'nhs-strength', title: 'Strength exercises',
  url: 'https://www.nhs.uk/live-well/exercise/strength-exercises/', authors: ['NHS'],
  license: 'OGL v3.0', license_url: 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/',
  section: 'Sit-to-stand',
}

vi.mock('./occupancy', () => ({ getOccupancy: async () => ({ occupancy: 0 }) }))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('replaces a legacy invalid draft in chat without presenting its exercise table or submission action', async () => {
  const invalid = {
    id: 'legacy-draft', plan_id: 'legacy-plan', version_number: 1, revision: 1, status: 'proposal', origin: 'ai',
    name: 'Treino antigo', objective: 'Ganhar massa muscular', submitted_for_review_at: null,
    preview: null, validation_error: 'Este rascunho contém exercícios inválidos e precisa ser gerado novamente.',
    items: [{ position: 1, exercise_name: 'Peso corporal (Dia A)', sets: 2, repetitions: '3-5', load_guidance: 'Peso corporal', rest_seconds: 60 }],
  }
  const corrected = { ...invalid, revision: 2, validation_error: undefined,
    items: [{ ...invalid.items[0], exercise_name: 'Agachamento com apoio' }],
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [], draft: invalid }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => corrected })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  const regenerate = await screen.findByRole('button', { name: 'Gerar nova ficha' })
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  expect(screen.queryByText('Peso corporal (Dia A)')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enviar rascunho para minha revisão' })).not.toBeInTheDocument()
  fireEvent.click(regenerate)
  expect(await screen.findByText('Agachamento com apoio')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' })).toBeInTheDocument()
  expect(fetchMock.mock.calls[3][0]).toBe('http://localhost:8000/training/initial-proposal')
})

test('shows the submitted message and processing feedback, then a visible validation error with retry', async () => {
  let finishResponse!: (value: unknown) => void
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockImplementationOnce(() => new Promise((resolve) => { finishResponse = resolve }))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000020' })
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText('Seu espaço para tirar dúvidas')
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: 'Sugira um treino para mim' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  expect(within(screen.getByRole('article', { name: 'Sua mensagem' })).getByText('Sugira um treino para mim')).toBeInTheDocument()
  expect(within(screen.getByRole('article', { name: 'Mensagem do assistente' })).getByRole('status')).toHaveTextContent('Preparando sua resposta…')
  expect(screen.getByRole('progressbar', { name: 'Gerando resposta do assistente' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Enviando…' })).toBeDisabled()
  finishResponse({ ok: false, status: 422 })
  expect(await screen.findByText('A resposta da IA não pôde ser validada. Tente novamente; seu treino não foi alterado.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument()
  expect(screen.queryByText('Preparando sua resposta…')).not.toBeInTheDocument()
})

test('previews a generated training table with sources and submits only on explicit click', async () => {
  const preview = 'Treino A — Corpo inteiro\nObjetivo: Ganhar força\nStatus: Aguardando revisão do instrutor\n\n| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |\n|---|---|---:|---|---|---:|\n| 1 | Agachamento | 3 | 8–12 | Carga confortável | 90 s |'
  const draft = {
    id: 'draft-1', plan_id: 'plan-1', version_number: 1, revision: 1, status: 'proposal', origin: 'ai',
    name: 'Corpo inteiro', objective: 'Ganhar força', submitted_for_review_at: null, preview,
    citations: [citation], knowledge_status: 'supported', knowledge_limitations: 'Revisão profissional necessária.',
    items: [{ position: 1, exercise_name: 'Agachamento', sets: 3, repetitions: '8–12', load_guidance: 'Carga confortável', rest_seconds: 90 }],
  }
  let finishSubmission!: (value: unknown) => void
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [{ role: 'assistant', content: preview, created_at: '2026-10-17T20:00:00Z', ...draft }], draft }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockImplementationOnce(() => new Promise((resolve) => { finishSubmission = resolve }))
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  expect(await screen.findByRole('table', { name: 'Ficha de exercícios' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Strength exercises (abre em nova aba)' })).toBeInTheDocument()
  const send = screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' })
  expect(fetchMock).toHaveBeenCalledTimes(3)
  fireEvent.click(send)
  expect(send).toBeDisabled()
  fireEvent.click(send)
  expect(fetchMock).toHaveBeenCalledTimes(4)
  expect(fetchMock.mock.calls[3][0]).toBe('http://localhost:8000/training/drafts/draft-1/submit')
  expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({ expected_revision: 1 })
  finishSubmission({ ok: true, json: async () => ({ ...draft, revision: 2, submitted_for_review_at: '2026-10-17T21:00:00Z' }) })
  expect(await screen.findByText(/Enviado para revisão do instrutor/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enviar rascunho para minha revisão' })).not.toBeInTheDocument()
})

test('sends a Portuguese client training-chat message with a frontend UUID', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [
      { role: 'user', content: 'Como faço o agachamento?', created_at: '2026-09-22T00:00:00Z' },
      { role: 'assistant', content: 'Faça com controle.', created_at: '2026-09-22T00:00:01Z', citations: [citation], knowledge_status: 'supported', knowledge_limitations: '' },
    ] }) })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000016' })

  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  expect(await screen.findByText('Seu espaço para tirar dúvidas')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: 'Como faço o agachamento?' } })
  fireEvent.keyDown(screen.getByLabelText('Escreva sua pergunta'), { key: 'Enter' })
  expect(await screen.findByText('Faça com controle.')).toBeInTheDocument()
  expect(within(screen.getByRole('article', { name: 'Mensagem do assistente' })).getByRole('region', { name: 'Fontes' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Strength exercises (abre em nova aba)' })).toHaveAttribute('href', citation.url)
  expect(fetchMock.mock.calls[3][0]).toBe('http://localhost:8000/training/chat/messages')
  expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({
    message: 'Como faço o agachamento?', client_request_id: '00000000-0000-4000-8000-000000000016',
  })
})

test('reuses its client request UUID for a retry and explains the draft-review boundary', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
    .mockResolvedValueOnce({ ok: false, status: 503 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000017' })

  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText('Seu espaço para tirar dúvidas')
  expect(screen.getByText(/Seu plano atual só muda após revisão profissional/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: 'Troque meu exercício' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  expect(await screen.findByText('O assistente de treino está indisponível no momento. Tente novamente.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }))
  await screen.findByText('Seu espaço para tirar dúvidas')
  expect(JSON.parse(fetchMock.mock.calls[3][1].body).client_request_id).toBe(
    JSON.parse(fetchMock.mock.calls[4][1].body).client_request_id,
  )
})

test('offers an AI-detected change for client confirmation before creating a proposal', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [
      {
        role: 'user', content: 'Meu joelho incomoda no agachamento.',
        created_at: '2026-09-23T00:00:00Z', client_request_id: '00000000-0000-4000-8000-000000000018',
      },
      {
        role: 'assistant', content: 'Posso preparar uma proposta para revisão.',
        created_at: '2026-09-23T00:00:01Z', reply_to_client_request_id: '00000000-0000-4000-8000-000000000018',
        adaptation_suggested: true, adaptation_reason: 'Desconforto relatado no agachamento.',
      },
    ] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: { plan_id: 'plan-1' } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({
      id: 'proposal-1', status: 'proposed', source_client_request_id: '00000000-0000-4000-8000-000000000018', reason: 'Desconforto relatado no agachamento.',
      explanation: 'Uma proposta será enviada para sua revisão.', operations: [],
      citations: [citation], knowledge_status: 'supported', knowledge_limitations: '',
    }) })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000019' })

  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText('Sugestão de alteração')
  fireEvent.click(screen.getByRole('button', { name: 'Gerar rascunho para conferir' }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
  expect(await screen.findByRole('link', { name: 'Strength exercises (abre em nova aba)' })).toBeInTheDocument()
  expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toMatchObject({
    source_client_request_id: '00000000-0000-4000-8000-000000000018',
  })
})

test('shows the complete adaptation table before sending it to instructor review and preserves it on failure', async () => {
  const preview = 'Treino A — Corpo inteiro\nObjetivo: Ganhar massa muscular\nStatus: Aguardando revisão do instrutor\n\n| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |\n|---|---|---:|---|---|---:|\n| 1 | Remada com apoio | 3 | 8–12 | Carga confortável para execução controlada | 90 s |\n| 2 | Ponte de quadril | 3 | 10–12 | Peso corporal, conforme tolerância | 60 s |'
  const proposal = {
    id: 'proposal-1', status: 'proposed', source_client_request_id: 'source-1',
    reason: 'Ajustar o treino.', explanation: 'Confira a ficha antes de enviar.', preview,
    operations: [], base_items: [], citations: [citation], knowledge_status: 'supported', knowledge_limitations: '',
  }
  let finishSubmission!: (value: unknown) => void
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [{
      role: 'assistant', content: 'Posso preparar uma proposta para revisão.',
      created_at: '2026-10-18T12:00:00Z', reply_to_client_request_id: 'source-1',
      adaptation_suggested: true, adaptation_reason: 'Ajustar o treino.',
    }] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: { plan_id: 'current-plan' } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => proposal })
    .mockImplementationOnce(() => new Promise((resolve) => { finishSubmission = resolve }))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...proposal, status: 'pending_instructor_review' }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Gerar rascunho para conferir' }))
  const table = await screen.findByRole('table', { name: 'Ficha de exercícios' })
  expect(within(table).getByText('Remada com apoio')).toBeInTheDocument()
  expect(within(table).getByText('Ponte de quadril')).toBeInTheDocument()
  expect(within(table).getByText('90 s')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(4)
  const send = screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' })
  fireEvent.click(send)
  expect(send).toBeDisabled()
  fireEvent.click(send)
  expect(fetchMock).toHaveBeenCalledTimes(5)
  expect(fetchMock.mock.calls[4][0]).toBe('http://localhost:8000/training/adaptations/proposal-1/client-decision')
  expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ accept: true })
  finishSubmission({ ok: false, status: 409 })
  await screen.findByText(/Já existe um rascunho ou o treino mudou/)
  expect(table).toBeInTheDocument()
  expect(send).toBeEnabled()
  expect(screen.queryByText(/Enviado para revisão do instrutor/)).not.toBeInTheDocument()
  fireEvent.click(send)
  expect(await screen.findByText(/Enviado para revisão do instrutor/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enviar rascunho para minha revisão' })).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(6)
  expect(fetchMock.mock.calls[5][0]).toBe(fetchMock.mock.calls[4][0])
})

test('reuses the adaptation generation request UUID after an unavailable response', async () => {
  let sequence = 0
  vi.stubGlobal('crypto', { randomUUID: () => `request-${++sequence}` })
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [{
      role: 'assistant', content: 'Posso preparar uma proposta.', created_at: '2026-10-18T12:00:00Z',
      reply_to_client_request_id: 'source-1', adaptation_suggested: true, adaptation_reason: 'Alterar a carga.',
    }] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: { plan_id: 'current-plan' } }) })
    .mockResolvedValueOnce({ ok: false, status: 503 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({
      id: 'proposal-1', status: 'proposed', source_client_request_id: 'source-1',
      explanation: 'Confira a ficha.', operations: [], preview: '',
    }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  const generate = await screen.findByRole('button', { name: 'Gerar rascunho para conferir' })
  fireEvent.click(generate)
  await screen.findByText('A proposta de alteração está indisponível no momento. Tente novamente.')
  fireEvent.click(generate)
  await screen.findByText('Confira a ficha.')
  expect(JSON.parse(fetchMock.mock.calls[3][1].body).client_request_id).toBe(
    JSON.parse(fetchMock.mock.calls[4][1].body).client_request_id,
  )
})

test('answers an exercise question with its targeted sheet and sends that revision directly to the instructor', async () => {
  const question = 'Que exercícios posso fazer para ganho de massa muscular no bíceps?'
  const preview = 'Treino A — Bíceps\nObjetivo: Ganho de massa muscular\nStatus: Aguardando revisão do instrutor\n\n| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |\n|---|---|---:|---|---|---:|\n| 1 | Rosca direta | 3 | 8–12 | Carga confortável e controlada | 90 s |\n| 2 | Rosca alternada | 3 | 10–12 | Conforme tolerância individual | 60 s |'
  const draft = {
    id: 'biceps-draft', plan_id: 'suggestion-plan', version_number: 1, revision: 4,
    status: 'proposal', origin: 'ai', name: 'Bíceps', objective: 'Ganho de massa muscular',
    submitted_for_review_at: null, preview, items: [], citations: [], knowledge_status: 'insufficient_evidence',
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: { plan_id: 'current-plan' } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [{ role: 'assistant', content: preview, created_at: '2026-10-18T15:00:00Z' }], draft }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...draft, revision: 5, submitted_for_review_at: '2026-10-18T15:01:00Z' }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText('Seu espaço para tirar dúvidas')
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: question } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  const table = await screen.findByRole('table', { name: 'Ficha de exercícios' })
  expect(within(table).getByText('Rosca direta')).toBeInTheDocument()
  expect(within(table).getByText('Rosca alternada')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Gerar rascunho para conferir' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' }))
  expect(await screen.findByText(/Enviado para revisão do instrutor/)).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(5)
  expect(fetchMock.mock.calls[4][0]).toBe('http://localhost:8000/training/drafts/biceps-draft/submit')
  expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ expected_revision: 4 })
  expect(fetchMock.mock.calls.some(([url, init]) => url.includes('/adaptations') && init?.method === 'POST')).toBe(false)
})

test.each([false, true])('shows the instructor submission button after rebuilding the routine (existing draft: %s)', async (hasDraft) => {
  const question = 'Refaça todo a minha ficha de treino do zero, para ganho de massa'
  const preview = 'Treino A — Ganho de massa\nObjetivo: Ganho de massa muscular\nStatus: Aguardando revisão do instrutor\n\n| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |\n|---|---|---:|---|---|---:|\n| 1 | Remada | 3 | 8–12 | Carga confortável | 90 s |'
  const draft = {
    id: 'rebuilt-draft', plan_id: 'rebuilt-plan', revision: 4, version_number: 1,
    status: 'proposal', origin: 'ai', name: 'Ganho de massa', objective: 'Ganho de massa muscular',
    submitted_for_review_at: null, preview, items: [], citations: [], knowledge_status: 'insufficient_evidence',
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [], draft: hasDraft ? { ...draft, revision: 3, submitted_for_review_at: '2026-10-20T12:00:00Z' } : null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: { plan_id: 'current-plan' } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [{ role: 'assistant', content: preview, created_at: '2026-10-20T15:00:00Z' }], draft }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...draft, revision: 5, submitted_for_review_at: '2026-10-20T15:01:00Z' }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText('Seu espaço para tirar dúvidas')
  expect(screen.queryByRole('button', { name: 'Enviar rascunho para minha revisão' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: question } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  const send = await screen.findByRole('button', { name: 'Enviar rascunho para minha revisão' })
  expect(screen.getAllByRole('table', { name: 'Ficha de exercícios' })).toHaveLength(1)
  expect(within(screen.getByRole('table', { name: 'Ficha de exercícios' })).getByText('Remada')).toBeInTheDocument()
  expect(JSON.parse(fetchMock.mock.calls[3][1].body).message).toBe(question)
  fireEvent.click(send)
  expect(await screen.findByText(/Enviado para revisão do instrutor/)).toBeInTheDocument()
  expect(fetchMock.mock.calls[4][0]).toBe('http://localhost:8000/training/drafts/rebuilt-draft/submit')
  expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ expected_revision: 4 })
  expect(fetchMock).toHaveBeenCalledTimes(5)
})

test('refreshes a superseded adaptation when a new targeted request replaces its draft', async () => {
  const adaptation = { id: 'adaptation', status: 'pending_instructor_review', source_client_request_id: 'source', explanation: 'Adaptação anterior', operations: [], base_items: [], preview: '' }
  const draft = { id: 'draft', plan_id: 'targeted-plan', revision: 2, name: 'Bíceps', objective: 'Hipertrofia', items: [{ exercise_name: 'Rosca direta', sets: 3, repetitions: '8–12', load_guidance: 'Carga confortável', rest_seconds: 90 }], submitted_for_review_at: null }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [adaptation] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: { plan_id: 'current-plan' } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [{ role: 'assistant', content: 'Preparei sua ficha de bíceps.', created_at: '2026-10-18T15:00:00Z' }], draft }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [{ ...adaptation, status: 'superseded' }] })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText(/Enviado para revisão do instrutor/)
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: 'Quais exercícios posso fazer para bíceps?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  await screen.findByText('Status: Substituída por uma nova solicitação ou versão')
  expect(screen.queryByText(/Enviado para revisão do instrutor/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Enviar rascunho para minha revisão' })).toBeInTheDocument()
  expect(screen.getByRole('table', { name: 'Ficha de exercícios' })).toHaveTextContent('Rosca direta')
  expect(fetchMock.mock.calls[4][0]).toBe('http://localhost:8000/training/adaptations')
})

test('keeps multiline messages editable without sending Shift+Enter', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  await screen.findByText('Seu espaço para tirar dúvidas')
  const input = screen.getByLabelText('Escreva sua pergunta')
  fireEvent.change(input, { target: { value: 'Treino dois dias\nPrefiro manhã' } })
  fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
  expect(fetchMock).toHaveBeenCalledTimes(3)
  expect(input).toHaveValue('Treino dois dias\nPrefiro manhã')
  expect(screen.getByText(/corrigir apenas um dado/)).toBeInTheDocument()
})

test('shows initial conversation failures instead of a permanent spinner', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Falha de conexão')))
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  expect(await screen.findByText('Falha de conexão')).toBeInTheDocument()
  expect(screen.queryByText('Carregando assistente de treino')).not.toBeInTheDocument()
})

test('restores persisted assistant sources and limitations without citing user messages', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [
      { role: 'user', content: 'Tenho dúvidas sobre mobilidade.', created_at: '2026-10-13T12:00:00Z', citations: [citation], knowledge_status: 'supported' },
      { role: 'assistant', content: 'Consulte seu instrutor antes de ajustar seu treino.', created_at: '2026-10-13T12:00:01Z', citations: [citation], knowledge_status: 'outdated', knowledge_limitations: 'A revisão desta fonte está vencida.' },
    ] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ plan: null }) }))
  render(<TrainingChatPage accessToken="access-token" onSignOut={vi.fn()} />)
  expect(await screen.findByText('Fontes desatualizadas')).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Fontes' })).getByRole('alert')).toHaveTextContent('A revisão desta fonte está vencida.')
  expect(within(screen.getByRole('article', { name: 'Sua mensagem' })).queryByRole('region', { name: 'Fontes' })).not.toBeInTheDocument()
  expect(within(screen.getByRole('article', { name: 'Mensagem do assistente' })).getByRole('link', { name: 'Strength exercises (abre em nova aba)' })).toBeInTheDocument()
})
