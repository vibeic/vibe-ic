#!/usr/bin/env python3
"""provenance_correction_note_check.py — a correction may not claim a repair
the row it sits on never received.

THIS GATE BLOCKS (rc=1).

WHY IT EXISTS (#413, the #381/#365 family)
------------------------------------------
`e025ba351` corrected two real defects in published provenance ledgers — a
`version` field that had captured the container entrypoint PATH banner, and a
`duration_ms` written as `0` with no measurement behind it. Both corrections
were right. It then stamped ONE SHARED note onto every row it touched:

    `version` captured the container entrypoint banner, not the tool version,
    and `duration_ms` was written as 0 without ever being measured. Both
    corrected to null …

But these files hold TWO KINDS of row, and each kind received only ONE of
those repairs. In-runner rows carry `superseded_fields.version` and never had
a `duration_ms` at all — several carry a real measured `duration_s`.
Back-filled rows carry `superseded_fields.duration_ms: 0` and never had a
`version`. So on every row, half the note described a repair that row did not
get; on in-runner rows it told a reader the duration was an unmeasured zero
that had been nulled, when that row held the only real measurement in the
file.

Measured when it was found: 50 of 54 noted rows across nine ledgers. A
correction note citing a repair its row did not receive is a fabricated
citation INSIDE the artefact whose job is to prevent exactly that.

WHAT IT CHECKS, and why not the prose
-------------------------------------
The tempting check is "does the note claim only what the row got", read out
of the note's English. That does not survive contact: a correct note has to
NAME the other repair in order to say the row did not receive it, and to
WITHDRAW the earlier false claim — so mention-counting false-FAILs the fixed
shape. Prose is checked for exactly one thing, the fingerprint of the known
shared note, which is unambiguous.

The rest is STRUCTURAL, and it is what a note's claims have to rest on:

    superseded_fields.version    ⇒ `version` is null   (the banner was removed)
    superseded_fields.duration_ms ⇒ `duration_ms` AND `duration_s` are both
                                    null, and `duration_unmeasured_reason`
                                    says why — an unmeasured row must be
                                    explicitly empty in BOTH duration keys,
                                    or the next reader fills one in
    a row with a `correction`     ⇒ has at least one `superseded_fields` key,
                                    i.e. something actually was repaired

Judged over TRACKED ledgers only. Local run directories under
`benchmark-data/ic/*/clean_run_*` are untracked by design and are not
published claims; scanning them reported 62 violations that no clone can see.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# The exact note `e025ba351` stamped on every row. Unambiguous, so it is the
# one thing worth matching in prose.
_SHARED_FINGERPRINT = "Both corrected to null (unknown / not measured)"


def _toplevel(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() \
        else start


def _tracked_ledgers(repo: Path):
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "benchmark-data"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git could not list tracked files: "
                           f"{r.stderr.strip()[:200]}")
    return [repo / x for x in r.stdout.splitlines()
            if x.endswith("provenance.jsonl")]


def audit(repo: Path) -> dict:
    findings, ledgers, noted = [], 0, 0
    for p in _tracked_ledgers(repo):
        ledgers += 1
        rel = p.relative_to(repo)
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                findings.append(f"{rel}:{i} UNPARSEABLE: {exc}")
                continue
            note = d.get("correction")
            if not note:
                continue
            noted += 1
            sf = d.get("superseded_fields") or {}
            if _SHARED_FINGERPRINT in note:
                findings.append(
                    f"{rel}:{i} SHARED_NOTE: carries the one-size-fits-all "
                    f"correction from e025ba351, which claims BOTH repairs on "
                    f"every row (#413)")
            if not sf:
                findings.append(
                    f"{rel}:{i} CORRECTION_WITHOUT_REPAIR: a `correction` note "
                    f"with no `superseded_fields` — nothing was actually "
                    f"replaced, so the note describes a repair that did not "
                    f"happen")
            if "version" in sf and d.get("version") is not None:
                findings.append(
                    f"{rel}:{i} VERSION_NOT_NULLED: `superseded_fields.version` "
                    f"records the banner, but `version` is still "
                    f"{d.get('version')!r}")
            if "duration_ms" in sf:
                for k in ("duration_ms", "duration_s"):
                    if d.get(k, None) is not None:
                        findings.append(
                            f"{rel}:{i} DURATION_NOT_EMPTY: the row was "
                            f"repaired for an unmeasured duration, but `{k}` "
                            f"is {d.get(k)!r} — an unmeasured row must be "
                            f"explicitly empty in BOTH duration keys")
                if not d.get("duration_unmeasured_reason"):
                    findings.append(
                        f"{rel}:{i} NO_UNMEASURED_REASON: duration nulled with "
                        f"no `duration_unmeasured_reason`; null alone does not "
                        f"tell a reader whether it was never taken or lost")
    return {"program": "provenance_correction_note_check",
            "ledgers": ledgers, "noted_rows": noted, "findings": findings,
            "verdict": "FAIL" if findings else "PASS"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    repo = _toplevel(Path(a.repo).resolve())
    try:
        rep = audit(repo)
    except RuntimeError as exc:
        print(f"[ERROR] provenance_correction_note_check: {exc}\n"
              "   Nothing was checked. This is NOT a clean result.")
        return 2
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")
    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} correction note(s) claim a "
              f"repair the row did not receive:")
        for f in rep["findings"][:40]:
            print(f"   {f}")
        if len(rep["findings"]) > 40:
            print(f"   … and {len(rep['findings']) - 40} more")
        return 1
    print(f"[PASS] provenance_correction_note_check: {rep['ledgers']} tracked "
          f"ledger(s), {rep['noted_rows']} corrected row(s) — every note rests "
          f"on a repair the row actually received.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
