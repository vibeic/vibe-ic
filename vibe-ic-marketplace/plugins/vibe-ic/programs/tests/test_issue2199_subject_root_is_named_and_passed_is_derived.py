"""vibe-ic#2199 — a gate that was not told what to measure must SAY SO, and a
published record must never disagree with the process's own exit code.

TWO DEFECTS, ONE SHAPE: OUTPUT THAT LOOKS ENTIRELY NORMAL
=========================================================
A gate that REFUSES is found the same day, because somebody is blocked. These
two did the opposite, which is how they survived in a tier that runs daily.

A. THREE GATES MEASURED THE INSTRUMENT.  `tools/ci/repo_hygiene_gates.sh`
   passed no subject root to `checker_execution_wiring_audit`,
   `gate_is_wired_check` or `hdl_declaration_scan_strips_comments_check`, and
   all three defaulted to a tree derived from their own `__file__`. Where the
   subject and the runtime are the same directory that is invisible. Where they
   differ — the fresh-worktree hygiene shape of #2008, an A/B base arm, every
   subject `gate_mutation_fixtures.invoke` builds — each one measured the
   instrument's tree and published the answer as a verdict about the subject.

   MEASURED on 8HD-4 at a61a8e4b4778 (tree 1de1e0882fec), two full clones, the
   subject carrying ONE extra program that is unwired and scans an HDL
   declaration over unstripped text, cwd = the subject in every arm:

       gate_is_wired_check      no --root : unwired 37 (baseline 37)   [PASS] rc 0
                                --root S  : unwired 38 (baseline 37)   [FAIL] rc 1
       hdl_declaration_scan     no --root : 159 sites, 2 new offenders       rc 1
                                --root S  : 160 sites, 3 new offenders       rc 1
       checker_execution_wiring no --root : the marker absent from the finding set
                                --root S  : the marker named in it

   `gate_is_wired_check` printed the runtime's path in its own "wiring sources"
   disclosure line while doing it. The evidence was on the screen and read as
   normal, which is the whole argument for a REFUSAL over a default: "I was not
   told what to measure" cannot be mistaken for a clean tree.

B. A HARD-CODED PASS.  `checker_execution_wiring_audit.audit()` returned
   `"passed": True` as a LITERAL and `main` dumped that record BEFORE computing
   the verdict. MEASURED on the same base tree with no synthetic input at all:
   rc 1, `[FAIL] 1 checker(s) that NOTHING but their own test runs`, and
   `"passed": true` in the JSON beside it. A consumer reading the record rather
   than the rc saw a pass.

WHAT THIS FILE PINS, AND IN BOTH DIRECTIONS
===========================================
Every arm below is written so that RESTORING the defect turns it red, not so
that today's tree happens to satisfy it:

  * the refusal arms drive each gate with NO subject and demand rc 2 — putting
    back `else Path(__file__)...` makes each of them go green-and-answer, which
    is the failure;
  * the structural arms refuse the `__file__` expression in the subject
    resolution itself, so a default that is restored WITH a refusal message
    still fails;
  * the redirect arms prove the argument reaches the subject resolution by
    naming a subject the gate cannot read and demanding that PATH in the
    refusal — a gate that quietly audits its own tree would answer instead;
  * the record arm drives four distinct outcomes (rc 0, rc 1 and two different
    rc 2s) through one `--json` path and demands `passed == (rc == 0)` every
    time, INCLUDING the rewrite of a stale PASS record by a later refusal;
  * the literal arm is structural: no `"passed"` key in the module may be
    assigned a constant, so re-introducing the literal is red whatever the
    surrounding control flow does.

chip-AGNOSTIC: gate plumbing only. No design, PDK, vendor or host literal.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent

#: `(module, subject flag, the name `main` binds the subject to)`. The third
#: field is what the structural arm walks: a gate may legitimately touch
#: `__file__` for its own baseline, so the refusal is scoped to the assignment
#: that decides WHAT IS MEASURED.
GATES = (
    ("checker_execution_wiring_audit", "--repo-root", "root"),

    ("hdl_declaration_scan_strips_comments_check", "--root", "root"),
)
_IDS = [g[0] for g in GATES]


def _run(module: str, *argv: str, cwd: Path = None):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / f"{module}.py"), *argv],
        capture_output=True, text=True, check=False,
        cwd=str(cwd) if cwd else None)


def _main_of(module: str) -> ast.FunctionDef:
    tree = ast.parse((PROGRAMS / f"{module}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError(f"{module} has no module-level main()")


# ───────────────────────────────────────────────────────────────────────────
# A — the subject
# ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("module,flag,_var", GATES, ids=_IDS)
def test_a_gate_not_told_what_to_measure_refuses(module, flag, _var):
    """No subject root -> rc 2 and a refusal that names the flag. NOT a pass.

    Driven from the repository root as cwd, which is the one place a restored
    `__file__` default would look most plausible: the tree it would audit is a
    real one and its answer would read as a normal verdict.
    """
    got = _run(module, cwd=PLUGIN.parents[2])
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, (
        f"{module} answered rc {got.returncode} for a subject nobody named. "
        f"A gate with no subject has no verdict to reach.\n{transcript}")
    assert "CANNOT DETERMINE" in transcript, transcript
    assert flag in transcript, (
        f"the refusal must name the argument that would fix it\n{transcript}")
    assert "2199" in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, (
        f"{module} reached a verdict without a subject\n{transcript}")


@pytest.mark.parametrize("module,flag,_var", GATES, ids=_IDS)
def test_the_named_subject_is_the_one_that_is_read(module, flag, _var,
                                                   tmp_path):
    """The refusal for an unreadable subject names THAT path, not its own.

    The cheapest total proof that the argument reaches the subject resolution:
    a gate still holding a `__file__` fallback would find its own perfectly
    readable tree here and answer about it, so this arm is red for exactly the
    substitution #2199 is about, whatever the refusal text says.
    """
    empty = tmp_path / "a-tree-with-no-plugin-in-it"
    empty.mkdir()
    got = _run(module, flag, str(empty), cwd=PLUGIN.parents[2])
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert str(empty) in transcript, (
        f"{module} was handed {empty} and its refusal does not name it — it "
        f"resolved some other tree.\n{transcript}")
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


def _file_derived_names(fn: ast.FunctionDef) -> set:
    """Locals in `fn` whose value came, directly or by alias, from `__file__`.

    ALIASES ARE THE WHOLE POINT, and this arm was written without them first.
    MEASURED against the mutation that restores the defect in
    `checker_execution_wiring_audit`: the fallback there does not name
    `__file__`, it names `here`, which was bound to `Path(__file__).resolve()`
    two lines earlier. A one-hop text check read that as clean and the arm
    passed on a tree carrying the exact defect it exists to refuse. The
    behavioural arms above caught it; this one did not, and a structural arm
    that only catches the naive spelling is worth less than its docstring
    claims.
    """
    tainted = set()
    for _ in range(6):                      # a fixpoint; six hops is generous
        grew = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            src = ast.unparse(node.value)
            if "__file__" not in src and not any(
                    n in {x.id for x in ast.walk(node.value)
                          if isinstance(x, ast.Name)} for n in tainted):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id not in tainted:
                    tainted.add(t.id)
                    grew = True
        if not grew:
            break
    return tainted


@pytest.mark.parametrize("module,_flag,var", GATES, ids=_IDS)
def test_no_file_derived_default_decides_the_subject(module, _flag, var):
    """Structural: nothing `__file__`-derived may be assigned to the subject.

    The behavioural arms above are the primary proof. This one closes the door
    they leave open — a default restored TOGETHER WITH a refusal branch that is
    never reached would satisfy them and re-arm the defect.
    """
    fn = _main_of(module)
    tainted = _file_derived_names(fn) - {var}
    offenders = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == var
                   for t in node.targets):
            continue
        names = {x.id for x in ast.walk(node.value) if isinstance(x, ast.Name)}
        if "__file__" in ast.unparse(node.value) or (names & tainted):
            offenders.append(f"line {node.lineno}: {ast.unparse(node)[:120]}"
                             + (f"   (via {sorted(names & tainted)})"
                                if names & tainted else ""))
    assert not offenders, (
        f"{module}.main resolves its SUBJECT from its own location:\n  "
        + "\n  ".join(offenders)
        + "\n\nA gate that substitutes the instrument's tree for the subject's "
          "answers confidently about a tree nobody asked about (vibe-ic#2199). "
          "The correct answer to 'I was not told what to measure' is a "
          "refusal, not a cleverer default.")


def test_the_wiring_audit_does_not_fall_back_to_its_own_plugin():
    """The SECOND door in the same code path: `_resolve`.

    It used to answer `Path(__file__).resolve().parent.parent` whenever the
    NAMED root carried no plugin layout — so a caller that did name a subject,
    and named one this program could not read, was answered about the
    instrument instead of being told. Same substitution, different door.
    """
    src = ast.parse(
        (PROGRAMS / "checker_execution_wiring_audit.py").read_text(
            encoding="utf-8"))
    fn = next(n for n in src.body
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve")
    # THE CODE, NOT THE PROSE. The docstring is where the removed fallback is
    # NAMED, and reading it would make this arm red for saying what it fixed.
    statements = [n for n in fn.body
                  if not (isinstance(n, ast.Expr)
                          and isinstance(n.value, ast.Constant)
                          and isinstance(n.value.value, str))]
    body = "\n".join(ast.unparse(n) for n in statements)
    assert "__file__" not in body, (
        "checker_execution_wiring_audit._resolve falls back to its own "
        f"location:\n{body}")


# ───────────────────────────────────────────────────────────────────────────
# B — the record and the exit code
# ───────────────────────────────────────────────────────────────────────────
_AUDIT = "checker_execution_wiring_audit"


def _subject_tree(root: Path) -> Path:
    """A minimal repository holding ONE checker that only its own test runs."""
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for rel in ("programs/tests", "flow", "skills", "agents", "commands",
                "tests"):
        (plugin / rel).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(exist_ok=True)
    (plugin / "programs" / "sample_check.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8")
    (plugin / "programs" / "tests" / "test_sample_check.py").write_text(
        "import sample_check\n", encoding="utf-8")
    return root


def _record(path: Path):
    assert path.is_file(), f"no record was written at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_published_record_and_the_exit_code_cannot_disagree(tmp_path):
    """Four distinct outcomes through one `--json` path; `passed == (rc == 0)`.

    Not "they agree today": each arm reaches a DIFFERENT branch of `main` —
    a verdict PASS, a verdict FAIL, a refusal before the subject is known and a
    refusal after it is — and the record is demanded of all four. An exit that
    forgets to route through the writer leaves a stale record, which the last
    arm is written to catch.
    """
    subject = _subject_tree(tmp_path / "subject")
    out = tmp_path / "record.json"
    baseline = tmp_path / "baseline.json"

    # rc 0 — the recorded debt is exactly what the tree owes.
    baseline.write_text(json.dumps({"known": ["sample_check.py"]}),
                        encoding="utf-8")
    got = _run(_AUDIT, "--repo-root", str(subject), "--baseline",
               str(baseline), "--json", str(out))
    assert got.returncode == 0, got.stdout + got.stderr
    assert _record(out)["passed"] is True, _record(out)

    # rc 1 — the same tree against a register that does not record it.
    baseline.write_text(json.dumps({"known": []}), encoding="utf-8")
    got = _run(_AUDIT, "--repo-root", str(subject), "--baseline",
               str(baseline), "--json", str(out))
    assert got.returncode == 1, got.stdout + got.stderr
    rec = _record(out)
    assert rec["passed"] is False, (
        "the process exited 1 and its own record says it passed — the exact "
        f"defect of vibe-ic#2199\n{rec}")
    assert "sample_check.py" in rec["test_only"], rec

    # rc 2 AFTER a PASS, same path — a refusal must REWRITE the record it
    # inherits, or the disagreement simply arrives one run later.
    baseline.write_text(json.dumps({"known": ["sample_check.py"]}),
                        encoding="utf-8")
    assert _run(_AUDIT, "--repo-root", str(subject), "--baseline",
                str(baseline), "--json", str(out)).returncode == 0
    assert _record(out)["passed"] is True
    got = _run(_AUDIT, "--json", str(out))          # no subject at all
    assert got.returncode == 2, got.stdout + got.stderr
    assert _record(out)["passed"] is False, (
        "a refusal left the previous run's PASS record on disk\n"
        f"{_record(out)}")

    # rc 2 — a baseline that states no readable measurement.
    unreadable = tmp_path / "truncated.json"
    unreadable.write_text('{"known": [', encoding="utf-8")
    got = _run(_AUDIT, "--repo-root", str(subject), "--baseline",
               str(unreadable), "--json", str(out))
    assert got.returncode == 2, got.stdout + got.stderr
    assert _record(out)["passed"] is False, _record(out)


def test_passed_is_never_written_as_a_literal():
    """Structural: no `"passed"` in this module may be a constant.

    Covers both spellings the defect can take — the key inside a dict display
    (`{..., "passed": True}`, which is how it shipped) and a later
    `rep["passed"] = True`. The behavioural arm above proves the value is right
    on four paths; this one proves it cannot be ASSERTED on any.
    """
    src = (PROGRAMS / f"{_AUDIT}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == "passed"
                        and isinstance(value, ast.Constant)):
                    offenders.append(
                        f"line {node.lineno}: a dict literal maps 'passed' to "
                        f"{value.value!r}")
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "passed"):
                    offenders.append(
                        f"line {node.lineno}: {ast.unparse(node)[:100]}")
    assert not offenders, (
        "a verdict written as a constant cannot disagree with itself, but it "
        "can disagree with the process:\n  " + "\n  ".join(offenders)
        + "\n\nDerive it from the exit code (vibe-ic#2199).")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
