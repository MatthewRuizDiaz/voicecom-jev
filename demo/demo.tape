# Terminal demo: run with `vhs demo/demo.tape` from the project root (needs TYPESAFE_API_KEY in .env).
# Uses --dry-run and --text so it records the Jev decisions without a mic or moving windows.
Output demo/demo.gif
Output demo/demo.mp4

Set FontSize 14
Set Width 1800
Set Height 520
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

Hide
Type "source .venv/bin/activate && clear" Enter
Show

Type "python -m voicecom --dry-run --text 'open safari' --text 'snap this window to the left' --text 'scroll down a lot' --text 'set the volume to thirty percent' --text 'search for the best tacos in austin' --text 'I will be there in ten minutes'"
Sleep 400ms
Enter
Sleep 9s

Type "python -m voicecom --dry-run --text 'close this tab'"
Enter
Sleep 4s
Type "no, keep it"
Enter
Sleep 4s
