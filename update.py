#!/usr/bin/env python3
"""
Refresh results.json with any draws that have landed since the last run.

Designed to run unattended from GitHub Actions every hour; draws land at
11:00 / 15:00 / 21:00 Honduras (UTC-6), and the sources post them late.

    python update.py              # normal: catch up from the newest stored day
    python update.py --start 2026-09-01   # force a re-fetch from a given day
    python update.py --dry-run    # show what would change, write nothing

EXIT CODES
  0  success (results.json possibly unchanged)
  1  something went wrong; results.json untouched
  3  results.json WAS written, but at least one slot is disputed between the two
     sources. The disputed slot is deliberately left empty rather than guessed,
     and this code makes the Actions run go red so a human comes and looks.

WHY A DISPUTED SLOT IS LEFT EMPTY
  resuloto has historically served a wrong "00" for a main number, which is the
  whole reason the scraper cross-checks lotodehonduras. A human refresh stops
  and asks. A cron cannot ask, so it publishes nothing for that slot instead of
  picking a side: a missing draw renders as an em-dash in the app and is
  self-healing on a later run, whereas a wrong number silently poisons the
  archive that Resultados and Algoritmo both rest on.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone

import scrape_la_diaria as s

FEED = "results.json"
# Honduras is UTC-6 year round (no DST).
HN = timezone(timedelta(hours=-6))
SLOT_ORDER = ("manana", "tarde", "noche")


def load_feed(path=FEED):
    with open(path, encoding="utf-8") as f:
        feed = json.load(f)
    if feed.get("v") != 1 or not isinstance(feed.get("packed"), str):
        raise SystemExit("results.json is not a v1 feed with a packed string")
    lines = [l.strip() for l in feed["packed"].split("\n") if l.strip()]
    return feed, lines


def parse_line(line):
    """'YYYYMMDDaabbcc' -> (datestr, {slot: 'NN'})."""
    d = line[:8]
    slots = {}
    for i, slot in enumerate(SLOT_ORDER):
        cell = line[8 + i * 2: 10 + i * 2]
        if cell != "..":
            slots[slot] = cell
    return d, slots


def build_line(d, slots):
    return d + "".join(slots.get(x, "..") for x in SLOT_ORDER)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--start", help="oldest day to re-fetch, YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delay", type=float, default=0.4)
    args = p.parse_args(argv)

    feed, lines = load_feed()
    by_date = dict(parse_line(l) for l in lines)
    newest_stored = lines[0][:8]

    today_hn = datetime.now(HN).date()
    # Start from the newest STORED day, not the day after: if its line is
    # partial (an earlier run caught only the 11:00 draw) re-fetching it is what
    # fills the later slots in place.
    start = date.fromisoformat(args.start) if args.start else date(
        int(newest_stored[:4]), int(newest_stored[4:6]), int(newest_stored[6:8])
    )
    if start > today_hn:
        print(f"Nothing to do: stored data already reaches {newest_stored}.")
        return 0

    print(f"Fetching {start.isoformat()} -> {today_hn.isoformat()} (Honduras time)")

    try:
        cross = s.fetch_lotodehonduras_recent()
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: cross-check source unavailable: {e}")
        cross = {}

    disputed = []
    changed = []
    for d in s.daterange_backward(today_hn, start):
        iso = d.isoformat()
        key = d.strftime("%Y%m%d")
        try:
            got = s.fetch_resuloto(d)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {iso}: {e}")
            continue

        other = cross.get(iso, {})
        for slot, val in list(other.items()):
            if slot in got and got[slot] != val:
                disputed.append((iso, slot, got[slot], val))
                # Publish nothing for a slot the two sources disagree about.
                del got[slot]

        existing = by_date.get(key, {})
        # Never let a failed/empty fetch erase a draw we already published.
        merged = dict(existing)
        merged.update(got)
        if merged != existing:
            changed.append(iso)
        # Skip days with no draws at all (a run before 11:00 Honduras), which
        # would otherwise add an all-".." line and inflate the day count.
        if merged:
            by_date[key] = merged
        import time
        time.sleep(args.delay)

    if disputed:
        print("\n!!! DISPUTED SLOTS — left empty rather than guessed:")
        for iso, slot, a, b in disputed:
            print(f"    {iso} {slot}: resuloto={a}  lotodehonduras={b}")

    # Rebuild, newest-first.
    keys = sorted(by_date, reverse=True)
    new_lines = [build_line(k, by_date[k]) for k in keys]
    packed = "\n".join(new_lines)

    if packed == feed["packed"]:
        print("\nNo change.")
        return 3 if disputed else 0

    draws = sum(len(by_date[k]) for k in keys)
    out = {
        "v": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "from": f"{keys[-1][:4]}-{keys[-1][4:6]}-{keys[-1][6:8]}",
        "to": f"{keys[0][:4]}-{keys[0][4:6]}-{keys[0][6:8]}",
        "days": len(keys),
        "draws": draws,
        "packed": packed,
    }

    print(f"\n{feed['days']} days / {feed['draws']} draws"
          f"  ->  {out['days']} days / {out['draws']} draws")
    print(f"changed days: {', '.join(changed) if changed else '(none)'}")

    if args.dry_run:
        print("--dry-run: not writing.")
        return 3 if disputed else 0

    with open(FEED, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"wrote {FEED}")
    return 3 if disputed else 0


if __name__ == "__main__":
    sys.exit(main())
