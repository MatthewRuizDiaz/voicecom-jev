# Split Chains with one Jev request over every candidate Span

To run several Commands from one Utterance ("open Safari and search for tacos"), plain code cuts the Transcript at every likely boundary ("and", "then", "and then", "after that", commas, sentence ends) into Pieces. Every run of consecutive Pieces is a Span. The single Jev request that classifies the whole sentence also asks a command Choice and a Destructive Noul for each Span, and an app Choice for Spans with an app verb. A dynamic program then picks the split into the most Steps (2 to 5) where every Span is a confident, non-Dictation Command (p ≥ 0.80), with ties going to the higher product of probabilities. If no such split exists, the sentence is one Command as before. The whole Chain is then gated once: any unparseable Step ignores it all, and any destructive or unsure Step confirms it all.

## Considered Options

- **Split on "and"/"then" in code alone.** Rejected because "type salt and pepper" and "search for rock and roll" are one Command each. Only the meaning of each piece can tell.
- **A Jev request per piece, in sequence.** Rejected: more round trips, and a piece can't be judged without knowing whether it should merge with its neighbour.
- **Ask Jev where to split.** Not possible: Jev answers typed questions over options we supply, so the options have to be the candidate Spans.

## Consequences

- No extra round trip. Measured on `jev-latest`: 1 question set in 0.10s, 6 in 0.13s, 15 in 0.16s. Real chains decide in 0.10–0.15s.
- Pieces are capped at 6 (20 Spans besides the whole sentence) and Chains at 5 Steps.
- A "click" Step after other Steps reads the screen at its turn, because earlier Steps change what's on screen. If its element is then unsure, the Chain stops there.
- Each Step waits for the previous one to take effect (the opened app in front, up to 2s, or a short settle) before acting.
- Dictation that happens to read as several Commands ("type I'll open Safari and search for it") will split. That's accepted for now.
