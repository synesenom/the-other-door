// What the stand-in tailor writes: a CV and a cover letter as HTML bodies, made from the persona's own
// cv.md, so door's fact check finds nothing unbacked. `<<company>>` and `<<title>>` are filled in by
// door's compile from the job's posting.json, as for the real tailor (#441).
import type { Persona } from './data/personas'

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')

/** Two skills from cv.md: the first two items of its most comma-separated line (the skills line, in any
 * language). A real tailor's keywords are in the CV it writes, so the ATS read-back finds them and `prepare`
 * does not run the tailor again (#21). */
export function cvKeywords(cv: string): string {
  const commas = (s: string) => s.split(',').length
  const line = cv.split('\n').reduce((best, l) => (commas(l) > commas(best) ? l : best), '')
  return line
    .replace(/\([^)]*\)/g, '')
    .replace(/^[^:]*:/, '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 2)
    .join(', ')
}

/** The kind of each heading the world's own CVs use; any other is `other`. */
const KINDS: Record<string, string> = {
  profile: 'summary', summary: 'summary', experience: 'experience', 'work experience': 'experience', education: 'education',
  skills: 'skills', certifications: 'certifications', languages: 'languages', interests: 'interests',
}
const kindOf = (heading: string) => KINDS[heading.trim().toLowerCase()] ?? 'other'

/** The CV body: every section of cv.md, headings as `<h2>` and bullets as list items. */
export function cvHtml(persona: Persona): string {
  const lines = persona.cv.split('\n')
  const out: string[] = [`<!-- Keywords: ${cvKeywords(persona.cv)} -->`, '']
  let inList = false
  const close = () => {
    if (inList) out.push('</ul>', '')
    inList = false
  }
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (line.startsWith('# ')) {
      close()
      out.push(`<header class="cv-header"><h1>${esc(line.slice(2))}</h1></header>`, '')
    } else if (line.startsWith('## ')) {
      close()
      out.push(`<h2 class="kind-${kindOf(line.slice(3))}">${esc(line.slice(3))}</h2>`, '')
    } else if (line.startsWith('### ')) {
      close()
      out.push(`<h3>${esc(line.slice(4))}</h3>`, '')
    } else if (/^\s*[-*] /.test(line)) {
      if (!inList) out.push('<ul>')
      inList = true
      out.push(`<li>${esc(line.replace(/^\s*[-*] /, ''))}</li>`)
    } else if (line.trim() === '') {
      close()
    } else {
      close()
      out.push(`<p>${esc(line)}</p>`, '')
    }
  }
  close()
  return out.join('\n')
}

/** The letter body: about 300 words, the posting's title and company filled in by compile. */
export function coverLetterHtml(persona: Persona): string {
  const profile = persona.cv.split('## ')[1]?.split('\n').slice(1).join(' ').trim() ?? ''
  const bullets = [...persona.cv.matchAll(/^\s*[-*] (.*)$/gm)].map((m) => m[1]).slice(0, 4)
  const paragraphs = [
    'Dear hiring team,',
    `I am writing to apply for the <<title>> position at <<company>>. ${profile}`,
    `In my current role I have worked on problems close to the ones this position describes. ${bullets.slice(0, 2).join(' ')} That work taught me to stay close to the people who use the results, and to keep the methods as simple as the decision allows.`,
    `Before that, ${bullets.slice(2, 4).join(' ')} I would bring the same habits to <<company>>: clear questions first, careful work with the data, and results that a team can act on the same week.`,
    `What draws me to <<company>> is the chance to work on problems where the answer changes what the organisation does next. I would welcome the chance to talk about how my experience fits the team, and I am happy to share examples of my work.`,
  ]
  // the tokens are the tailor's own and stay as written; everything else is escaped
  const text = (p: string) => esc(p.replace(/<<(title|company)>>/g, '\u0000$1\u0000')).replace(/\u0000(title|company)\u0000/g, '<<$1>>')
  return [...paragraphs.map((p) => `<p>${text(p)}</p>\n`), `<div class="closing"><p class="signoff">Kind regards,</p><p>${esc(persona.name)}</p></div>`, ''].join('\n')
}
