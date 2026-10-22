/** The flat API identifies sessions with the same suffix used by plan generation. */
export function trainingSessions<T extends { exercise_name: string; position?: number }>(items: readonly T[]) {
  const sessions = new Map<string, (T & { displayNumber: number })[]>()
  // Client positions are authoritative; instructor review DTOs use array order.
  const ordered = items.map((item, index) => ({ item, order: item.position ?? index + 1 }))
    .sort((first, second) => first.order - second.order)
  for (const { item } of ordered) {
    const match = /\s*\(dia\s+([a-z]|[1-7])\)\s*$/i.exec(item.exercise_name)
    const day = match?.[1].toUpperCase() ?? ''
    const label = /^[1-7]$/.test(day) ? 'ABCDEFG'[Number(day) - 1] : day
    const exercises = sessions.get(label) ?? []
    exercises.push({
      ...item,
      exercise_name: match ? item.exercise_name.slice(0, match.index) : item.exercise_name,
      displayNumber: exercises.length + 1,
    })
    sessions.set(label, exercises)
  }
  return [...sessions.entries()]
    .sort(([first], [second]) => (first || 'ZZ').localeCompare(second || 'ZZ'))
    .map(([label, exercises]) => ({ label, items: exercises }))
}
