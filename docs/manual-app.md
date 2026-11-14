# The desktop app

The desktop app is a window over the same tools Claude Code and the shell use. It comes as an
installer (below) or runs from a checkout ([`app/README.md`](../app/README.md)). This page is what
each screen does. The look is in [`design/`](design/README.md).

The first time you open it on a computer with no profile, a short wizard sets *The other door* up
([First launch](#first-launch)). "Find new jobs" runs the whole search from the app (below). [Profile](#profile) edits every setting of your profile, and Settings holds your [connections](#settings) (Claude and Google Drive) and the data folder. The app opens on Matches. When something needs you (Claude, your CV, Google Drive, something that keeps going wrong), a short line at the foot of the sidebar says so and opens where it is fixed.
Preparing an application needs the `claude` command line and a LaTeX compiler. The installed app
brings LaTeX (and the Python it runs on) with it; the first screen of the wizard installs Claude and
signs you in when it is missing. From a checkout, `./door doctor` checks them all.

## Installing the app

The installer carries everything *The other door* needs except Claude: its own Python with the pipeline's packages,
the pipeline itself and Tectonic (the LaTeX engine for the PDFs). Nothing else has to be installed. On the
first launch the wizard offers to install the `claude` command line if it is missing (Anthropic's
own installer, into `~/.local/bin`, for you only and without a password; it keeps itself up to date)
and signs you in to your Claude plan.

- **macOS** (12 or later; Apple silicon and Intel have their own `.dmg`): open the `.dmg` and drag
  *The other door* into Applications. The first time you open it, macOS refuses: allow it once as in
  [Opening it on macOS the first time](#opening-it-on-macos-the-first-time). The `claude` installer
  needs macOS 13 or later; on 12, install Claude Code another way first.
- **Windows** (10 or 11, x64): run the installer; it installs for you only, without an admin prompt.
  SmartScreen may warn the first time: More info → Run anyway.
- **Linux** (x64): the AppImage (make it executable and run it; on Ubuntu 24.04 and later it needs FUSE 2
  first: `sudo apt install libfuse2t64`) or the `.deb` (`sudo apt install ./the-other-door-….deb`).

**Updating**: the app does not install updates itself. An installed app checks for a newer version
when it starts, and Settings → Version shows the version you have, says when a newer one is out, and has a
Download button that opens its release page, and Check for updates. Install the download over this one; your data
stays where it is. The check sends no information about you; offline, or when the page cannot be reached,
it shows nothing and writes one line to the problem log. A build with no update feed does not check, and
then Settings has no Version part. The app and the pipeline inside it are always one version: an app that finds another says so
("Install the app again").

**Your data** (profile, jobs, applications, backups) lives in your user folder, never inside the
app: `~/Library/Application Support/The other door` on macOS, `%APPDATA%\The other door` on Windows, `~/.config/The other door`
on Linux (the same folder as the app's own settings). Settings → Your data shows it.
Uninstalling the app leaves it; delete that folder to remove your data too. Tectonic downloads the
LaTeX packages a CV needs the first time it makes one (`~/Library/Caches/Tectonic`, or the system's
cache folder), so the first Prepare needs the network, which it needs for Claude anyway.

### Opening it on macOS the first time

The app is not yet signed by a registered Apple developer, so macOS will not open it the first time.
Allow it once:

1. Open *The other door* from Applications. macOS says it could not verify the app and does not open it.
   Click **Done**, not Move to Trash.
2. Open **System Settings → Privacy & Security** and scroll down to **Security**. Beside the line saying
   *The other door* was blocked, click **Open Anyway**.
3. Confirm with your password or Touch ID, then click **Open Anyway** once more.

From then on it opens like any other app. macOS may ask again after you install a new version.

On macOS 12 to 14 there is a shorter way: Control-click *The other door* in Applications, choose **Open**,
then **Open** again.

## First launch

With no `profile/config.json`, the app opens a wizard instead of Matches. It is the app's
version of `/onboard` in Claude Code and of `./door init` in a shell, and it follows the same
three rules: nothing is written before you press Save, your CV is never overwritten without
your say (the old one is kept as `cv.md.bak`), and Claude is installed only after your yes.

**Connect Claude** comes first, and only if Claude is missing or signed out: "Install Claude" after
one yes, and "Sign in with Claude", which runs Claude's own sign-in: your browser opens on
claude.ai, you approve, and the wizard moves on by itself. If the page shows a code instead of
finishing by itself, click "The page showed a code?" and paste it. The login is the one the `claude`
command line uses, kept where it keeps it (the Keychain on macOS); the app never sees or stores your
password or token, and *The other door* never uses an API key. The sign-in gives up after five
minutes. On Windows it starts the `claude.exe` that `doctor --fix` installs; a `claude` installed
with npm (`claude.cmd`) cannot be started from the app, so sign in from a terminal there with
`claude auth login`. "Check again" re-reads the sign-in if you signed in some other way.

1. **Tell me about yourself.** Drop your CV and your LinkedIn PDF on the dashed box, or click it to choose them (PDF, DOCX,
   Markdown or text, up to 25 MB each), and type any public page, such as a personal site or GitHub, in the field below it.
   LinkedIn pages cannot be read: save your profile as a PDF (More, then Save to PDF) and add that
   file. LaTeX,
   needed only to make the PDFs, installs quietly by itself. Setup needs a source: a CV, a LinkedIn PDF
   or a public page. The example CV (Jane Doe's) is never used:
   nothing is scored or prepared while it is still in place.
   If you already use *The other door* on another computer, "Bring my profile from Google Drive" (a line under
   the title, on a first set-up only) connects Drive, which opens your browser once, and brings your
   profile, jobs and history here. You land on Matches: there is no review and no first run, and
   "Find new jobs" starts one. If Drive holds nothing yet, or the sign-in is refused, the line says so and
   the steps go on as usual. The Claude plan folder (`claude_config_dir`) does not travel: this computer
   keeps its own.
2. **Reading your CV.** A few minutes on your Claude plan: Claude drafts the CV, reads your details,
   finds titles that fit and chooses search terms; on a first set-up it also writes one example story from your CV.
   The running step shows its time so far. It asks nothing: what it could not find
   (your name, email, city or titles) is left for the review. A failed draft offers "Try again" or going on
   without one. The draft is a scratch file, `profile/cv.draft.md`.
3. **Check your answers.** Everything on one page, editable in place. A note at the top names what
   could not be found in your sources, and Save waits until it is filled in; a city in a country not
   covered yet is named, and you choose a city or keep yours under Other, where only the worldwide
   boards are searched:
   **You** (name, email, city, hybrid, remote only or on site, a photo for your CV where your city's country may carry one, held until you save, the job-ad languages);
   **Titles** (each with why it fits, the best ones ticked, and your own to add, as pills you can remove; changing them
   proposes the search terms again);
   **What matters to you** (optional, a text box: the kind of employer and job you want and anything you rule out, in your own words, for example "medical or green energy, maybe robotics; a smaller company, little travel; not banking or gambling"; when in doubt, scoring still shows the job);
   **Search** and **CV**, folded (the CV formatted, with a switch to its Markdown text; what the draft could not find is marked "to fill in", and a click on a marker selects that gap in the text; a file with no text, such as a scanned PDF, is named;
   the pages you used become the profile's enrich sources);
   **Your story bank** (on a first set-up: one story drafted from your CV, to show what a story is. Your CV lists
   what you did; a story tells what was behind it, and the tailor draws on your stories for every application.
   Fill in what the CV could not say, usually what you learned, or untick "Keep this story"; Save waits for one or the other.
   More stories go in Profile → [Stories](#your-stories));
   **Where to find employers** (LinkedIn, and profession.hu, HelloWork or Jobbsafari where they serve your city:
   each stays off unless you tick it, because their terms forbid automated access; see the
   [legal disclaimer](../LEGAL_DISCLAIMER.md), which opens from there; Settings → Risky sources changes it later).
   "Save and start searching" writes the profile and the CV and opens [Finding jobs](#finding-new-jobs)
   on a first search of the boards. Without a CV of your own or Claude, it saves and opens Matches,
   and a line at the foot of the sidebar says what is missing.

Companies and words to skip and the minimum score are not asked: they keep their defaults, and
Profile changes them.

If you have no CV yet, a line at the foot of the sidebar says so and opens Profile on the CV. (The example CV needs no line: a run refuses it and says why.)
While your CV is still the example one, "Draft it from your CV file or pages" in Profile's CV opens
the same screens with your answers filled in: your sources are read, with new titles to choose
from. Your answers stay, and Save starts no search.

`npm run dev:onboard` tries all of this on an empty folder (see [`app/README.md`](../app/README.md)).

## Finding new jobs

"Find new jobs" (the button at the foot of the sidebar; in a window narrower than 900 px, where
the sidebar is a tab bar, a pill beside "Add a job" on Matches) starts a run: the same five steps as `./door find`. The window shows them one under
the other.

1. **Search** reads the job boards for your country.
2. **Discover** finds employers on LinkedIn (slow: it is paced, so it can take minutes).
3. **Follow** finds the career pages of those employers.
4. **Collect** reads the career pages you follow.
5. **Match** scores every new ad against your CV.

A finished step has a check, what it found and how long it took; the running step has a ring
with its number, a line on what it is doing ("Reading Novo Nordisk · 23 of 57 employers"), a bar
when the total is known and, under it, the postings found per site; the steps to come say
what they will do. A step left out shows "Skipped".

While Search runs, the boards it reads are listed in small type under its bar: they are read at
the same time, each with a spinner until it answers, then a green check (or a red cross when it
failed), with the number of postings it has brought so far beside its name once there are any ("Jobindex · 14"),
and what a board at work is doing ("Jobindex · 40 · reading ads for 'data' (12 of 40)"): Jobindex reads
each on-topic ad's own page, so its count can stand still for half a minute while it works; the
bar counts the boards that answered ("3 of 8 boards"). A board resting after it
refused *The other door* is not listed. Discover lists its sources
(LinkedIn, profession.hu, …) the same way; they are read one after the other, and Discover
starts at once and works beside the other steps. A list goes away once everything in it is read.
A source serving your city that you never turned on is listed there too, with a warning mark:
"LinkedIn (not enabled, enable)"; "enable" opens Settings at Risky sources, where it is switched on.

You can switch screens while it runs: the button then reads "Finding jobs…" and takes you
back (on the Finding jobs screen itself it is greyed out), and Matches says above its list which
step is running ("Finding new jobs: scoring the new ads (12 of 40)"). Quitting *The other door* stops the run.
Which discovery sources run is your choice in Profile, not something asked per run.

### Stop

"Stop", beside the title, ends the run at once and takes you back to the screen you started it from. Nothing is lost: the postings already read stay on disk and are
scored by the next run, which picks up where this one stopped. A stopped run writes no run
record, so "Last run" under the button does not move. If your data is synced with Google
Drive, the push happens at the next run that finishes. A run that makes no sign of life for 15
minutes is stopped the same way.

### A run started somewhere else

A `./door find` in a terminal, or one Claude Code started, is shown in the same window,
read-only and without Stop ("A run started elsewhere is in progress (started 09:12)"), and
"Find new jobs" is off until it ends. It is also off while Prepare is writing an application,
and says so when you point at it.

### When the run is done

A card says how many new matches the run found ("2 new matches": the ads this run scored at or above your minimum score; a match an earlier run found is not counted again) and lists the best. It says nothing
about what did not work, because nothing there needs you: a site that could not be read is read
again on the next run, and a posting that could not be scored is scored then. Every site's outcome
and error is in the run record. "View matches" opens Matches on
"New only", "Show run record" shows the run's file in your file manager. Matches and "Last run" are refreshed.

When no match is new, the card says what the run did in one line ("917 jobs found, 40 close enough to
score, none reached your bar (65%)") and offers what you can do about it: "Follow employers" and
"Check your search terms" open Profile at those sections, "Lower the bar" at the minimum score. When the
run skipped Discover, Follow or Collect, it adds that the next full run also reads employers' own career sites.

After the first run, if it found fewer than three new matches and every employer discovery source
serving your city is off, the card adds one line: *The other door* can also find employers on
LinkedIn (and the other discovery sources serving your city), at your own risk, with the
[legal disclaimer](../LEGAL_DISCLAIMER.md) and "Turn it on in Settings", which opens Settings at
Risky sources. It is said only on that card, never again, and not on the phone.

### In the demo

`npm run dev:demo` plays a simulated run of about twenty seconds: nothing reaches the network or
your Claude plan. It finishes with two new made-up matches, one site that returned nothing and one
resting, so every part of the screen can be seen. Stop works as in a real run.

## Matches

The ranked list of postings that cleared your minimum score, best first. A dot marks a
posting you have not opened yet; opening it makes it seen, and the dot goes. The "New only"
switch shows only the unopened ones. The header says how many are new, and shows a note for a
board that failed on the last run.

An empty list says why: "Nothing scored yet. Find new jobs to start." only when nothing has been
scored; "Nothing has reached your bar (65%) yet." (with "Lower the bar", which opens Profile at the minimum
score) when ads were scored but none cleared it; "Nothing new since your last review." only after a review,
on "New only".

Until the first posting has reached your bar, that empty list also shows the three best ads below it as ordinary rows
marked "Weak match" (open, prepare or discard them like any other), under one line: "3 weak matches found." and, when
a discovery source serving your city is off, that the app can also find employers on LinkedIn and the other discovery sources, at your own
risk, with the legal disclaimer and "Turn it on in Settings" (opens Risky sources); with every source on, "Broaden your
search keywords to find closer ones." (opens Profile at the search). On the phone the line is plain text. Once any
posting has reached the bar, they are never shown again.

Choosing a row opens the posting on the whole page, as a card does in Applications, with a
"← Matches" link back (or Esc). Above the posting, "2 of 14" and ‹ › step to the previous and
next match without going back (or the k and j keys). Back in the list, it is where you left it,
and the row you last opened is marked.

In a window narrower than 900 px the sidebar becomes a tab bar and steps aside while a posting
is open. Ready to send is one more pushed screen ("← Posting") that shows one document at a
time behind a switch ("CV · 2 pages", "Letter · 310 words"), with Save and I've applied in a
bar at the bottom.

## A posting

Choosing a row shows the posting: title (and its English translation), company and place,
the score (the reason for it behind the info icon beside it: hover or focus it), the skills that fit and the gaps, the ad's language and
what it asks of you, the salary to expect once the job is prepared (below), and the ad itself. The buttons:

- **Prepare application** (the one dark button while nothing is prepared and the job is not
  yet applied) tailors a CV and a cover letter for this posting (below).
- **See the application** (the dark button once something is prepared) shows them. For a job
  you have already applied to, it is the only prepare button left.
- **Prepare again** (quiet, next to it, only before you apply) tailors them anew; it asks
  first, because it replaces the CV and letter and any revisions.
- **Apply on <the employer's site>** opens the employer's application page when the board's ad links to one (most LinkedIn and some Jobindex ads); otherwise **Open in browser** opens the ad where it was found.
- **Status** changes where the job stands (below).
- **Not for me** is the quick way to drop a job: it asks why, the job leaves the list, and the next match opens in its place. Once an application is prepared it is under **Status** instead.

## Prepare

**Prepare application** takes a few minutes: Claude tailors the CV and writes the letter, and
*The other door* builds the PDFs. The pane shows the latest step, how long it has run, and "You can
leave this open; it takes a few minutes." Its other buttons wait. You may look at other
jobs meanwhile; coming back shows it is still preparing.

- Only one run goes at a time. If a search or another prepare is on, it says "Another run is
  in progress. Try again when it finishes." and the pane looks for the result by itself.
- A job that is already prepared is not redone: the app just opens it.
- If preparing fails, the pane shows what *The other door* said, and nothing changes.
- Closing the app stops a prepare; the next one starts that job over.

When it is done the app shows the result (below), and the job moves to Applications as
Prepared.

Preparing also estimates the salary to expect, by itself: there is nothing to press. The posting and
Ready to send then show a **Salary** line ("55,000–70,000 DKK a month, gross"), the pages it was
read from as links under it, the ad's own figure when it states one, and, behind the info icon, where
your experience puts you and why. It is an estimate from public pages, not advice. It is one quick web
search on your Claude plan, done once per job and again only when the saved one is more than 90 days
old at the next prepare; it is skipped while the plan is close to its limit. When the search finds no
page to cite, there is no Salary line.

## Ready to send

The prepared application, one document at a time: a switch ("CV · 2 pages", "Letter · 310
words") picks the CV or the letter, shown large enough to read.
Its pages scroll in their own column, so the second page of the CV is one scroll away and the
column on the right stays in view; the wider the window, the larger the page. On a phone the
column comes under the pages.

- Under the title, the **Salary** line, when preparing found one (above).
- Under that, a line marked with the warning triangle names the numbers, employers, skills,
  certifications or degrees of the CV and letter that your `cv.md` and story bank do not back
  ("Not in your CV: 87%, Nordwind. Check them before you send it."). A claim the tailor kept as true shows its reason in brackets after the name. Revise can take them out.
- A CV is meant to be at most 2 pages, a letter 1 page and 250 to 350 words. When one is over,
  a note under the page says so in words ("(limit is 2)", "(aim for 250–350)").
- **Save CV** or **Save letter** under the page saves the document shown, named for you
  ("Jane Doe - CV.pdf", "Jane Doe - Cover letter.pdf": what an employer sees when you upload
  it). On the computer a save dialog opens in your Downloads folder; on the phone the browser
  saves it.
- **I've applied** records the job as applied in one click and takes you back to the list; it
  moves to Applied on the Applications board, where its status can be changed later.

The link at the top returns to the posting ("← Posting").

Once you have applied, the posting's button reads **See what you sent** and the screen is
**What you sent**: the CV and letter exactly as they were when you first marked the job applied
(the copy kept in `jobs/output/<job>/sent/`; for a job sent before that copy was kept, the files as
they are now), read only, with no Revise and no I've applied; the page takes the whole
width. Save saves that copy.

## Revise and Undo

Beside the pages, **Anything to change?** takes an instruction in your own words, for the
document the switch shows (the letter first). **Revise** sends it to Claude,
which takes up to a few minutes; the pages dim and the buttons wait. Then the pages are
rebuilt and shown, and a line says so.

- **Undo last change** puts back the version before the last revision. It goes one step back
  only. With nothing to undo it says "Nothing to undo."
- If the change was made but the PDF could not be rebuilt, the pages still show the previous
  version and a line says so; **Undo last change** puts the old text back.
- If Revise fails, it shows what went wrong and the pages stay as they were.

Change a prepared document only this way. Editing its files by hand leaves the PDF and the
pages out of date.

## Status

**Status** lists the eight states in words: Not yet applied, Prepared, Applied, Interview,
Ghosted, Rejected, Offer and Not for me. The current one is chosen.

- **Interview** asks which kind, one per round: Screening (a pre-screening or recruiter
  call), First impression (the first non-technical interview), Assessment (a personality or
  cognitive test) or Technical (a technical interview, case or take-home). Save waits for
  your choice. Record each round as it happens; Rejected or Ghosted ends the last one.
- **Notes** are optional, and say why or how it went. For Not for me a reason is required.

After saving, a line says what happened ("Applied: ... It is in Applications now.") and any
warning from *The other door*, for example that the ad is only a snippet, above the list, which
refreshes. After Not for me the next match opens instead, with the line above it. A job set back
to Not yet applied stays in Matches.

## Add a job

**Add a job** (in Matches and in Applications) brings in a posting you found yourself.

- **Link**: paste the address. *The other door* reads the page and finds the title and company; you
  can fill them in if it gets them wrong. A page behind a login or built only with
  JavaScript fails: use Paste text.
- **Paste text**: the ad's text, plus its title and company (both required).

The ad is scored on the spot, which takes a little while (a spinner says so; **Cancel** leaves). The result shows its score and the
reason; **Open** shows the posting even if it scored below your minimum. Without a profile
yet, it says "Not scored yet. It is scored on the next run." (**Why?** unfolds the reason).
Importing an ad you already imported asks first: "Import again anyway" replaces it.

## Applications

A board of five columns, Prepared, Applied, Interviewing, Offer and Closed, each headed by
its count, the most recently changed job first. A card is the job's title and company and one
line: when it last moved, its interview rounds as dots (ink for a round passed, a blue ring for
the one now) with the round's name, or how it ended. Closed holds the applications that ended,
rejected, ghosted or withdrawn after you prepared or sent them (a match you dismissed with
"Not for me" is not one). The line under the title counts
the jobs in play and in interviews. Clicking a card opens its posting across the whole window,
where you change its status or open a prepared job's application; "← Applications" goes back.
**Add a job** imports an ad. When nothing is in play, the screen says so. On a narrow window
the board scrolls sideways in its own box.

## Notifications

When a long job finishes while *The other door* is not the window in front, your system shows a
notification, and clicking it brings *The other door* forward on the screen with the result. Nothing is
shown while the window is in front (the screen already says it), and not for quick actions
like changing a status, for a run you stopped yourself, or for "a run is in progress".

| Title | When | A click opens |
|---|---|---|
| New jobs found | a search finished with new matches ("3 new matches") | Matches, New only |
| No new matches | a search finished with none | the run summary |
| The search stopped | *The other door* heard nothing for 15 minutes | the run screen |
| The search didn't finish | the search failed (the first line of the reason) | the run screen |
| A run finished | a run started from a terminal or Claude Code ended while the app was open | Matches, New only |
| Application ready | Prepare finished | that job's Ready to send |
| Preparing didn't finish | Prepare failed | that job's posting |
| Revision done | a Revise finished | Ready to send, on the CV or the letter you changed |
| The PDF could not be rebuilt | a Revise left a document that did not compile | Ready to send ("Undo last change" puts it back) |
| Ad imported | an ad imported by link was read and scored (a pasted ad is quick and is not announced) | that posting |

Notifications are always on for now; the Settings screen will get a switch. In development
on macOS they are shown as coming from "Electron" until the app has its own name.

## Profile

Who you are and the jobs you want (how the app works is in [Settings](#settings)). Three parts, picked with the
switch at the top or from the list on the right: Details (the settings below), [CV](#your-cv) and
[Stories](#your-stories). The list names Details' sections, the one you are reading marked, then CV and
Stories; a click jumps to a section or opens a part (a window narrower than 900 px leaves the list out).

The everyday settings of `profile/config.json` ([Configuration](configuration.md)), in sections:
About you (name, email, city, whether you need a visa or work permit there, where you would work, the languages of the job ads), What to
look for (role targets, what matters to you, as free text that applies from the next run, how close a match to show: Broad,
Balanced or Strong), and What to skip (companies and words).
The settings for tuning a run (how many sites at once, the limits, how old an ad may be, when to stop following
a quiet employer, asking Claude where a careers page is, the Claude config folder for people with two plans, the prescreen, the
models) and the template paths are
left to `profile/config.json`; the form keeps any you set there and never sends them. The employers
*The other door* follows are its own business: it finds and follows them, and an employer you never want to
hear from goes under Companies to skip.

What the job boards are searched for follows your role targets, and is not on screen: when a Save changes
your role targets or the languages of the ads, Claude proposes the search keywords and the words a job title
must contain again from those, in each ad language, and they are saved with the rest (if that call fails, the
terms you had stay). They aim wide: a term that is off brings in some ads that score low, nothing worse. Claude Code ("expand my search
keywords") and `profile/config.json` can still change them by hand. Nothing is saved until you press Save,
which sends only what you changed; the foot says how many changes are unsaved, and "Undo changes" puts the saved values
back. *The other door* checks everything before writing anything: a value it refuses is explained in a
sentence under its field, and your other changes stay in the form.

**Photo** (in About you): where CVs in your city's country may carry one (Denmark, France, Hungary and Sweden:
optional), "Choose a photo…" opens the file dialog (a JPEG or PNG), and the picture is saved at once, not with Save:
it is checked, stripped of its camera and location data and scaled to CV size, and the preview shows what is kept.
A picture it refuses is explained under the field. "Remove" deletes it. The same question is on the setup
review, held until you save. A photo is only put on the CVs for jobs in a country that allows one; the cover letter
never has one. It is not on the phone.

### Your CV

The pages your CV is read from come first: each page is a chip with a × to forget it, and under them
**Add a page** and **Check again**. Then `profile/cv.md` in an editor, "Your CV (Markdown)" with the
Preview switch on its right, which shows how it reads, with each gap (`TODO`) marked "to fill in": a click on a marker opens the editor with that gap selected. Save keeps the previous version as
`cv.md.bak` (one step back), and "Undo changes" drops what you have not saved; what you typed stays
while you look at Details. With no CV yet, a line above says so and offers "Draft it from your CV
file or pages", the wizard's screens. A `cv.md` that cannot be read as text (another encoding, a Word file
renamed) is said above an empty editor; saving there keeps that file as `cv.md.bak`.

- **Add a page** (the `/expand` skill as a button): a dialog asks for one page (your portfolio, GitHub,
  a publication list, a course page) and "Read it". One Claude call on your plan (a few minutes)
  proposes what the page shows and your CV does not, grouped by the section each would go into.
  Untick what should not go in and "Add … to my CV": they go under their sections, and the old CV
  is kept as `cv.md.bak`. The page is remembered among your pages.
- **Check again** reads all your pages for what is new on them since, each proposal naming its page.
  What the CV already says, even worded or punctuated a little differently, is not proposed again,
  so checking twice adds nothing twice.

Both wait until your unsaved edits are saved or undone, since adding rewrites the file. What was added
is tinted in the editor and the preview, brought into view, until you next type or save.

### Your stories

The story bank the tailor draws on when it prepares an application (`profile/story_bank.md`): each story is CARL: the context (what happened and what was asked), what you did (action), what came of it (result) and what you learned. Every story is shown whole: its title, then its four parts, each name beside its text, with **Edit**, which opens it in a dialog and changes it in place (renaming it too), and **Remove**, which asks first.

- **Write a story**: in a dialog, describe something you did in your own words and "Draft it". One Claude call (a few minutes) proposes a story from what you wrote, read beside your CV: where they differ it keeps your text and shows what differs; a field it could not fill is left empty and marked, and you fill it before saving.

Stories are not on the phone.

## Settings

How *The other door* works for you (who you are and what you want is in [Profile](#profile)). One column of
sections: **Connections**, **Risky sources**, **Your data**, **Appearance**, **Version** (installed builds with an update feed), **Documentation** (with the
legal disclaimer) and, last, **Report a problem**. The same list as Profile's sits on the right.
Opening it checks Claude's sign-in again; nothing else runs until you click.

**Connections** lists what *The other door* is connected to, each with its state in words (a ✓ when it is
fine, an empty ring when not) and what you can do about it.

- **Claude** (required): *The other door* scores jobs and writes applications with your Claude Pro or Max
  plan. Signed in, it says as whom and on which plan, with "Use another account" to switch accounts.
  Signed out (or signed in with an API key, which *The other door* never uses), "Sign in with Claude" runs
  the same sign-in as the first launch. If the Claude command line is missing, "Install" puts it
  in for you only, after you say yes.
- **Google Drive** (optional, off until you connect it): keeps this computer and another one in
  step through one archive in `My Drive/The other door/`. "Connect" opens your browser to allow access
  (it waits up to five minutes); the app never connects by itself. There is nothing to press to
  sync: it syncs as it connects, each time the app opens, around every change to your data, and
  before it disconnects. Connected, it shows the account, the last sync and the last error, with
  "Disconnect". After you install a newer version on one computer, install it on the others that share
  Drive too: an older one shows "Google Drive has data from a newer version of The other door; install it on
  this computer too" and neither pulls nor pushes until it is upgraded. After a sync that brought Drive's data here, the screens read it again. When this
  computer and Drive both changed since the last sync, nothing is replaced until you choose
  ("Google Drive needs a choice" at the sidebar's foot opens it): "Keep this computer" (its data
  replaces the copy on Drive) or "Keep Drive" (Drive's data replaces this computer's, which is
  kept in `backups/`). "Disconnect" asks first, sends the last changes, and the copy on Drive stays. In the demo
  and the onboarding sandbox Drive is not available (made-up data never reaches your Drive),
  and a build without *The other door*'s Google client says so.

**Risky sources**: sites whose terms forbid automated reading (LinkedIn and the others),
which *The other door* can still read for employers to follow, if you choose to. Only the ones serving your city
are listed, each with what its terms say. Off until you tick one; a tick is saved at once.

When Claude is not signed in or not installed, or a Drive sync failed or needs a choice, a short line at the foot of
the sidebar says so and opens Settings (your CV's line opens Profile). Nothing is said when all is
well or when Drive is simply off. A site a run could not read is not said: the next run reads it again (its error is in the run record).

Three more lines are about your data folder, when this version cannot open it. Every screen then refuses to work with it
(nothing is changed), and only Settings and Report a problem still answer:

- **"Your data could not be upgraded. Send a report"** (opens Report a problem): an upgrade step failed and put your
  data back as it was. Save the logs and send them; the next start tries again.
- **"Install the latest version of The other door"** (opens Settings): the data was written by a newer version, for
  instance after you used a newer version on this computer or on Google Drive. Install the latest version.
- **"Your data is from an older version of The other door"** (opens Settings): the data was written by an earlier
  major version, which this one does not upgrade. Either keep using that version, or start a new profile: quit the app,
  rename the data folder (Settings → Your data shows where it is, for instance `The other door` to `The other door old`;
  never delete it), and open the app again for the first-launch set-up. Rename the folder back to return to the old data
  with the old version.

**Your data** says where your profile and jobs are stored; click the folder's path to open it. It also moves them to another computer without a terminal. "Export…" asks
where to save one archive (`door-export-<date>.tar.gz`; it never replaces a file that is there,
so choose a new name) and says how many files went in. On the other computer, "Import…" asks for
the archive, then says in words what it replaces before anything happens: your profile and jobs
there are replaced by the archive's, and what was there is moved to `backups/` first. After the
import it says where that backup is and names anything worth checking (a template path the other
computer had and this one does not), and the screens read the new data. Google Drive, when
connected, keeps two computers in step without this; after an import on a connected computer,
the next sync sends the imported data to Drive, replacing the copy there (if Drive changed in the
meantime, it asks which side to keep first). On macOS the save panel may offer to replace a file that is there; the
export still refuses it and writes nothing.

**Appearance** picks the theme: the same as the system (the default), light or dark. The choice
is this computer's.

**Version** shows the version you have and whether a newer one is out (see Updating above).

**Report a problem** is for when something does not work and the screens do not say why (they show
an error only when it stops a mistake or you can fix it). "Save logs…" asks where to save one
file (`door-report-<date>.zip`; it never replaces a file that is there) and then says to send it to
enys.mones@gmail.com. It holds no personal data: what went wrong
lately (the log in `logs/door.log` of the data folder: failed actions, job sites that could not be
read, ads left unscored, a crash of *The other door*'s server), the last five runs' counts and errors,
the checks of this computer, and the version and system. Your CV, profile, the job ads and your
applications are never in it, and emails and folder names are replaced by `<email>`,
`<data folder>` and `~`. Nothing is sent by itself: you attach the file to an email. The phone
does not offer it.

A failure that happens once is said nowhere: the next run tries again. When the same thing keeps
going wrong (a job site failed in each of its last three runs, ads could not be scored in each of
the last two runs, *The other door*'s server stopped or would not start, or the same action failed
three times in a day), a line at the foot of the sidebar says **"Something keeps going wrong. Send a
report"**. It opens Settings at Report a problem. Once you save a report the
line goes (only what goes wrong after it counts again), and it also goes by itself when the problem
stops. The phone does not show it.

## On your phone

The phone app is this app's screens in your phone's browser, installed like an app (no app store).
The computer running *The other door* does all the work: it keeps your data, runs the searches and Claude, and serves the app;
the phone shows it and holds no data of its own.

Set it up by hand, on the computer running *The other door*, once:

1. Build the phone app: `cd app && npm run build:web`.
2. Start the server: `./door serve` (it listens on this machine only, port 8765).
3. Give it an `https://` address your phone can reach. A phone installs an app only from a secure
   address. Two free ways, neither opens your router:
   - **Cloudflare quick tunnel**, no account: install `cloudflared`, then
     `cloudflared tunnel --url http://localhost:8765`. It prints an address like
     `https://<random>.trycloudflare.com` that works from anywhere, for as long as it runs (a new
     address each time; a named tunnel on your own domain keeps one).
   - **Tailscale**: `tailscale serve 8765` gives `https://<machine>.<tailnet>.ts.net`, reachable from
     your own devices with the Tailscale app.
4. Make a pairing code: `./door serve pair --device "My phone" --url https://<that address>`. It
   prints a code and a QR code; both work once, for ten minutes.

On the phone: scan the QR code (or open the address and type the code), then in Chrome's menu tap
**Install app** (iPhone: Safari's Share → **Add to Home Screen**). The app opens on your matches.

The phone is for what you do on the road: find new jobs (the run goes on while the phone is locked),
read postings, import an ad, prepare and revise an application, and keep Applications up to date. It
has three tabs, Matches, Applications and Settings (only the look and where your data is).
Everything else is done on the computer running *The other door*: first-time setup, your profile, CV
and employers (Profile is not on the phone), signing in to
Claude, connecting Google Drive and moving your data. A data
folder that has no profile yet says to set it up there first.

**What a paired phone can do.** It is not a Claude Code session on your machine: the server answers only
the tools the phone app uses, never a file path on the machine (an ad comes as a link or text), never an
address on the machine or your home network, and no question to Claude. Every
prepared or revised CV and letter is refused before compiling if it would read or write another file.
With a Cloudflare quick tunnel, Cloudflare's servers see the traffic decrypted on its way through;
Tailscale keeps it encrypted to your machine.

**Share an ad to The other door.** On Android, Share → **The other door** from Chrome, the LinkedIn app or an email
imports the ad and scores it against your CV, then opens it, with Prepare and Not for me as usual. On an
iPhone (which does not offer web apps in the share sheet), copy the link and paste it in Matches →
**Add a job**.

`./door serve devices` lists the paired phones; `./door serve unpair "My phone"` takes one away
(it shows the pairing screen again).
