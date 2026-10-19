import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import { TrainingChatContent } from './training-chat-content'

afterEach(cleanup)

test('renders the assistant exercise table as accessible cells and leaves ordinary text readable', () => {
  render(<TrainingChatContent content={'Treino A — Corpo inteiro\nObjetivo: Ganhar força\nStatus: Aguardando revisão do instrutor\n\n| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |\n|---|---|---:|---|---|---:|\n| 1 | Remada \\| apoio | 3 | 8–12 | Carga confortável | 90 s |\n\nConfira antes de enviar.'} />)
  expect(screen.getByRole('table', { name: 'Ficha de exercícios' })).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: 'Remada | apoio' })).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: '8–12' })).toBeInTheDocument()
  expect(screen.getByText('Confira antes de enviar.')).toBeInTheDocument()
})

test('keeps malformed tables and HTML as escaped text', () => {
  const content = '<script>alert("test")</script>\n| exercício | carga |'
  const { container } = render(<TrainingChatContent content={content} />)
  expect(container.textContent).toBe(content)
  expect(container.querySelector('script')).toBeNull()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})

test('renders all three full-body sheets with their own exercise tables', () => {
  const content = ['A', 'B', 'C'].map((day) => `Treino ${day} — Corpo inteiro\nObjetivo: Ganho de massa muscular\nStatus: Aguardando revisão do instrutor\n\n| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |\n|---|---|---:|---|---|---:|\n| 1 | Remada ${day} | 3 | 8–12 | Carga confortável | 90 s |`).join('\n\n')
  render(<TrainingChatContent content={content} />)
  expect(screen.getAllByRole('table', { name: 'Ficha de exercícios' })).toHaveLength(3)
  for (const day of ['A', 'B', 'C']) {
    expect(screen.getByText(new RegExp(`Treino ${day} — Corpo inteiro`))).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: `Remada ${day}` })).toBeInTheDocument()
  }
})
