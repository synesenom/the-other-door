---
name: scraper-fixer-request
description: Not for direct use — do not invoke it from a conversation; `door.core.scraper_fix` sends this as the `-p` request that runs the scraper-fixer agent for one site, filling in the site, the saved response and the scraper's file.
---

Invoke the scraper-fixer agent for site {site}. The saved drift response is {raw_path}. Repair {scraper} test-first per .claude/agents/scraper-fixer.md, then finish with a short plain-text summary of what changed and why.
