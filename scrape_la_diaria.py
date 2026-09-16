#!/usr/bin/env python3
"""
Scrape La Diaria (Honduras / LHO) winning results and emit packed lines for
constants/pastResultsData.ts.

This is the tool used to keep the app's baked past-results history current. It
lives in the repo on purpose — the scratchpad copy kept getting lost between
sessions and having to be reconstructed. Python 3, standard library only.

WORKFLOW for a routine refresh
------------------------------
1. Run:   python scripts/scrape_la_diaria.py 2026-07-30 2026-07-20
   (END START, inclusive, walking backward — START is the oldest day.)
2. It fetches each day from resuloto, CROSS-VALIDATES against lotodehonduras,
   and prints:
     - any MISMATCHES between the two sources (investigate before trusting),
     - the packed lines, newest-first, ready to paste at the top of PACKED.
3. Paste the new lines into constants/pastResultsData.ts (replace any partial
   line whose slots are now filled), then bump the header "Data span" + counts.
4. tsc --noEmit, then a decode-parity check.

DATA MODEL
----------
La Diaria draws 3×/day: 11:00 -> manana, 15:00 -> tarde, 21:00 -> noche.
Each result is "MM + N": we keep only the 2-digit MAIN number MM (00-99); the
secondary "signo" digit is dropped (inconsistent across sources, irrelevant to
a 2-digit analysis). Packed line = YYYYMMDD + <manana><tarde><noche>, each slot
a 2-digit number or ".." when that draw is missing / not yet drawn.

SOURCES
-------
- Primary:  resuloto.com per-date page. Result spans carry class
  "txtTituloJuego" and read like "Día32 + 0" / "Tarde30 + 4" / "Noche59 + 9"
  (a slot-LABEL prefix + "MM + N"). The label word gives the slot. NOTE: an
  older parser matched a bare "MM" span and broke when the label prefix
  appeared — key off the Dia/Tarde/Noche label, not span position.
- Cross-check: lotodehonduras.com/la-diaria/ front page lists the last ~week
  inline as "<Weekday>, DD <Month> YYYY  11:00 a.m. NN + NN Word ...".
  Historically resuloto occasionally serves a wrong "00" main number; this
  second source is how those get caught and corrected.
"""
import argparse
import re
import ssl
import sys
import time
import urllib.request
from datetime import date, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

SLOTS = ("manana", "tarde", "noche")
_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _fetch(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25, context=_CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - transient network, retry
            last = e
            time.sleep(1.0 + attempt)
    raise last


def _clean(s):
    s = s.replace("&iacute;", "i").replace("&aacute;", "a").replace("&eacute;", "e")
    return re.sub(r"<[^>]+>", "", s).strip()


# ----------------------------------------------------------------------------
# Primary source: resuloto per-date page
# ----------------------------------------------------------------------------
def fetch_resuloto(d):
    """Return {slot: 'MM'} for a single date from resuloto (missing slots absent)."""
    url = f"https://www.resuloto.com/hn/lho/la-diaria.php?fecha={d.isoformat()}"
    html = _fetch(url)
    spans = [_clean(s) for s in re.findall(r"txtTituloJuego[^>]*>(.*?)</span>", html, re.S | re.I)]
    out = {}
    for label, slot in (("Dia", "manana"), ("Tarde", "tarde"), ("Noche", "noche")):
        for s in spans:
            m = re.match(rf"^{label}\s*(\d{{2}})\s*\+\s*\d+", s)
            if m:
                out[slot] = m.group(1)
                break
    return out


# ----------------------------------------------------------------------------
# Cross-check source: lotodehonduras front page (recent ~week, inline)
# ----------------------------------------------------------------------------
def fetch_lotodehonduras_recent():
    """Return {date: {slot: 'MM'}} for whatever recent days the front page lists."""
    html = _fetch("https://lotodehonduras.com/la-diaria/")
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    # Split on each "<Weekday>, DD <Month> YYYY" header, keep the trailing block.
    header = re.compile(
        r"[A-Za-z\xe1\xe9\xed\xf3\xfa]+,\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I
    )
    out = {}
    marks = list(header.finditer(txt))
    for i, m in enumerate(marks):
        day = int(m.group(1))
        month = _MONTHS_ES.get(m.group(2).strip().lower())
        year = int(m.group(3))
        if not month:
            continue
        block = txt[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(txt)]
        slots = {}
        for tm, slot in (("11:00", "manana"), ("3:00", "tarde"), ("9:00", "noche")):
            mm = re.search(re.escape(tm) + r"\s*[ap]\.?m\.?\s*(\d{2})\s*\+", block, re.I)
            if mm:
                slots[slot] = mm.group(1)
        if slots:
            out[date(year, month, day).isoformat()] = slots
    return out


def pack_line(d, slots):
    cells = "".join(slots.get(s, "..") for s in SLOTS)
    return f"{d.strftime('%Y%m%d')}{cells}"


def daterange_backward(end, start):
    d = end
    while d >= start:
        yield d
        d -= timedelta(days=1)


def main(argv=None):
    p = argparse.ArgumentParser(description="Scrape La Diaria results -> packed lines.")
    p.add_argument("end", help="most recent date, YYYY-MM-DD (usually today)")
    p.add_argument("start", help="oldest date, YYYY-MM-DD (inclusive)")
    p.add_argument("--no-crosscheck", action="store_true", help="skip lotodehonduras validation")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between resuloto requests")
    args = p.parse_args(argv)

    end = date.fromisoformat(args.end)
    start = date.fromisoformat(args.start)
    if end < start:
        p.error("end must be >= start (we walk backward from end to start)")

    cross = {}
    if not args.no_crosscheck:
        try:
            cross = fetch_lotodehonduras_recent()
        except Exception as e:  # noqa: BLE001
            print(f"# WARNING: cross-check fetch failed: {e}", file=sys.stderr)

    lines, mismatches = [], []
    for d in daterange_backward(end, start):
        try:
            res = fetch_resuloto(d)
        except Exception as e:  # noqa: BLE001
            print(f"# ERROR {d}: {e}", file=sys.stderr)
            res = {}
        # Validate overlapping slots against the cross-check source.
        other = cross.get(d.isoformat(), {})
        for slot, val in other.items():
            if slot in res and res[slot] != val:
                mismatches.append((d.isoformat(), slot, res[slot], val))
        lines.append(pack_line(d, res))
        time.sleep(args.delay)

    if mismatches:
        print("# !!! MISMATCHES (resuloto vs lotodehonduras) — resolve before trusting:")
        for iso, slot, a, b in mismatches:
            print(f"#   {iso} {slot}: resuloto={a}  lotodehonduras={b}")
    else:
        print("# cross-check: no mismatches on overlapping slots"
              + ("" if cross else " (cross-check unavailable)"))

    print("# packed lines, newest-first — paste at the top of PACKED:")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
