#!/usr/bin/env python3
"""bundled_attribution_notice_check.py — every BUNDLED third-party work must be
accounted for in NOTICE.

THIS GATE BLOCKS (rc=1). It REFUSES (rc=2) rather than passing when it found
nothing to check.

WHY THIS FILE EXISTS  (vibe-ic#1043)
====================================
#1043 reported that a withdrawal deletes `SOURCE_MANIFEST.md` files while the
vendored Apache-2.0 RTL they attribute stays in the tree, and proposed the
narrow fix: exempt those manifests from the withdrawal.

MEASURED, and the measurement moves the defect
----------------------------------------------
Between `origin/main` and `origin/withdraw/nonpassing-published-runs`:

    benchmark-data files      main 17216   withdrawal 12007   deleted 5209
    SOURCE_MANIFEST.md        main     9   withdrawal     7   deleted    2
    Apache-2.0 SPDX RTL       main   475   SURVIVING    312

So the withdrawal deletes TWO manifests, not five — the "5 of 6" in the issue
is measured against a different branch — and 312 attributed files survive it.

But the obligation gap is NOT created by the withdrawal, and exempting the
manifests would not close it. The file whose job this is under Apache-2.0
§4(d) is `NOTICE`, it is at the repo root, the withdrawal does not touch it,
and it accounts for NONE of them. Measured on `NOTICE` at v1.10.33:

    caravel / chipfoundry / opentitan / ibex / lowRISC / user_proj / vendored
        -> 0 occurrences each

while its THIRD-PARTY COMPONENTS section states, of the third-party work,
"None are bundled in this repository". 502 SPDX-headered source files say
otherwise:

    Apache-2.0  474        ISC  28
    lowRISC contributors (OpenTitan)  432
    Olof Kindgren                      34
    Efabless Corporation               27
    The SkyWater PDK Authors            2

A per-run manifest inside a withdrawable directory was never the right home
for a distribution obligation: the duty attaches to shipping the WORK, so the
record has to live where the work does — at the root, outside anything a run
withdrawal can take down. That is what this gate enforces, and it is why the
withdrawal question becomes moot rather than needing an exemption.

WHAT IT DOES NOT DO
===================
It does not judge licence COMPATIBILITY, does not read licence text, and does
not decide whether a file may be bundled at all. It asks one decidable
question — is this bundled work NAMED in NOTICE — and nothing else. A gate
that quietly grew into a licence opinion would be worse than none.

EXIT CODES
    0  every bundled third-party holder is accounted for in NOTICE
    1  at least one is not (each named, with a file that carries it)
    2  refused — no SPDX-headered source found, so nothing was established
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_polarity import (  # noqa: E402
    DENIAL_CORE_RE, is_denied, sentence_scope)

#: Source extensions carrying an SPDX header. Deliberately the HDL set plus the
#: scripting set: this gate is about work BUNDLED as source, and a licence
#: header in a build script binds exactly as one in RTL does.
SOURCE_SUFFIXES = (".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl",
                   ".c", ".h", ".cc", ".cpp", ".py", ".tcl", ".sdc")

#: Directories that are not part of what this repository distributes.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv"}

_SPDX_LICENSE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")
#: Both spellings, because upstreams use both and a gate that saw one would
#: report a confident zero on a tree full of the other.
_COPYRIGHT = re.compile(
    r"(?:SPDX-FileCopyrightText:|[Cc]opyright)\s*"
    r"(?:\(c\)|\(C\)|©)?\s*"
    r"(?:\d{4}(?:\s*[-,]\s*\d{4})*)?\s*"
    r"(?:\(c\)|\(C\)|©)?\s*"
    r"(.+)")

#: How many lines of a file may carry the header. Licence headers are at the
#: top by convention and by the licences' own instructions.
HEADER_LINES = 40


def _is_bare_denial(holder: str) -> Optional[str]:
    """The denial word, when the holder name is NOTHING BUT denial vocabulary.

    SPDX specifies the literal values ``NONE`` and ``NOASSERTION`` for
    `SPDX-FileCopyrightText`, and ``NONE`` means precisely "there is no
    copyright holder". Read blind, it becomes a bundled third-party holder
    named "NONE" that `NOTICE` is then required to name.

    WHOLE-STRING, NOT SUBSTRING, and that is the load-bearing part. `Non-Profit
    Foundation` has `_distinctive` "Non-Profit", and `\\bnon-?\\b` matches
    inside it — so a `is_denied(holder)` here would drop a real holder and the
    gate would go quietly green on work it never attributed. `_prose_polarity`
    names that direction as the silent one; this is the shape it warns about.
    """
    core = re.sub(r"[^A-Za-z/]+", " ", holder or "").strip()
    if not core:
        return None
    words = core.split()
    if all(DENIAL_CORE_RE.fullmatch(w) for w in words):
        return words[0]
    return None


def _clean_holder(raw: str) -> str:
    """The holder name, with punctuation and trailing noise removed."""
    s = raw.strip().strip("*/-#; \t").rstrip(".").strip()
    s = re.sub(r"\s+", " ", s)
    # a trailing "and others" / "All rights reserved" is not part of the name
    s = re.sub(r"[,;]?\s*(all rights reserved|and others)\.?$", "", s,
               flags=re.I).strip()
    return s


def _distinctive(holder: str) -> str:
    """The token NOTICE has to carry for this holder to count as named.

    The FIRST word that is not a bare year and not a generic corporate suffix.
    Derived from the holder string rather than listed, so a new upstream needs
    no edit here — which is the property that keeps this from rotting into an
    allowlist of the four upstreams that happen to be bundled today.
    """
    generic = {"the", "inc", "inc.", "ltd", "llc", "corp", "corporation",
               "contributors", "authors", "project", "foundation"}
    for word in re.split(r"[\s,]+", holder):
        w = word.strip("()<>.,;").strip()
        if not w or w.isdigit():
            continue
        if w.lower() in generic:
            continue
        return w
    return holder


def scan(root: Path) -> Dict[str, Dict[str, object]]:
    """`{holder: {"licences": {...}, "files": [...], "n": int}}` for the tree."""
    found: Dict[str, Dict[str, object]] = defaultdict(
        lambda: {"licences": set(), "files": [], "n": 0})
    for path in sorted(root.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        if SKIP_DIRS.intersection(path.parts):
            continue
        try:
            head = "\n".join(path.read_text(errors="replace").splitlines()[:HEADER_LINES])
        except OSError:
            continue
        lic = _SPDX_LICENSE.search(head)
        if not lic:
            continue
        holder = None
        pos = 0
        for line in head.splitlines():
            m = _COPYRIGHT.search(line)
            if m:
                cand = _clean_holder(m.group(1))
                # POLARITY (vibe-ic#712, wired here by #1241). Two ways this
                # assertion can be denied, and they need different instruments:
                #
                #   * the NAME is a bare SPDX sentinel. SPDX specifies the
                #     literal `NONE` for `SPDX-FileCopyrightText`, meaning
                #     "there is no copyright holder"; read blind it becomes a
                #     bundled holder called "NONE" that NOTICE must then name.
                #   * the SENTENCE denies it: "this file is not copyrighted by
                #     Acme Corp" is read as the holder `ed by Acme Corp`,
                #     because `[Cc]opyright` matches inside *copyrighted*. Its
                #     `_distinctive` token is `ed`, and NOTICE contains "ed" as
                #     a substring of ordinary English — so the fabricated holder
                #     is silently accounted for. A loud failure gets found; that
                #     one never would.
                #
                # The scope EXCLUDES the captured name, because `Non-Profit
                # Foundation` matches `\bnon-?\b` and a denial read off the name
                # would DROP a real holder and take the gate quietly green —
                # the silent direction `_prose_polarity` names.
                #
                # The reach comes from `sentence_scope`, not a private "the
                # line" rule, with `extra_breaks=("\n",)` because a licence
                # header is a block of RECORDS rather than flowing prose.
                denial = None
                if cand:
                    lo, _hi = sentence_scope(head, pos + m.start(),
                                             pos + m.start(1),
                                             extra_breaks=("\n",))
                    denial = (_is_bare_denial(cand)
                              or is_denied(head[lo:pos + m.start(1)]))
                # A DENIED assertion is not this file's holder. Keep reading —
                # a header may deny in one line and assert in the next, and
                # stopping at the denial would report the file as unattributed
                # when it is attributed one line down.
                if cand and not denial:
                    holder = cand
                    break
            pos += len(line) + 1
        if not holder:
            continue
        rec = found[holder]
        rec["licences"].add(lic.group(1))            # type: ignore[union-attr]
        rec["n"] = int(rec["n"]) + 1                 # type: ignore[arg-type]
        if len(rec["files"]) < 5:                    # type: ignore[arg-type]
            rec["files"].append(str(path.relative_to(root)))  # type: ignore[union-attr]
    return dict(found)


def own_holders(notice_text: str) -> List[str]:
    """The repository's OWN copyright holder, read out of NOTICE itself.

    Read rather than stated so that renaming the project does not silently turn
    the project's own files into unattributed third-party works — and so this
    gate carries no name of its own to drift from the real one.
    """
    out: List[str] = []
    for line in notice_text.splitlines()[:12]:
        m = _COPYRIGHT.search(line)
        if m:
            h = _clean_holder(m.group(1))
            if h:
                out.append(h)
    return out


def unaccounted(root: Path, notice: Path) -> Tuple[List[str], Dict[str, Dict[str, object]], List[str]]:
    """`(unaccounted_holders, scan_result, own)`."""
    text = notice.read_text(errors="replace") if notice.is_file() else ""
    own = own_holders(text)
    own_tokens = {_distinctive(h).lower() for h in own}
    result = scan(root)
    missing: List[str] = []
    for holder in sorted(result):
        token = _distinctive(holder)
        if token.lower() in own_tokens:
            continue                       # our own work, not a bundled one
        if re.search(re.escape(token), text, re.I):
            continue
        missing.append(holder)
    return missing, result, own


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", nargs="?", default=".", type=Path,
                    help="repository root to scan")
    ap.add_argument("--notice", type=Path, default=None,
                    help="the NOTICE file (default: <root>/NOTICE)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    root = args.root.resolve()
    notice = args.notice or (root / "NOTICE")
    if not notice.is_file():
        print(f"[FAIL] no NOTICE at {notice} — a distribution that bundles "
              f"third-party work and ships no NOTICE has nowhere to carry the "
              f"attribution at all.")
        return 1

    missing, result, own = unaccounted(root, notice)
    total = sum(int(v["n"]) for v in result.values())
    report = {
        "root": str(root), "notice": str(notice),
        "own_holders": own,
        "spdx_files": total,
        "holders": {h: {"n": int(v["n"]),
                        "licences": sorted(v["licences"]),      # type: ignore[arg-type]
                        "examples": v["files"]}
                    for h, v in sorted(result.items())},
        "unaccounted": missing,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")

    if not result:
        # A census over nothing matches an empty NOTICE trivially. That is the
        # confident zero this repo keeps finding, so it is rc 2, not rc 0.
        print(f"REFUSE — no SPDX-headered source found under {root}. This run "
              f"establishes nothing about attribution; it did not look at a "
              f"tree that has any.")
        return 2

    if missing:
        print(f"[FAIL] {len(missing)} bundled third-party holder(s) are NOT "
              f"named in {notice.name}, across {total} SPDX-headered file(s):")
        for h in missing:
            rec = result[h]
            print(f"   {h}  —  {rec['n']} file(s), "
                  f"{'/'.join(sorted(rec['licences']))}")     # type: ignore[arg-type]
            for f in rec["files"][:2]:                        # type: ignore[index]
                print(f"        e.g. {f}")
        print(f"  Apache-2.0 §4(d) attaches to distributing the WORK, so the "
              f"record has to live where the work does. Add each holder to "
              f"{notice.name}.")
        return 1

    print(f"[PASS] every bundled third-party holder is named in {notice.name}: "
          f"{len(result)} holder(s) over {total} SPDX-headered file(s) "
          f"(own: {', '.join(own) or 'none declared'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
