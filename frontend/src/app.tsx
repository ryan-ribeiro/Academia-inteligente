import { Alert, Box, Button, Card, CardContent, Stack, Typography } from '@mui/material'
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { BrowserRouter, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { AdminShell, ClientNavigationStateProvider, ClientShell, PublicShell } from './components/application-shell'
import { RouterButtonLink } from './components/router-button-link'
import { LoadingState, PageHeader, StatusNotice } from './components/ui'
import { OidcSessionClient, type Session } from './auth'
import { replaceLocation } from './browser-navigation'
import { AdminWorkspace } from './admin-workspace'
import { FacialAccessPage } from './facial-access-page'
import { OnboardingAccessPage } from './onboarding-access-page'
import { OnboardingConversationPage } from './onboarding-conversation-page'
import { OnboardingForm } from './onboarding-form'
import { getOwnOnboardingDraft } from './onboarding-draft'
import { CurrentTrainingPage } from './current-training-page'
import { TrainingChatPage } from './training-chat-page'
import { InstructorPendingPlansPage } from './instructor-pending-plans-page'
import { InstructorPlanCollectionsPage } from './instructor-plan-collections-page'
import { InstructorClientsPage } from './instructor-clients-page'
import { InstructorEquipmentPage } from './instructor-equipment-page'
import { ProgressPage } from './progress-page'
import { ProgressModerationPage } from './progress-moderation-page'
import { EquipmentCatalogPage } from './equipment-catalog-page'
import { EquipmentManagementPage } from './equipment-management-page'
import { SocialProfilePage } from './social-profile-page'
import { PostDetailPage } from './post-detail-page'
import { InstructorFeedPage } from './instructor-feed-page'
import { InstructorPostDetailPage } from './instructor-post-detail-page'
import { InstructorShell } from './instructor-shell'
import { SessionContext } from './session-context'

const oidcSessionClient = new OidcSessionClient()

export function App() {
  const [session, setSession] = useState<Session | null>(() => oidcSessionClient.getSession())
  return <SessionContext.Provider value={session}><BrowserRouter><Application session={session} setSession={setSession} /></BrowserRouter></SessionContext.Provider>
}

function Application({ session, setSession }: { session: Session | null; setSession: Dispatch<SetStateAction<Session | null>> }) {
  const location = useLocation()
  const navigate = useNavigate()
  const isEquipmentCatalogRoute = location.pathname === '/equipamentos'
  const onboardingToken = new URLSearchParams(location.search).get('token')
  const isInvitationRoute = location.pathname === '/onboarding' && Boolean(onboardingToken)
  const [completingLogin, setCompletingLogin] = useState(() => {
    const query = new URLSearchParams(window.location.search)
    return query.has('code') || query.has('error')
  })
  const [authenticationError, setAuthenticationError] = useState<string | null>(null)
  const [loggedOut, setLoggedOut] = useState(() => oidcSessionClient.hasLoggedOut())
  const [onboardingComplete, setOnboardingComplete] = useState<boolean | null>(null)
  const [onboardingError, setOnboardingError] = useState(false)
  const [onboardingRetry, setOnboardingRetry] = useState(0)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState(false)
  const logoutDestination = useRef<URL | null>(null)
  const loginCompletionStarted = useRef(false)
  const loginRedirectStarted = useRef(false)
  const logoutStarted = useRef(false)

  useEffect(() => {
    const query = new URL(window.location.href).searchParams
    if ((!query.has('code') && !query.has('error')) || loginCompletionStarted.current) return
    loginCompletionStarted.current = true
    setCompletingLogin(true)
    void oidcSessionClient
      .completeLogin()
      .then((returnPath) => {
        setSession(oidcSessionClient.getSession())
        setLoggedOut(false)
        navigate(returnPath, { replace: true })
      })
      .catch(() => setAuthenticationError('Não foi possível iniciar a sessão. Tente novamente.'))
      .finally(() => setCompletingLogin(false))
  }, [navigate])

  useEffect(() => {
    if (completingLogin || !session?.roles.includes('client') || session.expiresAt <= Date.now()) {
      setOnboardingComplete(null)
      return
    }
    let active = true
    // A token refresh revalidates onboarding without unmounting an active chat.
    // Missing/expired sessions still clear it in the guard above.
    setOnboardingError(false)
    void getOwnOnboardingDraft(session.accessToken)
      .then((draft) => active && setOnboardingComplete(draft.status === 'completed'))
      .catch(() => active && setOnboardingError(true))
    return () => { active = false }
  }, [session, onboardingRetry, completingLogin])

  useEffect(() => {
    if (
      session
      || completingLogin
      || loginCompletionStarted.current
      || authenticationError
      || isEquipmentCatalogRoute
      || isInvitationRoute
      || new URL(window.location.href).searchParams.has('code')
      || new URL(window.location.href).searchParams.has('error')
      || loggedOut
      || loginRedirectStarted.current
    ) return
    loginRedirectStarted.current = true
    void oidcSessionClient.startLogin().catch(() => {
      loginRedirectStarted.current = false
      setAuthenticationError('Não foi possível abrir o login. Tente novamente.')
    })
  }, [authenticationError, completingLogin, loggedOut, session, isEquipmentCatalogRoute, isInvitationRoute])

  useEffect(() => {
    let refreshing = false
    let lastRecordedActivity = 0
    const refreshIfNeeded = async () => {
      const current = oidcSessionClient.getSession()
      if (!current) {
        setSession(null)
        if (oidcSessionClient.hasLoggedOut()) setLoggedOut(true)
        return
      }
      if (current.expiresAt - Date.now() > 60_000 || refreshing) return
      refreshing = true
      try {
        await oidcSessionClient.refreshSession()
        setSession(oidcSessionClient.getSession())
        if (oidcSessionClient.hasLoggedOut()) setLoggedOut(true)
      } finally {
        refreshing = false
      }
    }
    const recordActivity = () => {
      if (Date.now() - lastRecordedActivity < 1_000) return
      lastRecordedActivity = Date.now()
      oidcSessionClient.recordActivity()
      void refreshIfNeeded()
    }
    const activityEvents = ['pointerdown', 'keydown', 'touchstart', 'scroll'] as const
    activityEvents.forEach((event) => window.addEventListener(event, recordActivity, { passive: true }))
    void refreshIfNeeded()
    const timer = window.setInterval(() => { void refreshIfNeeded() }, 1_000)
    // A restored history page must recheck storage before displaying protected data.
    window.addEventListener('pageshow', refreshIfNeeded)
    return () => {
      activityEvents.forEach((event) => window.removeEventListener(event, recordActivity))
      window.clearInterval(timer)
      window.removeEventListener('pageshow', refreshIfNeeded)
    }
  }, [])

  const isAdministrator = session?.roles.includes('admin') ?? false
  const isAdministrativeRoute = location.pathname === '/admin'
    || (isAdministrator && (location.pathname === '/' || location.pathname === '/dashboard'))
  const isProgressModerationRoute = location.pathname === '/admin/publicacoes'
  const isOnboardingRoute = location.pathname === '/onboarding'
  const isOnboardingConversationRoute = location.pathname === '/onboarding/conversa'
  const isCurrentTrainingRoute = location.pathname === '/treino'
  const isTrainingChatRoute = location.pathname === '/assistente'
  const isProgressRoute = location.pathname === '/feed'
  const isEquipmentManagementRoute = location.pathname === '/admin/equipamentos'
  const isFacialAccessRoute = location.pathname === '/admin/acesso-facial'
  const isProfileRoute = location.pathname === '/perfil'
  const viewedProfileId = location.pathname.match(/^\/perfis\/([^/]+)$/)?.[1]
  const viewedPostId = location.pathname.match(/^\/publicacoes\/([^/]+)$/)?.[1]
  const isInstructorRoute = location.pathname.startsWith('/instrutor')
  const instructorPostId = location.pathname.match(/^\/instrutor\/publicacoes\/([^/]+)$/)?.[1]
  const isClientOnboardingRoute = isOnboardingRoute || isOnboardingConversationRoute
  const isClientEntryRoute = location.pathname === '/cliente'
  const isClientRoute = isClientEntryRoute || isClientOnboardingRoute || isCurrentTrainingRoute || isTrainingChatRoute || isProgressRoute || isProfileRoute || Boolean(viewedProfileId) || Boolean(viewedPostId)
  const isInstructor = session?.roles.includes('instructor') ?? false

  function clearSession() {
    oidcSessionClient.clearSession()
    setSession(null)
    setLoggedOut(true)
  }

  async function endSession() {
    if (logoutStarted.current) return
    logoutStarted.current = true
    setLoggingOut(true)
    setLogoutError(false)
    // endSession clears storage synchronously, before optional revocation waits.
    const destination = logoutDestination.current ? Promise.resolve(logoutDestination.current) : oidcSessionClient.endSession()
    setSession(null)
    setLoggedOut(true)
    try {
      logoutDestination.current = await destination
      replaceLocation(logoutDestination.current)
    } catch {
      setLogoutError(true)
      setLoggingOut(false)
      logoutStarted.current = false
    }
  }

  if (loggingOut) return <PublicShell><LoadingState label="Encerrando sessão" /></PublicShell>
  if (logoutError) return <PublicShell><Stack spacing={2}><PageHeader title="Saída pendente" /><StatusNotice severity="error">O acesso neste navegador foi encerrado, mas não foi possível concluir a saída no serviço de login.</StatusNotice><Button variant="contained" onClick={() => void endSession()}>Tentar concluir saída</Button></Stack></PublicShell>
  if (completingLogin || (session && session.expiresAt <= Date.now())) return <PublicShell><LoadingState label="Iniciando sessão" /></PublicShell>

  if (isOnboardingRoute && onboardingToken) {
    return <OnboardingAccessPage token={onboardingToken} />
  }

  if (isEquipmentCatalogRoute) {
    if (session?.roles.includes('client')) {
      return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><EquipmentCatalogPage onSignOut={endSession} showClientNavigation /></ClientNavigationStateProvider>
    }
    return <EquipmentCatalogPage />
  }

  if (authenticationError) {
    return (
      <PublicShell>
        <Stack spacing={3} sx={{ maxWidth: 650, py: { xs: 2, sm: 5 } }}>
          <Typography component="h1" variant="h2">Não foi possível entrar</Typography>
          <Alert severity="error" variant="outlined">{authenticationError}</Alert>
          <Box><Button onClick={() => { oidcSessionClient.beginLoginAfterLogout(); setLoggedOut(false); loginCompletionStarted.current = false; loginRedirectStarted.current = false; setAuthenticationError(null) }} variant="contained">Tentar novamente</Button></Box>
        </Stack>
      </PublicShell>
    )
  }

  if (!session) {
    if (loggedOut) {
      return (
        <PublicShell>
          <Stack spacing={3} sx={{ maxWidth: 520, py: { xs: 2, sm: 5 } }}>
            <Typography component="h1" variant="h2">Sessão encerrada</Typography>
            <Typography color="text.secondary">Sua sessão foi encerrada. Entre novamente para continuar.</Typography>
            <Box><Button onClick={() => { oidcSessionClient.beginLoginAfterLogout(); setLoggedOut(false); loginCompletionStarted.current = false; loginRedirectStarted.current = false }} variant="contained">Entrar novamente</Button></Box>
          </Stack>
        </PublicShell>
      )
    }
    return <PublicShell><LoadingState label="Redirecionando para o login" /></PublicShell>
  }

  if (isAdministrator && (location.pathname === '/' || location.pathname === '/dashboard')) return <Navigate replace to="/admin" />
  if (isInstructor && (location.pathname === '/' || location.pathname === '/dashboard' || location.pathname === '/instrutor')) return <Navigate replace to="/instrutor/feed" />

  const onboardingStatus = onboardingError
    ? <Stack spacing={2}><StatusNotice severity="error">Não foi possível preparar sua área. Tente novamente.</StatusNotice><Button onClick={() => setOnboardingRetry((value) => value + 1)} variant="outlined">Tentar novamente</Button></Stack>
    : <LoadingState label="Preparando sua área" />

  if (isInstructorRoute && !isInstructor) {
    return <ClientShell onSignOut={endSession}><StatusNotice severity="error">Você não tem permissão para acessar esta área.</StatusNotice></ClientShell>
  }
  if (isInstructorRoute && session) {
    if (location.pathname === '/instrutor/equipamentos') return <InstructorEquipmentPage accessToken={session.accessToken} onSignOut={endSession} />
    if (location.pathname === '/instrutor/clientes') return <InstructorClientsPage accessToken={session.accessToken} onSignOut={endSession} />
    if (location.pathname === '/instrutor/adaptacoes') return <Navigate replace to="/instrutor/planos-pendentes" />
    if (location.pathname === '/instrutor/planos-pendentes') return <InstructorPendingPlansPage accessToken={session.accessToken} onSignOut={endSession} />
    if (location.pathname === '/instrutor/meus-planos' || location.pathname === '/instrutor/todos-os-planos') return <InstructorPlanCollectionsPage key={location.pathname} mine={location.pathname === '/instrutor/meus-planos'} accessToken={session.accessToken} onSignOut={endSession} />
    if (instructorPostId) return <InstructorPostDetailPage accessToken={session.accessToken} onSignOut={endSession} postId={instructorPostId} />
    if (location.pathname === '/instrutor/feed') return <InstructorFeedPage accessToken={session.accessToken} onSignOut={endSession} onOpenPost={(id) => navigate(`/instrutor/publicacoes/${id}`)} />
    const title = location.pathname === '/instrutor/perfil' ? 'Perfil do instrutor' : 'Em breve'
    const description = location.pathname === '/instrutor/perfil' ? 'O perfil profissional do instrutor será disponibilizado em uma etapa futura.' : 'Esta funcionalidade ainda não está disponível.'
    return <InstructorShell onSignOut={endSession}><PageHeader eyebrow="Área do instrutor" title={title} description={description} /></InstructorShell>
  }

  if (
    session.roles.includes('client')
    && (isClientEntryRoute || (!isAdministrator && (location.pathname === '/' || location.pathname === '/dashboard')))
  ) {
    return (
      <ClientNavigationStateProvider onboardingComplete={onboardingComplete}>
        {onboardingComplete === null
          ? <ClientShell onSignOut={endSession} showClientNavigation>{onboardingStatus}</ClientShell>
          : <Navigate replace to={onboardingComplete ? '/feed' : '/onboarding'} />}
      </ClientNavigationStateProvider>
    )
  }

  if (isClientRoute && !session?.roles.includes('client')) {
    return (
      <ClientNavigationStateProvider onboardingComplete={onboardingComplete}>
        <ClientShell onSignOut={endSession} showClientNavigation={session.roles.includes('client')}>
          <PageHeader eyebrow="Acesso protegido" title="Área do cliente indisponível" />
          <Alert severity="error" variant="outlined">Você não tem permissão para acessar esta área.</Alert>
        </ClientShell>
      </ClientNavigationStateProvider>
    )
  }

  if (isOnboardingConversationRoute && session) {
    return <Navigate replace to="/assistente" />
  }

  if (isOnboardingRoute && session) {
    return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><OnboardingForm accessToken={session.accessToken} onCompleted={() => setOnboardingComplete(true)} onSignOut={endSession} /></ClientNavigationStateProvider>
  }

  if (location.pathname === '/ocupacao' && session.roles.includes('client')) {
    return <Navigate replace to="/feed" />
  }

  if (isCurrentTrainingRoute && session) {
    return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><CurrentTrainingPage accessToken={session.accessToken} onSignOut={endSession} /></ClientNavigationStateProvider>
  }

  if (isTrainingChatRoute && session) {
    return (
      <ClientNavigationStateProvider onboardingComplete={onboardingComplete}>
        {onboardingComplete === null
          ? <ClientShell onSignOut={endSession} showClientNavigation>{onboardingStatus}</ClientShell>
          : onboardingComplete
            ? <TrainingChatPage accessToken={session.accessToken} onSignOut={endSession} />
            : <OnboardingConversationPage accessToken={session.accessToken} onSignOut={endSession} />}
      </ClientNavigationStateProvider>
    )
  }

  if (isProgressRoute && session) {
    return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><ProgressPage accessToken={session.accessToken} onSignOut={endSession} /></ClientNavigationStateProvider>
  }

  if (isProfileRoute && session) {
    return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><SocialProfilePage accessToken={session.accessToken} onSignOut={endSession} /></ClientNavigationStateProvider>
  }

  if (viewedProfileId && session) {
    return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><SocialProfilePage accessToken={session.accessToken} onSignOut={endSession} profileId={viewedProfileId} /></ClientNavigationStateProvider>
  }

  if (viewedPostId && session) {
    return <ClientNavigationStateProvider onboardingComplete={onboardingComplete}><PostDetailPage accessToken={session.accessToken} onSignOut={endSession} postId={viewedPostId} /></ClientNavigationStateProvider>
  }

  if ((isAdministrativeRoute || isProgressModerationRoute || isEquipmentManagementRoute || isFacialAccessRoute) && !isAdministrator) {
    return (
      <ClientNavigationStateProvider onboardingComplete={onboardingComplete}>
        <ClientShell onSignOut={endSession} showClientNavigation={session.roles.includes('client')}>
          <PageHeader eyebrow="Acesso protegido" title="Área restrita" />
          <Alert severity="error" variant="outlined">Você não tem permissão para acessar esta página.</Alert>
        </ClientShell>
      </ClientNavigationStateProvider>
    )
  }

  if (isProgressModerationRoute && session) {
    return <ProgressModerationPage accessToken={session.accessToken} onSignOut={endSession} />
  }

  if (isEquipmentManagementRoute && session) {
    return <EquipmentManagementPage accessToken={session.accessToken} onSignOut={endSession} />
  }

  if (isFacialAccessRoute && session) {
    return <FacialAccessPage accessToken={session.accessToken} onSignOut={endSession} onUnauthenticated={clearSession} />
  }

  if (isAdministrativeRoute && session) {
    return (
      <AdminShell onSignOut={endSession}>
        <AdminWorkspace accessToken={session.accessToken} onUnauthenticated={clearSession} />
      </AdminShell>
    )
  }

  if (session) {
    return (
      <ClientNavigationStateProvider onboardingComplete={onboardingComplete}>
      <ClientShell onSignOut={endSession} showClientNavigation={!isAdministrator && session.roles.includes('client')}>
        <Stack spacing={3} sx={{ maxWidth: 760 }}>
          <PageHeader eyebrow="Sessão segura" title="Bem-vindo à Academia Inteligente" />
          <StatusNotice severity="success">Sessão autenticada.</StatusNotice>
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography component="h2" variant="h3">Seu espaço está pronto</Typography>
                <Typography color="text.secondary">Novos recursos pessoais aparecerão aqui conforme forem disponibilizados.</Typography>
                {!isAdministrator && (
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} sx={{ alignItems: { xs: 'stretch', sm: 'center' } }}>
                    {onboardingComplete === false && <RouterButtonLink to="/onboarding" variant="contained">Preencher onboarding</RouterButtonLink>}
                    <RouterButtonLink to="/treino" variant="outlined">Ver meu treino</RouterButtonLink>
                    <RouterButtonLink to="/assistente" variant="outlined">Assistente de treino</RouterButtonLink>
                  </Stack>
                )}
                {isAdministrator && <Box><RouterButtonLink to="/admin" variant="contained">Administração</RouterButtonLink></Box>}
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </ClientShell>
      </ClientNavigationStateProvider>
    )
  }

  return null
}
