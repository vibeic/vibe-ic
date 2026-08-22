"""ORGANIC #493 — the `typical_scaffolds` mechanism is RETIRED.

Two kinds of test here, and the distinction matters:

  * The RECORD tests assert that the retirement is documented, so the
    deletion carries its reason forward (the vibe-ic#439 /
    `phase1_k5_quality_check._RETIRED_CHECKS` precedent). Without them a
    future reader sees only absence and cannot tell a considered removal
    from an accident.

  * The BEHAVIOUR tests DRIVE the real entry points (`auto_fill`,
    `detect_gaps`) on a fact graph whose `class_path` genuinely resolves in
    the class tree, and assert on the resulting facts. They deliberately do
    NOT assert on source text: a test that greps for a function name passes
    the moment someone renames it, and fails the moment someone reformats a
    comment. Every assertion below reads an observable result.

The behaviour tests are the regression guard proper. Each one FAILS if the
mechanism is restored in its original shape, because each targets one of the
two mechanical defects that made the mechanism harmful:

  (a) AES-128 facts hung on `crypto-engine`, the PARENT of `hash-function`,
      `stream-cipher` and `rng` — so a SHA-256 core inherited `rounds = 10`
      (it has 64), a `key[256]` port (it is keyless) and 128-bit block
      ports (it is 512-bit block / 256-bit digest).
  (b) `L9.top_level_ports` gap-filled with `suggested_default = []`, which
      renders as an empty list and directly trips `l9_completeness_check`'s
      "Section 'X' exists but is empty" ERROR.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

# THE REPO ROOT MUST BE ON `sys.path` BEFORE THE ABSOLUTE IMPORT BELOW, and
# this file has to say so rather than inherit it from how it was launched.
# `python3 -m pytest` put the cwd on `sys.path[0]`; the landing arms now run
# through `trusted_pytest_entry.py` under `python3 -I`, which deliberately keeps
# the subject cwd OFF `sys.path` — that is the property the trusted entry exists
# to guarantee. Without this the module raises
# `ModuleNotFoundError: No module named 'tools'` AT COLLECTION, the session exits
# rc=2 with no complete junit, and the landing reports the file NORECORD:
# UNKNOWN, not clean and not red. Six of the eight files in this directory
# already carry these three lines; this was one of the two that did not.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.phase1_engine import gap_detect
from tools.phase1_engine.gap_detect import (
    DEFAULT_CLASS_KB,
    DEFAULT_DEFAULTS_DIR,
    auto_fill,
    detect_gaps,
)
from tools.phase1_engine.render import render_layers
from tools.phase1_engine.schema import FactGraph


# The three classes that inherited the AES-specific scaffolds through the
# `crypto-engine` parent. Asserted (not assumed) by
# `test_the_wrong_node_inheritance_that_made_this_harmful_still_exists`.
_AES_INHERITORS = ["hash-function", "stream-cipher", "rng"]

_SCAFFOLDED_CLASSES = ["apb-peripheral", "uart-peripheral", "crypto-engine",
                       "simple-cpu", "bus-controller"]


def _graph(class_path: str, ic_name: str = "probe_ic") -> FactGraph:
    """A minimal graph whose class_path RESOLVES in the class tree.

    Resolution is the whole point: the corpus never resolves (breadcrumb
    `class_path` values plus two disjoint taxonomies — vibe-ic#495), so a
    test built on corpus-shaped input would pass whether or not the
    mechanism exists. These tests use the normalized form so the class
    chain really is walked and the injector really would fire.
    """
    g = FactGraph(ic_name=ic_name, class_path=class_path)
    g.add_fact(path="L1.ic_name", value=ic_name, views=["L1"],
               source="user_stated", origin="test", confidence=1.0,
               reasoning="probe")
    return g


# ===========================================================================
# 1. The retirement RECORD
# ===========================================================================
def test_retirement_record_exists():
    assert hasattr(gap_detect, "_RETIRED_MECHANISMS")
    assert "typical_scaffolds" in gap_detect._RETIRED_MECHANISMS


def test_retirement_record_names_what_was_removed():
    e = gap_detect._RETIRED_MECHANISMS["typical_scaffolds"]
    assert e["issue"] == "vibe-ic#493"
    assert e["entries_removed"] == 59
    assert sum(e["classes_removed"].values()) == 59
    assert set(e["classes_removed"]) == set(_SCAFFOLDED_CLASSES)
    # BOTH readers must be named. The issue named only the injector; the
    # gap-conditional lookup in `_k3_default_for_gap` was the second reader
    # and the only one on the shipping path.
    was = " ".join(e["was"])
    assert "_apply_typical_scaffolds" in was
    assert "_k3_default_for_gap" in was


def test_retirement_record_states_the_measured_coverage_and_both_defects():
    """A removal must record WHY, not merely THAT."""
    e = gap_detect._RETIRED_MECHANISMS["typical_scaffolds"]
    assert "0" in e["measured_coverage"] and "201" in e["measured_coverage"]
    reason = e["reason"].lower()
    # defect (a) — scaffolds hung on the wrong inheritance node
    assert "parent" in reason
    assert "sha-256" in reason or "sha256" in reason
    # defect (b) — an empty container filled into a required field
    assert "empty" in reason
    assert "top_level_ports" in reason
    assert len(e["reason"]) > 200, "the reason must survive as evidence"
    # and it must say what was deliberately NOT removed
    assert "auto-fill" in e["kept"] or "auto_fill" in e["kept"]


def test_the_injector_is_gone():
    assert not hasattr(gap_detect, "_apply_typical_scaffolds"), (
        "retired in #493; do not resurrect without the class_path taxonomy "
        "decision (#495), scaffolds re-homed to a node whose members are "
        "homogeneous in that field, and topology-level claims dropped")


def test_the_summary_no_longer_advertises_a_counter_that_can_only_be_zero():
    summary = auto_fill(_graph("apb-peripheral"))
    assert "scaffolds_applied" not in summary, (
        "a permanently-zero counter for a removed mechanism reads as coverage")


# ===========================================================================
# 2. The shipped DATA carries no scaffolds
# ===========================================================================
def test_no_shipped_class_declares_typical_scaffolds():
    """Data-side guard: re-adding the YAML block alone must fail a test.

    Loaded through the engine's own K3 loader, so this reads exactly the
    file the engine reads.
    """
    ref = gap_detect._load_k3_defaults()["class_reference"]
    assert len(ref) >= 30, (
        f"class_reference did not load ({len(ref)} classes) — "
        f"DEFAULT_DEFAULTS_DIR is relative ({DEFAULT_DEFAULTS_DIR}), so a "
        f"wrong cwd yields an empty dict and a FALSE pass")
    offenders = {k for k, v in ref.items()
                 if isinstance(v, dict) and v.get("typical_scaffolds")}
    assert offenders == set(), f"typical_scaffolds re-added to {offenders}"


def test_the_other_class_reference_content_survived():
    """Guard against over-removal: only the scaffolds were meant to go."""
    ref = gap_detect._load_k3_defaults()["class_reference"]
    # Same denominator guard as above, and it is not decoration: without it an
    # empty load reports `apb-peripheral itself must not have been deleted`,
    # which names a deletion that never happened and sends the reader to the
    # wrong file. An empty corpus is a load failure, not an over-removal.
    assert len(ref) >= 30, (
        f"class_reference did not load ({len(ref)} classes) — nothing was "
        f"deleted; DEFAULT_DEFAULTS_DIR ({DEFAULT_DEFAULTS_DIR}) did not "
        f"resolve from this cwd")
    for cls in _SCAFFOLDED_CLASSES:
        assert cls in ref, f"{cls} itself must not have been deleted"
        assert ref[cls].get("reference"), f"{cls} lost its `reference`"
    assert ref["crypto-engine"].get("typical_structure"), (
        "the semantic-shape half of crypto-engine must survive")
    assert ref["apb-peripheral"].get("typical_apb_version") == "APB3"
    assert ref["bus-controller"].get("typical_id_width") == 4


# ===========================================================================
# 3. BEHAVIOUR — defect (a): AES facts must not reach non-AES crypto classes
# ===========================================================================
def test_the_wrong_node_inheritance_that_made_this_harmful_still_exists():
    """The tree shape is the PREMISE of the next test, so assert it.

    If `hash-function` ever stops inheriting from `crypto-engine`, the next
    test would pass vacuously and silently stop guarding anything.
    """
    tree = gap_detect._load_yaml(DEFAULT_CLASS_KB / "class-tree.yaml")
    for cls in _AES_INHERITORS:
        chain = gap_detect._parent_chain(cls, tree)
        assert "crypto-engine" in chain, (
            f"{cls} no longer inherits crypto-engine; this test's premise "
            f"is stale — re-derive it before trusting the guard")


@pytest.mark.parametrize("class_path", _AES_INHERITORS)
def test_non_aes_crypto_classes_receive_no_aes_facts(class_path):
    """Drive auto_fill and read the facts. No AES-128 specifics may appear.

    Pre-#493 this FAILED for all three: walking the parent chain pulled the
    12 crypto-engine scaffolds into every child.
    """
    g = _graph(class_path, ic_name="sha256_core")
    auto_fill(g)

    rounds = g.by_path("L2.rounds")
    assert rounds is None or rounds.value != 10, (
        f"{class_path} was injected with the AES-128 round count")

    blob = json.dumps([f.value for f in g.facts], default=str)
    for aes_token in ("block_in", "block_out", "key_len", "encdec",
                      "aes_encipher", "aes_sbox", "aes_mixcol",
                      "mixcol", "sbox"):
        assert aes_token not in blob, (
            f"{class_path} was injected with AES-specific content "
            f"({aes_token!r}); AES facts belong on `block-cipher`, not on "
            f"the `crypto-engine` parent")

    assert g.by_path("L9.dtop_top_level") is None, (
        f"{class_path} was given a class-typical L9 TOPOLOGY; the members "
        f"of these classes are not homogeneous in L9 shape")


@pytest.mark.parametrize("class_path", _SCAFFOLDED_CLASSES)
def test_no_fact_is_attributed_to_the_retired_mechanism(class_path):
    """Provenance-side guard, driven end to end.

    `origin` was `class_reference:<cls>:typical_scaffolds` — the only
    unambiguous marker of a scaffold fact. None may survive.
    """
    g = _graph(class_path)
    auto_fill(g)
    origins = [f.provenance.origin or "" for f in g.facts]
    assert not [o for o in origins if "typical_scaffolds" in o]


def test_the_shipping_path_suggests_no_scaffold_defaults():
    """`run-all` → detect_gaps → _k3_default_for_gap was the SECOND reader.

    Reader 1 (the injector) sat behind the `auto-fill` verb, which the
    shipping runner never calls; this one is on the shipping path, so it is
    checked separately rather than via auto_fill.
    """
    for class_path in _SCAFFOLDED_CLASSES + _AES_INHERITORS:
        for gap in detect_gaps(_graph(class_path)):
            sd = json.dumps(gap.suggested_default, default=str)
            for aes_token in ("block_in", "encdec", "aes_sbox", "mixcol"):
                assert aes_token not in sd, (
                    f"{class_path}: gap {gap.layer}.{gap.path} still "
                    f"suggests a scaffold default")


# ===========================================================================
# 4. BEHAVIOUR — defect (b) is PRE-EXISTING, and its attribution is pinned
# ===========================================================================
@pytest.mark.parametrize("class_path", _SCAFFOLDED_CLASSES)
def test_the_empty_l9_container_is_not_attributable_to_this_mechanism(
        class_path, tmp_path):
    """Attribution guard for the co-requisite hazard recorded in the note.

    The #493 report read the empty `L9.top_level_ports` as scaffold damage,
    because it only ever showed up in the counterfactual run where
    `class_path` was normalized. It is actually the ROOT `any-ic` template's
    required `top_level_ports` being gap-filled with `suggested_default =
    []` — it reproduces with the scaffolds gone, on every resolvable class.

    This test therefore does NOT assert the empty container is absent (this
    removal does not fix it, and a test claiming otherwise would be a lie).
    It asserts the WEAKER, TRUE thing: whatever empty container renders, no
    part of it comes from the retired mechanism. If someone later fixes the
    gap-fill defect, this test keeps passing; if someone re-lands the
    scaffolds, it fails.
    """
    g = _graph(class_path)
    auto_fill(g)
    out = tmp_path / class_path
    out.mkdir(parents=True)
    render_layers(g, out)

    l9_path = out / "L9_INTEGRATION_SPEC.json"
    if not l9_path.exists():
        pytest.skip(f"{class_path} renders no L9")

    fact = g.by_path("L9.top_level_ports")
    if fact is not None and fact.value == []:
        assert "typical_scaffolds" not in (fact.provenance.origin or ""), (
            "the empty L9.top_level_ports came from the retired mechanism")
        assert fact.provenance.origin == "auto_fill:any-ic", (
            f"the empty container's provenance changed to "
            f"{fact.provenance.origin!r}; re-derive the attribution recorded "
            f"in _RETIRED_MECHANISMS before trusting this guard")

    l9 = json.loads(l9_path.read_text())
    srcs = " ".join(str(s) for s in (l9.get("source_documents") or []))
    assert "typical_scaffolds" not in srcs, (
        f"{class_path}: the rendered L9 still cites the retired mechanism")


# ===========================================================================
# 5. Guard against OVER-removal — the retained passes still work
# ===========================================================================
def test_auto_fill_still_runs_its_retained_passes():
    """The `auto-fill` verb, auto_fill() and its sentinel / interfaces_floor
    / gap-fill passes were deliberately KEPT (the training loop uses them).
    Removing the scaffolds pass must not have taken them with it."""
    summary = auto_fill(_graph("apb-peripheral"))
    for key in ("filled", "no_default", "total_gaps", "sentinels_added",
                "interfaces_added"):
        assert key in summary, f"auto_fill lost its `{key}` result"


def test_the_sentinel_pass_still_emits_its_facts():
    """Driven, not asserted from the summary integer: a graph whose class
    chain declares no L3 requirements must actually carry the L3-family
    sentinel facts afterwards.

    Only the L3 family is asserted: `bus-controller` DOES declare L4
    requirements, so the L4 sentinel correctly does not fire for it. An
    earlier draft asserted `L4.regmap_present` here and failed — the test
    was wrong, not the code.
    """
    g = _graph("bus-controller")
    summary = auto_fill(g)
    paths = {f.path for f in g.facts}
    assert summary["sentinels_added"] > 0
    assert "L1.protocol_present" in paths
    assert "L3.protocol_present" in paths
    assert g.by_path("L3.protocol_present").provenance.origin.startswith(
        "sentinel:")


def test_the_interfaces_floor_pass_still_runs():
    g = _graph("apb-peripheral")
    summary = auto_fill(g)
    assert summary["interfaces_added"] >= 1
    assert g.by_path("L1.supported_interfaces") is not None


def test_the_auto_fill_cli_verb_is_still_registered():
    """The verb itself was explicitly NOT part of this removal."""
    from tools.phase1_engine import cli
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        assert hasattr(cli, "_cmd_auto_fill")
    else:
        assert "auto-fill" in parser.format_help()


# ===========================================================================
# 6. The two engine copies must stay in lockstep
# ===========================================================================
_A_REL = "tools/phase1_engine/gap_detect.py"
_B_REL = "vibe-ic-marketplace/plugins/vibe-ic/tools/phase1_engine/gap_detect.py"


def _repo_root():
    """Locate the repo root by SEARCHING for the two known copies.

    Not a fixed `parents[N]`: this module is imported from `tools/` in a
    checkout and from `<plugin>/tools/` in an installed plugin, so a fixed
    index silently skips in one of the two — and a test that skips guards
    nothing.
    """
    from pathlib import Path
    here = Path(gap_detect.__file__).resolve()
    for anc in (here, *here.parents):
        if (anc / _A_REL).is_file() and (anc / _B_REL).is_file():
            return anc
    return None


def test_the_repo_root_is_locatable_from_a_checkout():
    """Fails loudly rather than letting the next two tests skip silently."""
    from pathlib import Path
    here = Path(gap_detect.__file__).resolve()
    in_checkout = any((anc / _A_REL).is_file() for anc in (here, *here.parents))
    if not in_checkout:
        pytest.skip("installed-plugin layout: only one copy exists here")
    assert _repo_root() is not None, (
        "running from a checkout that has tools/phase1_engine but no plugin "
        "copy — the two are meant to be kept in lockstep")


def test_both_engine_copies_agree():
    """`tools/phase1_engine` and the plugin's bundled copy are byte-identical
    by convention; a removal applied to only one would ship a live injector
    to installed plugins."""
    repo = _repo_root()
    if repo is None:
        pytest.skip("installed-plugin layout")
    a, b = repo / _A_REL, repo / _B_REL
    assert a.read_text() == b.read_text(), (
        "the two phase1_engine copies have diverged")
    for f in (a, b):
        assert "_RETIRED_MECHANISMS" in f.read_text()
        assert "def _apply_typical_scaffolds" not in f.read_text()


def test_the_shipped_yaml_has_no_scaffold_block():
    """Read the file the plugin ships, independently of the loader cache."""
    repo = _repo_root()
    if repo is None:
        pytest.skip("installed-plugin layout")
    y = (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "agents"
         / "defaults" / "class_reference.yaml")
    data = yaml.safe_load(y.read_text())
    assert len(data) >= 30
    assert not [k for k, v in data.items()
                if isinstance(v, dict) and v.get("typical_scaffolds")]


# ---------------------------------------------------------------------------
# THE cwd DEPENDENCE, DRIVEN — not asserted from a cwd where it cannot appear
# ---------------------------------------------------------------------------
# `DEFAULT_DEFAULTS_DIR` was a bare relative path, so it resolved only when cwd
# happened to be a repo root. `_load_k3_defaults` reads it as
# `f.exists() else {}`, so a wrong cwd did not raise — it yielded an EMPTY
# class_reference and `suggest_default` then found no default for any gap and
# said nothing. Silent degradation.
#
# WHY THIS RUNS IN A CHILD PROCESS. The condition is "cwd is not a repo root",
# and pytest has already resolved this file's package by the time any test body
# runs — from a cwd where the defect appears, the module cannot even be
# collected. `os.chdir` inside a test would also leak into every later test in
# the session. A child with its own cwd is the only way to exercise the real
# condition without either problem.
#
# MEASURED, and it is why this test exists rather than the assertion above it:
# reverting `_resolve_default_defaults_dir` and keeping every test in this file
# leaves BOTH trees at 121 passed. The `len(ref) >= 30` guard is a real
# improvement to the failure MESSAGE, but it only fires once the load is already
# empty, and the suite never runs from a cwd where that happens.
_CWD_PROBE = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
os.chdir(sys.argv[2])
from phase1_engine.gap_detect import DEFAULT_DEFAULTS_DIR
ref = Path(DEFAULT_DEFAULTS_DIR) / "class_reference.yaml"
print("RESOLVES" if ref.is_file() else "EMPTY")
"""


def test_the_defaults_dir_resolves_from_a_cwd_OUTSIDE_the_repo(tmp_path):
    """The defect's own condition, in a child process."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path
    pkg_parent = str(_Path(__file__).resolve().parents[2])  # dir holding phase1_engine/
    probe = tmp_path / "probe.py"
    probe.write_text(_CWD_PROBE)
    # 60s is the inner ceiling a 180s harness implies; this is an import, so the
    # bound is insurance against a hang rather than a budget.
    out = subprocess.run([_sys.executable, str(probe), pkg_parent, str(tmp_path)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, f"probe failed: {out.stderr[-800:]}"
    assert out.stdout.strip() == "RESOLVES", (
        "DEFAULT_DEFAULTS_DIR did not resolve from a cwd outside the repo, so "
        "`_load_k3_defaults` returns {} and `suggest_default` silently offers "
        "nothing for every gap. This is the defect the resolver was added to "
        f"remove.\nprobe said: {out.stdout.strip()!r}\ncwd used: {tmp_path}")


def test_the_defaults_dir_is_ANCHORED_and_not_cwd_relative():
    """The property in one line, so the reason survives a refactor.

    A relative `DEFAULT_DEFAULTS_DIR` is the defect by construction, whatever
    the cwd of the run that happens to observe it. Note this is NOT what the
    `len(ref) >= 30` guards above assert: those fire only once the load is
    already empty, and mention the relative path in their MESSAGE.
    """
    from pathlib import Path as _Path
    assert _Path(DEFAULT_DEFAULTS_DIR).is_absolute(), (
        f"DEFAULT_DEFAULTS_DIR is relative ({DEFAULT_DEFAULTS_DIR!r}), so it "
        f"resolves only when cwd is a repo root — the cwd dependence is back")
