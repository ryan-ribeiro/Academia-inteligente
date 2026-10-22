import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import { expectReviewSessions } from '../test/training-session-assertions'
import { sessionReviewItems } from '../test/training-session-fixture'
import { TrainingPlanContent } from './training-plan-content'

afterEach(cleanup)

test('groups positionless review items into expanded named sessions with complete prescriptions', () => {
  const before = structuredClone(sessionReviewItems)
  const { container } = render(<TrainingPlanContent plan={{ name: 'Três dias', objective: 'Ganhar força', items: sessionReviewItems }} />)
  expect(screen.getAllByRole('region').map((section) => section.getAttribute('aria-label'))).toEqual(['Treino A', 'Treino B', 'Treino C'])
  expectReviewSessions(container)
  expect(sessionReviewItems).toEqual(before)
})

test('keeps single-session and mixed unassigned content without inferring days from the plan name', () => {
  const plain = { ...sessionReviewItems[0], exercise_name: 'Remada (pegada neutra)' }
  const { rerender } = render(<TrainingPlanContent plan={{ name: 'Treino A/B/C', objective: 'Força', items: [plain, plain] }} />)
  expect(screen.queryByRole('heading', { name: 'Treino A' })).not.toBeInTheDocument()
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
  expect(screen.getAllByRole('heading', { name: plain.exercise_name })).toHaveLength(2)
  rerender(<TrainingPlanContent plan={{ name: 'Misto', objective: 'Força', items: [plain, { ...plain, exercise_name: 'Remada (pegada neutra) (dia 7)' }] }} />)
  expect(within(screen.getByRole('region', { name: 'Treino G' })).getByRole('heading', { name: plain.exercise_name })).toBeInTheDocument()
  const unassigned = within(screen.getByRole('region', { name: 'Exercícios sem ficha definida' }))
  expect(unassigned.getByRole('heading', { name: 'Exercícios sem ficha definida', level: 3 })).toBeInTheDocument()
  expect(unassigned.getByText('1 exercício')).toBeInTheDocument()
  expect(unassigned.getByRole('heading', { name: plain.exercise_name })).toBeInTheDocument()
})
