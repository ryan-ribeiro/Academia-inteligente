import { Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material'

import type { CurrentTrainingItem } from '../training-plan'

export const trainingColumns = ['Ordem', 'Exercício', 'Séries', 'Repetições ou duração', 'Carga', 'Descanso']

export function TrainingExerciseTable({ rows }: { rows: string[][] }) {
  return <TableContainer aria-label="Tabela de exercícios; role para ver todas as colunas" role="region" tabIndex={0} sx={{ maxWidth: '100%', overflowX: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
    <Table aria-label="Ficha de exercícios" size="small" sx={{ minWidth: 640, '& th, & td': { verticalAlign: 'top', overflowWrap: 'anywhere', whiteSpace: 'normal' } }}>
      <TableHead><TableRow>{trainingColumns.map((column, index) => <TableCell key={column} scope="col" align={index === 0 || index === 2 || index === 5 ? 'right' : 'left'}>{column}</TableCell>)}</TableRow></TableHead>
      <TableBody>{rows.map((row, index) => <TableRow key={index}>{row.map((value, column) => <TableCell key={column} component={column === 0 ? 'th' : 'td'} scope={column === 0 ? 'row' : undefined} align={column === 0 || column === 2 || column === 5 ? 'right' : 'left'}>{value}</TableCell>)}</TableRow>)}</TableBody>
    </Table>
  </TableContainer>
}

export function trainingRows(items: CurrentTrainingItem[]) {
  return [...items].sort((first, second) => first.position - second.position).map((item) => [
    String(item.position), item.exercise_name, String(item.sets), item.repetitions,
    item.load_guidance, `${item.rest_seconds} s`,
  ])
}

export function trainingTitle(name: string) {
  return /^Treino [A-Z]\s*[—–-]/.test(name) ? name : `Treino A — ${name}`
}
