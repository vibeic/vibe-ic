"""`plugin self-audit` — a changelog metric no source in the tree computes.

THE MUTATION IS THE ESCAPE THE DISPATCHER WAS WRITTEN FOR. Its own header
names it: the v1.6.37 release shipped CHANGELOG numerics that "don't trace back
to source". So the subject's CHANGELOG quotes a margin in mV, and the two trees
differ in that number alone — in one it is the value the subject's emitter
actually reports, in the other it is a value nothing in the tree computes.

WHY THE DECLARED REASON IS THE DISPATCHER'S OWN LINE AND NOT THE FINDING'S
RULE NAME. This gate's executable is `run_plugin_self_audit.sh`, and what it
contributes over the seven checkers it calls — several of which carry their own
fixtures in this directory — is the AGGREGATION: a non-zero status from any one
of them has to survive the loop and become the lane's verdict. `gate(s) FAILed`
is printed only by that script and only on its failure branch, so a refusal
carrying it is the dispatcher refusing, not a checker's output passing through.

THE SUBJECT CARRIES THE CHECKERS, and it has no choice: the script reads them
out of `$PLUGIN_ROOT/programs`, which the declaration binds to the same
argument as the tree under audit. They are COPIED from the shipped
`programs/` — byte for byte, at build time — rather than written here, because
a hand-made stand-in would make this fixture a test of itself. The set copied
is the IMPORT CLOSURE, not the seven names: `source_chip_agnostic_check`
imports `_commercial_pdk` inside a function, so a scan of top-level imports
reports it as standard-library-only and the copy then dies of
ModuleNotFoundError, which the dispatcher reports as a gate FAILING. A subject
that refuses for a missing module has been shown nothing about the mutation.

BOTH TREES ARE OTHERWISE IDENTICAL: same dispatcher, same checkers, same
emitter, same CHANGELOG down to the quoted command. Only the number moves, and
`test_gate_fixture_plugin_self_audit.py` measures that: six of the seven
dispatched gates return the same block of output in both arms, and the seventh
is the one the mutation names.

ONE OF THE SEVEN IS VACUOUS HERE, SAID PLAINLY.
`self_audit_doc_claim_consistency_check` reports `VACUOUS_PASS: no
1st_benchmark_*/ tree on this host` in both directions. It computes its repo
root as `plugin_root.parent.parent.parent`, which under this declaration walks
OUT of the subject into the scratch directory's ancestors, so no fixture can
give it a population without writing outside its own subject — and it is a
`can_pass` that would be reaching for it, not a `can_fail`. The other six all
report a non-zero denominator (`9 source file(s)`, `8 file(s) scanned`, `1
metric(s)`, `1 quoted command(s)`, `9 python file(s)`), so this pair is not a
green over an empty tree.
"""
from pathlib import Path
import ast
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "plugin self-audit"

_DISPATCHER_REL = "tools/ci/run_plugin_self_audit.sh"

#: The gates `run_plugin_self_audit.sh` dispatches, in its own two arrays.
#: Read from the script rather than restated, so a gate added to it cannot
#: leave this fixture quietly running the old set.
def _dispatched_checkers() -> list:
    text = (F.REPO_ROOT / _DISPATCHER_REL).read_text(encoding="utf-8")
    out, inside = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("GATES=(") or stripped.startswith("GATES_ROOT_FLAG=("):
            inside = True
            continue
        if inside:
            if stripped == ")":
                inside = False
                continue
            if stripped.startswith('"') and stripped.endswith('"'):
                out.append(stripped.strip('"'))
    return out


def _import_closure(names) -> list:
    """`names` plus every `programs/`-local module they import, transitively.

    Walked with `ast` rather than grepped for a top-level `import` line,
    because the one dependency in this set is imported inside a function body.
    """
    seen, queue = set(), list(names)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        src = F.PROGRAMS / f"{name}.py"
        if not src.is_file():
            continue
        seen.add(name)
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                queue.append(node.module.split(".")[0])
    return sorted(seen)


#: An emitter with an honest failure mode: the tool's status is read, a missing
#: count is refused rather than defaulted, and the only numeric it reports is
#: the one the CHANGELOG quotes back at it.
_EMITTER = '''"""A synthetic emitter, the one program in this subject's tree."""
import json
import subprocess
import sys

#: The single measured quantity this emitter reports.
NOMINAL_MARGIN_MV = 12.5


def emit(out_path, tool_log):
    rc = subprocess.run(["true"], capture_output=True).returncode
    if rc != 0:
        verdict, count = "TOOL_FAILED", None
    else:
        count = _count_from(tool_log)
        verdict = "PASS" if count == 0 else "FAIL"
    with open(out_path, "w") as fh:
        json.dump({"verdict": verdict, "violations": count,
                   "margin_mv": NOMINAL_MARGIN_MV}, fh)
    return 0


def _count_from(tool_log):
    with open(tool_log) as fh:
        for line in fh:
            if line.startswith("violations="):
                return int(line.split("=", 1)[1])
    raise SystemExit("no violation count in the tool log")


if __name__ == "__main__":
    sys.exit(emit(sys.argv[1], sys.argv[2]))
'''

#: `12.5` is `NOMINAL_MARGIN_MV` above; `98.7` is computed nowhere in the
#: subject. `test_the_mutated_number_is_absent_from_the_subject_corpus` in
#: `test_gate_fixture_plugin_self_audit.py` measures that second claim rather
#: than asserting it, because the corpus includes the seven copied checkers.
_TRUE_MARGIN = "12.5"
_FABRICATED_MARGIN = "98.7"

_CHANGELOG = '''# Changelog

## [synthetic] — the changelog this subject is audited against

Run the audit:

```
$ bash tools/ci/run_plugin_self_audit.sh
```

The emitter reports a margin of {margin} mV.
'''


def _tree(work: Path, margin: str) -> Path:
    root = work / "subject"
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (root / _DISPATCHER_REL).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(F.REPO_ROOT / _DISPATCHER_REL, root / _DISPATCHER_REL)
    for name in _import_closure(_dispatched_checkers()):
        shutil.copyfile(F.PROGRAMS / f"{name}.py", programs / f"{name}.py")
    # `source_chip_agnostic_check` reads its vendor deny list from
    # `programs/tests/chip_deny_list.txt`, resolved beside itself. A plugin
    # tree that ships the checker ships the list, so the subject does too.
    #
    # MEASURED on 6c798ce4b, with the checker copied and the list left out: it
    # reported `FAIL: 4074 forbidden-token occurrence(s)` over a two-file tree,
    # crediting TWO hits to a file whose entire content is `x = 1`, each with
    # `"token": ""`. An empty deny list compiles to an alternation that matches
    # at every position. That is a defect in the checker — its own loader
    # comment says a missing list means "the gate reports PASS" — and it is NOT
    # this fixture's to fix; the fixture avoids it by presenting a COMPLETE
    # subject rather than by tolerating an incomplete one.
    (programs / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(F.PROGRAMS / "tests" / "chip_deny_list.txt",
                    programs / "tests" / "chip_deny_list.txt")
    (programs / "synthetic_report_emit.py").write_text(_EMITTER, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(_CHANGELOG.format(margin=margin),
                                       encoding="utf-8")
    # `run_plugin_self_audit.sh` exits 2 outside a git work tree, before it
    # reaches any gate. rc 2 is "the question could not be put", not a verdict,
    # so the subject is made a work tree rather than allowed to produce one.
    subprocess.run(["git", "init", "-q", "."], cwd=str(root), check=True)
    return root


def can_pass(work: Path) -> Path:
    """Every quoted number traces to the source of this tree."""
    return _tree(work, _TRUE_MARGIN)


def can_fail(work: Path):
    """The same tree, quoting a margin nothing in it computes."""
    return _tree(work, _FABRICATED_MARGIN), "gate(s) FAILed"
