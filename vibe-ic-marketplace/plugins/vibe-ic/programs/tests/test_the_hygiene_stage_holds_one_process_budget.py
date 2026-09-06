"""vibe-ic#2072 — the hygiene stage's fan-out is a QUEUE at one budget.

Three layers each picked a width and nobody multiplied them out:
`tools/gatekeeper-land.sh` capped the LANDING path at 8, this stage took a CLI
default of 8 and launched `jobs * 2` shards at once, and every shard was a
fresh `repo_hygiene_gates.sh` that re-defaulted at `tools/ci/_gate_dispatch.sh`
to 8 more.  8 x 2 x 8 = 128.  MEASURED on 8HD-4 (32 cores) at v1.18.35 from a
host at load1 5.05: 108 concurrent dispatch-side processes and load1 96.3,
where the landing path at the same tree holds 8.

These cases hold the three properties that make the product arithmetic:

  * the budget comes from ONE source, in a stated order, and a malformed knob
    is refused rather than guessed at;
  * every env that launches a gate-executing shard carries the forward, so a
    shard cannot re-default to a width of its own;
  * the pool is the budget and not a multiple of it, and every shard the plan
    produced is still submitted to it.

That the shard READS the forwarded knob is measured separately and already
shipped: `tools/ci/test_gate_concurrency.sh` — "GATEKEEPER_HYGIENE_JOBS bounds
concurrency exactly (measured at 2, 3 and 8)".

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
SOURCE = PROGRAMS / "repo_hygiene_parallel.py"
spec = importlib.util.spec_from_file_location(
    "_hygiene_stage_budget", SOURCE)
assert spec and spec.loader
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

ROOT = PROGRAMS.parents[3]
DISPATCH = ROOT / "tools" / "ci" / "_gate_dispatch.sh"
LANDING = ROOT / "tools" / "gatekeeper-land.sh"

#: The env that launches a shard is the env that carries an attestation file:
#: a shard is exactly the thing that executes gates and records them.  The
#: `--list` call deliberately POPS this key and is therefore not a shard.
SHARD_MARK = "GATE_DISPATCH_ATTESTATION_FILE"


def _module_tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))


# --- ONE SOURCE, IN A STATED ORDER -----------------------------------------

def test_an_unset_knob_puts_the_stage_at_the_landing_paths_own_width(
        monkeypatch):
    monkeypatch.delenv(P.JOBS_ENV, raising=False)
    assert P.stage_process_budget() == P.DEFAULT_JOBS


@pytest.mark.skipif(not DISPATCH.is_file(), reason="dispatcher not in tree")
def test_the_stage_default_is_the_same_number_the_dispatcher_defaults_to():
    """Not "both happen to be 8" — the same number, checked across the files.

    A stage whose fallback drifts from the dispatcher's is #2072 again with a
    different constant, and nothing else in the tree compares the two.
    """
    text = DISPATCH.read_text(encoding="utf-8")
    hits = re.findall(
        r'GATE_DISPATCH_JOBS="\$\{' + P.JOBS_ENV + r':-(\d+)\}"', text)
    assert hits, f"{DISPATCH} no longer defaults {P.JOBS_ENV} in a readable form"
    assert {int(h) for h in hits} == {P.DEFAULT_JOBS}


@pytest.mark.skipif(not LANDING.is_file(), reason="landing script not in tree")
def test_the_stage_default_is_the_same_number_the_landing_path_budgets():
    text = LANDING.read_text(encoding="utf-8")
    hits = re.findall(
        r'budget="\$\{' + P.JOBS_ENV + r':-(\d+)\}"', text)
    assert hits, f"{LANDING} no longer budgets {P.JOBS_ENV} in a readable form"
    assert {int(h) for h in hits} == {P.DEFAULT_JOBS}


def test_the_environment_is_read_and_beats_the_module_default(monkeypatch):
    monkeypatch.setenv(P.JOBS_ENV, "3")
    assert P.stage_process_budget() == 3
    assert P.stage_process_budget() != P.DEFAULT_JOBS


def test_an_explicit_jobs_beats_the_environment(monkeypatch):
    monkeypatch.setenv(P.JOBS_ENV, "3")
    assert P.stage_process_budget(5) == 5


@pytest.mark.parametrize("bad", ["eight", "0", "-1", "2.5", " ", "8x", "1 2"])
def test_a_malformed_knob_is_refused_and_never_rounded(monkeypatch, bad):
    """The dispatcher refuses "to guess how much of this run to parallelise".

    A stage that guessed where the dispatcher refuses would reintroduce the
    divergence by the back door, so it refuses in the same direction.
    """
    monkeypatch.setenv(P.JOBS_ENV, bad)
    with pytest.raises(P.BudgetRefused):
        P.stage_process_budget()


def test_an_empty_knob_is_absent_and_not_malformed(monkeypatch):
    """`FOO=` is how a shell spells "unset" on an export line."""
    monkeypatch.setenv(P.JOBS_ENV, "")
    assert P.stage_process_budget() == P.DEFAULT_JOBS


@pytest.mark.parametrize("bad", [0, -1])
def test_an_explicit_nonpositive_jobs_is_refused(bad):
    with pytest.raises(P.BudgetRefused):
        P.stage_process_budget(bad)


# --- THE FORWARD -----------------------------------------------------------

def test_a_shard_is_given_exactly_one_unit_of_the_budget():
    assert P.shard_env({})[P.JOBS_ENV] == "1"
    assert int(P.SHARD_DISPATCH_JOBS) == 1


def test_a_shard_cannot_inherit_the_stages_own_width():
    """The stage's width is a total. Inherited, it would be a per-shard width."""
    inherited = P.shard_env({P.JOBS_ENV: str(P.DEFAULT_JOBS)})
    assert inherited[P.JOBS_ENV] == "1"


def test_every_gate_executing_shard_env_carries_the_forward():
    """MEMBERSHIP, so a fourth shard site cannot be added without the forward.

    Reads the module rather than one launch: #2072 was three launch sites that
    each looked correct beside the other two.
    """
    tree = _module_tree()
    marked: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and isinstance(tgt.slice, ast.Constant)
                    and tgt.slice.value == SHARD_MARK):
                marked.append((tgt.value.id, node.lineno))
    assert marked, ("no shard env is built in this module any more; this test "
                    "would pass vacuously")

    # The nearest preceding binding of each marked name must be `shard_env(...)`.
    bindings: dict[str, list[tuple[int, ast.expr]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            bindings.setdefault(node.targets[0].id, []).append(
                (node.lineno, node.value))

    unforwarded = []
    for name, line in marked:
        prior = [b for b in bindings.get(name, []) if b[0] <= line]
        if not prior:
            unforwarded.append(f"{name} @{line}: no binding found")
            continue
        _, value = max(prior, key=lambda b: b[0])
        ok = (isinstance(value, ast.Call)
              and isinstance(value.func, ast.Name)
              and value.func.id == "shard_env")
        if not ok:
            unforwarded.append(f"{name} @{line}: built without shard_env()")
    assert not unforwarded, (
        "a shard env is launched without the job-count forward, so that shard "
        "re-defaults to the dispatcher's own width (vibe-ic#2072): "
        + "; ".join(unforwarded))


# --- THE POOL IS THE BUDGET, AND IT DROPS NOTHING --------------------------

def _executor_calls(tree: ast.Module) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "ThreadPoolExecutor"):
            out.append(node)
    return out


def test_the_shard_pool_is_the_budget_and_not_a_multiple_of_it():
    calls = _executor_calls(_module_tree())
    assert len(calls) == 1, (
        f"expected exactly one shard pool in this module, found {len(calls)}; "
        "a second pool is a second, unbudgeted width")
    width = {kw.arg: kw.value for kw in calls[0].keywords}.get("max_workers")
    assert width is not None, "the shard pool no longer states a width"
    assert isinstance(width, ast.Name) and width.id == "budget", (
        "the shard pool's width is "
        f"{ast.unparse(width)!r}, not the stage budget; any expression over "
        "the budget makes the peak a product again (vibe-ic#2072)")


def test_both_arms_of_every_bucket_are_still_submitted_to_the_pool():
    """A narrower pool must QUEUE the work, never shed it.

    Guards the one way this fix could have been cheated: bounding the peak by
    launching fewer shards instead of by running them a few at a time.
    """
    tree = _module_tree()
    mapped = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr == "map"
              and isinstance(node.func.value, ast.Name)
              and node.func.value.id == "pool"]
    assert len(mapped) == 1, "the shard pool no longer drains one worker list"
    assert any(isinstance(a, ast.Name) and a.id == "workers"
               for a in mapped[0].args), (
        "the pool no longer drains the full `workers` list, so some shard the "
        "plan produced may never be submitted")

    appended = [node for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "workers"]
    assert appended, "no shard is appended to the worker list any more"
