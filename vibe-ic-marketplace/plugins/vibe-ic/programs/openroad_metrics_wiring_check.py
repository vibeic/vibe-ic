#!/usr/bin/env python3
"""Every OpenROAD invocation must ask the tool for its own numbers. W5.

WHAT THIS CHECKS AND WHY IT IS A CHECK RATHER THAN A REFACTOR
=============================================================
OpenROAD-flow-scripts gets this property from having ONE place that builds the
command (`flow/scripts/flow.sh:15`, which appends `-metrics "$LOG_DIR/$1.json"`).
We build the command in a dozen places. Collapsing those into one wrapper is a
large edit to a 39k-line runner and would not, by itself, stop the thirteenth
call site from being written without the flag next week. The property we
actually want — *no OpenROAD invocation runs unmeasured* — is checkable
statically, so it is checked, and then the thirteenth call site is caught by
the same rule as the first twelve.

MEASURED ON THIS TREE at 8e60dd954, BEFORE THE CHANGE, by this program:

    16 OpenROAD invocation site(s) in shipped code:
       0 wired to -metrics, 13 unwired, 3 exempt

and independently, `grep -rn '\\-metrics '` over `programs/` and `mcp-eda/`
returned two docstring mentions and no call site at all. Every number the
backend gates read was therefore re-parsed out of a log.

WHAT COUNTS AS AN INVOCATION
============================
A string EXPRESSION, in shipped code, that runs the binary: the token `openroad`
— as a command, not as a path component — followed by flags including `-exit`.
Four exclusions, each of which exists because including it would make the check
dishonest rather than strict:

* DOCSTRINGS are skipped, via `ast` rather than a regex, because prose that
  quotes a command is describing one, not making one. (`# comments` never reach
  `ast` at all.)
* `programs/tests/` is skipped: a test that constructs an unwired command as its
  FIXTURE is doing its job, and forcing the flag into it would delete the
  negative control that proves this gate can fail.
* This module itself: its string constants ARE the exemption register, so
  scanning them finds the register's own copy of each excused command.
* Anything in the exemption register below, each with a stated reason. A stale
  exemption — one whose file IS in the scanned tree and no longer contains the
  text — is itself a FAILURE, so the register cannot quietly outlive the thing
  it excused.

NEVER MADE TO PASS BY CHECKING LESS: the exemption register is data, the reason
is mandatory and length-floored, and an empty scan is `NOT CHECKED` (rc 2), not
a pass. If this program ever reports zero sites it has lost its ability to see,
and it says so rather than printing PASS.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openroad_metrics as _om  # noqa: E402
from _atomic_artefact import write_json as _atomic_write_json  # noqa: E402  vibe-ic#1082

RC_OK = 0
RC_VIOLATION = 1
RC_UNDETERMINED = 2

#: A reason shorter than this is a rubber stamp, and the repo's waiver schema
#: already sets this floor for the same reason.
MIN_REASON_CHARS = 20

#: This module's own string constants ARE the register of exempted sites, so
#: scanning it finds the register's copy of each excused command and reports it
#: as a fresh unwired call site. That is a self-reference, not a call site. The
#: skip is safe to state flatly because this module runs nothing: it reads
#: source and prints, and `test_openroad_metrics_wiring_check` pins that it
#: imports no process-spawning module, so a real invocation could not hide here.
_SELF = "openroad_metrics_wiring_check.py"

#: Sites that are NOT invocations, each with the reason it is not. Keyed by
#: (path suffix, a substring stable enough to survive reformatting).
EXEMPTIONS: List[Dict[str, str]] = [
    {
        "file": "programs/phase3_one_shot_runner.py",
        "contains": "openroad -no_init -exit pnr.tcl",
        "reason": ("a provenance RECORD of the command that ran, written into "
                   "the run journal; it is an abbreviated description and not "
                   "a command this process constructs or executes"),
    },
    {
        "file": "programs/phase3_one_shot_runner.py",
        "contains": "openroad -no_init -no_splash -exit <<'EOF'",
        "reason": ("a CAPABILITY PROBE: it asks the binary whether a command "
                   "and a flag are accepted, reads the two diagnostics against "
                   "each other and writes no design artefact, so there is no "
                   "measurement for -metrics to carry"),
    },
    {
        "file": "programs/phase3_one_shot_runner.py",
        "contains": "openroad -no_init -exit (RC extraction",
        "reason": ("a provenance RECORD, and one that already substitutes a "
                   "prose phrase for the script path, so it is plainly a "
                   "description rather than an executable command line"),
    },
]


def _docstring_nodes(tree: ast.AST) -> set:
    """Every string node that is a docstring, by identity."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


#: The wrapper that derives the metrics path from the `tee` target the site
#: already names. A command routed through it is WIRED even though its literal
#: carries no `-metrics` — and routing through it is the better of the two
#: spellings, because a derived path cannot drift out of step with the log path
#: the way a second hand-typed literal can.
WRAPPER = "with_metrics"


def _wrapped_constant_ids(tree: ast.AST) -> set:
    """Ids of every string node passed to `…with_metrics(...)`."""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else \
            (fn.id if isinstance(fn, ast.Name) else "")
        if name != WRAPPER:
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, (ast.JoinedStr, ast.Constant)):
                    out.add(id(sub))
    return out


def _joined_text(node: ast.AST) -> str:
    """An f-string's literal text with `{}` where its holes are."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant)
            and isinstance(part.value, str) else "{}"
            for part in node.values)
    return ""


def _string_constants(text: str) -> List[tuple]:
    """`(lineno, value, wrapped)` for every non-docstring string EXPRESSION.

    WHOLE EXPRESSIONS, NOT INDIVIDUAL PARTS, and that distinction is the check's
    reach. A call site is written across several adjacent f-strings::

        cmd = (f"openroad -metrics {m} "
               f"-no_init -exit {tcl} 2>&1 | tee {log}")

    Python's implicit concatenation makes that ONE `JoinedStr`, but its `openroad`
    and its `-exit` live in DIFFERENT `Constant` parts of it. Scanning parts
    therefore saw a command with no `-exit`, decided it was prose, and reported
    the site as absent — measured on exactly the fixture above, which the check
    silently declined to see. Reconstructing the expression, holes and all, is
    what makes the two tokens meet.
    """
    tree = ast.parse(text)
    skip = _docstring_nodes(tree)
    wrapped = _wrapped_constant_ids(tree)
    inner: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                inner.add(id(part))
    out: List[tuple] = []
    for node in ast.walk(tree):
        if id(node) in inner or id(node) in skip:
            continue
        if isinstance(node, ast.JoinedStr) or (
                isinstance(node, ast.Constant) and isinstance(node.value, str)):
            value = _joined_text(node)
            if value:
                out.append((getattr(node, "lineno", 0), value,
                            id(node) in wrapped))
    return out


def _is_invocation(flags: str) -> bool:
    """Runs the binary, as opposed to naming it. `-exit` is the discriminator:
    every real call site in this tree drives a TCL script and exits, and the
    strings that merely mention the tool (a log line, an error code, a PATH
    export) carry no such flag."""
    return "-exit" in flags.split()


def scan_file(path: Path) -> List[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        consts = _string_constants(text)
    except (OSError, SyntaxError, ValueError):
        return []
    found: List[Dict[str, Any]] = []
    for lineno, value, wrapped in consts:
        for inv in _om.invocations(value):
            if not _is_invocation(inv["flags"]):
                continue
            found.append({"line": lineno, "text": inv["text"],
                          "flags": inv["flags"],
                          "wired_via": (WRAPPER if wrapped else
                                        "literal" if inv["has_metrics"] else ""),
                          "has_metrics": inv["has_metrics"] or wrapped})
    return found


def _exemption_for(rel: str, text: str) -> Optional[Dict[str, str]]:
    for ex in EXEMPTIONS:
        if rel.endswith(ex["file"]) and ex["contains"] in text:
            return ex
    return None


def audit(root: Path) -> Dict[str, Any]:
    plugin = root / "vibe-ic-marketplace/plugins/vibe-ic"
    if not plugin.is_dir():
        plugin = root
    roots = [plugin / "programs", plugin / "mcp-eda" / "src"]
    sites: List[Dict[str, Any]] = []
    scanned: List[Path] = []
    for base in roots:
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            if "/tests/" in f.as_posix() or f.name.startswith("test_"):
                continue
            if f.name == _SELF:
                continue
            scanned.append(f)
            rel = f.relative_to(root).as_posix() if root in f.parents \
                else f.as_posix()
            for hit in scan_file(f):
                ex = _exemption_for(rel, hit["text"])
                sites.append({**hit, "file": rel,
                              "exempt": bool(ex),
                              "exempt_reason": ex["reason"] if ex else ""})

    unwired = [s for s in sites if not s["has_metrics"] and not s["exempt"]]
    wired = [s for s in sites if s["has_metrics"]]
    exempt = [s for s in sites if s["exempt"]]

    defects: List[str] = []
    for s in unwired:
        defects.append(
            f"{s['file']}:{s['line']}: OpenROAD is invoked without `-metrics`, "
            f"so this stage's numbers exist only as prose in its log — "
            f"{s['text'][:90]}")
    for ex in EXEMPTIONS:
        if len(ex["reason"]) < MIN_REASON_CHARS:
            defects.append(f"exemption for {ex['file']} states a "
                           f"{len(ex['reason'])}-char reason; the floor is "
                           f"{MIN_REASON_CHARS}")
        # STALENESS IS SCOPED TO FILES THIS SCAN ACTUALLY READ. An exemption for
        # a file that is not in the tree under audit is out of scope, not stale
        # — and reporting it as stale would make every synthetic-tree run, and
        # every partial checkout, fail for a reason that is not about them.
        target_present = any(f.name == Path(ex["file"]).name
                             for f in scanned)
        if target_present and not any(
                s["exempt"] and s["file"].endswith(ex["file"])
                and ex["contains"] in s["text"] for s in sites):
            defects.append(
                f"exemption {ex['contains']!r} in {ex['file']} matches nothing "
                f"any more; a register that outlives what it excused starts "
                f"excusing whatever moves into its place")

    return {"sites": sites, "wired": len(wired), "unwired": unwired,
            "exempt": len(exempt), "total": len(sites), "defects": defects}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    rep = audit(Path(args.root).resolve())
    if args.json_out:
        p = Path(args.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(p, rep, indent=1)  # vibe-ic#1082

    print(f"{rep['total']} OpenROAD invocation site(s) in shipped code: "
          f"{rep['wired']} wired to -metrics, {len(rep['unwired'])} unwired, "
          f"{rep['exempt']} exempt")
    if not rep["total"]:
        print("[NOT CHECKED] no invocation site was found at all — this "
              "program has lost its ability to see, which is not a pass",
              file=sys.stderr)
        return RC_UNDETERMINED
    if rep["defects"]:
        print(f"[FAIL] {len(rep['defects'])} site(s) run OpenROAD without "
              f"asking it for its numbers:", file=sys.stderr)
        for d in rep["defects"]:
            print(f"  {d}", file=sys.stderr)
        return RC_VIOLATION
    print("[PASS] every OpenROAD invocation carries -metrics")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
