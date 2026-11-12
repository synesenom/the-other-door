// The one place the wizard writes: init_profile with every answer, then the CV the user wrote
// (only if they wrote one), then the photo they chose or removed, then the example story if kept, then the profile read back. Called by the review's Save.
import { call, errorText } from '../../api'
import { toInitArgs } from './reducer'
import type { ShowProfile, WizardState } from './reducer'

export type SaveResult =
  | { ok: true; profile: ShowProfile }
  /** `init_profile` refused some fields: `error` has one `profile/config.json: <field> — <message>` per line. */
  | { ok: false; kind: 'fields'; error: string }
  | { ok: false; kind: 'cv'; error: string }
  /** The photo was refused or could not be kept (the answers and the CV are saved): `error` is the reason. */
  | { ok: false; kind: 'photo'; error: string }
  /** The example story was refused (everything before it is saved): `error` is the reason. */
  | { ok: false; kind: 'story'; error: string }
  | { ok: false; kind: 'read'; error: string }

export async function saveProfile(state: WizardState): Promise<SaveResult> {
  try {
    await call('init_profile', toInitArgs(state))
  } catch (e) {
    return { ok: false, kind: 'fields', error: errorText(e) }
  }
  // After init_profile: it copies the example CV only where there is none, so the CV written here wins.
  if (state.cvText && state.cvText.trim() !== '') {
    try {
      await call('save_cv', { markdown: state.cvText })
    } catch (e) {
      return { ok: false, kind: 'cv', error: errorText(e) }
    }
  }
  // The photo has its own tools: a picked picture is saved by its token, one marked for removal is deleted.
  if (state.photo.kind === 'new') {
    const saved = await window.door.savePhoto(state.photo.token)
    if (!saved.ok) return { ok: false, kind: 'photo', error: saved.error }
  } else if (state.photo.kind === 'none') {
    try {
      await call('remove_photo')
    } catch (e) {
      return { ok: false, kind: 'photo', error: errorText(e) }
    }
  }
  if (state.story?.keep) {
    try {
      await call('save_story', { ...state.story.values })
    } catch (e) {
      return { ok: false, kind: 'story', error: errorText(e) }
    }
  }
  try {
    return { ok: true, profile: await call<ShowProfile>('show_profile') }
  } catch (e) {
    return { ok: false, kind: 'read', error: errorText(e) }
  }
}
