# Confirm with overlay buttons, not a spoken yes or no

When the Gate says Confirm, the Overlay keeps the Card up with **Run** and **Cancel** buttons, a checkbox on each Step of a Chain, and destructive Steps in red. The user clicks; there's no spoken question and no second Utterance to judge. The question lasts 10 seconds (the countdown pauses while the pointer is over the panel), then it's dropped. Speaking again also drops it, because a new Utterance is a new command. This supersedes the "spoken confirmation, judged by a Noul" part of ADR 0002.

## Considered Options

- **Keep voice yes/no (an `is_yes` Noul over the reply).** Rejected by the user: a robotic spoken question for every risky Chain feels like a robocaller, and clicking is faster than holding the key and speaking again.
- **Voice and buttons together.** Rejected by the user: one way to answer is simpler, and a mis-heard "yes" can't run a destructive Step.
- **Return/Esc on the keyboard.** Rejected: macOS also delivers the key to the app you're in, so Return could send a message. Swallowing it needs a lower-level event tap.
- **Partial approval by voice ("only the first two").** Replaced by per-Step checkboxes: the same result with no parsing.

## Consequences

- `Jev.is_yes` and its threshold are deleted. voicecom now uses Jev for the command, destructive and filler questions plus the click element, but not for confirmations.
- Clicking the panel never takes focus (non-activating panel), so Run acts on the app you were in.
- `--speak` adds the spoken prompt back for anyone who wants it. `--text` and `--repl` answer with y/n at the keyboard. With `--no-overlay` in voice mode there's nothing to click, so a confirm simply lapses at the next Utterance.
