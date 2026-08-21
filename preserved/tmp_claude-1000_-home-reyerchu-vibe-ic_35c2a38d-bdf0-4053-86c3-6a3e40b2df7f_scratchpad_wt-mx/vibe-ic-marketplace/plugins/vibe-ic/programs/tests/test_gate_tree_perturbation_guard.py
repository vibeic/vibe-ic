"""A gate must hand the NEXT gate the tree it was handed.

MEASURED 2026-08-12, on `tools/gatekeeper-land.sh`'s full tier. Three gates in
`repo_hygiene_gates.sh` write into the WORKTREE, and every gate declared after
them measures what they left:

    :678  gate_host_independence_check      re-runs every gate above it IN THE
                                            WORKING CHECKOUT — that is its
                                            subject, so their leavings are its
                                            leavings
    :943  gen_matrix_63x8_census.py --check
    :964  policy_direction_pin_check --verify-pins

One landing run that day reported THREE failures — host-independence, census
freshness, argued-direction-pinned — that a clean uncontended run of the same
tree did not reproduce.

The bracket that would have caught this ALREADY EXISTED, one directory wide:
`_gate_dispatch.sh` has wrapped every gate in a `git status` since #720, scoped
to `benchmark-data/`. `benchmark-data/` is not where these gates write.

WHY THE FALSE-RED IS THE LESS IMPORTANT HALF. A false red costs a re-run and
looks like diligence. The identical mechanism produces a false GREEN whenever
an earlier gate's leavings happen to SATISFY a later gate's question, and
nobody re-runs a green.

Every test here sources the REAL `_gate_dispatch.sh` and drives the REAL
`_dispatch`, for the reason that file's header gives: a fixture copy of the
dispatch code would drift from the code CI runs.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"
_GUARD = _PROGRAMS / "suite_write_guard.py"

#: Every fixture gate returns instantly. This only stops a hung one from taking
#: the pytest session down, and must stay under the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces — above it the bound could never
#: fire as a TEST failure, because pytest kills the session at 180 s first.
_T = 55


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _repo(tmp_path: Path) -> Path:
    """A throwaway repo with one tracked source file and one tracked corpus."""
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "shipped.py").write_text('LITERAL = "richer"\n')
    (r / "benchmark-data").mkdir()
    (r / "benchmark-data" / "kept.txt").write_text("x\n")
    (r / ".gitignore").write_text("__pycache__/\n*.log\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def _run(root: Path, gate_lines: str, *, mode: str = "report",
         record: Path = None):
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    s = root / "tools" / "ci" / "gates.sh"
    s.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    argv = ["bash", str(s)]
    if record is not None:
        argv += ["--summary-json", str(record)]
    env = {"PATH": __import__("os").environ["PATH"],
           "HOME": __import__("os").environ.get("HOME", str(root)),
           "GATE_TREE_GUARD": mode}
    return subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                          timeout=_T, env=env)


def _py(root: Path, name: str, body: str) -> Path:
    p = root / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return p


def _reader(root: Path, name: str = "reader") -> Path:
    """A gate that only READS. The false-positive control for everything here."""
    return _py(root, name, """\
        print('PASS (1 item examined)')
        """)


def _leaver(root: Path, name: str = "leaver", rel: str = "src/left.txt"):
    """A gate that leaves an untracked path — what `git add -A` would ship."""
    return _py(root, name, f"""\
        import pathlib
        pathlib.Path({str(root)!r}, {rel!r}).write_text('leftover\\n')
        print('PASS (1 item examined)')
        """)


def _mutator(root: Path, name: str = "mutator"):
    """A gate with the PIN GATE's shape: flip a shipped literal, measure, put
    it back. Clean at both ends to `git status`, and a mutator throughout."""
    return _py(root, name, f"""\
        import pathlib, time
        p = pathlib.Path({str(root)!r}, 'src/shipped.py')
        orig = p.read_bytes()
        p.write_bytes(orig.replace(b'richer', b'sparser'))
        time.sleep(0.02)
        p.write_bytes(orig)
        print('PASS (1 site examined)')
        """)


# --------------------------------------------------------------------------
# the bug: a gate writes, and the gates after it measure what it wrote
# --------------------------------------------------------------------------
def test_a_gate_that_writes_into_the_source_tree_is_named(tmp_path):
    r = _repo(tmp_path)
    _leaver(r)
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/leaver.py"\n'
                  f'run "the gate after it" "$ROOT" python3 "{_reader(r)}"\n')
    text = out.stdout + out.stderr
    assert "WROTE INTO THE SOURCE TREE" in text, text
    assert "a writer" in text, (
        "the writer is not NAMED. A count cannot tell a reader which gate "
        f"poisoned the tree for everything after it:\n{text}")
    assert "left.txt" in text, ("the guard did not say WHICH path:\n" + text)


def test_the_downstream_gates_are_counted_because_they_are_the_damage(tmp_path):
    """Naming the writer alone lets a reader think the damage is the writer's.

    It is not. The damage belongs to whatever was declared AFTER it, whose
    verdicts are about a tree this run wrote.
    """
    r = _repo(tmp_path)
    _leaver(r)
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/leaver.py"\n'
                  f'run "downstream one" "$ROOT" python3 "{_reader(r, "r1")}"\n'
                  f'run "downstream two" "$ROOT" python3 "{_reader(r, "r2")}"\n')
    text = out.stdout + out.stderr
    assert "2 gate(s) were declared AFTER the first such writer" in text, text
    assert '"a writer"' in text, text


def test_all_gates_passed_is_refused_over_a_tree_the_run_rewrote(tmp_path):
    """#539's rule, applied to the SUBJECT rather than to the population.

    The gates did all pass. They did not all pass over the same tree, and
    "all N passed" is what a reader takes away.
    """
    r = _repo(tmp_path)
    _leaver(r)
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/leaver.py"\n'
                  f'run "after" "$ROOT" python3 "{_reader(r)}"\n')
    text = out.stdout + out.stderr
    assert "WROTE INTO THE SOURCE TREE" in text.split("\n")[-1] or \
        "but 1 of them WROTE INTO THE SOURCE TREE" in text, (
        "the closing sentence stood unqualified over a rewritten tree:\n"
        + text)
    assert "the gates after them did not measure the tree this run was "\
           "handed" in text, text


# --------------------------------------------------------------------------
# the half nothing else in this repo can see: written AND restored
# --------------------------------------------------------------------------
def test_a_write_that_was_reverted_is_still_a_mutation_and_is_named(tmp_path):
    r = _repo(tmp_path)
    _mutator(r)
    out = _run(r, f'run "the pin gate shape" "$ROOT" python3 "{r}/mutator.py"\n')
    text = out.stdout + out.stderr
    assert "MUTATED THE TREE AND PUT IT BACK" in text, (
        "a gate that flipped a shipped literal, ran against it and restored "
        "it was reported as having done nothing. That window is ~23s wide in "
        f"the real pin gate:\n{text}")
    assert "src/shipped.py" in text, text


def test_git_status_cannot_see_it_which_is_why_the_deep_channel_exists(tmp_path):
    """The bidirectional control: the SHALLOW guard — the one this repo already
    shipped and already wraps around the full tier — reports the same event as
    clean. A test that cannot fail against the pre-fix code proves nothing.
    """
    r = _repo(tmp_path)
    _mutator(r)
    shallow, deep = tmp_path / "shallow.json", tmp_path / "deep.json"
    for snap, extra in ((shallow, []), (deep, ["--deep"])):
        subprocess.run(["python3", str(_GUARD), "--repo", str(r),
                        "--snapshot", str(snap)] + extra,
                       check=True, capture_output=True, timeout=_T)
    subprocess.run(["python3", str(r / "mutator.py")], check=True,
                   capture_output=True, timeout=_T)

    def _compare(base):
        return subprocess.run(
            ["python3", str(_GUARD), "--repo", str(r), "--compare", str(base)],
            capture_output=True, text=True, timeout=_T)

    a, b = _compare(shallow), _compare(deep)
    assert "WRITTEN AND RESTORED" not in a.stdout, (
        "the shallow guard claimed to see a reverted write — then this test "
        f"is not measuring the new channel:\n{a.stdout}")
    assert "WRITTEN AND RESTORED" in b.stdout, b.stdout
    assert "src/shipped.py" in b.stdout, b.stdout


def test_deep_against_a_shallow_baseline_refuses_rather_than_answering(tmp_path):
    """"I could not look" must never arrive as "I looked and it was clean"."""
    r = _repo(tmp_path)
    shallow = tmp_path / "shallow.json"
    subprocess.run(["python3", str(_GUARD), "--repo", str(r),
                    "--snapshot", str(shallow)], check=True,
                   capture_output=True, timeout=_T)
    out = subprocess.run(
        ["python3", str(_GUARD), "--repo", str(r), "--compare", str(shallow),
         "--deep"], capture_output=True, text=True, timeout=_T)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "WRITE_GUARD_NOT_CHECKED" in out.stderr, out.stderr


def test_the_rotating_bracket_leaves_the_baseline_for_the_next_stage(tmp_path):
    """`--compare prev --snapshot next` is what makes a per-stage sweep
    affordable: one snapshot per boundary instead of two."""
    r = _repo(tmp_path)
    # OUTSIDE the repo. A snapshot written into the subject is itself a write
    # into the subject, and the guard is right to say so — which is how the
    # first draft of this test failed. `_dispatch` uses `mktemp -t` for the
    # same reason.
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    subprocess.run(["python3", str(_GUARD), "--repo", str(r), "--snapshot",
                    str(a), "--deep"], check=True, capture_output=True,
                   timeout=_T)
    (r / "src" / "one.txt").write_text("1\n")
    first = subprocess.run(
        ["python3", str(_GUARD), "--repo", str(r), "--compare", str(a),
         "--snapshot", str(b)], capture_output=True, text=True, timeout=_T)
    assert first.returncode == 1 and "one.txt" in first.stdout, first.stdout
    assert b.is_file(), "the rotated baseline was not written"
    # The SECOND stage did nothing, and must not inherit the first's finding.
    second = subprocess.run(
        ["python3", str(_GUARD), "--repo", str(r), "--compare", str(b)],
        capture_output=True, text=True, timeout=_T)
    assert second.returncode == 0, (
        "the rotated baseline did not carry stage one's leftovers forward, so "
        f"stage two was blamed for them:\n{second.stdout}")


# --------------------------------------------------------------------------
# false-positive controls — a gate that reads must never be named
# --------------------------------------------------------------------------
def test_a_read_only_gate_is_never_named(tmp_path):
    r = _repo(tmp_path)
    out = _run(r, f'run "reads only" "$ROOT" python3 "{_reader(r)}"\n')
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    for phrase in ("WROTE INTO THE SOURCE TREE", "MUTATED THE TREE",
                   "NOT ACTIVE"):
        assert phrase not in text, (
            f"a read-only gate was reported as {phrase!r}:\n{text}")


def test_regenerable_cache_artefacts_do_not_fail_a_gate(tmp_path):
    """`__pycache__` churn is universal and harmless, and a gate that fires on
    every run in every checkout is a gate people learn to route around."""
    r = _repo(tmp_path)
    _py(r, "cacher", f"""\
        import pathlib
        d = pathlib.Path({str(r)!r}, '__pycache__')
        d.mkdir(exist_ok=True)
        (d / 'x.pyc').write_bytes(b'\\x00')
        print('PASS (1 item examined)')
        """)
    out = _run(r, f'run "makes bytecode" "$ROOT" python3 "{r}/cacher.py"\n',
               mode="block")
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert "WROTE INTO THE SOURCE TREE" not in text, text


def test_a_developers_pre_existing_edit_is_not_blamed_on_a_gate(tmp_path):
    """The baseline is the tree as the gate was handed it, never an empty tree."""
    r = _repo(tmp_path)
    (r / "src" / "shipped.py").write_text('LITERAL = "edited in flight"\n')
    out = _run(r, f'run "reads only" "$ROOT" python3 "{_reader(r)}"\n',
               mode="block")
    text = out.stdout + out.stderr
    assert out.returncode == 0, (
        "an edit that pre-dated the run was attributed to a gate:\n" + text)
    assert "WROTE INTO THE SOURCE TREE" not in text, text


# --------------------------------------------------------------------------
# prove-by-run: a gate declared BLOCKING actually stops the flow
# --------------------------------------------------------------------------
def test_block_mode_fails_the_run_and_report_mode_does_not(tmp_path):
    r = _repo(tmp_path)
    _leaver(r)
    line = f'run "a writer" "$ROOT" python3 "{r}/leaver.py"\n'

    reported = _run(r, line, mode="report")
    assert reported.returncode == 0, (
        "report mode changed a verdict — then it is not a report:\n"
        + reported.stdout + reported.stderr)
    assert "reported, NOT blocking" in reported.stdout + reported.stderr

    (r / "src" / "left.txt").unlink()
    blocked = _run(r, line, mode="block")
    assert blocked.returncode == 1, (
        "GATE_TREE_GUARD=block did not stop the run. A gate declared BLOCKING "
        "that does not block is the defect this repo removes from gates one "
        f"at a time:\n{blocked.stdout}{blocked.stderr}")


def test_off_announces_itself_because_a_silent_guard_is_a_vacuous_pass(tmp_path):
    r = _repo(tmp_path)
    _leaver(r)
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/leaver.py"\n',
               mode="off")
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert "WROTE INTO THE SOURCE TREE" not in text, text


# --------------------------------------------------------------------------
# the declared mutator
# --------------------------------------------------------------------------
def test_a_declared_mutator_is_still_named_but_does_not_fail_the_run(tmp_path):
    """Declaring it does not make it safe, and the log must not imply it does.

    What the declaration buys is that the perturbation is a reviewed fact with
    an owner — and that THAT set, which is small and visible, is the one worth
    giving its own checkout, rather than every gate paying for a checkout
    because nobody knows which ones need it.
    """
    r = _repo(tmp_path)
    _leaver(r, "declared")
    out = _run(r,
               f'run_mutating_the_tree "its subject is the tree" "$ROOT" '
               f'python3 "{r}/declared.py"\n', mode="block")
    text = out.stdout + out.stderr
    assert out.returncode == 0, (
        "a DECLARED mutator failed the run — then the declaration does "
        f"nothing and nobody will use it:\n{text}")
    assert "DECLARED via run_mutating_the_tree" in text, text
    assert "the gates after it do not read the tree it was handed" in text, (
        "the declared case was silent about the consequence, which is the "
        f"same consequence:\n{text}")


def test_the_new_wrapper_is_visible_to_the_parsers_that_read_this_script(tmp_path):
    """Two programs parse the gate script for `run(?:_\\w+)?` lines. A wrapper
    they cannot see is a gate that vanishes from the host-independence sweep
    and from the denominator audit.
    """
    import re
    pat = re.compile(r'^\s*run(?:_\w+)?\s')
    assert pat.match('run_mutating_the_tree "x" "$ROOT" python3 y.py')
    src = _LIB.read_text()
    assert "run_mutating_the_tree()" in src, (
        "the wrapper is not defined in the dispatcher")


def test_the_guard_is_found_from_the_library_not_from_the_subject(tmp_path):
    """`$ROOT` is the SUBJECT — a fixture repo, a scratch worktree — and a
    subject is not required to ship the instrument that measures it. Keying on
    it would make the guard silently absent for every fixture.
    """
    r = _repo(tmp_path)
    assert not (r / "vibe-ic-marketplace").exists()
    _leaver(r)
    out = _run(r, f'run "a writer" "$ROOT" python3 "{r}/leaver.py"\n')
    text = out.stdout + out.stderr
    assert "NOT ACTIVE" not in text, (
        "the guard could not find itself from a subject that does not ship "
        f"it:\n{text}")
    assert "WROTE INTO THE SOURCE TREE" in text, text


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------
def test_the_gate_that_wrote_still_records_its_own_verdict(tmp_path):
    """Perturbing the tree and failing your own question are independent. A
    gate can do either, both or neither, and collapsing them loses which."""
    r = _repo(tmp_path)
    _leaver(r)
    rec = tmp_path / "record.json"
    out = _run(r, f'run "a writer that passes" "$ROOT" python3 "{r}/leaver.py"\n',
               record=rec)
    data = json.loads(rec.read_text())
    states = {g["label"]: g["state"] for g in data["gates"]}
    assert states["a writer that passes"] == "PASS", (
        "the write overwrote the gate's own verdict in the record:\n"
        f"{states}\n{out.stdout}{out.stderr}")


# --------------------------------------------------------------------------
# isolation — the user's instinct, priced and bounded
# --------------------------------------------------------------------------
def test_an_isolated_mutator_leaves_the_shared_tree_untouched(tmp_path):
    """The two arms of the fix, on one fixture.

    ARM 1: the declared mutator runs in the shared tree and leaves its artefact
           there, where every gate after it will read it.
    ARM 2: the same gate, the same command, isolated — and the shared tree is
           byte-identical afterwards.
    """
    r = _repo(tmp_path)
    _leaver(r, "declared", "src/left.txt")
    line = (f'run_mutating_the_tree "declared mutator" "$ROOT" '
            f'python3 "{r}/declared.py"\n')

    a = _run(r, line, mode="report")
    assert (r / "src" / "left.txt").exists(), (
        "arm 1 did not construct the contamination, so arm 2 proves nothing:\n"
        + a.stdout + a.stderr)
    (r / "src" / "left.txt").unlink()

    env = {"GATE_TREE_ISOLATE": "1"}
    import os as _os
    s = r / "tools" / "ci" / "gates.sh"
    b = subprocess.run(
        ["bash", str(s)], cwd=str(r), capture_output=True, text=True,
        timeout=_T,
        env={"PATH": _os.environ["PATH"],
             "HOME": _os.environ.get("HOME", str(r)),
             "GATE_TREE_GUARD": "report", **env})
    text = b.stdout + b.stderr
    assert "isolated: running in a throwaway checkout" in text, text
    assert not (r / "src" / "left.txt").exists(), (
        "the gate wrote into the shared tree despite isolation — the "
        f"substitution did not reach its paths:\n{text}")
    assert "WROTE INTO THE SOURCE TREE" not in text, text


def test_isolation_that_could_not_be_obtained_says_so(tmp_path):
    """"I asked for isolation" must never be indistinguishable from "I got it".

    A non-repository cannot produce a worktree, and the gate then runs in the
    shared tree exactly as it would have without the flag — which is safe only
    because it is LOUD.
    """
    r = tmp_path / "notarepo"
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "src").mkdir()
    _leaver(r, "declared", "src/left.txt")
    s = r / "tools" / "ci" / "gates.sh"
    s.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{r}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        run_mutating_the_tree "m" "$ROOT" python3 "{r}/declared.py"
        gate_dispatch_finish
        """))
    import os as _os
    out = subprocess.run(
        ["bash", str(s)], cwd=str(r), capture_output=True, text=True,
        timeout=_T,
        env={"PATH": _os.environ["PATH"],
             "HOME": _os.environ.get("HOME", str(r)),
             "GATE_TREE_GUARD": "report", "GATE_TREE_ISOLATE": "1"})
    assert "ISOLATION ASKED FOR AND NOT OBTAINED" in out.stdout + out.stderr, (
        out.stdout + out.stderr)


# --------------------------------------------------------------------------
# the landing gate's own full tier
# --------------------------------------------------------------------------
_LAND = _REPO / "tools" / "gatekeeper-land.sh"


def test_every_full_tier_stage_is_bracketed():
    """The tier's existing guard is taken around the WHOLE window, which can
    answer "did the tier write" and not "which stage" — and only the second
    form is actionable, because the damage is that every stage AFTER the writer
    measured what it left.

    Wiring is asserted statically for the reason `gate_is_wired_check` exists:
    running the tier to find out costs ~57 min, so nobody would run it, so the
    wiring would rot.
    """
    src = _LAND.read_text()
    tier = src.split("--- full tier", 1)[1]
    for stage in ("targeted tests", "repo hygiene gates", "plugin full audit"):
        assert (f'stage "{stage}"' in tier
                or f'stage_bracket "{stage}"' in tier), (
            f"full-tier stage {stage!r} is not bracketed, so a write it makes "
            f"is attributed to nothing:\n{tier[:400]}")
    assert "--deep" in tier, (
        "the tier's per-stage bracket does not ask for the reverted channel, "
        "and two of the three known writers put the tree back")


def test_the_per_stage_bracket_is_a_report_not_a_second_refusal():
    """The tier already refuses a write via `--compare "$WG_BASE"`. Stating the
    same refusal twice would fail one landing twice for one cause; what was
    missing was never the refusal, it was the ATTRIBUTION."""
    src = _LAND.read_text()
    body = src.split("stage_bracket() {", 1)[1].split("\n}", 1)[0]
    assert "FAILED=1" not in body, (
        "the per-stage bracket sets the run's failure flag, duplicating the "
        f"whole-tier refusal below it:\n{body}")
    assert "REPORT" in body, body
