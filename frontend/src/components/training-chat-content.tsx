import { Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'

import { TrainingExerciseTable, trainingColumns } from './training-exercise-table'

function cells(line: string) {
  if (!line.trim().startsWith('|') || !line.trim().endsWith('|')) return []
  return line.trim().slice(1, -1).split(/(?<!\\)\|/).map((cell) => cell.trim().replaceAll('\\|', '|'))
}

/** Render only the training-table syntax; all other content stays escaped text. */
export function TrainingChatContent({ content }: { content: string }) {
  const lines = content.split('\n')
  const blocks: ReactNode[] = []
  let plain: string[] = []
  function flush() {
    if (plain.length) blocks.push(<Typography key={`text-${blocks.length}`} component="div" sx={{ whiteSpace: 'pre-wrap' }}>{plain.join('\n')}</Typography>)
    plain = []
  }
  for (let index = 0; index < lines.length; index += 1) {
    const header = cells(lines[index])
    const separator = cells(lines[index + 1] ?? '')
    if (header.join('|') === trainingColumns.join('|') && separator.length === 6 && separator.every((cell) => /^:?-{3,}:?$/.test(cell))) {
      const rows: string[][] = []
      let end = index + 2
      while (end < lines.length && cells(lines[end]).length === 6) rows.push(cells(lines[end++]))
      if (rows.length) {
        flush()
        blocks.push(<TrainingExerciseTable key={`table-${blocks.length}`} rows={rows} />)
        index = end - 1
        continue
      }
    }
    plain.push(lines[index])
  }
  flush()
  return <Stack spacing={1.5} sx={{ minWidth: 0 }}>{blocks}</Stack>
}
