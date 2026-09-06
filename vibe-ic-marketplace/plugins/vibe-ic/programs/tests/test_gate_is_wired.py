"""vibe-ic#693 — a gate no automatic verdict consults.

The gate under test answers a question nothing in the repo was asking. These
tests drive its REAL entry point over a synthetic tree, so a wiring defect
inside `main` cannot hide behind green unit tests of the helpers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "gate_is_wired_check.py"

sys.path.insert(0, str(PROGRAMS))
import gate_is_wired_check as giw  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _tree(root: Path, *, gates=(), flow_names=(), flow_declared=(),
          skill_names=(), ci_names=()):
    """A minimal plugin+repo: `gates` exist, the others name some of them.

    TWO FLOW SHAPES, because the difference between them is the whole rule
    (vibe-ic#2065). `flow_names` writes a real GATE CLAUSE — a command whose
    entry is the gate — and is an invocation. `flow_declared` writes a
    `programs:` list entry, which is a DECLARATION and runs nothing.
    """
    (root / "programs").mkdir(parents=True, exist_ok=True)
    for g in gates:
        (root / "programs" / f"{g}.py").write_text("# a gate\n")
    (root / "flow").mkdir(exist_ok=True)
    steps = []
    for n in flow_names:
        steps.append(
            f"  - id: s_{n}\n"
            f"    gate:\n"
            f"      all_of:\n"
            f'        - program_exit_zero: "{n} . --json reports/{n}.json"\n')
    for n in flow_declared:
        steps.append(f"  - id: d_{n}\n"
                     f"    programs:\n"
                     f"      - {n}\n")
    (root / "flow" / "phase1_phase2_phase3.yaml").write_text(
        ("steps:\n" + "".join(steps)) if steps else "steps: []\n")
    (root / "skills" / "s").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "s" / "SKILL.md").write_text(
        "".join(f"run `{n}.py`\n" for n in skill_names) or "nothing\n")
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "".join(f'run "x" python3 "$PG/{n}.py"\n' for n in ci_names) or "true\n")
    return root


def _run(root: Path, *args):
    # <=60s: the targeted-subset harness dies at 180s, and an inner bound above
    # the ceiling kills the SESSION instead of the test. Every case here runs
    # over a synthetic tree of a handful of files and finishes in well under a
    # second; measured worst case is ~0.4s.
    r = _pr.run([sys.executable, str(GATE), "--root", str(root), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# --------------------------------------------------------------- what it reads

def test_a_flow_GATE_CLAUSE_counts_as_wired(tmp_path):
    """The flow invokes a gate when a CLAUSE names it as its command entry."""
    root = _tree(tmp_path, gates=["a_check"], flow_names=["a_check"])
    assert giw.unwired(root, root)[0] == []


def test_a_flow_programs_DECLARATION_does_NOT_count_as_wired(tmp_path):
    """THE RULING, vibe-ic#2065, and the hole it closes.

    `counter_decode_lookahead_phase_check` shipped in v1.18.3 with its own
    tests and NO caller. It was named in a step's `programs:` list and in
    `benchmark/CAPTURE_ROUTING.json`, and this register — which then credited a
    NAME in any file that could execute — read it as consulted. A register that
    credits a declaration cannot see an unwired gate, which is the one thing it
    exists to see.

    Neither list runs anything: `programs:` is what a step DECLARES it uses,
    and the routing table is read by an agent choosing what to consult."""
    root = _tree(tmp_path, gates=["a_check"], flow_declared=["a_check"])
    names, w = giw.unwired(root, root)
    assert names == ["a_check"], (
        "a `programs:` declaration was credited as an invocation")
    assert not w["a_check"]["executable"]


def test_a_ci_reference_counts_as_wired(tmp_path):
    root = _tree(tmp_path, gates=["a_check"], ci_names=["a_check"])
    assert giw.unwired(root, root)[0] == []


def test_a_skill_mention_does_NOT_count_as_wired(tmp_path):
    """The distinction the whole gate turns on.

    `drc_vacuous_pass_check` is named in a SKILL, so it runs if an agent reads
    that skill and remembers to. For a gate whose job is to catch a vacuous
    pass, depending on an agent's memory is the same as absent at the moment it
    matters — and this repo's own program-first doctrine says so."""
    root = _tree(tmp_path, gates=["a_check"], skill_names=["a_check"])
    names, w = giw.unwired(root, root)
    assert names == ["a_check"]
    assert w["a_check"]["skill"], "the mention must still be RECORDED"


def test_a_gate_does_not_wire_itself(tmp_path):
    """Its own source names it on every line; that is not a caller."""
    root = _tree(tmp_path, gates=["a_check"])
    (root / "programs" / "a_check.py").write_text("# a_check does a_check\n")
    assert giw.unwired(root, root)[0] == ["a_check"]


def test_the_auditor_does_not_wire_its_own_subjects(tmp_path):
    """MEASURED, and it was wrong at first: this gate's docstring names six
    gates as examples, and counting that as wiring made all six read as
    consulted — 34 unwired instead of 38. The gate committed the exact defect
    it exists to find. An auditor naming what it audits is not a caller."""
    root = _tree(tmp_path, gates=["a_check", "b_check"])
    # stand a copy of the auditor in the tree, naming both gates as examples
    (root / "programs" / f"{giw.Path(giw.__file__).stem}.py").write_text(
        '"""Examples: a_check does X, b_check does Y."""\n')
    names, _ = giw.unwired(root, root)
    # (the planted copy ends in `_check`, so it is itself a gate in the census)
    assert {"a_check", "b_check"} <= set(names), (
        f"the auditor wired its own examples: {sorted(set(['a_check','b_check']) - set(names))} "
        f"read as consulted")


def test_a_COMMENT_naming_a_gate_is_not_a_caller(tmp_path):
    """MEASURED, and the gate got this wrong on real incoming work.

    vibe-ic#702 repaired `handoff_bundle_check` and deliberately left it OFF a
    rail. This gate reported it newly WIRED on the strength of one line in
    another program:

        #: reproduced end-to-end through `handoff_bundle_check`, where the …

    a comment. Believing it would have shrunk the baseline by one over a gate
    that still runs nowhere. Applying the rule generally moved the count from
    29 to 73 — 44 gates had been held up by a comment somewhere.
    """
    root = _tree(tmp_path, gates=["a_check"])
    (root / "programs" / "other.py").write_text(
        "# a_check is the gate that would have caught this\n"
        "'''module docstring mentioning a_check too'''\n"
        "def f():\n"
        "    '''and a function docstring naming a_check'''\n"
        "    return 1  # a_check again\n")
    assert giw.unwired(root, root)[0] == ["a_check"]


def test_a_STRING_naming_a_gate_IS_a_caller(tmp_path):
    """The other half of the same rule: a subprocess argv is a string literal,
    and that is the ONLY form a real call takes. Dropping strings along with
    comments would report every genuinely-wired gate as unwired."""
    root = _tree(tmp_path, gates=["a_check"])
    (root / "programs" / "runner.py").write_text(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['python3', 'a_check.py'])\n")
    assert giw.unwired(root, root)[0] == []


def test_a_yaml_comment_is_not_a_caller(tmp_path):
    root = _tree(tmp_path, gates=["a_check"])
    (root / "flow" / "phase1_phase2_phase3.yaml").write_text(
        "steps:\n  # a_check would go here one day\n  - id: s1\n")
    assert giw.unwired(root, root)[0] == ["a_check"]


def test_a_hash_inside_a_quoted_shell_string_does_not_truncate_the_line(tmp_path):
    """The comment strip must not eat a real invocation that happens to sit
    after a quoted `#` — that would report a wired gate as unwired, the
    opposite error and just as wrong."""
    root = _tree(tmp_path, gates=["a_check"])
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        'echo "issue #693"; python3 "$PG/a_check.py"\n')
    assert giw.unwired(root, root)[0] == []


def test_only_gate_suffixes_are_in_scope(tmp_path):
    root = _tree(tmp_path, gates=["a_check", "b_lint", "c_audit", "d_guard"])
    (root / "programs" / "helper.py").write_text("# not a gate\n")
    assert giw.gates(root) == {"a_check", "b_lint", "c_audit", "d_guard"}


# ------------------------------------------------------- the blocking behaviour

def test_a_NEW_unwired_gate_FAILS(tmp_path):
    root = _tree(tmp_path, gates=["old_check"], flow_names=[])
    rc, _ = _run(root, "--write-baseline")
    assert rc == 0
    (root / "programs" / "new_check.py").write_text("# added later\n")
    rc, out = _run(root)
    assert rc == 1, out
    assert "new_check" in out
    assert "old_check" not in out.split("newly consulted")[-1]


def test_the_recorded_set_alone_PASSES(tmp_path):
    root = _tree(tmp_path, gates=["old_check"])
    assert _run(root, "--write-baseline")[0] == 0
    rc, out = _run(root)
    assert rc == 0, out
    assert "[PASS]" in out


def test_wiring_a_recorded_gate_is_reported_and_still_passes(tmp_path):
    root = _tree(tmp_path, gates=["old_check"])
    _run(root, "--write-baseline")
    _tree(root, gates=["old_check"], ci_names=["old_check"])
    rc, out = _run(root)
    assert rc == 0, out
    assert "TIGHTENED" in out and "old_check" in out
    # AND IT DOES NOT SEND THE READER TO THE FLAG THAT ERASES A REGRESSION.
    # `--write-baseline` records whatever THIS run measured, arrivals included,
    # so recommending it on every shrink recommends it on the days a shrink and
    # a new offender land together. Measured on the shipped tree: that flag
    # exited 0 over a one-out-one-in swap at unchanged size.
    assert "--write-baseline" not in out, out


def test_the_baseline_may_not_GROW(tmp_path):
    root = _tree(tmp_path, gates=["a_check"])
    _run(root, "--write-baseline")
    (root / "programs" / "b_check.py").write_text("# added\n")
    rc, out = _run(root, "--write-baseline")
    assert rc == 1, out
    # THE REFUSAL MUST NAME WHAT IT REFUSED. The previous assertion was the
    # word "GREW", which a message can carry while saying nothing about which
    # entry arrived — and the guard behind it was a COUNT, so a one-out-one-in
    # swap never reached this branch at all. Naming the entry is checkable and
    # is what a reader needs.
    assert "b_check" in out, out
    # and the recorded set is untouched by the refusal
    kept = json.loads((root / "programs"
                       / "gate_is_wired_baseline.json").read_text())["unwired"]
    assert kept == ["a_check"]


# ------------------------------------------- absence never renders as a pass

def test_no_baseline_is_CANNOT_DETERMINE_not_a_pass(tmp_path):
    root = _tree(tmp_path, gates=["a_check"])
    rc, out = _run(root)
    assert rc == 2, out
    assert "CANNOT DETERMINE" in out and "NOT a pass" in out


def test_an_unreadable_baseline_is_CANNOT_DETERMINE(tmp_path):
    root = _tree(tmp_path, gates=["a_check"])
    (root / "programs" / "gate_is_wired_baseline.json").write_text("{not json")
    rc, out = _run(root)
    assert rc == 2, out
    assert "CANNOT DETERMINE" in out


def test_no_programs_dir_is_CANNOT_DETERMINE(tmp_path):
    rc, out = _run(tmp_path / "nowhere")
    assert rc == 2, out


def test_a_stale_baseline_that_grew_without_a_new_name_FAILS(tmp_path):
    """The set grew but every name is recorded — only possible if the recorded
    set has entries the tree no longer has. Silence here would let the count
    drift upward under cover of a name-only comparison."""
    root = _tree(tmp_path, gates=["a_check", "b_check"])
    bpath = root / "programs" / "gate_is_wired_baseline.json"
    bpath.write_text(json.dumps({"unwired": ["a_check", "b_check", "gone_check"]}))
    rc, out = _run(root)
    assert rc == 0, out          # 2 <= 3, and no new name
    bpath.write_text(json.dumps({"unwired": ["a_check"]}))
    rc, out = _run(root)
    assert rc == 1 and "b_check" in out


# -------------------------------------------------- against the real repo tree

def test_the_real_repo_is_consistent_with_its_own_recorded_set():
    """Guards the gate against the tree it actually ships with — a synthetic
    fixture cannot catch a glob that misses this repo's real layout."""
    plugin = PROGRAMS.parent
    if not (plugin / "flow").is_dir():
        pytest.skip("not running inside the plugin tree")
    repo = plugin
    for _ in range(6):
        if (repo / "tools" / "ci").is_dir():
            break
        repo = repo.parent
    names, _ = giw.unwired(plugin, repo)
    assert giw.gates(plugin), "no gate found at all — the glob is wrong"
    assert "gate_is_wired_check" not in names, (
        "the gate that finds unwired gates must itself be wired")


# ---- the four timing-signoff gates this change wired, on the REAL tree ----

_NEWLY_WIRED = ("arith_ss_corner_risk_check",
                "hold_area_budget_check",
                "hold_corner_coverage_check",
                "pnr_timing_repair_completeness_check")


def _real_plugin():
    plugin = PROGRAMS.parent
    if not (plugin / "flow").is_dir():
        pytest.skip("not running inside the plugin tree")
    return plugin


def _real_repo(plugin):
    """The SAME walk `main()` does. Resolving the repo root differently gives
    a different `tools/ci` sweep and therefore a different unwired set — which
    is exactly how the first draft of the GROW test silently compared 61
    against 60 and concluded the ratchet was gone."""
    repo = plugin
    for _ in range(6):
        if (repo / ".git").exists() or (repo / "tools" / "ci").is_dir():
            break
        repo = repo.parent
    return repo


def test_the_shipped_register_no_longer_holds_the_four_wired_gates():
    """A debt register may only SHRINK, and an entry that describes nothing is
    debt the register is not carrying. These four are now named in the flow
    yaml's gate clauses, so leaving them recorded would have the tool print
    `Re-run with --write-baseline` on every run — a standing instruction
    nobody executes, which is how a ratchet stops being one."""
    plugin = _real_plugin()
    recorded = json.loads(
        (plugin / "programs" / "gate_is_wired_baseline.json").read_text(
            encoding="utf-8"))
    for name in _NEWLY_WIRED:
        assert name not in recorded["unwired"], name
        assert name not in recorded["skill_only"], name


def test_the_four_are_reachable_from_an_executable_location():
    """The register shrank because the tree changed, not because the entry was
    deleted. Measured through the gate's own `wiring()`, whose
    `executable_text()` strips comments and docstrings first — so a gate named
    only in the prose beside its wiring would still read as unwired here."""
    plugin = _real_plugin()
    w = giw.wiring(plugin, _real_repo(plugin))
    for name in _NEWLY_WIRED:
        assert w[name]["executable"], (
            f"{name} is recorded as wired but is named in no executable "
            f"location")


def test_the_shipped_register_still_refuses_to_GROW(tmp_path):
    """The shrink must not have spent the ratchet. Drive the REAL tree against
    a baseline one entry SHORTER than the truth: the tool must refuse, both in
    check mode (a name it has never seen) and in write mode (a count that
    grew). No file in the repo is touched — `--baseline` points elsewhere."""
    plugin = _real_plugin()
    now, _ = giw.unwired(plugin, _real_repo(plugin))
    assert len(now) > 1
    short = tmp_path / "short_baseline.json"
    short.write_text(json.dumps({"unwired": sorted(now)[1:]}))

    r = _pr.run(
        [sys.executable, str(GATE), "--root", str(plugin),
         "--baseline", str(short)],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert sorted(now)[0] in r.stdout + r.stderr

    r2 = _pr.run(
        [sys.executable, str(GATE), "--root", str(plugin),
         "--baseline", str(short), "--write-baseline"],
        capture_output=True, text=True)
    assert r2.returncode == 1, r2.stdout + r2.stderr
    assert sorted(now)[0] in r2.stdout + r2.stderr, (
        "the write path refused without naming the entry it refused")
    # the refusal left the register it was pointed at untouched
    assert json.loads(short.read_text())["unwired"] == sorted(now)[1:]


# ---- the rule stamp, and the one door through which the register may GROW ---

def test_the_shipped_register_is_stamped_with_the_rule_it_was_measured_under():
    """Without the stamp there is no way to tell a POPULATION CHANGE — the
    instrument starting to measure a different question — from a debt that
    grew, and the two need opposite responses."""
    plugin = _real_plugin()
    doc = json.loads((plugin / "programs" / "gate_is_wired_baseline.json")
                     .read_text(encoding="utf-8"))
    assert doc.get("measured_under") == giw._RULE_ID, doc.get("measured_under")


def test_a_register_with_NO_stamp_may_still_not_GROW(tmp_path):
    """THE HOLE THIS ARM WAS WRITTEN FROM, and it was open for one commit.

    The re-derivation door first opened on `recorded rule != this rule`, and an
    ABSENT stamp satisfies that — so deleting one line from the register turned
    `--write-baseline` back into the laundering flag vibe-ic#900 removed. It
    was caught by `test_the_shipped_register_still_refuses_to_GROW`, whose
    synthetic register carries no stamp, going from refusing to writing.

    The door now needs the stamp PRESENT and DIFFERENT. A future rule change
    migrates by bumping `_RULE_ID`; nothing else opens it."""
    root = _tree(tmp_path, gates=["a_check", "b_check"], flow_names=["a_check"])
    bl = tmp_path / "unstamped.json"
    bl.write_text(json.dumps({"unwired": []}))          # no measured_under
    rc, out = _run(root, "--baseline", str(bl), "--write-baseline")
    assert rc == 1, out
    assert "b_check" in out, out
    assert json.loads(bl.read_text())["unwired"] == []


def test_a_register_stamped_with_ANOTHER_rule_may_be_re_derived(tmp_path):
    """The other direction — the door must actually open, and must name every
    entry it adds rather than reporting a count."""
    root = _tree(tmp_path, gates=["a_check", "b_check"], flow_names=["a_check"])
    bl = tmp_path / "old_rule.json"
    bl.write_text(json.dumps({"measured_under": "name.v0", "unwired": ["z_check"]}))
    rc, out = _run(root, "--baseline", str(bl), "--write-baseline")
    assert rc == 0, out
    assert "POPULATION CHANGE" in out, out
    assert "+ b_check" in out, out
    after = json.loads(bl.read_text())
    assert after["unwired"] == ["b_check"], after
    assert after["measured_under"] == giw._RULE_ID
    # and the door has closed behind it
    (root / "programs" / "c_check.py").write_text("# added later\n")
    rc2, out2 = _run(root, "--baseline", str(bl), "--write-baseline")
    assert rc2 == 1, out2
    assert "c_check" in out2, out2


# ------------- the corpus the verdict depends on, and saying so (#1467) ------

def _nested(tmp_path: Path, *, marketplace_is_a_checkout: bool,
            repo_tools: bool = True, extra_gates=()):
    """The REAL shape: repo root, plugin three levels down inside it.

    `_tree` puts `tools/ci/` under the plugin, which is the one layout where
    the repo-root walk cannot go wrong. This repo's actual layout is
    `<repo>/vibe-ic-marketplace/plugins/vibe-ic`, with the wiring corpus three
    levels ABOVE the plugin — so the walk is load-bearing, and only a nested
    fixture exercises it.
    """
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    for g in ("a_check",) + tuple(extra_gates):
        (plugin / "programs" / f"{g}.py").write_text("# a gate\n")
    (plugin / "flow").mkdir()
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text("steps: []\n")
    (repo / ".git").mkdir(parents=True)
    if repo_tools:
        (repo / "tools" / "ci").mkdir(parents=True)
        (repo / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
            'run "a" "$ROOT" python3 "$PG/a_check.py"\n')
    if marketplace_is_a_checkout:
        (repo / "vibe-ic-marketplace" / ".git").write_text(
            "gitdir: /elsewhere/.git/worktrees/mkt\n")
    (plugin / "programs" / "gate_is_wired_baseline.json").write_text(
        json.dumps({"unwired": []}))
    return repo, plugin


def test_an_intermediate_dot_git_does_not_capture_the_repo_root(tmp_path):
    """MEASURED on this repo's own bytes, `programs/` and `tools/` HARDLINKED
    into both arms so the two runs read the same inodes, one `.git` at the
    `vibe-ic-marketplace/` level the only difference:

        without it   wiring sources 1147 + 66   unwired 59   [PASS]  rc 0
        with it      wiring sources 1147 +  0   unwired 110  [FAIL] 50   rc 1

    Fifty accusations over an unchanged tree, because the walk tested `.git`
    BEFORE `tools/ci` and stopped at whichever came first.
    `container_login_banner_parse_check` — one of the three names vibe-ic#1467
    could not account for — is in those fifty. The marketplace is published
    separately, so a `.git` there is a layout somebody will have. `tools/ci` is
    the marker now; `.git` is only the fallback."""
    repo, plugin = _nested(tmp_path, marketplace_is_a_checkout=True)
    assert giw.repo_root(plugin) == repo, (
        f"anchored on {giw.repo_root(plugin)}, which carries no tools/ci")
    assert giw.unwired(plugin, giw.repo_root(plugin))[0] == []
    rc, out = _run(plugin)
    assert rc == 0, out
    assert "a_check" not in out.split("newly consulted")[-1]


def test_an_EMPTY_repo_corpus_is_CANNOT_DETERMINE_not_a_list_of_names(tmp_path):
    """An empty result is not a zero.

    Four of the wiring globs are anchored on the repo root, and for several
    gates `tools/ci/repo_hygiene_gates.sh` is the only caller there is. Read
    nothing from there and the honest answer is "I could not look", not a
    confident FAIL naming every gate whose caller lives where the tool did not
    reach. rc 2 still BLOCKS — `repo_hygiene_gates.sh` dispatches this gate
    with plain `run`, which forgives nothing."""
    _, plugin = _nested(tmp_path, marketplace_is_a_checkout=False,
                        repo_tools=False)
    rc, out = _run(plugin)
    assert rc == 2, out
    assert "CANNOT DETERMINE" in out and "NOT a pass" in out
    assert "newly consulted by no automatic verdict" not in out, (
        "a failed look was reported as a finding")


def test_an_empty_corpus_with_NO_root_at_all_says_which_it_was(tmp_path):
    """The two ways to end up with nothing read differently to whoever has to
    fix it: a root that was found and is bare, versus no root found at all."""
    repo, plugin = _nested(tmp_path, marketplace_is_a_checkout=False,
                           repo_tools=False)
    (repo / ".git").rmdir()
    assert giw.repo_root(plugin) is None
    rc, out = _run(plugin)
    assert rc == 2, out
    assert "NO REPO ROOT FOUND" in out and "tools/ci" in out


def test_the_run_discloses_both_corpora_it_read(tmp_path):
    """vibe-ic#1467 collected contradictory red lists from three hosts at one
    commit and could not settle which corpus each run had read, because no line
    of the output said. Both counts are printed on every run, pass or fail, so
    two runs that disagree can be compared from their output alone."""
    repo, plugin = _nested(tmp_path, marketplace_is_a_checkout=False)
    rc, out = _run(plugin)
    assert rc == 0, out
    assert "wiring sources:" in out
    assert str(plugin) in out and str(repo) in out
    assert "+ 1 under" in out, out          # the one hygiene script at the root


def test_a_readable_corpus_still_FAILS_a_genuinely_unwired_gate(tmp_path):
    """The other direction, and the one that matters: rc 2 must not have become
    a way out. With the corpus present and readable, a gate nothing invokes is
    still a blocking finding, named."""
    _, plugin = _nested(tmp_path, marketplace_is_a_checkout=False,
                        extra_gates=("b_check",))
    rc, out = _run(plugin)
    assert rc == 1, out
    assert "b_check" in out
    assert "CANNOT DETERMINE" not in out
