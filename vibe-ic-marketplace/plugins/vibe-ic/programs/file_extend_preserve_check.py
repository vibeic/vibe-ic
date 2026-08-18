#!/usr/bin/env python3
"""file_extend_preserve_check.py — the deterministic half of the general
"extend, don't replace, given files" lesson (issue #139, the
functional-modification clobber class).

THE GENERAL DESIGN PRINCIPLE (the lesson's judgment half lives in the
IC Expert DB, class `functional-modification-delivery`)
--------------------------------------------------------------------
When a modification task asks the author to ADD a module/feature to an
EXISTING provided file, the delivered file must PRESERVE the original
module(s) and add the new top alongside them. Overwriting the file with only
the new module deletes the definition the new logic depends on — a blind
human expert asked to EXTEND a design never deletes what was given.

THE DETERMINISTIC (zero-false-positive) CORE
--------------------------------------------
Overlay the delivered files onto the original set; for every module M that
was defined in an original file the delivery OVERWRITES, if M is no longer
defined ANYWHERE in the final file set AND the final set still INSTANTIATES
M, the delivery is SELF-BREAKING: a file set that instantiates an undefined
module cannot elaborate (unknown-module error). This sub-case needs no
intent judgment, so it is a program.

why_not_bucket_a (the judgment residual): whether dropping an original
module that NOTHING still instantiates was an intended REPLACEMENT or an
accidental deletion depends on the task wording — that half stays advisory
prose in the IC Expert DB and is deliberately NOT flagged here.

USAGE
-----
    python3 file_extend_preserve_check.py --before <dir> --after <dir> [--json]

`--before` holds the ORIGINAL provided files, `--after` the delivered files
(same relative paths for overwritten files). HDL suffixes scanned:
.v/.sv/.svh/.vh. Import surface: `check_sets(original, emitted)` on plain
{relative_path: content} dicts.

EXIT CODES
----------
    0  no self-breaking clobber (clean, or nothing overlaps).
    1  finding(s) — an overwritten definition the delivered set still
       instantiates.
    2  IO error.

chip-AGNOSTIC: pure Verilog-grammar structure — no chip/vendor/SKU literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

# single source for comment stripping among the programs/ emit helpers
from leaf_typo_alias_emit import _strip_comments  # noqa: E402

_HDL_SUFFIXES = (".v", ".sv", ".svh", ".vh")
_MODULE_DEF_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
# SV/Verilog keywords that can precede an identifier+`(` without being a
# module instantiation (mirrors the cvdp_gate #715 insight at the granularity
# this check needs — the candidate module NAME is already known here, so the
# only false-fire shape left is the module's own declaration header).
_DECL_KEYWORDS = ("module", "macromodule")


def modules_defined(text: str) -> set:
    """Module names DEFINED in `text` (comment-stripped view)."""
    return set(_MODULE_DEF_RE.findall(_strip_comments(text or "")))


def instantiates(text: str, name: str) -> bool:
    """True when `text` (comment-stripped) contains a structural instantiation
    of module `name`: `<name> [#(...)] <inst_name> (` — and the match is NOT
    the module's own declaration (`module <name> (`)."""
    clean = _strip_comments(text or "")
    # `<name>` then EITHER a parameter block `#(...)` OR at least one space,
    # then the instance identifier and `(`. The mandatory separation keeps a
    # longer identifier that merely STARTS with `name` (`<name>_reg(...)`)
    # from false-firing.
    pat = re.compile(
        r"\b" + re.escape(name) +
        r"(?:\s*#\s*\([^;]*?\)\s*|\s+)[A-Za-z_]\w*\s*\(")
    for m in pat.finditer(clean):
        head = clean[:m.start()].rstrip()
        last_word = re.search(r"([A-Za-z_]\w*)\s*\Z", head)
        if last_word and last_word.group(1) in _DECL_KEYWORDS:
            continue                    # `module <name> u_x (` cannot occur,
            # but `module <name> (` with <name> re-matched is excluded here
        return True
    return False


def check_sets(original: Dict[str, str], emitted: Dict[str, str]) -> List[str]:
    """The zero-FP core. `original` = the provided file set, `emitted` = the
    delivered files (relative paths matching `original` where a file is
    overwritten). Returns findings (empty == clean)."""
    final: Dict[str, str] = dict(original)
    final.update(emitted)
    defined_final: set = set()
    for text in final.values():
        defined_final |= modules_defined(text)
    findings: List[str] = []
    for path, _new_text in sorted(emitted.items()):
        if path not in original:
            continue                     # a NEW file cannot clobber anything
        lost = modules_defined(original[path]) - defined_final
        for mod in sorted(lost):
            if any(instantiates(t, mod) for t in final.values()):
                findings.append(
                    f"{path}: overwrites the provided definition of module "
                    f"'{mod}' while the delivered set still instantiates it "
                    f"— extend, don't replace (self-breaking clobber: the "
                    f"design cannot elaborate)")
    return findings


def _load_tree(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in _HDL_SUFFIXES:
            out[str(p.relative_to(root))] = p.read_text(errors="replace")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Flag a modification delivery that overwrites a provided "
                    "module the delivered set still instantiates "
                    "(extend-don't-replace, deterministic half).")
    ap.add_argument("--before", required=True, type=Path,
                    help="directory of the ORIGINAL provided files")
    ap.add_argument("--after", required=True, type=Path,
                    help="directory of the DELIVERED files")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")
    a = ap.parse_args(argv)
    if not a.before.is_dir() or not a.after.is_dir():
        print(f"error: --before/--after must be directories "
              f"({a.before} / {a.after})", file=sys.stderr)
        return 2
    findings = check_sets(_load_tree(a.before), _load_tree(a.after))
    if a.json:
        print(json.dumps({"pass": not findings, "findings": findings}))
    else:
        if findings:
            for f in findings:
                print(f"FAIL: {f}")
        else:
            print("PASS: no self-breaking clobber "
                  "(every overwritten-and-still-instantiated module is "
                  "preserved)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
