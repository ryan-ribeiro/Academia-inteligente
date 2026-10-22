import { within } from '@testing-library/react'
import { expect } from 'vitest'

import { sessionItemIndexes, sessionNames, sessionReviewItems } from './training-session-fixture'

export function expectReviewSessions(container: HTMLElement, items = sessionReviewItems, names = sessionNames) {
  const view = within(container)
  for (const [index, label] of ['A', 'B', 'C'].entries()) {
    const section = within(view.getByRole('region', { name: `Treino ${label}` }))
    expect(section.getByRole('heading', { name: `Treino ${label}`, level: 3 })).toBeInTheDocument()
    expect(section.getByText('2 exercícios')).toBeInTheDocument()
    const exercises = section.getAllByRole('listitem')
    expect(exercises).toHaveLength(2)
    exercises.forEach((exercise, order) => {
      const item = items[sessionItemIndexes[index][order]]
      const details = within(exercise)
      expect(details.getByRole('heading', { name: names[index][order], level: 4 })).toBeInTheDocument()
      for (const text of [String(order + 1).padStart(2, '0'), String(item.sets), item.repetitions, `${item.rest_seconds} s`, item.load_guidance, item.equipment_requirement!]) expect(details.getByText(text)).toBeInTheDocument()
    })
  }
}
