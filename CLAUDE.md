# voicecom-jev

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Project tracking

All work, decisions, and progress are tracked through the skills above: GitHub issues under the tracking issue #1 (sub-issues with native blocking edges and triage labels), ADRs in `docs/adr/` for hard-to-reverse decisions, and terms in `GLOSSARY.md`. When work lands, close its ticket with a comment giving the commit and the verification evidence, and update the Progress checklist in #1. File new work as a ticket before starting it.
