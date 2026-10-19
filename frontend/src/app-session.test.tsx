import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from './app'
import { OidcSessionClient, sessionIdleTimeoutMs } from './auth'
import { replaceLocation } from './browser-navigation'

vi.mock('./browser-navigation', () => ({ replaceLocation: vi.fn() }))
beforeEach(() => {
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
  vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000')
  vi.stubEnv('VITE_OIDC_ISSUER', 'http://localhost:8080/realms/academia')
  vi.stubEnv('VITE_OIDC_REDIRECT_URI', 'http://localhost:5173/')
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

function session(roles: string[], overrides = {}) {
  sessionStorage.setItem('academia.session', JSON.stringify({ accessToken: 'access', refreshToken: 'refresh', idToken: 'id', expiresAt: Date.now() + 300_000, lastActivityAt: Date.now(), roles, ...overrides }))
}
const response = (data: unknown) => ({ ok: true, json: async () => data })
function api(url: string) {
  if (url.endsWith('/onboarding/me')) return response({ status: 'completed' })
  if (url.endsWith('/active-clients')) return response({ active_clients: 10 })
  if (url.endsWith('/attendance')) return response({ weeks: [] })
  if (url.endsWith('/occupancy')) return response({ occupancy: 0, status: 'current' })
  if (url.endsWith('/clients') || url.endsWith('/employees')) return response([])
  return { ok: false, status: 404, json: async () => ({ detail: 'Not found' }) }
}

test.each([
  ['client', '/treino', false], ['client', '/treino', true],
  ['instructor', '/instrutor/perfil', false], ['instructor', '/instrutor/perfil', true],
  ['admin', '/admin', false], ['admin', '/admin', true],
] as const)('%s Sair at %s (mobile=%s) clears data immediately and redirects exactly once', async (role, path, mobile) => {
  session([role])
  window.history.replaceState({}, '', path)
  let finishRevocation!: (value: unknown) => void
  const revocation = new Promise((resolve) => { finishRevocation = resolve })
  const fetchMock = vi.fn(async (url: string) => url.endsWith('/revoke') ? revocation : api(url))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  if (mobile) fireEvent.click(screen.getByRole('button', { name: 'Abrir navegação' }))
  fireEvent.click(screen.getByRole('button', { name: 'Sair' }))
  expect(sessionStorage.getItem('academia.session')).toBeNull()
  expect(screen.getByText('Encerrando sessão')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sair' })).not.toBeInTheDocument()
  expect(replaceLocation).not.toHaveBeenCalled()
  await act(async () => { finishRevocation(response({})) })
  expect(replaceLocation).toHaveBeenCalledOnce()
  const url = vi.mocked(replaceLocation).mock.calls[0][0]
  expect(url.pathname).toBe('/realms/academia/protocol/openid-connect/logout')
  expect(url.searchParams.get('id_token_hint')).toBe('id')
  expect(url.searchParams.get('post_logout_redirect_uri')).toBe('http://localhost:5173/')
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/revoke'))).toHaveLength(1)
})

test('provider return and Back to a protected page stay signed out until an explicit new login', async () => {
  sessionStorage.setItem('academia.logged-out', 'true')
  const startLogin = vi.spyOn(OidcSessionClient.prototype, 'startLogin').mockResolvedValue()
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Sessão encerrada' })).toBeInTheDocument()
  act(() => { window.history.pushState({}, '', '/admin'); window.dispatchEvent(new PopStateEvent('popstate')) })
  expect(screen.queryByRole('heading', { name: 'Painel administrativo' })).not.toBeInTheDocument()
  expect(startLogin).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Entrar novamente' }))
  await waitFor(() => expect(startLogin).toHaveBeenCalledOnce())
})

test('failed logout navigation is recoverable without exposing data or losing the ID-token hint', async () => {
  session(['instructor'])
  window.history.replaceState({}, '', '/instrutor/perfil')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({})))
  vi.mocked(replaceLocation).mockImplementationOnce(() => { throw new Error('Navigation blocked') })
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Sair' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Tentar concluir saída' }))
  await waitFor(() => expect(replaceLocation).toHaveBeenCalledTimes(2))
  expect(vi.mocked(replaceLocation).mock.calls[1][0].searchParams.get('id_token_hint')).toBe('id')
  expect(fetch).toHaveBeenCalledOnce()
  expect(sessionStorage.getItem('academia.session')).toBeNull()
})

test.each(['client', 'instructor', 'admin'])('%s idle session ends without an automatic SSO login loop', async (role) => {
  vi.useFakeTimers()
  session([role])
  window.history.replaceState({}, '', role === 'client' ? '/treino' : role === 'instructor' ? '/instrutor/perfil' : '/admin')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => api(url)))
  const startLogin = vi.spyOn(OidcSessionClient.prototype, 'startLogin').mockResolvedValue()
  render(<App />)
  vi.setSystemTime(Date.now() + sessionIdleTimeoutMs)
  await act(async () => { window.dispatchEvent(new Event('pageshow')) })
  expect(screen.getByRole('heading', { name: 'Sessão encerrada' })).toBeInTheDocument()
  expect(sessionStorage.getItem('academia.session')).toBeNull()
  expect(startLogin).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Entrar novamente' }))
  expect(startLogin).toHaveBeenCalledOnce()
})

test('cancelled OIDC callback gives a controlled retry and never loops automatically', async () => {
  window.history.replaceState({}, '', '/?error=access_denied&state=state&error_description=cancelled')
  sessionStorage.setItem('academia.oidc.state', 'state')
  sessionStorage.setItem('academia.pkce.verifier', 'verifier')
  const startLogin = vi.spyOn(OidcSessionClient.prototype, 'startLogin').mockResolvedValue()
  render(<App />)
  const retry = await screen.findByRole('button', { name: 'Tentar novamente' })
  expect(window.location.search).toBe('')
  expect(startLogin).not.toHaveBeenCalled()
  fireEvent.click(retry)
  await waitFor(() => expect(startLogin).toHaveBeenCalledOnce())
})

test('public invitation opens without an unrelated login redirect', async () => {
  window.history.replaceState({}, '', '/onboarding?token=synthetic-invitation')
  const startLogin = vi.spyOn(OidcSessionClient.prototype, 'startLogin').mockResolvedValue()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ status: 'valid' })))
  render(<App />)
  expect(await screen.findByRole('button', { name: 'Iniciar onboarding' })).toBeInTheDocument()
  expect(startLogin).not.toHaveBeenCalled()
})

test('moving from the public catalog to a protected route starts authentication', async () => {
  window.history.replaceState({}, '', '/equipamentos')
  const startLogin = vi.spyOn(OidcSessionClient.prototype, 'startLogin').mockResolvedValue()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response([])))
  render(<App />)
  expect(startLogin).not.toHaveBeenCalled()
  act(() => { window.history.pushState({}, '', '/admin'); window.dispatchEvent(new PopStateEvent('popstate')) })
  await waitFor(() => expect(startLogin).toHaveBeenCalledOnce())
})

test('an expired access token is renewed before showing a protected instructor page', async () => {
  session(['instructor'], { expiresAt: Date.now() - 1 })
  window.history.replaceState({}, '', '/instrutor/perfil')
  let finish!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    .mockResolvedValue(response({ roles: ['instructor'] })))
  render(<App />)
  expect(screen.getByText('Iniciando sessão')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Perfil do instrutor' })).not.toBeInTheDocument()
  await act(async () => { finish(response({ access_token: 'renewed', refresh_token: 'rotated', expires_in: 300 })) })
  expect(await screen.findByRole('heading', { name: 'Perfil do instrutor' })).toBeInTheDocument()
})

test('login completion followed by refresh failure offers a working new login, not an endless spinner', async () => {
  vi.useFakeTimers()
  window.history.replaceState({}, '', '/?code=one-use&state=state')
  sessionStorage.setItem('academia.oidc.state', 'state')
  sessionStorage.setItem('academia.pkce.verifier', 'verifier')
  const startLogin = vi.spyOn(OidcSessionClient.prototype, 'startLogin').mockResolvedValue()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ access_token: 'access', refresh_token: 'refresh', expires_in: 300 }))
    .mockResolvedValueOnce(response({ roles: ['instructor'] })).mockResolvedValue({ ok: false, status: 401 }))
  await act(async () => { render(<App />) })
  vi.setSystemTime(Date.now() + 241_000)
  await act(async () => { window.dispatchEvent(new Event('pageshow')) })
  expect(screen.getByRole('heading', { name: 'Sessão encerrada' })).toBeInTheDocument()
  expect(startLogin).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Entrar novamente' }))
  expect(startLogin).toHaveBeenCalledOnce()
})

test('client landing lookup failure offers retry instead of remaining in preparation forever', async () => {
  session(['client'])
  let failed = true
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/onboarding/me') && failed ? { ok: false, status: 503 } : api(url)))
  render(<App />)
  const retry = await screen.findByRole('button', { name: 'Tentar novamente' })
  failed = false
  fireEvent.click(retry)
  await waitFor(() => expect(window.location.pathname).toBe('/feed'))
})

test.each(['success', 'unavailable'] as const)('refreshing a client token preserves a pending chat through a %s response', async (outcome) => {
  vi.useFakeTimers()
  session(['client'])
  window.history.replaceState({}, '', '/assistente')
  let finishMessage!: (value: unknown) => void
  let finishOnboarding!: (value: unknown) => void
  let onboardingCalls = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/onboarding/me')) {
      onboardingCalls += 1
      return onboardingCalls === 1 ? response({ status: 'completed' }) : new Promise((resolve) => { finishOnboarding = resolve })
    }
    if (url.endsWith('/training/chat/messages')) return new Promise((resolve) => { finishMessage = resolve })
    if (url.endsWith('/training/chat')) return response({ messages: [] })
    if (url.endsWith('/training/current')) return response({ plan: null })
    if (url.endsWith('/training/adaptations')) return response([])
    if (url.endsWith('/token')) return response({ access_token: 'renewed', refresh_token: 'rotated', expires_in: 300 })
    if (url.endsWith('/identity/me')) return response({ roles: ['client'] })
    return api(url)
  }))
  await act(async () => { render(<App />) })
  fireEvent.change(screen.getByLabelText('Escreva sua pergunta'), { target: { value: 'Gere um treino para bíceps.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  expect(screen.getByText('Preparando sua resposta…')).toBeInTheDocument()
  vi.setSystemTime(Date.now() + 241_000)
  await act(async () => { window.dispatchEvent(new Event('pageshow')) })
  expect(onboardingCalls).toBe(2)
  expect(screen.getByText('Preparando sua resposta…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Enviando…' })).toBeDisabled()
  expect(screen.getByLabelText('Escreva sua pergunta')).toHaveValue('Gere um treino para bíceps.')
  await act(async () => { finishOnboarding(response({ status: 'completed' })) })
  await act(async () => { finishMessage(outcome === 'unavailable' ? { ok: false, status: 503 } : response({ messages: [
    { role: 'user', content: 'Gere um treino para bíceps.', created_at: '2026-10-18T20:00:00Z' },
    { role: 'assistant', content: 'Seu rascunho está pronto para conferir.', created_at: '2026-10-18T20:00:01Z' },
  ] })) })
  if (outcome === 'success') {
    expect(screen.getByText('Seu rascunho está pronto para conferir.')).toBeInTheDocument()
  } else {
    expect(screen.getByText('O assistente de treino está indisponível no momento. Tente novamente.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument()
    expect(screen.getByLabelText('Escreva sua pergunta')).toHaveValue('Gere um treino para bíceps.')
  }
  expect(screen.queryByText('Preparando sua resposta…')).not.toBeInTheDocument()
  expect(replaceLocation).not.toHaveBeenCalled()
})

test.each([
  [['admin'], '/admin'], [['instructor'], '/instrutor/feed'],
  [['client', 'instructor'], '/instrutor/feed'], [['admin', 'instructor'], '/admin'],
] as const)('root routes roles %s to %s', async (roles, destination) => {
  session([...roles])
  vi.stubGlobal('fetch', vi.fn(async (url: string) => api(url)))
  render(<App />)
  await waitFor(() => expect(window.location.pathname).toBe(destination))
})
