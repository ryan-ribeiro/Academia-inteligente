import type { CurrentTrainingItem } from './training-plan'

/** The flat API identifies sessions with the same suffix used by plan generation. */
export function trainingSessions(items: CurrentTrainingItem[]) {
  const sessions = new Map<string, CurrentTrainingItem[]>()
  for (const item of [...items].sort((first, second) => first.position - second.position)) {
    const match = /\s*\(dia\s+([a-z]|[1-7])\)\s*$/i.exec(item.exercise_name)
    const day = match?.[1].toUpperCase() ?? ''
    const label = /^[1-7]$/.test(day) ? 'ABCDEFG'[Number(day) - 1] : day
    const exercises = sessions.get(label) ?? []
    exercises.push({
      ...item,
      exercise_name: match ? item.exercise_name.slice(0, match.index).trim() : item.exercise_name,
      position: exercises.length + 1,
    })
    sessions.set(label, exercises)
  }
  return [...sessions.entries()]
    .sort(([first], [second]) => (first || 'ZZ').localeCompare(second || 'ZZ'))
    .map(([label, exercises]) => ({ label, items: exercises }))
}
