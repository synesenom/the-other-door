---
name: tailor-request
description: Not for direct use — do not invoke it from a conversation; `door.commands.prepare` sends this as the `-p` request that runs the tailor agent for one posting, filling the job, the paths and the CV conventions in.
---

Tailor job_id {job_id}: `job` is the posting at {posting}, `profile` is {config} (the profile folder is {profile_dir}; the story bank is {story_bank}). The CV template is {cv_template} and the cover letter template is {cover_letter_template} (they hold the building blocks; you write only the body, never a whole page). Produce {output_dir}/posting.json, cv.html and cover_letter.html and compile them to PDFs, following your steps in order; new stories go to {stories}. {conventions} Use these absolute paths, not paths relative to the working directory.
