# A Claude Code review session (claude_session.py, typed as `claude`; recorded by record.sh
# after seeding a run in a fresh sandbox). The same settings as the CLI tapes.
Output claude.gif

Set Shell "bash"
Set FontSize 14
Set Width 1240
Set Height 600
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms
Set WindowBar Colorful

Hide
Type "export PS1='$ ' && alias claude=./claude-demo && clear"
Enter
Show

Sleep 500ms
Type "claude"
Sleep 400ms
Enter
# The session takes about 40s to its last reply, then waits on its input box.
Sleep 47s
