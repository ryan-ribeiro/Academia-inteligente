import { expect, test } from 'vitest'

import { sessionCurrentItems, sessionReviewItems } from './test/training-session-fixture'
import { trainingSessions } from './training-sessions'

test('orders client positions while keeping positions, references and source objects unchanged', () => {
  const items = [...sessionCurrentItems].reverse()
  const before = structuredClone(items)
  const sessions = trainingSessions(items)
  expect(sessions.map(({ label }) => label)).toEqual(['A', 'B', 'C'])
  expect(sessions.map(({ items }) => items.map(({ position }) => position))).toEqual([[2, 4], [1, 5], [3, 6]])
  expect(sessions.map(({ items }) => items.map(({ displayNumber }) => displayNumber))).toEqual([[1, 2], [1, 2], [1, 2]])
  for (const item of sessions.flatMap(({ items }) => items)) {
    const original = before.find(({ position }) => position === item.position)!
    expect(item).toMatchObject({ ...original, exercise_name: original.exercise_name.replace(/ \(Dia [ABC]\)$/, '') })
    expect(item).not.toBe(items.find(({ position }) => position === item.position))
  }
  expect(items).toEqual(before)
})

test('retains review array order, repeated exercises and exact prescriptions without adding positions', () => {
  const before = structuredClone(sessionReviewItems)
  const sessions = trainingSessions(sessionReviewItems)
  expect(sessions.map(({ items }) => items.map(({ equipment_model_id }) => equipment_model_id))).toEqual([
    ['model-2', 'model-4'], ['model-1', 'model-5'], ['model-3', 'model-6'],
  ])
  expect(sessions.flatMap(({ items }) => items).filter(({ exercise_name }) => exercise_name === 'Agachamento (com apoio)')).toHaveLength(2)
  expect(sessions.flatMap(({ items }) => items).every((item) => !('position' in item))).toBe(true)
  expect(sessionReviewItems).toEqual(before)
})

test('recognizes all legacy days and letter labels case-insensitively, stripping only the trailing marker', () => {
  const items = ['7', '6', '5', '4', '3', '2', '1', 'z', 'D'].map((day) => ({ exercise_name: `Remada (dia A) (pegada neutra) (dIa ${day})  ` }))
  const sessions = trainingSessions(items)
  expect(sessions.map(({ label }) => label)).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'Z'])
  expect(sessions.flatMap(({ items }) => items).every(({ exercise_name }) => exercise_name === 'Remada (dia A) (pegada neutra)')).toBe(true)
  expect(sessions.find(({ label }) => label === 'D')?.items).toHaveLength(2)
})

test('keeps unmatched markers as ordinary content and places mixed unassigned exercises last', () => {
  const ordinary = ['Remada (Dia 8)', 'Remada (Dia AA)', 'Remada (Dia A) com apoio', 'Remada (pegada neutra)'].map((exercise_name) => ({ exercise_name }))
  expect(trainingSessions(ordinary)).toEqual([{ label: '', items: ordinary.map((item, index) => ({ ...item, displayNumber: index + 1 })) }])
  const sessions = trainingSessions([ordinary[0], { exercise_name: 'Prancha (Dia C)' }, ordinary[1]])
  expect(sessions.map(({ label }) => label)).toEqual(['C', ''])
  expect(sessions[1].items.map(({ exercise_name }) => exercise_name)).toEqual([ordinary[0].exercise_name, ordinary[1].exercise_name])
  expect(trainingSessions([])).toEqual([])
})

test('keeps identical prescriptions across days and preserves all text except the trailing marker', () => {
  const base = sessionReviewItems[0]
  const items = ['B', 'A'].map((label) => ({ ...base, exercise_name: `  Remada (pegada neutra) (Dia ${label})` }))
  const sessions = trainingSessions(items)
  expect(sessions.map(({ label }) => label)).toEqual(['A', 'B'])
  expect(sessions.map(({ items }) => items)).toEqual([
    [{ ...base, exercise_name: '  Remada (pegada neutra)', displayNumber: 1 }],
    [{ ...base, exercise_name: '  Remada (pegada neutra)', displayNumber: 1 }],
  ])
})
