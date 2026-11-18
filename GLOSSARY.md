# voicecom-jev

A push-to-talk voice command tool: the user speaks, Jev decides what was meant, and plain code acts on the computer.

## Speech

**Utterance**:
One stretch of speech recorded while the push-to-talk key is held.
_Avoid_: recording, clip, voice input

**Transcript**:
The text of an Utterance, produced locally by speech-to-text.
_Avoid_: query, prompt, input

**Push-to-talk key**:
The key the user holds down to record an Utterance.
_Avoid_: hotkey, trigger, wake key

## Deciding

**Command**:
A named, registered thing the computer can do, described in plain language so Jev can choose it.
_Avoid_: intent, action, skill, tool

**Registry**:
The full set of Commands Jev chooses between.
_Avoid_: command list, catalog

**Dictation**:
The fallback Command for speech that isn't an instruction; the Transcript is typed as-is.
_Avoid_: free text, passthrough

**Decision**:
Jev's typed answer to one Transcript: the chosen Command and its probability, the Destructive score, and the named App.
_Avoid_: classification, prediction, result

**Destructive score**:
The probability, from a yes/no Jev question, that carrying out a request would close, quit, delete, send, or discard something.
_Avoid_: risk score, danger level

**Target element**:
The labeled, clickable element in the foreground window that a click request refers to.
_Avoid_: widget, control, button (when meaning any element)

## Acting

**Gate**:
The rule that turns a Decision into one of three outcomes: Run, Confirm, or Ignore.
_Avoid_: filter, policy, threshold check

**Run**:
Gate outcome: perform the Plan immediately.

**Confirm**:
Gate outcome: ask the user aloud, then judge the next Utterance as a yes or no.
_Avoid_: prompt, verify

**Ignore**:
Gate outcome: do nothing, because Jev isn't sure enough what was meant.
_Avoid_: reject, drop

**Plan**:
The concrete, described action a Command will take for one Transcript, prepared before the Gate allows it.
_Avoid_: job, task, execution

**Automation layer**:
The per-operating-system code that actually opens apps, presses keys, clicks, and moves windows.
_Avoid_: driver, backend, executor

**Dry run**:
A mode where Decisions and Plans are made and logged but the Automation layer performs nothing.
_Avoid_: simulation, test mode

**Chain**:
Several Commands said in one Utterance ("open Safari and search for tacos"), run in order as Steps after one Gate decision for the whole Chain.
_Avoid_: macro, batch, sequence

**Step**:
One Command within a Chain, with its own Plan.
_Avoid_: sub-command, action

**Span**:
A candidate stretch of the Transcript between likely boundaries ("and", "then", commas) that Jev classifies on its own, to decide where a Chain splits.
_Avoid_: chunk, segment, clause
