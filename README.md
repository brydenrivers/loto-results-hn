# loto-results-hn

Public winning-results archive for **La Diaria** (Honduras), published as a
single JSON file so an installed phone app can stay current without a backend.

- **Feed:** [`results.json`](results.json)
- **Coverage:** every daily draw since 2020-06-10, three per day —
  11:00 (mañana), 15:00 (tarde), 21:00 (noche), Honduras time (UTC-6).
- **Updated:** automatically, three times a day, 40 minutes after each draw.

These are published lottery results. Nothing here is personal data, and nothing
in this repository identifies anyone.

## Format

```json
{
  "v": 1,
  "generatedAt": "2026-09-16T02:10:00Z",
  "from": "2020-06-10",
  "to": "2026-09-15",
  "days": 2281,
  "draws": 6803,
  "packed": "202609152267..\n20260914012904\n…"
}
```

`packed` is one line per day, **newest first**:

```
YYYYMMDD + <mañana><tarde><noche>
```

Each slot is a two-digit number `00`–`99`, or `..` when that draw is missing or
has not happened yet. The line above (`202609152267..`) is a normal partial day:
mañana `22`, tarde `67`, noche not yet drawn.

Only the main two-digit number is kept. The secondary "signo" digit is dropped —
it is inconsistent between sources and irrelevant to a two-digit archive.

Consumers should treat `v` as a hard gate and ignore any payload where it is not
`1`.

## How it stays current

`update.py` runs on a schedule, catches up from the newest stored day, and
commits only when something actually changed. It always restarts from the newest
*stored* day rather than the day after, so a day that was partial when it was
first written gets its later slots filled in place.

Results come from resuloto and are **cross-checked against lotodehonduras**.
When the two disagree about a slot, that slot is published as `..` rather than
guessed, and the scheduled run is marked failed so a human resolves it. This is
not hypothetical: resuloto has historically served a wrong `00` for a main
number, which is the entire reason the second source is consulted.

Run it by hand with:

```bash
python update.py --dry-run              # show what would change
python update.py                        # catch up and write
python update.py --start 2026-09-01     # force a re-fetch from a date
```

Python 3, standard library only.

## Why this repository is separate

The app that consumes this feed lives in a private repository. Only the results
data is public, because only the results data needs to be — it is public
information already, and a feed has to be fetchable without a token.

---

The app this serves is for entertainment. Two-digit lottery draws are
independent and uniform: nothing in this archive predicts a future draw, and it
is not published as a tipping service.
