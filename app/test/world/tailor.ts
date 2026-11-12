// What the stand-in tailor writes: a CV and a cover letter in LaTeX, made from the persona's own
// cv.md, so door's fact check finds nothing unbacked. `<<company>>` and `<<title>>` are filled in by
// door's compile from the job's posting.json, as for the real tailor (#441).
import type { Persona } from './data/personas'

const esc = (s: string) => s.replace(/\\/g, '').replace(/([&%$#_{}])/g, '\\$1').replace(/\*\*(.*?)\*\*/g, '\\textbf{$1}')

/** The CV: every section of cv.md, headings as sections and bullets as items. */
export function cvTex(persona: Persona): string {
  const lines = persona.cv.split('\n')
  const out: string[] = ['\\documentclass[10pt]{article}', '% Keywords: <<title>>', '\\begin{document}', '']
  let inList = false
  const close = () => {
    if (inList) out.push('\\end{itemize}', '')
    inList = false
  }
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (line.startsWith('# ')) {
      close()
      out.push(`\\textbf{${esc(line.slice(2))}}`, '')
    } else if (line.startsWith('## ')) {
      close()
      out.push(`\\section*{${esc(line.slice(3))}}`, '')
    } else if (line.startsWith('### ')) {
      close()
      out.push(`\\subsection*{${esc(line.slice(4))}}`, '')
    } else if (/^\s*[-*] /.test(line)) {
      if (!inList) out.push('\\begin{itemize}')
      inList = true
      out.push(`\\item ${esc(line.replace(/^\s*[-*] /, ''))}`)
    } else if (line.trim() === '') {
      close()
    } else {
      close()
      out.push(esc(line), '')
    }
  }
  close()
  out.push('\\end{document}', '')
  return out.join('\n')
}

/** The letter: about 300 words, the posting's title and company filled in by compile. */
export function coverLetterTex(persona: Persona): string {
  const profile = persona.cv.split('## ')[1]?.split('\n').slice(1).join(' ').trim() ?? ''
  const bullets = [...persona.cv.matchAll(/^\s*[-*] (.*)$/gm)].map((m) => m[1]).slice(0, 4)
  const paragraphs = [
    'Dear hiring team,',
    `I am writing to apply for the <<title>> position at <<company>>. ${profile}`,
    `In my current role I have worked on problems close to the ones this position describes. ${bullets.slice(0, 2).join(' ')} That work taught me to stay close to the people who use the results, and to keep the methods as simple as the decision allows.`,
    `Before that, ${bullets.slice(2, 4).join(' ')} I would bring the same habits to <<company>>: clear questions first, careful work with the data, and results that a team can act on the same week.`,
    `What draws me to <<company>> is the chance to work on problems where the answer changes what the organisation does next. I would welcome the chance to talk about how my experience fits the team, and I am happy to share examples of my work.`,
    `Kind regards,\n\n${persona.name}`,
  ]
  return ['\\documentclass[11pt]{letter}', '\\begin{document}', '', ...paragraphs.map((p) => esc(p).replace(/&lt;/g, '<') + '\n'), '\\end{document}', ''].join('\n')
}
