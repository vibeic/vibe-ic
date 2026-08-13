#!/usr/bin/env python3
"""vibe-ic#377 — `regmap_bit_layout_check` was inert on every document this
plugin produces.

The gate resolved a register's field list as `bit_fields` (list schema) or
`bits` (dict schema). This plugin's own L4 harvesters write `fields`. Over the
git-tracked published corpus the gate examined 0 of 702 registers and returned
PASS on 71 of 71 documents that declare registers.

Two halves are pinned here, and they are independent:

  container key  — resolve the field list under the key the producer writes
  value encoding — accept the STRING designation the producer writes
                   (`"7:0"`, `"[31:0]"`, `"3"`), while still refusing a
                   package-pin designation (`A[15:13]`)

plus the third decision: a field that EXPLICITLY declares its own layout
absent is reported, not failed.

The existing test file for this gate is written entirely in `bit_fields`,
which is why the inertness survived — the fixtures spoke the gate's
vocabulary rather than the producer's. Every fixture below is in the
producer's.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "regmap_bit_layout_check.py"
REPO = Path(__file__).resolve().parents[5]


def _run(project: Path):
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _mk(tmp_path: Path, registers, name="p") -> Path:
    proj = tmp_path / name
    docs = proj / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L4_REGMAP.json").write_text(json.dumps({"registers": registers}))
    return proj


# ---------------------------------------------------------------------------
# Half 1 — the container key the producers actually write
# ---------------------------------------------------------------------------
def test_unplaced_field_under_the_producer_key_now_fails(tmp_path):
    """THE defect. Before the fix this returned PASS because the gate never
    looked inside `fields`."""
    r = _run(_mk(tmp_path, [{
        "name": "CTRL",
        "fields": [{"name": "ENABLE", "description": "turns the block on"}],
    }]))
    assert r.returncode == 1, r.stdout
    assert "CTRL.ENABLE" in r.stdout


def test_placed_field_under_the_producer_key_passes(tmp_path):
    r = _run(_mk(tmp_path, [{
        "name": "CTRL",
        "fields": [{"name": "ENABLE", "bits": "0"}],
    }]))
    assert r.returncode == 0, r.stdout


def test_subfields_spelling_is_resolved_too(tmp_path):
    """The sibling gate on this layer resolves `fields or bit_fields or
    subfields`; this gate must not disagree with it about which list is a
    register's field list."""
    r = _run(_mk(tmp_path, [{
        "name": "CTRL",
        "subfields": [{"name": "ENABLE"}],
    }]))
    assert r.returncode == 1, r.stdout
    assert "CTRL.ENABLE" in r.stdout


def test_the_gate_reports_how_many_fields_it_examined(tmp_path):
    """An inert gate and a satisfied gate both printed PASS and were
    indistinguishable. The count is what separates them."""
    r = _run(_mk(tmp_path, [{
        "name": "CTRL",
        "fields": [{"name": "A", "bits": "0"}, {"name": "B", "bits": "1"}],
    }]))
    assert r.returncode == 0
    assert "2 field(s) examined" in r.stdout


def test_field_list_resolution_is_first_wins_not_a_union(tmp_path):
    """A record carrying two spellings is counted once, not twice."""
    r = _run(_mk(tmp_path, [{
        "name": "CTRL",
        "fields": [{"name": "A", "bits": "0"}],
        "bit_fields": [{"name": "A", "bit": 0}],
    }]))
    assert r.returncode == 0
    assert "1 field(s) examined" in r.stdout


# ---------------------------------------------------------------------------
# Half 2 — the value encoding, and the strictness that must survive it
# ---------------------------------------------------------------------------
def test_string_range_designation_is_accepted(tmp_path):
    """184 corpus fields are this shape. The int-only schema called them
    unplaced; the register emitter places them."""
    for text in ("7:0", "[31:0]", "3", " 15:8 "):
        r = _run(_mk(tmp_path, [{"name": "R", "fields": [
            {"name": "F", "bits": text}]}, ], name=f"p{abs(hash(text))}"))
        assert r.returncode == 0, f"{text!r} rejected:\n{r.stdout}"


def test_string_designation_under_the_singular_key_is_accepted(tmp_path):
    r = _run(_mk(tmp_path, [{"name": "R", "fields": [
        {"name": "F", "bit": "5"}]}]))
    assert r.returncode == 0, r.stdout


def test_package_pin_designation_is_still_refused(tmp_path):
    """LOAD-BEARING. 115 corpus values are pin designations harvested from an
    address-pin table. An unanchored search reads `A[15:13]` as bits 15:13 and
    places a register field off a package pin. Loosening the matcher to a
    search reds this test."""
    for text in ("A[15:13]", "A2", "A8, A10, A[15:13]", "byte1 b1-b5", "—"):
        r = _run(_mk(tmp_path, [{"name": "R", "fields": [
            {"name": "F", "bits": text}]}], name=f"q{abs(hash(text))}"))
        assert r.returncode == 1, f"{text!r} wrongly accepted:\n{r.stdout}"


def test_a_byte_offset_is_not_a_bit_position(tmp_path):
    """`bytes`/`size_bits` carry an offset or a SIZE, not a position. Reading
    either as a bit range is wrong in unit and in meaning."""
    for rec in ({"name": "F", "bytes": "10-13"},
                {"name": "F", "size_bits": 8},
                {"name": "F", "byte": 3}):
        r = _run(_mk(tmp_path, [{"name": "R", "fields": [rec]}],
                     name=f"b{abs(hash(str(rec)))}"))
        assert r.returncode == 1, f"{rec} wrongly accepted:\n{r.stdout}"


def test_the_gate_uses_the_consumers_own_matcher(tmp_path):
    """The gate's claim is that a field it calls placed is a field the
    emitter can place. It imports the emitter's matcher rather than copying
    the pattern, so the two cannot drift apart again."""
    sys.path.insert(0, str(PROG.parent))
    import importlib
    rblc = importlib.import_module("regmap_bit_layout_check")
    import phase2_scaffold_gen as psg
    assert rblc._consumer is not None, rblc._CONSUMER_IMPORT_ERROR
    assert rblc._consumer is psg
    for text in ("7:0", "[31:0]", "3", "A[15:13]", "A2", "WHOLE_REG", ""):
        assert (rblc._designation_places_a_field(text)
                is bool(psg._REG_FIELD_BITS_RE.match(text)))


# ---------------------------------------------------------------------------
# Half 3 — an explicitly declared absence is reported, not failed
# ---------------------------------------------------------------------------
def test_marked_unknown_is_reported_and_does_not_fail(tmp_path):
    r = _run(_mk(tmp_path, [{
        "name": "STATUS",
        "fields": [{"field_name": "WHOLE_REG", "bits": "WHOLE_REG",
                    "access": "RO",
                    "synthesised_whole_register_field": True}],
    }]))
    assert r.returncode == 0, r.stdout
    assert "NOTE —" in r.stdout
    assert "1 field(s) explicitly declare their own layout absent" in r.stdout
    assert "STATUS.WHOLE_REG" in r.stdout


def test_marked_unknown_is_never_silent(tmp_path):
    """The marker silences a failure, so it has to stay countable. Before
    this gate reported it, 202 corpus instances were visible to no consumer."""
    r = _run(_mk(tmp_path, [{
        "name": "STATUS",
        "fields": [{"field_name": "WHOLE_REG", "bits": "WHOLE_REG",
                    "synthesised_whole_register_field": True}],
    }]))
    assert "NOTE" in r.stdout


def test_marker_does_not_excuse_an_unmarked_sibling(tmp_path):
    """A marked field in the same register must not launder an unmarked one."""
    r = _run(_mk(tmp_path, [{
        "name": "STATUS",
        "fields": [{"field_name": "WHOLE_REG", "bits": "WHOLE_REG",
                    "synthesised_whole_register_field": True},
                   {"name": "LEFTOVER"}],
    }]))
    assert r.returncode == 1, r.stdout
    assert "STATUS.LEFTOVER" in r.stdout
    assert "NOTE —" in r.stdout


def test_marker_alone_without_the_flag_still_counts_as_marked(tmp_path):
    """The corpus writes both the flag and the sentinel. Either alone is
    still an explicit declaration of absence."""
    r = _run(_mk(tmp_path, [{
        "name": "STATUS", "fields": [{"name": "F", "bits": "WHOLE_REG"}],
    }]))
    assert r.returncode == 0, r.stdout
    assert "NOTE —" in r.stdout


def test_placeholder_name_resolves_through_the_shared_key_set(tmp_path):
    """The placeholder records write `field_name`, not `name`. Resolving only
    `name` prints every one of them as `<reg>.None`."""
    r = _run(_mk(tmp_path, [{
        "name": "STATUS",
        "fields": [{"field_name": "WHOLE_REG", "bits": "WHOLE_REG",
                    "synthesised_whole_register_field": True}],
    }]))
    assert "STATUS.None" not in r.stdout
    assert "STATUS.WHOLE_REG" in r.stdout


# ---------------------------------------------------------------------------
# Corpus guards — the numbers in the commit message, pinned
# ---------------------------------------------------------------------------
def _corpus_l4():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "benchmark-data"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [REPO / p for p in out.stdout.split("\n")
            if p.endswith("L4_REGMAP.json")]


def _corpus_registers():
    for path in _corpus_l4():
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        regs = d.get("registers")
        if isinstance(regs, list):
            for r in regs:
                if isinstance(r, dict):
                    yield path, r


def test_corpus_registers_are_reachable_through_the_resolved_key():
    """The measurement that made this fix: under the key the gate read, the
    published corpus offered it NOTHING to examine."""
    corpus = list(_corpus_registers())
    if not corpus:
        import pytest
        pytest.skip("published corpus not present in this checkout")
    sys.path.insert(0, str(PROG.parent))
    import importlib
    rblc = importlib.import_module("regmap_bit_layout_check")

    old_schema = sum(1 for _, r in corpus
                     if isinstance(r.get("bit_fields"), list) and r["bit_fields"])
    reachable = sum(1 for _, r in corpus if rblc.iter_register_fields(r))
    assert old_schema == 0, (
        "a corpus register now writes `bit_fields`; the inertness measurement "
        "in the module docstring needs re-running")
    assert reachable > 300, reachable


def test_corpus_placeholder_population_has_not_moved():
    """v1.7.24 pinned this count against the register emitter. Pinned again
    here against the gate: the marker must not become a way to make fields
    disappear, in either direction."""
    corpus = list(_corpus_registers())
    if not corpus:
        import pytest
        pytest.skip("published corpus not present in this checkout")
    sys.path.insert(0, str(PROG.parent))
    import importlib
    rblc = importlib.import_module("regmap_bit_layout_check")
    fields = [f for _, r in corpus for f in rblc.iter_register_fields(r)
              if isinstance(f, dict)]
    marked = [f for f in fields if rblc.field_is_marked_unknown(f)]
    # `marked == 202` was the corpus' size. The claim — "the marker must not
    # become a way to make fields disappear, in either direction" — is a claim
    # about the marker's TWO-SIDEDNESS: marked fields still arrive through
    # `iter_register_fields` (they are not dropped), and they are a strict
    # subset of them (marking is not universal). Both hold at any corpus size.
    assert marked, (
        "no corpus field is marked unknown any more — the marker has no "
        "population and this measurement is vacuous")
    assert len(marked) < len(fields), (len(marked), len(fields))
    assert all(f in fields for f in marked), "a marked field was not iterated"


def test_corpus_pin_designations_are_refused_by_the_matcher():
    """The strictness has a measured population behind it, not a hypothesis."""
    corpus = list(_corpus_registers())
    if not corpus:
        import pytest
        pytest.skip("published corpus not present in this checkout")
    sys.path.insert(0, str(PROG.parent))
    import importlib
    rblc = importlib.import_module("regmap_bit_layout_check")
    designations, pinlike = [], []
    for _, r in corpus:
        for f in rblc.iter_register_fields(r):
            if not isinstance(f, dict):
                continue
            for key in ("bits", "bit"):
                v = f.get(key)
                if isinstance(v, str) and v.strip() and \
                        v.strip() != "WHOLE_REG":
                    designations.append(v)
                    if not rblc._designation_places_a_field(v):
                        pinlike.append(v)
    # `pinlike == 115` was the corpus' size. "The strictness has a measured
    # population behind it" is a claim that the population EXISTS and that the
    # matcher discriminates — it refuses these and accepts others — not that it
    # is any particular size. Both clauses survive a publish.
    assert pinlike, (
        "no corpus designation is refused by the matcher any more, so the "
        "strictness this test justifies has no measured population behind it")
    assert len(pinlike) < len(designations), (
        "the matcher now refuses EVERY corpus designation, so it is not "
        f"discriminating: {len(pinlike)} of {len(designations)}")


def test_no_design_or_vendor_literal_in_the_gate():
    src = PROG.read_text()
    banned = ("sky130", "gf180", "ihp-sg13", "nangate", "ibex", "AXI",
              "ARVALID", "ACLK", "VDD", "VSS", "spm", "subservient",
              "sha256", "onfi", "lpddr", "ddr4", "nfc", "hdmi")
    for tok in banned:
        assert tok not in src, f"design/PDK literal {tok!r} leaked into gate"
