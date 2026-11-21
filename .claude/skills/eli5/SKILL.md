---
name: eli5
description: Re-explain your last message in plain, simple words, shorter, as one person talking to another. Only when the user types /eli5.
disable-model-invocation: true
---

Re-explain your previous message so someone outside the work understands it on one read.

- Say the point first, in one sentence: what happened, or what you are proposing.
- Use everyday words. Drop jargon, file paths, function names, issue numbers and flags unless the user needs one to act; when a technical term cannot be avoided, say what it means in a few words.
- Keep it short: a few sentences, or at most five bullets. Leave out details, caveats and evidence that do not change the point.
- A small everyday comparison is fine when it makes the idea click; skip it when it does not.
- If the message asked the user something or needs something from them, end with that, in one plain sentence.
- Add nothing new: no new findings, opinions or options. If the original was wrong or unclear, say that plainly instead of smoothing it over.
- Do not mention that you are simplifying, and do not repeat the original.

If the user adds text after /eli5 (`/eli5 the merge part`), explain only that part.
