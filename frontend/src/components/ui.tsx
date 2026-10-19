import { Alert, Box, CircularProgress, Stack, Typography } from '@mui/material'
import { useContext, type ReactNode } from 'react'
import { WorkspacePresentationContext } from './workspace-presentation'

type PageHeaderProps = {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}

export function PageHeader({ eyebrow, title, description, action }: PageHeaderProps) {
  const workspace = useContext(WorkspacePresentationContext)
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' }, justifyContent: 'space-between', mb: 3, ...(workspace ? { pb: { xs: 2.5, sm: 3 }, borderBottom: '1px solid', borderColor: 'divider', gap: 1 } : {}) }}>
      <Box sx={{ minWidth: 0 }}>
        {eyebrow && <Typography color="primary.main" variant="overline" sx={workspace ? { display: 'block', mb: 1 } : undefined}>{eyebrow}</Typography>}
        <Typography component="h1" sx={{ overflowWrap: 'anywhere' }} variant="h2">{title}</Typography>
        {description && <Typography color="text.secondary" sx={{ maxWidth: 680, mt: 1 }}>{description}</Typography>}
      </Box>
      {action && <Box sx={{ alignSelf: { xs: 'stretch', sm: 'center' }, flexShrink: 0 }}>{action}</Box>}
    </Stack>
  )
}

export function LoadingState({ label }: { label: string }) {
  return (
    <Stack aria-live="polite" role="status" spacing={1.5} sx={{ alignItems: 'center', minHeight: 200, justifyContent: 'center', py: 5 }}>
      <CircularProgress aria-label={label} />
      <Typography color="text.secondary">{label}</Typography>
    </Stack>
  )
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  const workspace = useContext(WorkspacePresentationContext)
  return (
    <Stack component="section" spacing={0.75} sx={{ alignItems: 'flex-start', border: '1px dashed', borderColor: 'divider', borderRadius: 2, maxWidth: 680, p: 3, ...(workspace ? { width: '100%', borderStyle: 'solid', bgcolor: 'background.paper', borderRadius: 3, py: 4 } : {}) }}>
      <Typography component="h2" variant="h4">{title}</Typography>
      <Typography color="text.secondary">{description}</Typography>
    </Stack>
  )
}

export function StatusNotice({ severity, children }: { severity: 'error' | 'success' | 'info'; children: ReactNode }) {
  return <Alert severity={severity} variant="outlined">{children}</Alert>
}

export function ChatMessage({ role, children, footer }: { role: 'user' | 'assistant'; children: ReactNode; footer?: ReactNode }) {
  const isUser = role === 'user'
  return (
    <Box
      aria-label={isUser ? 'Sua mensagem' : 'Mensagem do assistente'}
      component="article"
      sx={{
        alignSelf: isUser ? 'flex-end' : 'flex-start',
        bgcolor: isUser ? 'rgba(255,133,100,0.10)' : 'background.paper',
        border: '1px solid',
        borderColor: isUser ? 'rgba(255,133,100,0.3)' : 'divider',
        borderRadius: isUser ? '20px 20px 4px 20px' : '4px 20px 20px 20px',
        color: 'text.primary',
        maxWidth: { xs: '96%', sm: '84%' },
        minWidth: 0,
        overflowWrap: 'anywhere',
        px: 2,
        py: 1.5,
      }}
    >
      <Typography color="primary.main" variant="overline">
        {isUser ? 'Você' : 'Assistente'}
      </Typography>
      {typeof children === 'string'
        ? <Typography component="p" sx={{ whiteSpace: 'pre-wrap' }}>{children}</Typography>
        : <Box sx={{ minWidth: 0 }}>{children}</Box>}
      {footer && <Box sx={{ mt: 1.5 }}>{footer}</Box>}
    </Box>
  )
}
