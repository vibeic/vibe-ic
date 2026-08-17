#!/usr/bin/env python3
"""Print the failing test cases in a merged JUnit report, by NAME.

WHY THIS EXISTS
===============
The landing gate could report `aggregate complete rc=1 cases=2817 red=4` and leave a
reader with no way to learn which four. Two things caused that, and both are fixed by
this file plus the two lines that call it:

  * The FAIL path rendered the driver's output with `tail -6`. The driver's summary
    block is ALWAYS nine lines, so the tail lands inside the arithmetic every time and
    pytest's failure list has already scrolled past above it. No tail depth fixes it —
    the red count is unbounded.
  * An earlier attempt grepped that same stdout for `^RED  ` lines. MEASURED: the
    driver emits no such line, so it printed nothing, and the reason the names were
    unreadable simply moved. That is the failure this file exists to not repeat: the
    names live in the JUNIT, so the junit is what gets read.

A truncated or unparseable junit prints an explicit UNREADABLE line and exits 2. It
must never be mistaken for "no failures": an empty result is not a zero.

Usage:  print_junit_reds.py <merged.xml> [--limit N]
Exit:   0 report produced (with or without failures) / 2 could not read the junit
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def reds(path: Path):
    root = ET.parse(path).getroot()
    out = []
    for tc in root.iter("testcase"):
        bad = [c for c in tc if c.tag in ("failure", "error")]
        if not bad:
            continue
        cls = tc.get("classname") or ""
        name = tc.get("name") or ""
        msg = (bad[0].get("message") or bad[0].text or "").strip().replace("\n", " ")
        out.append((cls, name, msg, bad[0].tag))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("junit")
    ap.add_argument("--limit", type=int, default=40,
                    help="cap the printed list; the TOTAL is always printed in full, "
                         "so a cap can never read as a smaller failure count")
    a = ap.parse_args(argv)

    p = Path(a.junit)
    if not p.is_file() or p.stat().st_size == 0:
        print(f"RED NAMES UNREADABLE: {p} is missing or empty — this is NOT "
              f"'no failures'", file=sys.stderr)
        return 2
    try:
        rows = reds(p)
    except Exception as exc:                      # noqa: BLE001 — any parse trouble
        print(f"RED NAMES UNREADABLE: {type(exc).__name__}: {exc} — this is NOT "
              f"'no failures'", file=sys.stderr)
        return 2

    for cls, name, msg, kind in rows[:a.limit]:
        print(f"RED  {cls}::{name}" if cls else f"RED  {name}")
        if msg:
            print(f"       [{kind}] {msg[:150]}")
    if len(rows) > a.limit:
        print(f"       ... {len(rows) - a.limit} more not printed")
    print(f"RED TOTAL: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
