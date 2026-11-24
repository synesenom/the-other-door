import { CheckMark, CrossMark } from './CheckMark'

/**
 * One column of skills, a posting's or the market's: those in the CV with the green check, the rest with the red
 * cross (the marks of Finding jobs' sources and `jobs show`'s ✓/✗). The marks say which column is which; its name
 * and each skill's "in your CV" are for screen readers. `note` adds muted words after a skill (the market's share).
 */
export function SkillColumn({ name, skills, fits, className, note }: { name: string; skills: string[]; fits: boolean; className: string; note?: (skill: string) => string }) {
  return (
    <ul className={`${className} small`} aria-label={name}>
      {skills.map((skill) => (
        <li key={skill} className={`marked ${fits ? 'skill-fits' : 'skill-gap'}`} aria-label={`${skill}, ${fits ? 'in your CV' : 'not in your CV'}`}>
          <span className="mark" aria-hidden="true">
            {fits ? <CheckMark /> : <CrossMark />}
          </span>
          <span>
            {skill}
            {note && <span className="muted">{note(skill)}</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}
