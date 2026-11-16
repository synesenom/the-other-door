#set page(paper: "a4", margin: 0pt)
#set text(font: "Lato", size: 9.5pt, fill: rgb("#1E1A16"), lang: "en")
#set par(leading: 0.5em, spacing: 0.6em)
#set list(indent: 0pt, body-indent: 0.4em, spacing: 0.3em)
#let accent = rgb("#0B7285")
#let muted = rgb("#5C6770")
#let sec(t) = block(above: 10pt, below: 3pt, sticky: true)[#text(size: 11pt, fill: accent, tracking: 0.05em, weight: "bold")[#upper(t)] #v(-5pt) #line(length: 100%, stroke: 1pt + accent)]
#let job(role, dates, company) = block(above: 8pt, below: 0pt, sticky: true)[#grid(columns: (1fr, auto), text(weight: "bold")[#role], text(fill: muted, weight: "regular")[#dates]) #text(fill: accent)[#company]]
#place(top + left, dx: 36pt, dy: 36pt, text(size: 26pt, fill: accent, weight: "bold")[Mira Valdis])
#place(top + left, dx: 36pt, dy: 74pt, text(size: 12pt, fill: muted)[Data Engineer])
#place(top + left, dx: 36pt, dy: 98pt, block(width: 523pt)[Data Engineer with eight years of experience, who likes clear plans and small, steady steps.])
#place(top + left, dx: 36pt, dy: 150pt, image("icons/mail.svg", width: 12pt, height: 12pt))
#place(top + left, dx: 56pt, dy: 150pt, text(size: 9pt)[mira.valdis\@example.com])
#place(top + left, dx: 36pt, dy: 172pt, image("icons/phone.svg", width: 12pt, height: 12pt))
#place(top + left, dx: 56pt, dy: 172pt, text(size: 9pt)[+45 20 30 40 10])
#place(top + left, dx: 36pt, dy: 194pt, image("icons/web.svg", width: 12pt, height: 12pt))
#place(top + left, dx: 56pt, dy: 194pt, text(size: 9pt)[example.com/mira.valdis])
#place(top + left, dx: 36pt, dy: 216pt, image("icons/pin.svg", width: 12pt, height: 12pt))
#place(top + left, dx: 56pt, dy: 216pt, text(size: 9pt)[Copenhagen])
#place(top + left, dx: 36pt, dy: 250pt, block(width: 150pt)[#sec[Skills] SQL \ Docker \ Git \ Project planning \ Data analysis \ Figma \ TypeScript #sec[Languages] English (fluent) \ Danish (native) \ French (basic)])
#place(top + left, dx: 215pt, dy: 140pt, block(width: 344pt)[#sec[Experience]
#job[Data Engineer][2023 - present][Bluebird Systems]
- Cut the nightly pipeline from 3 hours to 25 minutes by rewriting its slowest stage.
- Led a team of 4 through a migration with no downtime.
- Wrote the onboarding guide that new colleagues still start from.
#job[Data Engineer][2020 - 2023][Kestrel Analytics]
- Led a team of 4 through a migration with no downtime.
- Wrote the onboarding guide that new colleagues still start from.
- Introduced code review and automated checks across 6 repositories.
#job[Data Engineer][2017 - 2020][Fjord Software]
- Wrote the onboarding guide that new colleagues still start from.
- Introduced code review and automated checks across 6 repositories.
- Presented results to management every quarter and agreed the next priorities.
#sec[Education]
#text(weight: "bold")[MSc in Computer Science] \ Example University, 2013 - 2015 \
#text(weight: "bold")[BSc in Mathematics] \ Example University, 2010 - 2013
])
