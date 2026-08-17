#!/usr/bin/env python3
"""pytest_parallel_policy.py — which selected test files may share a machine.

WHY THIS EXISTS
===============
`pytest-xdist` is installed on every landing host and used nowhere. On a
17-file corpus it was measured equivalent at widths serial/8/16/32 (identical
normalised verdict hash), which was read as "parallelism is safe here". It is
not safe on the corpus that a real landing actually runs.

MEASURED, 2026-08-17, on a tree carrying a 16-file change whose selector output
is 93 files (2414 cases), the SAME tree hash on four hosts, one width each:

    width      cases   normalised verdict hash   wall
    n=8         2414   09f2d3e7a8401e97          273.4 s
    n=16        2414   35a6262dc8bd433a          367.8 s
    n=24        2414   d531e92ec6b7aa72          381.2 s

Every width produced the same 2414 cases and the same per-file case map, and
`git status --porcelain` was EMPTY after all three. The verdicts still differed,
and two of the differences are not flakiness — they are one named mechanism:

    programs/tests/test_gate_skip_routing_check.py plants
        programs/_i528_planted_unrouted_check.py
        programs/_i528_report_only_disclosure_check.py
    into the LIVE plugin tree for the duration of two tests, because the
    shipped ratchet it is driving resolves gate names against the real
    PROGRAMS dir and there is nothing else to drive it against.

Under `--dist loadfile` that file is on ONE worker, so within its own file the
plant is invisible to everyone. It is NOT invisible to the other 92 files. Two
whole-tree scanners ran concurrently on other workers and SAW it:

    test_issue833_analog_l5_vacuous_reaches_umbrella::
        test_the_gate_is_out_of_the_unrouted_inventory
      -> FAILED at n=16 and n=24, and the failure text names the planted file:
         "Finding(gate='_i528_planted_unrouted_check', rule='u…'"

    test_issue1130_wiring_population_parity::
        test_the_wiring_gates_state_their_denominator_on_a_clean_run
        [checker_execution_wiring_audit.py-…]
      -> FAILED at n=16 and n=24: the denominator it states is a count of the
         programs directory, and the plant is in it.

Both PASSED at n=8 and both PASS serially. That is the worst possible shape for
a landing gate: a verdict that depends on how the scheduler happened to
interleave two files, reported as a property of the branch.

WHAT THIS FILE DOES, AND DELIBERATELY DOES NOT DO
=================================================
DECLARES   the roster of selected test files that must be run with NOTHING
           else running beside them, each with the reason it is on the roster.
PARTITIONS a selection into (serial, parallel) preserving selection order, so
           a caller can run the parallel group under xdist and the serial group
           in its own session and still cover every selected file exactly once.
AUDITS     the corpus for the hazard the roster exists for — a test file that
           writes into the shipped tree — and FAILS when one is found that the
           roster does not name. The roster is therefore not a list somebody
           has to remember to update: a new live-tree writer fails this check
           the day it lands.
NEVER      decides that a parallel run is equivalent to a serial one. It is
           not. `--dist loadfile` covers a PARTITION of the cross-file ordered
           pairs a single session covers; at n=8 over 93 files that is roughly
           8·C(12,2)/C(93,2) ≈ 12% of them. Any caller that trades the serial
           whole-selection session for a parallel one is giving up the rest,
           and this module states that rather than hiding it. It is the reason
           the driver flag that consumes this policy is OFF by default.

BLOCKING (declared, per flow-change-acceptance §5): `--audit` exits 1 on an
unrostered live-tree writer, 0 when the corpus matches the roster, and 2 when
it could not look (which is not a pass).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

#: Path methods that MUTATE the object they are called on.
#:
#: `replace` and `chmod` are DELIBERATELY absent. `replace` is also `str.replace`
#: and this suite is full of `SOME_LIVE_PATH.read_text().replace(...)`, which
#: writes nothing; including it produced 12 false findings on the shipped tree
#: before it was removed. A gate that cries wolf about a read is a gate whose
#: findings get skimmed.
_MUTATORS = frozenset({
    "write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir",
    "rename", "symlink_to", "hardlink_to",
})
#: `shutil` entry points that mutate their FIRST-or-SECOND positional target.
_SHUTIL_WRITERS = frozenset({"copy", "copy2", "copyfile", "copytree", "move",
                             "rmtree", "make_archive"})

#: Module-level names that, in this suite, resolve to a path INSIDE the shipped
#: tree. Every test file that touches the live tree reaches it through one of
#: these; a test that builds its own scratch reaches it through `tmp_path`,
#: which is a fixture argument and therefore never a module-level name.
_LIVE_ROOT_NAMES = frozenset({
    "_PROGRAMS", "_PLUGIN", "_ROOT", "_REPO", "_REPO_ROOT", "_PLUGIN_ROOT",
    "PROGRAMS", "PLUGIN", "ROOT", "REPO", "REPO_ROOT", "PLUGIN_ROOT",
    "PROGRAMS_DIR", "PLUGIN_DIR",
})

#: THE ROSTER. Key: path relative to the plugin root, exactly as the selector
#: emits it. Value: why this file cannot share a machine with the other 92.
#:
#: A file belongs here when running it CONCURRENTLY with an arbitrary other
#: selected file can change either one's verdict. Slowness is NOT a reason —
#: a slow file is the reason to run it first, not alone.
SERIAL_ONLY: Dict[str, str] = {
    "programs/tests/test_gate_skip_routing_check.py": (
        "plants programs/_i528_planted_unrouted_check.py and "
        "programs/_i528_report_only_disclosure_check.py into the LIVE plugin "
        "tree, because the shipped ratchet under test resolves gate names "
        "against the real PROGRAMS dir. MEASURED 2026-08-17: with this file "
        "running beside the rest at n=16 and n=24, "
        "test_issue833_analog_l5_vacuous_reaches_umbrella and "
        "test_issue1130_wiring_population_parity FAILED naming the planted "
        "file; both pass at n=8 and serially."
    ),
    "programs/tests/test_flow_compliance_check_gate.py": (
        "plants programs/_pytest_rc2_helper.py and "
        "programs/_pytest_rc1_helper.py into the LIVE plugin tree, for the "
        "same structural reason: flow_compliance_check._check_program_exit_"
        "zero resolves a bare program NAME against PROGRAMS_DIR, so the only "
        "way to drive the shipped resolver is to put the helper where it "
        "looks. FOUND BY --audit, not by a failure: this file is not in the "
        "93-file corpus the n=16/n=24 hazard was measured on, and it would "
        "have poisoned the same whole-tree scanners the first time a change "
        "selected both."
    ),
    # ── the rest of the population, FOUND BY `--audit`, not by a failure ──
    # Each writes into the shipped tree for the same structural reason: the
    # subject resolves a path from ITS OWN location, so the only way to drive
    # the shipped resolver is to put the fixture where it looks. None of them
    # is in the 93-file corpus the n=16/n=24 hazard was measured on; each of
    # them is one selection away from being.
    "programs/tests/test_gate_discloses_denominator.py": (
        "writes programs/_probe_<name>.py into the LIVE tree to drive the "
        "denominator disclosure over a gate whose behaviour it controls; any "
        "concurrent enumerator of programs/ counts the probe."
    ),
    "programs/tests/test_issue1387_glob_consumers_are_selected.py": (
        "writes programs/tests/test_zz1387_derived_probe.py into the LIVE "
        "tree — the whole point is that a BRAND-NEW file nobody named is "
        "picked up, so it cannot be a tmp_path fixture. A concurrent selector "
        "or tests-directory census sees a test file that is not in git."
    ),
    "programs/tests/test_issue538_merge_gate_covers_ci_hygiene.py": (
        "writes a throwaway module into the LIVE tree so the merge gate's own "
        "hygiene sweep has an offender to find; concurrently, every other "
        "hygiene sweep in the selection finds it too."
    ),
    "programs/tests/test_issue546_corpus_gates_enumerate_the_commit.py": (
        "creates a git-ignored fixture directory and file INSIDE a scanned "
        "subtree of the shipped tree, deliberately, to prove the corpus gates "
        "enumerate the commit and not the disk."
    ),
    "programs/tests/test_issue559_drift_check_rule_b_blindspot.py": (
        "creates and unlinks programs/<name>.py in the LIVE tree to drive the "
        "drift check against a module that exists only for the duration of "
        "the test."
    ),
    "programs/tests/test_phase2a_gate_contract_check.py": (
        "writes a fake gate into the LIVE programs directory so the contract "
        "check runs against a gate whose shape the test chose."
    ),
    "programs/tests/test_rtl_gen_preserves_authored_rtl.py": (
        "writes a stub generator into the LIVE programs directory, because "
        "the runner under test imports generators by name from there."
    ),
    "programs/tests/test_gds_geometry_signoff_wiring.py": (
        "creates scratch_geom_signoff_tests/ at the REPO ROOT when the "
        "KLayout runner cannot reach pytest's tmp dir; that directory is "
        "inside the tree the write-guard and every hygiene sweep measure."
    ),
    "programs/tests/test_issue630_labels_on_a_layer_the_extractor_reads.py": (
        "unlinks reports/phase3/gds_port_labels.json under a REPO-relative "
        "corpus path, so it mutates the tree rather than a scratch copy."
    ),
}


# ---------------------------------------------------------------------------
# the audit: find live-tree writers by reading the source, not by running it
# ---------------------------------------------------------------------------
def _root_of(node: ast.AST) -> str | None:
    """The leftmost NAME of an attribute/subscript/`/`-chain, or None.

    A CALL deliberately terminates the walk. `LIVE.read_text().splitlines()`
    is rooted at a live path but operates on the STRING the call returned, and
    treating that as a live-tree write is how a static scanner ends up naming
    every reader in the suite.
    """
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
        else:
            return None


class _LiveWriteFinder(ast.NodeVisitor):
    """Collect (lineno, snippet) for every write aimed at the shipped tree.

    Two hops, which is what the suite actually uses:
      1. `_PROGRAMS / "x.py"` written directly;
      2. `g = _PROGRAMS / "x.py"` … `g.write_text(...)`.
    A third hop has never appeared in this corpus; if one does, it shows up as
    a live-tree write the audit does NOT see, which is why the roster is also
    a human-readable declaration and not only a derived set.

    LOCALS ARE SCOPED TO THEIR FUNCTION. The suite reuses short names —
    `plugin`, `probe`, `d`, `p` — for a tmp_path child in one test and for a
    shipped path in another. A file-wide alias set marked eleven readers of
    `tmp_path / "plugin"` as tree writers on the first run of this scanner.
    """

    def __init__(self, source_lines: Sequence[str],
                 aliases: Iterable[str] = (),
                 shadowed: Iterable[str] = ()) -> None:
        self.lines = source_lines
        self.hits: List[Tuple[int, str]] = []
        self._shadowed: set[str] = set(shadowed)
        #: Derived aliases only. The DECLARED roots in `_LIVE_ROOT_NAMES` are
        #: never in here and never cleared: a module writes
        #: `_PROGRAMS = Path(__file__).resolve().parent.parent`, whose value
        #: expression is a Call and therefore reads as "not live" — clearing
        #: the declared name on that line made the scanner blind to every
        #: write in the file, which is how the first version of this module
        #: passed a corpus containing its own planted-defect fixture.
        self._alias: set[str] = set(aliases)

    def _is_live(self, node: ast.AST) -> bool:
        root = _root_of(node)
        if root is None or root in self._shadowed:
            return False
        return root in _LIVE_ROOT_NAMES or root in self._alias

    # A nested scope starts from the enclosing alias set and cannot leak back.
    def _visit_scope(self, node: ast.AST) -> None:
        inner = _LiveWriteFinder(self.lines, self._alias, self._shadowed)
        for child in ast.iter_child_nodes(node):
            inner.visit(child)
        self.hits.extend(inner.hits)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        live = self._is_live(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                # REBINDING TO A NON-LIVE VALUE CLEARS THE ALIAS. `p = _PLUGIN
                # / "x"` then `p = tmp_path / "x"` must not leave `p` live.
                self._alias.discard(target.id)
                if live:
                    self._alias.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in _MUTATORS and self._is_live(func.value):
                self._record(node.lineno)
            elif (func.attr in _SHUTIL_WRITERS
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "shutil"):
                # `copytree(SRC, DST)` writes DST; `rmtree(X)` writes X.
                if func.attr == "rmtree" or func.attr == "make_archive":
                    targets = node.args[:1]
                else:
                    targets = node.args[1:2]
                if any(self._is_live(arg) for arg in targets):
                    self._record(node.lineno)
        self.generic_visit(node)

    def _record(self, lineno: int) -> None:
        text = ""
        if 1 <= lineno <= len(self.lines):
            text = self.lines[lineno - 1].strip()
        self.hits.append((lineno, text[:120]))


#: A module-level root whose VALUE is a temporary directory is not the shipped
#: tree, whatever it is called. `test_hold_corner_liberty_content` binds
#: `_ROOT = Path(tempfile.gettempdir()) / f"vibeic_holdlib_{os.getpid()}"` and
#: then `shutil.rmtree(_ROOT)`, which is a per-pid scratch and safe to run
#: beside anything.
_SCRATCH_MARKERS = ("tempfile", "gettempdir", "mkdtemp", "mkstemp",
                    "TMPDIR", "tmp_path", "tmp_path_factory")


def _shadowed_roots(tree: ast.AST, text: str) -> set:
    """Declared root names that this module rebinds to a temporary directory."""
    shadowed = set()
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if not names & _LIVE_ROOT_NAMES:
            continue
        rhs = ast.get_source_segment(text, node.value) or ""
        if any(marker in rhs for marker in _SCRATCH_MARKERS):
            shadowed |= names & _LIVE_ROOT_NAMES
    return shadowed


def live_tree_writes(path: Path) -> List[Tuple[int, str]]:
    """Every write this test file aims at the shipped tree, by line."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file that will not parse cannot be scheduled either; the pytest
        # session says so far more usefully than this audit would.
        return []
    finder = _LiveWriteFinder(text.splitlines(),
                              shadowed=_shadowed_roots(tree, text))
    finder.visit(tree)
    return sorted(set(finder.hits))


def audit(plugin_root: Path, corpus: Iterable[str]) -> Tuple[bool, List[str]]:
    """(ok, findings). A finding is an unrostered live-tree writer."""
    findings: List[str] = []
    examined = 0
    for rel in corpus:
        path = plugin_root / rel
        if not path.is_file():
            continue
        examined += 1
        hits = live_tree_writes(path)
        if hits and rel not in SERIAL_ONLY:
            where = ", ".join(f"line {n}: {s}" for n, s in hits[:3])
            findings.append(
                f"{rel} writes into the SHIPPED tree ({where}) and is not on "
                f"the serial roster. Concurrently with any whole-tree scanner "
                f"in the same selection this changes that scanner's verdict — "
                f"add it to SERIAL_ONLY with the reason, or make the test "
                f"write into tmp_path instead.")
    if examined == 0:
        raise LookupError(
            "the corpus enumerated ZERO test files — the audit examined "
            "nothing, which is not a pass")
    return (not findings), findings


# ---------------------------------------------------------------------------
# the partition
# ---------------------------------------------------------------------------
def partition(selection: Sequence[str]) -> Tuple[List[str], List[str]]:
    """(serial, parallel), order-preserving, disjoint, and total.

    Total is the property that matters: every selected file lands in exactly
    one group, so the two sessions together still measure the whole selection.
    """
    serial = [f for f in selection if f in SERIAL_ONLY]
    parallel = [f for f in selection if f not in SERIAL_ONLY]
    return serial, parallel


def _read_selection(path: Path) -> List[str]:
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--plugin-root", default=None,
                    help="plugin root (default: this file's parent's parent)")
    ap.add_argument("--selection",
                    help="file listing plugin-relative test paths, one per line")
    ap.add_argument("--audit", action="store_true",
                    help="FAIL when a corpus file writes into the shipped tree "
                         "and is not on the serial roster")
    ap.add_argument("--partition", action="store_true",
                    help="print SERIAL <path> / PARALLEL <path> for --selection")
    a = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    plugin_root = (Path(a.plugin_root).resolve() if a.plugin_root
                   else Path(__file__).resolve().parent.parent)

    if a.partition:
        if not a.selection:
            print("[SKIP] --partition needs --selection", file=sys.stderr)
            return 2
        selection = _read_selection(Path(a.selection))
        if not selection:
            print("[SKIP] the selection is EMPTY — an empty corpus is not a "
                  "partition of anything", file=sys.stderr)
            return 2
        serial, parallel = partition(selection)
        for f in serial:
            print(f"SERIAL {f}")
        for f in parallel:
            print(f"PARALLEL {f}")
        return 0

    if a.audit:
        if a.selection:
            corpus = _read_selection(Path(a.selection))
        else:
            tests = plugin_root / "programs" / "tests"
            corpus = sorted(
                str(p.relative_to(plugin_root))
                for p in tests.glob("test_*.py"))
        try:
            ok, findings = audit(plugin_root, corpus)
        except LookupError as exc:
            print(f"[SKIP] pytest_parallel_policy: {exc}", file=sys.stderr)
            return 2
        if ok:
            print(f"PASS: {len(list(corpus))} corpus file(s) examined; "
                  f"{len(SERIAL_ONLY)} on the serial roster; no unrostered "
                  f"writer into the shipped tree")
            return 0
        for f in findings:
            print(f"[FAIL] {f}")
        print(f"FAIL: {len(findings)} unrostered live-tree writer(s)")
        return 1

    ap.error("choose --audit or --partition")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
