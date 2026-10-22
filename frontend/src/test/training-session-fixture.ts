import type { CurrentTrainingItem } from '../training-plan'
import type { ReviewItem } from '../training-review'

// Deliberately interleaved API order, with a repeated exercise across sessions.
export const sessionReviewItems: ReviewItem[] = [
  ['Remada (Dia B)', '10', 60],
  ['Agachamento (com apoio) (Dia A)', '8–10', 90],
  ['Ponte de quadril (Dia C)', '12', 45],
  ['Flexão de braços (Dia A)', '6–8', 75],
  ['Agachamento (com apoio) (Dia B)', '8–10', 90],
  ['Prancha (Dia C)', '30 segundos', 0],
].map(([exerciseName, repetitions, restSeconds], index) => ({
  exercise_name: String(exerciseName), sets: index + 1, repetitions: String(repetitions),
  rest_seconds: Number(restSeconds), load_guidance: `Orientação ${index + 1}: técnica controlada, sem dor.`,
  equipment_requirement: `Equipamento registrado ${index + 1}`, equipment_model_id: `model-${index + 1}`,
}))

export const sessionCurrentItems: CurrentTrainingItem[] = sessionReviewItems.map((item, index) => ({ ...item, position: index + 1 }))
export const sessionNames = [
  ['Agachamento (com apoio)', 'Flexão de braços'],
  ['Remada', 'Agachamento (com apoio)'],
  ['Ponte de quadril', 'Prancha'],
]
export const sessionItemIndexes = [[1, 3], [0, 4], [2, 5]]
