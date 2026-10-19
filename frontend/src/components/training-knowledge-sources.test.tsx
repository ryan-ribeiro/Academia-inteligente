import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import type { TrainingCitation } from '../training-knowledge'
import { TrainingKnowledgeSources } from './training-knowledge-sources'

const citation: TrainingCitation = {
  chunk_id: 'nhs-strength-1', source_id: 'nhs-strength', title: 'Strength exercises',
  url: 'https://www.nhs.uk/live-well/exercise/strength-exercises/', authors: ['NHS'],
  license: 'OGL v3.0', license_url: 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/',
  section: 'Sit-to-stand', captured_at: '2026-10-13',
  attribution: 'Information from the NHS website, as at 131026.',
}
afterEach(cleanup)

test('shows accessible source, authors, section, license, attribution and localized capture date', () => {
  render(<TrainingKnowledgeSources citations={[citation]} knowledge_status="supported" />)
  expect(screen.getByRole('region', { name: 'Fontes' })).toBeInTheDocument()
  const source = screen.getByRole('link', { name: 'Strength exercises (abre em nova aba)' })
  expect(source).toHaveAttribute('href', citation.url)
  expect(source).toHaveAttribute('target', '_blank')
  expect(source).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByRole('link', { name: /Licença OGL v3.0 de Strength exercises/ })).toHaveAttribute('href', citation.license_url)
  expect(screen.getByText('Autoria: NHS')).toBeInTheDocument()
  expect(screen.getByText('Trecho: Sit-to-stand')).toBeInTheDocument()
  expect(screen.getByText(`Atribuição: ${citation.attribution}`)).toBeInTheDocument()
  expect(screen.getByText('Fonte consultada em 13/10/2026')).toBeInTheDocument()
})

test.each(['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', '/relative', 'https://user:password@example.com/'])('keeps unsafe URL %s as plain text', (url) => {
  render(<TrainingKnowledgeSources citations={[{ ...citation, url, license_url: url }]} knowledge_status="supported" />)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.getByText('Strength exercises')).toBeInTheDocument()
  expect(screen.getByText('Licença: OGL v3.0')).toBeInTheDocument()
})

test.each([
  ['insufficient_evidence', 'Evidência bibliográfica insuficiente', /não oferecem evidência suficiente/],
  ['outdated', 'Fontes desatualizadas', /precisam de atualização/],
  ['unavailable', 'Consulta às fontes indisponível', /Não foi possível consultar as fontes/],
] as const)('explains %s with a controlled limitation', (knowledge_status, label, limitation) => {
  render(<TrainingKnowledgeSources citations={[]} knowledge_status={knowledge_status} />)
  expect(screen.getByText(label)).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent(limitation)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

test('preserves returned limitations and derivative license scope', () => {
  render(<TrainingKnowledgeSources
    citations={[{ ...citation, content_note: 'Resumo traduzido e adaptado. CC BY-SA 4.0 aplica-se apenas a este resumo.' }]}
    knowledge_status="supported" knowledge_limitations="Esta fonte não avalia a sua condição individual."
  />)
  expect(screen.getByRole('alert')).toHaveTextContent('Esta fonte não avalia a sua condição individual.')
  expect(screen.getByText(/CC BY-SA 4.0 aplica-se apenas a este resumo/)).toBeInTheDocument()
})

test('does not create bibliographic claims for legacy messages without metadata', () => {
  const { container } = render(<TrainingKnowledgeSources />)
  expect(container).toBeEmptyDOMElement()
})
