# ./door jobs show (and its description in the pager) / prepare / status picked from lists, after a run (recorded by record.sh after find.tape).
Output prepare.gif

Set Shell "bash"
Set FontSize 14
Set Width 1240
Set Height 600
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms
Set WindowBar Colorful

Hide
Type "export PS1='$ ' LESS=-R && clear"
Enter
Show

Sleep 500ms
Type "./door jobs show globex"
Sleep 400ms
Enter
# Two Globex jobs match: pick the first from the list.
Sleep 2s
Enter
Sleep 5s
# d opens the description in the pager, q closes it; q again leaves the menu.
Type "d"
Sleep 3s
Type "q"
Sleep 1500ms
Type "q"
Sleep 1s
Type "clear"
Enter
Type "./door jobs prepare globex"
Sleep 400ms
Enter
Sleep 2s
Enter
Sleep 14s
Sleep 4s
Type "clear"
Enter
# Pick the posting, then the status, from lists; today, no note.
Type "./door jobs status"
Sleep 400ms
Enter
Sleep 2s
Enter
Sleep 1500ms
Down
Sleep 800ms
Enter
Sleep 1500ms
Enter
Sleep 800ms
Enter
Sleep 4s
