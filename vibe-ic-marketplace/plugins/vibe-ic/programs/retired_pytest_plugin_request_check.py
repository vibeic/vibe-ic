#!/usr/bin/env python3
"""retired_pytest_plugin_request_check.py — no file may hand pytest a plugin
the anchored runtime does not carry.

THE DEFECT IT EXISTS FOR (measured 2026-08-20 at 9cc09b863, v1.11.5)
====================================================================
This repo RETIRED `pytest-timeout`. Five places say so in prose or in a local
assertion::

    programs/pytest_per_file_junit.py:70   "There is deliberately no
                                            pytest-timeout guard on the landing path"
    tools/ci/test_phase_b_activated_parity.py:541    assert "-p pytest_timeout" not in fn
    tools/ci/test_repo_tools_tests_gate.py:254       assert "-p pytest_timeout" not in body
    tools/ci/test_hermetic_test_arm_entry.py:17      assert "pytest_timeout" not in body
    tools/liar_census.py:1418  +  tools/ci/repo_hygiene_gates.sh:998

Every one of those five is scoped to ONE named file. Nothing looked at the tree.
So four live requests survived the retirement in files nobody had pinned --
`programs/tests/test_pytest_per_file_junit.py`, two in
`programs/tests/test_issue1181_probe_budget_and_summary.py`, and the DEFAULT
RUNNER of the production tool `tools/core_agent/covered_by.py`.

`-p <name>` is a HARD import: pytest refuses to start when the module is absent,
dying in its pre-parse before collecting one test. `pytest-timeout` is absent
from `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff` -- the image
`tools/ci/protected_landing_transition.json` names as `.runner.image` -- and from
its newer 0.3.13 tag. MEASURED, the same 90 cases from the same tree::

    image sha256:66c33ff2 (py3.12 / pytest 9.0.3)   90 cases   30 red
    host              (py3.10 / pytest 9.1.1)       90 cases    3 red
    per-test set difference: 28 image-only reds, ALL of them this cause

Twenty-eight red cells on the landing gate that said nothing whatever about the
code under test. And `covered_by.py` -- which is not a test and produced no red
at all -- could not measure a single candidate inside the anchored runtime: its
arms printed no summary line, `classify_run` read that as UNMEASURED, and the
tool reported UNKNOWN for every PR in a shape that reads like "the branches were
unreachable" rather than "my own argv cannot start".

The disagreement was not that anybody was wrong about the doctrine. It was that
the doctrine was enforced FILE BY FILE, five times, and a file-by-file rule
cannot see the sixth file. This gate is the tree-wide form.

WHY A DECLARED LIST AND NOT A LIVE PROBE
========================================
The verdict is about the ANCHORED runtime, not about the interpreter that
happens to run this gate. Probing THIS host is exactly the mistake that let the
drift live: the 28 tests were green on every developer host, because every
developer host had an ambient `pip install pytest-timeout` that nothing in this
tree declares. `--probe` is therefore available and is DIAGNOSTIC ONLY: it
reports whether this interpreter can import each retired name, and never changes
the exit code. A gate whose verdict moves with the host is the defect.

WHAT COUNTS AS A REQUEST -- AND WHAT DELIBERATELY DOES NOT
==========================================================
A REQUEST is argv construction:

  * Python: a list/tuple literal whose elements include `-p` immediately
    followed by a retired name, or a `--timeout=`/`--timeout-method` option in a
    literal that also builds a pytest argv. Found by `ast`, so a COMMENT or a
    DOCSTRING can never be a hit.
  * Shell/YAML: a non-comment line carrying `-p <retired name>`.

NOT a request, and each of these is present in this tree today:

  * prose in a comment or docstring explaining WHY the idiom was retired
    (`tools/liar_census.py`, `tools/ci/repo_hygiene_gates.sh`, this file);
  * an assertion FORBIDDING it -- `assert "-p pytest_timeout" not in body` --
    which is one string constant, never a two-element sequence;
  * `@pytest.mark.timeout(...)`, a marker and not a plugin request.

WHAT THIS GATE CANNOT SEE, STATED RATHER THAN LEFT TO BE DISCOVERED
==================================================================
It reads SOURCE, so it sees a request that is written down and nothing else.
Three shapes are outside it and are named here so a green verdict is not read
as more than it is:

  * an argv assembled from a shell string -- `subprocess.run("pytest -p <name>",
    shell=True)` -- because the option and the plugin name are one constant and
    no adjacency exists to find;
  * an argv whose `-p` and whose plugin name live in DIFFERENT literals joined
    at runtime (`["-p"] + [NAME]`), or that reads the name from configuration;
  * a plugin loaded through `pytest.ini` / `PYTEST_ADDOPTS` / an entry point
    rather than through `-p`. The landing arms all set
    `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, which closes the entry-point door, but
    this gate does not check that they still do.

None of the three was the defect measured here, and a source scanner cannot
close them without becoming a runtime probe -- which is the thing this gate
deliberately is not (see the section above). The honest scope is: an argv
written down in the tree cannot ask the anchored runtime for a plugin it does
not carry.

"I COULD NOT READ IT" IS NOT "IT WAS CLEAN"
===========================================
A file that cannot be enumerated, decoded or parsed is REFUSED (rc 2) and named,
never skipped into a green total. A run that examined zero files is a disclosed
VACUOUS_PASS (rc 2), not a PASS -- `tools/ci/repo_hygiene_gates.sh`'s `run`
helper fails the suite on any non-zero rc, so a mis-rooted invocation goes RED
there instead of quietly clean.

DECLARED BLOCKING. It is wired into `tools/ci/repo_hygiene_gates.sh`, whose
`run` helper turns any non-zero rc into a suite failure.

chip-AGNOSTIC: interpreter and argv shape only. No design, PDK, vendor, process
node or chip name appears anywhere in this program.

Exit: 0 = PASS (files examined, no request found)
      1 = FAIL (requests listed)
      2 = REFUSED (a file could not be read/parsed) or VACUOUS_PASS (nothing
          was examined) -- both disclosed, neither a clean verdict
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa                                   # noqa: E402
import _gate_denominator as _gd                                  # noqa: E402

RC_PASS, RC_FAIL, RC_REFUSED = 0, 1, 2

#: The retired names, each with the reason and the replacement, so the remedy
#: travels with the refusal instead of living in somebody's memory. Assembled
#: from fragments for one reason only: this file must be able to scan ITSELF
#: without its own declaration being the hit it reports.
RETIRED: Dict[str, Dict[str, str]] = {
    "pytest" + "_timeout": {
        "reason":
            "absent from the anchored runner image "
            "ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff "
            "(tools/ci/protected_landing_transition.json .runner.image) and "
            "from its newer 0.3.13 tag; `-p <name>` is a hard import, so the "
            "session dies in pytest's pre-parse before collecting one test. "
            "Retired at v1.10.69 for a second, independent reason: "
            "--timeout-method=thread kills the SESSION, so the run that trips "
            "it writes no junit and loses every result it had already earned.",
        "replacement":
            "bound the CHILD, not the session: subprocess.run(timeout=...), "
            "whose overrun is a named UNMEASURED and never a clean zero; and "
            "for the landing populations, the semantic forward-progress "
            "supervision in programs/pytest_per_file_junit.py "
            "(--stall-after / --aggregate-stall-after).",
    },
}

#: Option prefixes that only `pytest-timeout` supplies. A pytest argv carrying
#: one of these is requesting the plugin even when it does not name it -- and
#: with `-p no:cacheprovider` in the same argv it would die on the option
#: instead of on the import, which is the same red wearing a different message.
_TIMEOUT_OPTION_PREFIXES = ("--timeout=", "--timeout-method")

_PY_SUFFIXES = {".py"}
_LINE_SUFFIXES = {".sh", ".bash", ".yaml", ".yml"}
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules",
              ".venv", "venv"}

#: What ONE unit is, in this gate's own terms.
DENOMINATOR_UNIT = "source file(s) parsed for a pytest plugin request"


class Refusal(RuntimeError):
    """A file the gate could not read. Never silently skipped."""


# ── enumeration ──────────────────────────────────────────────────────────────

def _git_tracked(root: Path) -> Optional[List[Path]]:
    """Tracked files, or None when git cannot answer (caller REFUSES)."""
    try:
        p = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    names = [n for n in p.stdout.decode("utf-8", "replace").split("\0") if n]
    return [root / n for n in names]


def _walked(root: Path) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            out.append(Path(dirpath) / fn)
    return out


def enumerate_files(root: Path) -> Tuple[List[Path], str]:
    """(candidate files, how they were enumerated).

    NAMED IN EVERY VERDICT: a `git ls-files` sweep and a disk walk can disagree
    (an untracked scratch file, a deleted-but-not-committed one), and a reader
    who cannot see which one ran cannot tell a shrinking denominator from a
    clean tree.
    """
    tracked = _git_tracked(root)
    if tracked is not None:
        how = "git-tracked"
        cands = tracked
    else:
        how = "disk-walk"
        cands = _walked(root)
    keep = [p for p in cands
            if p.suffix in _PY_SUFFIXES or p.suffix in _LINE_SUFFIXES]
    return sorted(set(keep)), how


# ── the two scanners ─────────────────────────────────────────────────────────

def _seq_strings(node: ast.AST) -> Optional[List[Optional[str]]]:
    """The element strings of a list/tuple literal, `None` for non-constants.

    A non-literal element (a variable, an f-string, a call) becomes `None`, so
    `[sys.executable, "-m", "pytest", "-p", "pytest_timeout"]` still exposes the
    adjacency this gate looks for.
    """
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    out: List[Optional[str]] = []
    for el in node.elts:
        if isinstance(el, ast.Constant) and isinstance(el.value, str):
            out.append(el.value)
        elif isinstance(el, ast.JoinedStr) and el.values:
            # `f"--timeout={_INNER_TIMEOUT}"` is a JoinedStr, not a Constant,
            # and it is EXACTLY how the request appeared in
            # `programs/tests/test_pytest_per_file_junit.py:390`. Its literal
            # PREFIX is fixed source text and is all this gate needs; the
            # interpolated part is runtime data and is deliberately not read.
            head = el.values[0]
            out.append(head.value
                       if isinstance(head, ast.Constant)
                       and isinstance(head.value, str) else None)
        else:
            out.append(None)
    return out


def _looks_like_pytest_argv(items: Sequence[Optional[str]]) -> bool:
    """True when this literal is building a pytest command line.

    Deliberately narrow. `--timeout=` is a perfectly ordinary option for other
    tools in this tree, so the option rule below fires only inside a literal
    that is demonstrably a pytest argv: an element that IS `pytest`, or one that
    ends in `/pytest`.
    """
    for s in items:
        if not s:
            continue
        if s == "pytest" or s.endswith("/pytest"):
            return True
    return False


def scan_python(path: Path, text: str) -> List[str]:
    """Hits in one Python file. Raises `Refusal` when it cannot be parsed."""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:                                  # pragma: no cover
        raise Refusal(f"{path}: cannot parse ({exc})") from exc
    hits: List[str] = []
    for node in ast.walk(tree):
        items = _seq_strings(node)
        if items is None:
            continue
        line = getattr(node, "lineno", 0)
        for i, s in enumerate(items):
            if s != "-p":
                continue
            nxt = items[i + 1] if i + 1 < len(items) else None
            if nxt in RETIRED:
                hits.append(
                    f"{path}:{line}: pytest argv requests retired plugin "
                    f"`{nxt}` via `-p`")
        if not _looks_like_pytest_argv(items):
            continue
        for s in items:
            if s and s.startswith(_TIMEOUT_OPTION_PREFIXES):
                hits.append(
                    f"{path}:{line}: pytest argv carries `{s}`, an option only "
                    f"the retired `{next(iter(RETIRED))}` plugin supplies")
    return hits


def scan_lines(path: Path, text: str) -> List[str]:
    """Hits in one shell/YAML file: non-comment lines only."""
    hits: List[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for name in RETIRED:
            if f"-p {name}" in stripped:
                hits.append(f"{path}:{n}: requests retired plugin `{name}`"
                            " via `-p`")
    return hits


def scan(root: Path) -> Tuple[List[str], List[str], Dict[str, object]]:
    """(hits, refusals, statistics) over the whole tree."""
    files, how = enumerate_files(root)
    hits: List[str] = []
    refusals: List[str] = []
    examined = 0
    for path in files:
        if not path.is_file():
            # A tracked path that is not on disk is a fact about the checkout,
            # not about the file's content. Named, never counted as examined.
            refusals.append(f"{path}: tracked but not present on disk")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            refusals.append(f"{path}: cannot read ({exc})")
            continue
        try:
            if path.suffix in _PY_SUFFIXES:
                hits.extend(scan_python(path, text))
            else:
                hits.extend(scan_lines(path, text))
        except Refusal as exc:
            refusals.append(str(exc))
            continue
        examined += 1
    return hits, refusals, {"examined": examined, "considered": len(files),
                            "enumeration": how}


# ── diagnostic probe (never changes the verdict) ─────────────────────────────

def probe_here() -> Dict[str, bool]:
    """Whether THIS interpreter can import each retired name.

    Diagnostic only. The verdict is about the anchored runtime; a gate whose
    answer moves with the host is the defect this program exists for.
    """
    return {name: importlib.util.find_spec(name) is not None
            for name in RETIRED}


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", nargs="?", default=".",
                   help="repository root to scan (default: %(default)s)")
    p.add_argument("--probe", action="store_true",
                   help="also report whether THIS interpreter carries each "
                        "retired plugin (diagnostic; never changes the rc)")
    p.add_argument("--json", dest="json_out", default=None,
                   help="write the machine-readable summary here")
    a = p.parse_args(list(argv) if argv is not None else sys.argv[1:])

    root = Path(a.root).resolve()
    hits, refusals, stats = scan(root)
    how = stats["enumeration"]

    reason = ""
    if not stats["examined"]:
        reason = (f"no .py/.sh/.yaml file was examined under {root} "
                  f"[{how}] — the root is wrong or the tree is empty")
    denom = _gd.Denominator(
        unit=DENOMINATOR_UNIT, examined=int(stats["examined"]),
        considered=int(stats["considered"]), not_applicable_reason=reason,
        details={"enumeration": how, "retired": sorted(RETIRED),
                 "refusals": len(refusals), "root": str(root)})
    summary: Dict[str, object] = {"hits": len(hits), "refusals": len(refusals),
                                  "hit_lines": hits,
                                  "refusal_lines": refusals}
    _gd.attach(summary, denom)
    if a.probe:
        summary["probe_this_interpreter"] = probe_here()

    for line in refusals:
        print(f"REFUSED  {line}")
    for line in hits:
        print(line)
    if a.probe:
        for name, present in sorted(summary["probe_this_interpreter"].items()):
            print(f"[probe] this interpreter {'HAS' if present else 'lacks'} "
                  f"`{name}` — diagnostic only, the verdict is about the "
                  f"anchored runtime")
    if a.json_out:
        # Atomically: a reader that opens this report mid-write must never see
        # a half-written verdict and read it as a clean one.
        _aa.write_json(Path(a.json_out), summary, indent=2, sort_keys=True)

    if refusals:
        print(f"REFUSED — {len(refusals)} file(s) could not be read or parsed; "
              f"{_gd.line_of(summary)} [{how}]. 'I could not look' is not "
              f"'I looked and it was clean'.")
        return RC_REFUSED
    if hits:
        for name, info in sorted(RETIRED.items()):
            print(f"  `{name}` is retired: {info['reason']}")
            print(f"  use instead: {info['replacement']}")
        print(f"FAIL — {len(hits)} retired pytest-plugin request(s); "
              f"{_gd.line_of(summary)} [{how}]")
        return RC_FAIL
    if denom.is_vacuous:
        print(f"[VACUOUS_PASS] retired_pytest_plugin_request_check: "
              f"{_gd.line_of(summary)} [{how}]")
        print(f"VACUOUS_PASS: {reason}", file=sys.stderr)
        return RC_REFUSED
    print(f"PASS — 0 retired pytest-plugin request(s); "
          f"{_gd.line_of(summary)} [{how}]")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
