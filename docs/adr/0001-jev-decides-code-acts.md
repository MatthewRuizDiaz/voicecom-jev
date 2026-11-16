# Jev decides, plain code acts and extracts arguments

Jev (TypeSafe's System One model) only answers typed questions about a Transcript: a Choice for the Command, a Noul for the Destructive score, a Choice for the named App, and a second Choice for the Target element. It never produces the action or its arguments. Numbers, key chords, scroll amounts, search queries, and text to type are parsed by ordinary code, and every action is deterministic code in the Automation layer. We chose this over LLM function calling because Jev returns calibrated probabilities that the Gate can threshold, answers in about 0.1s, and can't invent an action or an argument that isn't in the Registry.

## Consequences

- One Jev request per Utterance asks every question at once, including the App Choice, which is only read when the chosen Command takes an app (TypeSafe's "speculative fan-out" pattern). This avoids a second round trip for open/quit.
- Click is the one Command that makes a second request, because its options (the elements in the foreground window) aren't known until the window is read.
- Argument parsing is English-only and keyword-based. A phrasing the parser misses yields no Plan, and the Utterance is Ignored rather than guessed.
