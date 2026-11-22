import { scoreText } from '../api'
import fields from './profile-form/fields.json'

/** The setting's one name, read from Profile's own label, said the same wherever the setting comes up. */
export const MIN_SCORE_NAME = fields.fields.find((f) => f.key === 'min_score')!.label

/** The setting's three choices as Profile offers them. */
export const MATCH: [number, string][] = [[0.5, 'Broad'], [0.65, 'Balanced'], [0.75, 'Strong']]

/** The setting's value read the way scores are: "0.65 or better". */
export const minScoreValue = (minScore: number) => `${scoreText(minScore)} or better`

/** The choice Profile shows for a value: one of the three, or "Your own (0.70)" for a value set by hand. */
export const minScoreChoice = (minScore: number) => MATCH.find(([n]) => n === minScore)?.[1] ?? `Your own (${scoreText(minScore)})`

/** The setting as Profile shows it: "Match fit: Balanced". */
export const minScoreSetting = (minScore: number) => `${MIN_SCORE_NAME}: ${minScoreChoice(minScore)}`
