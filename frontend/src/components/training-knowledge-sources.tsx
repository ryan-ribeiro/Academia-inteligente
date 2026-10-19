import { Alert, Box, Link, Stack, Typography } from '@mui/material'
import { useId } from 'react'

import type { TrainingKnowledge } from '../training-knowledge'

const statuses = {
  supported: 'Evidência bibliográfica disponível',
  insufficient_evidence: 'Evidência bibliográfica insuficiente',
  outdated: 'Fontes desatualizadas',
  unavailable: 'Consulta às fontes indisponível',
}
const limitations = {
  insufficient_evidence: 'As fontes consultadas não oferecem evidência suficiente para esta orientação. Revise com seu instrutor.',
  outdated: 'As fontes consultadas precisam de atualização. A orientação exige cautela e revisão profissional.',
  unavailable: 'Não foi possível consultar as fontes. A orientação exige revisão profissional.',
}

function safeExternalUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined
  } catch { return undefined }
}

function captureDate(value?: string | null): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString('pt-BR', {
    timeZone: /^\d{4}-\d{2}-\d{2}$/.test(value) ? 'UTC' : 'America/Sao_Paulo',
  })
}

export function TrainingKnowledgeSources({ citations = [], knowledge_status, knowledge_limitations, title = 'Fontes' }: TrainingKnowledge & { title?: string }) {
  const headingId = useId()
  if (!knowledge_status && !knowledge_limitations && citations.length === 0) return null
  const status = knowledge_status ?? 'unavailable'
  const limitation = knowledge_limitations?.trim() || (status === 'supported' ? null : limitations[status])

  return <Stack component="section" aria-labelledby={headingId} spacing={1.25} sx={{ borderTop: '1px solid', borderColor: 'divider', pt: 1.5, minWidth: 0, overflowWrap: 'anywhere' }}>
    <Typography component="h3" id={headingId} variant="subtitle2">{title}</Typography>
    <Typography variant="body2" color="text.secondary">{statuses[status]}</Typography>
    {limitation && <Alert severity={status === 'supported' ? 'info' : 'warning'} variant="outlined">{limitation}</Alert>}
    {citations.length > 0 && <Stack component="ul" spacing={1.5} sx={{ p: 0, m: 0, listStyle: 'none' }}>
      {citations.map((citation, index) => {
        const sourceUrl = safeExternalUrl(citation.url)
        const licenseUrl = safeExternalUrl(citation.license_url)
        const capturedAt = captureDate(citation.captured_at)
        return <Box component="li" key={`${citation.source_id}-${citation.chunk_id}-${index}`}>
          <Typography variant="body2">
            {sourceUrl
              ? <Link href={sourceUrl} target="_blank" rel="noopener noreferrer" aria-label={`${citation.title} (abre em nova aba)`}>{citation.title}</Link>
              : citation.title}
          </Typography>
          {citation.authors.length > 0 && <Typography component="p" variant="caption" color="text.secondary">Autoria: {citation.authors.join(', ')}</Typography>}
          {citation.section && <Typography component="p" variant="caption" color="text.secondary">Trecho: {citation.section}</Typography>}
          <Typography component="p" variant="caption" color="text.secondary">Licença: {licenseUrl
            ? <Link href={licenseUrl} target="_blank" rel="noopener noreferrer" aria-label={`Licença ${citation.license} de ${citation.title} (abre em nova aba)`}>{citation.license}</Link>
            : citation.license}</Typography>
          {citation.attribution && <Typography component="p" variant="caption" color="text.secondary">Atribuição: {citation.attribution}</Typography>}
          {citation.content_note && <Typography component="p" variant="caption" color="text.secondary">{citation.content_note}</Typography>}
          {capturedAt && <Typography component="p" variant="caption" color="text.secondary">Fonte consultada em {capturedAt}</Typography>}
        </Box>
      })}
    </Stack>}
  </Stack>
}
