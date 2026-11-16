# Gate on the chosen option's probability, with a three-way outcome

The Gate thresholds the probability of the chosen Command (and of the chosen Target element), not Jev's `confidence` field. TypeSafe's docs recommend this for Choice answers, because a probability reads directly as "chance this is the wrong command", while confidence summarizes how spread out the distribution is. Every Decision lands in one of three outcomes rather than a yes/no: Run at p ≥ 0.80, Confirm at 0.40–0.80, Ignore below 0.40. Click requires its element probability too: Run at ≥ 0.70, Confirm at 0.30–0.70. A Destructive score ≥ 0.50 forces Confirm, however sure Jev is about the Command.

## Considered Options

- **A static "destructive" flag per Command.** Rejected because destructiveness depends on what was said ("close this tab" vs "close the sidebar"), and the user asked for a Noul.
- **A single threshold.** Rejected: rounding the uncertain middle band to either side either acts on misheard speech or makes the tool feel deaf.

## Consequences

Confirmation replies are judged by another Noul ("does the reply agree to go ahead?", Run at ≥ 0.70), so the user can answer naturally ("yeah do it", "no keep it") instead of saying a fixed word.
