#!/usr/bin/env python3
"""Drift guard for every STATED count of the programs/ population.

The MCP tool count has had a generator and a drift test for a long time
(`mcp-eda/tools/gen_mcp_tool_inventory.py` +
`mcp-eda/test/test_mcp_tool_inventory_no_drift.py`) and the number is still
right: 56. The program count had neither, and drifted by 261 files without a
single check noticing — "917" was measured at 73d1efb20 on 2026-07-20 and was
still being stated in two READMEs, nine times, a month later.

Two separate stated numbers described the SAME population and disagreed with
each other ("1608 test files" and "2,545 test files"). That is the shape of the
real defect: nothing in the repo said WHAT any stated number counted, so a
stale count and a different measurement were indistinguishable to a reader and
to a reviewer.

This file is the gate. It fails when:
  * the committed PROGRAM_INVENTORY.json no longer matches the tree, or
  * a stated count in a bound document drifts from its population, or
  * a bound claim site is reworded away (unchecked != correct), or
  * a document grows a count claim that is bound to no population.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

GEN = plugin_path("programs", "gen_program_inventory.py")
INV = plugin_path("programs", "PROGRAM_INVENTORY.json")


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_program_inventory", GEN)
    mod = importlib.util.module_from_spec(spec)
    # the generator resolves every path from its own __file__, so importing it
    # from anywhere measures the tree it ships in.
    spec.loader.exec_module(mod)
    return mod


def test_generator_and_inventory_are_shipped():
    assert GEN.exists(), f"{GEN} missing — the count has no generator again"
    assert INV.exists(), (
        f"{INV} missing — run `python3 programs/gen_program_inventory.py`")


def test_committed_inventory_matches_the_tree():
    code = _load_gen().discover()
    committed = json.loads(INV.read_text())
    for key, want in code["populations"].items():
        have = committed["populations"].get(key)
        assert have is not None, (
            f"PROGRAM_INVENTORY.json has no population {key!r}; re-run "
            f"`python3 programs/gen_program_inventory.py`")
        assert have["sha256_of_sorted_paths"] == want["sha256_of_sorted_paths"], (
            f"PROGRAM_INVENTORY.json is stale for {key}: committed "
            f"{have['count']}, tree {want['count']}. Re-run "
            f"`python3 programs/gen_program_inventory.py`.")
    assert set(committed["populations"]) == set(code["populations"])


def test_every_population_carries_a_definition():
    """1179 and 577 are both true. A count with no stated definition is what
    let the drift survive, so an undefined population is itself a failure."""
    inv = json.loads(INV.read_text())
    for key, p in inv["populations"].items():
        assert p.get("definition", "").strip(), f"{key} states no definition"
        assert len(p["definition"]) > 40, (
            f"{key}'s definition is too short to disambiguate it from the "
            f"other populations")
    defs = [p["definition"] for p in inv["populations"].values()]
    assert len(set(defs)) == len(defs), (
        "two populations share a definition, so the artefact cannot say what "
        "distinguishes them")
    # NOT asserted: that the counts are pairwise distinct. Two populations
    # coinciding on a given day is arithmetic, not a defect, and asserting it
    # would put the gate red over nothing. Attribution is guaranteed instead by
    # every stated count being bound to a KEY in _CLAIMS.


def test_artefact_says_it_must_not_be_hand_typed():
    inv = json.loads(INV.read_text())
    c = inv["_comment"].lower()
    assert "do not hand-edit" in c
    assert "must read populations" in c


def test_the_artefact_ships_no_list_of_program_names():
    """MEASURED regression guard, not a style rule.

    The first version shipped `members` — every top-level program filename —
    and the tree's unwired-disclosure test went red: a program that nothing
    invokes read as WIRED purely because this artefact contained its name. A
    shipped name list satisfies every wiring detector that searches for names,
    including the ones not yet written, so the counts are carried by digest.

    The assertion is over ALL program stems rather than the one that happened
    to go red, so it also holds for detectors nobody has written yet.
    """
    inv = json.loads(INV.read_text())
    for key, p in inv["populations"].items():
        assert "members" not in p, (
            f"{key} ships a filename list; that makes unwired programs read as "
            f"wired repo-wide. Carry sha256_of_sorted_paths instead.")
        assert p["sha256_of_sorted_paths"], f"{key} carries no digest"

    raw = INV.read_text()
    gen_stem = GEN.stem
    leaked = sorted(f.stem for f in GEN.parent.glob("*.py")
                    if f.stem != gen_stem and f.stem in raw)
    assert not leaked, (
        f"{len(leaked)} program name(s) leaked into the inventory artefact, "
        f"which makes them read as referenced by every name-searching wiring "
        f"detector: {leaked[:8]}")
    # non-vacuity: the probe must have had a real population to search.
    assert len(list(GEN.parent.glob("*.py"))) > 1000, "the stem probe found no corpus"


def test_catalogued_agrees_with_the_shipped_index():
    inv = json.loads(INV.read_text())
    index = plugin_path("programs", "INDEX.md")
    assert index.exists(), "INDEX.md missing — nothing to cross-check against"
    m = re.search(
        r"\*\*Total programs \(excluding helpers / shims\):\*\* (\d+)",
        index.read_text())
    assert m, "INDEX.md states no total"
    assert int(m.group(1)) == inv["populations"]["programs_catalogued"]["count"]


def test_the_inventory_is_enumerated_from_the_tracked_set():
    """MEASURED flake guard.

    Globbing the working tree read 1180 top-level programs on a tree that ships
    1179: another test writes a probe module into the REAL programs/ directory
    and removes it moments later. Two runs forty seconds apart disagreed with
    nothing committed between them, and the gate's verdict was a confident
    wrong number rather than an admission it could not look.
    """
    gen = _load_gen()
    inv = gen.discover()
    assert inv["enumerated_from"] == "git-tracked", (
        "this checkout is a git work tree, so the inventory must be enumerated "
        f"from it, not from {inv['enumerated_from']!r}")
    assert json.loads(INV.read_text())["enumerated_from"] == "git-tracked"


def test_an_untracked_stray_module_does_not_move_any_count(monkeypatch):
    """Non-vacuity twin: prove discover() really reads that listing, by adding
    one entry to it and watching every affected count move by exactly one."""
    gen = _load_gen()
    before = gen.discover()["populations"]
    real = gen._tracked_under_plugin()
    assert real and len(real) > 1000, "the tracked listing came back empty"
    monkeypatch.setattr(gen, "_tracked_under_plugin",
                        lambda: real + ["programs/_stray_probe_not_on_disk.py"])
    after = gen.discover()["populations"]
    assert after["programs_top_level"]["count"] == before["programs_top_level"]["count"] + 1
    assert after["programs_tree_all_py"]["count"] == before["programs_tree_all_py"]["count"] + 1
    # ...and the real listing does not carry anything git calls untracked.
    out = _pr.run(["git", "-C", str(GEN.parent.parent), "ls-files", "-o",
                          "--exclude-standard", "--", "."],
                         capture_output=True, text=True)
    if out.returncode == 0:
        untracked = {l for l in out.stdout.split("\n") if l.endswith(".py")}
        assert not (untracked & set(real)), sorted(untracked & set(real))[:5]


def test_a_source_mismatch_is_not_checked_rather_than_a_drift_verdict():
    """A tracked-set count compared against a working-tree count is two
    populations, and any verdict from that comparison is unearned.

    Exercised in memory: this test reads the tree and must therefore not write
    to it, which is why `compare_committed` takes both dicts as arguments.
    """
    gen = _load_gen()
    inv = gen.discover()
    committed = json.loads(INV.read_text())

    status, msgs = gen.compare_committed(inv, committed)
    assert (status, msgs) == ("MEASURED", []), (status, msgs)

    forged = json.loads(json.dumps(committed))
    forged["enumerated_from"] = "working-tree"
    status, msgs = gen.compare_committed(inv, forged)
    assert status == "NOT_CHECKED", (status, msgs)
    assert "different populations" in msgs[0]

    # an absent declaration is a mismatch too, not a pass by omission
    forged.pop("enumerated_from")
    assert gen.compare_committed(inv, forged)[0] == "NOT_CHECKED"

    # and a genuine drift inside the SAME population is still a drift, not
    # NOT_CHECKED — the two outcomes must not collapse into one another.
    forged = json.loads(json.dumps(committed))
    forged["populations"]["programs_top_level"]["sha256_of_sorted_paths"] = "0" * 64
    status, msgs = gen.compare_committed(inv, forged)
    assert status == "MEASURED" and any("is stale" in m for m in msgs), (status, msgs)


@pytest.mark.parametrize("body,label", [
    ('{"schema_version": 1, "popul', "truncated"),
    ('', "empty"),
])
def test_an_unreadable_artefact_is_not_checked_not_a_clean_sweep(
        tmp_path, monkeypatch, body, label):
    """An artefact that states no measurement must not be read as one.

    Read as an empty inventory it reports every population as newly drifted;
    read as agreement it reports a clean sweep over a comparison that never
    happened. exit 2 is the only earned answer. Writes to tmp_path only.
    """
    gen = _load_gen()
    forged = tmp_path / "PROGRAM_INVENTORY.json"
    forged.write_text(body)
    monkeypatch.setattr(gen, "OUT", forged)
    monkeypatch.setattr(sys, "argv", ["gen_program_inventory.py", "--check"])
    with pytest.raises(SystemExit) as e:
        gen.main()
    assert e.value.code == 2, f"{label} artefact exited {e.value.code}, not 2"


def test_stated_counts_in_the_documents_match_the_tree():
    """The gate proper: every stated count in the bound READMEs."""
    gen = _load_gen()
    fails = gen.check_documents(gen.discover())
    assert not fails, "stated count drift:\n  " + "\n  ".join(fails)


def test_check_mode_exits_zero_on_the_committed_tree():
    """The CLI is the form CI and a human both run; exercise it end to end."""
    r = _pr.run([sys.executable, str(GEN), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"`gen_program_inventory.py --check` exited {r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")
    assert "OK:" in r.stdout


# ── the gate must be able to FAIL — a guard that cannot go red is not a gate ──
def test_a_drifted_stated_count_is_caught(tmp_path):
    """Feed check_documents an inventory whose counts are deliberately wrong
    and assert it reports EVERY bound claim site. Without this, a regex that
    silently stops matching would leave the gate green forever."""
    gen = _load_gen()
    inv = gen.discover()
    for p in inv["populations"].values():
        p["count"] += 1
    fails = gen.check_documents(inv)
    # Per SITE, not per (file, key) pair: programs_top_level alone is stated at
    # four places in one file, and a bound-pair assertion would be satisfied by
    # any ONE of them going red while the other three sat unchecked.
    import re as _re
    unchecked = []
    for rel, key, pattern in gen._CLAIMS:
        text = gen._read_doc(rel)
        for m in _re.finditer(pattern, text):
            line = text[:m.start(1)].count("\n") + 1
            wanted = f"{rel}:{line}: states {m.group(1)} for {key}"
            if not any(f.startswith(wanted) for f in fails):
                unchecked.append(wanted)
    assert not unchecked, (
        "these claim sites did NOT go red under a deliberately wrong "
        "inventory, so nothing is checking them:\n  " + "\n  ".join(unchecked))
    # and every site that exists produced exactly one drift line
    n_sites = sum(len(_re.findall(pat, gen._read_doc(rel)))
                  for rel, _, pat in gen._CLAIMS)
    assert len([f for f in fails if " states " in f]) == n_sites, (
        f"{n_sites} bound claim sites but "
        f"{len([f for f in fails if ' states ' in f])} drift lines")


def test_a_reworded_claim_site_is_a_failure(monkeypatch):
    """A claim nothing can find reads exactly like a claim that is correct."""
    gen = _load_gen()
    real = gen._read_doc

    def _blank(rel):
        return "no counts here at all\n" if rel == "README.md" else real(rel)

    monkeypatch.setattr(gen, "_read_doc", _blank)
    fails = gen.check_documents(gen.discover())
    assert any("VANISHED" in f for f in fails), fails


def test_an_unregistered_new_claim_is_a_failure(monkeypatch):
    """The half that catches a NEWLY hand-typed number rather than a stale one."""
    gen = _load_gen()
    real = gen._read_doc

    def _extra(rel):
        t = real(rel)
        if rel == "README.md":
            t += "\n\nThe suite ships 4242 programs today.\n"
        return t

    monkeypatch.setattr(gen, "_read_doc", _extra)
    fails = gen.check_documents(gen.discover())
    assert any("UNREGISTERED" in f and "4242" in f for f in fails), fails


def test_clean_tree_reports_no_failure():
    """Negative control for the three tests above: the same code path must be
    silent on the tree as committed, or their red proves nothing."""
    gen = _load_gen()
    assert gen.check_documents(gen.discover()) == []


@pytest.mark.parametrize("snippet", [s for _, s, _ in _load_gen()._NOT_A_POPULATION_COUNT])
def test_declared_non_counts_are_still_present(snippet):
    """The not-a-count list is an assertion about specific sentences, not a
    blanket waiver: if one is reworded the gate must be re-examined."""
    gen = _load_gen()
    docs = {rel for rel, _, _ in gen._NOT_A_POPULATION_COUNT}
    assert any(snippet in gen._read_doc(rel) for rel in docs), (
        f"declared not-a-count sentence is gone: {snippet!r}")
