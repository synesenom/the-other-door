import { scoreText } from '../api'

/** The setting's one name: Profile's label (`profile-form/fields.json`), said the same wherever the setting comes up. */
export const MIN_SCORE_NAME = 'How close a match to show'

/** The setting's value read the way scores are: "0.65 or better". */
export const minScoreValue = (minScore: number) => `${scoreText(minScore)} or better`
