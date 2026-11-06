"""Unit tests for enhancement_emit.py — the driver of the
benchmark-enhancement-capture closed loop (v0.1.35).

Eight cases cover the four-bucket routing + per-step target resolution:
  1. Bucket A is routed to the program file declared in CAPTURE_ROUTING.json
  2. Bucket B is routed to the skill file declared in CAPTURE_ROUTING.json
  3. Bucket C emits a YAML backlog with the expected ORGANIC- prefix + schema fields
  4. Bucket D emits a discard log (never silently drops)
  5. Same-bucket records targeting DIFFERENT steps land in DIFFERENT output files
  6. Same-bucket records targeting the SAME step are concatenated into ONE file
  7. Unknown step IDs fall back to the default_routing.bucket_B_skill_file
  8. Summary JSON records every target file touched for review
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from _published_corpus import corpus_root, needs_corpus

ROUTING = Path(__file__).parent.parent.parent / "benchmark" / "CAPTURE_ROUTING.json"
_CVDP_NEGATIVE_CONTROL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "cvdp_negative_control_population.json")
assert ROUTING.exists(), f"missing routing table: {ROUTING}"




# ── 1. Bucket A routes to the program file declared in the routing table ──














# ── 2. Bucket B routes to the skill file declared in the routing table ──


# ── 3. Bucket C emits YAML with ORGANIC- prefix + required schema fields ──


# ── 4. Bucket D produces a discard log (no silent drops) ──


# ── 5. Same-bucket DIFFERENT-step records land in DIFFERENT output files ──


# ── 6. Same-bucket SAME-step records concatenate into ONE output file ──


# ── 7. Unknown step ID falls back to default_routing.bucket_B_skill_file ──


# ── 8. Summary records every target file the session would touch (audit trail) ──


# ── v0.1.39 audit Finding 1 tests — honesty enforcement ──────────────────────
import importlib.util






# ── `pattern` is required AT EMIT, not only downstream ───────────────────────
#
# Two backlog-landing PRs an hour apart shipped a broken `pattern` on a
# required field — one byte-identical text copied off an unrelated defect, one
# empty. One cause: `backlog_slug` above RAISES when absent, while `pattern`
# was read as `rec.get("pattern", "")` and `_validate_general_text` returns
# early on a falsy value. An omitted pattern emitted well-formed YAML with an
# empty block and no error, while `backlog_sanitize_check.REQUIRED_FIELDS`
# demands the field of that very file. Required downstream, undefined upstream,
# unenforced here — so both ways of resolving it were available.

_PATTERNLESS = {"title": "A gate accepts what it should refuse",
                "suggested_fix": "Make the gate refuse.",
                "backlog_slug": "generic-issue-category"}

_REAL_PATTERN = ("A required field that is defaulted at its write site but "
                 "demanded by a downstream gate: the write succeeds, the "
                 "record looks complete, and the refusal lands on whoever "
                 "reads it next.")
















































# ---------------------------------------------------------------------------
# v0.2.15 — PROGRAM-FIRST gate (user directive: capture must enforce
# program-first). Bucket B/C downgrades require a non-empty why_not_bucket_a.
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# #197 finding 1 — a Bucket-A record whose step has no `bucket_A_program`
# (either a LISTED step with an explicit null program layer, or an UNLISTED
# step that falls through to default_routing's null) must be reported as
# UNROUTED, never crash the batch with AttributeError('NoneType' … 'replace')
# and leave a partially-written output directory.
# ---------------------------------------------------------------------------








# ═══════════════════════════════════════════════════════════════════════════
# #795 — the provenance fields this emitter stamps must be MEASUREMENTS.
#
# `plugin_version` was the literal "0.1.33" and `submitted_at`'s time-of-day
# was the literal midnight. Both are formatted like data, so a wrong value is
# invisible: no reader, and no gate, can tell a defaulted record from a
# measured one. `backlog_sanitize_check.py` requires `plugin_version` but only
# checks it is non-empty, and `tools/ci/staged_version_claim_check.py` exempts
# `community/backlogs/` from version-claim checking entirely.
#
# The tests below therefore REFUSE to be satisfied by a constant. Each one
# changes the thing the emitter is supposed to be reading and asserts the
# emitted value FOLLOWED it. Swapping one hardcoded constant for another
# cannot pass any of them.
# ═══════════════════════════════════════════════════════════════════════════
import datetime as _dt
import importlib as _importlib
import re as _re
import time as _time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

# The single source of truth, read here INDEPENDENTLY of the program under
# test — the test must not learn the expected version from the code that is
# supposed to be reading it.
_PLUGIN_JSON = _PROGRAMS_DIR.parent / ".claude-plugin" / "plugin.json"


def _shipped_version() -> str:
    return json.loads(_PLUGIN_JSON.read_text())["version"]


def _bucket_c_record(**over) -> dict:
    rec = {
        "step": "phase2.rtl_gen", "design": "d1", "bucket": "C",
        "why_not_bucket_a": "needs judgement no predicate can make",
        "title": "a captured gap", "pattern": "a general pattern",
        "suggested_fix": "a general fix", "backlog_slug": "provenance-probe",
        "backlog_type": "bug", "severity": "P2",
        "component": "program:enhancement_emit",
        "session_context": "captured from a convergence run",
    }
    rec.update(over)
    return rec


def _yaml_field(body: str, key: str) -> str:
    for line in body.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip().strip('"')
    raise AssertionError(f"field {key!r} absent from emitted backlog:\n{body}")


def _fake_plugin_root(tmp_path: Path, version) -> Path:
    """A minimal plugin tree whose manifest declares `version`."""
    root = tmp_path / "fake_plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    doc = {"name": "vibe-ic"}
    if version is not None:
        doc["version"] = version
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(doc))
    return root
















# ── #798 — the backtick leak guard must not refuse legitimate names ──────────
#
# What the guard is FOR: keeping BENCHMARK DESIGN identifiers out of captured
# plugin content. A true positive is a design leaf-name (`radix2_div`,
# `mux256to1`, `ece241_2014_q5a`), a Prob ID, a benchmark family name, or one
# of those with its separators stripped to evade the shape rules
# (`radix2divbyeven`).
#
# Two predicates in `_check_backtick_content` fired on things that are none of
# those. Both are pinned below in BOTH directions: the false positive must stop
# firing AND the structurally-adjacent true positive must still fire. The
# negative half is the load-bearing one — a false positive costs a re-run, a
# leaking exemption ships a defect as PASS.












#: #798 — the count of `verilogeval_v2/problems.list` LEAF-names (the
#: `ProbNNN_` prefix stripped, i.e. the name a leaking author actually writes)
#: that the digit-shape rule refuses on origin/main. Narrowing that rule to
#: "require an alphabetic tail after the digits" was authored and reverted
#: here because it drops this to 38 — `lemmings1`, `kmap4`, `circuit10`,
#: `fsm3`, `vector5`, `popcount255`, `rule110`, `lfsr32`, `dff8`, `count10`,
#: `shift18` and 36 more. These floors exist so the next narrowing cannot be
#: silent. RAISING them is fine; lowering one is a coverage loss that must be
#: argued in the PR, not absorbed.
#:
#: SCOPE — both of these pin the DIGIT-SHAPE rule and NOTHING ELSE. All 85 and
#: all 91 are refused with "benchmark-leaf-name shape"; no VerilogEval leaf-name
#: has an unbroken alphanumeric run over 30 characters, so deleting the
#: run-length cap outright leaves both numbers untouched. Do not read a green
#: `_VE_LEAF_*` as evidence about the run-length cap — see
#: `_CVDP_LEAF_RUN_FLOOR` for the constant that covers that rule.
_VE_LEAF_FLOOR = 85
_VE_LEAF_CONCAT_FLOOR = 91

#: #798 — the CVDP DESIGN leaf-name floor, and the one number in this change
#: that went DOWN. Over the 229 unique CVDP design leaf-names (a cell id minus
#: its `cvdp_<track>_` prefix and `_NNNN` ordinal, harvested from tracked paths
#: AND file contents) origin/main catches 14 and this branch catches 8. The six
#: freed are all separator-bearing names longer than 30 characters, which the
#: old total-length cap refused as a side effect:
#:     arithmetic_progression_generator        (32)
#:     configurable_digital_low_pass_filter    (36)
#:     reed_solomon_encoder_and_decoder        (32)
#:     secure_read_write_register_bank         (31)
#:     sequencial_binary_to_one_hot_decoder    (36)
#:     write_through_data_direct_mapped_cache  (38)
#: This is DISCLOSED, not repaired. No length or shape discriminator exists —
#: `configurable_digital_low_pass_filter` is 36 chars and
#: `declared_pdk_is_the_pdk_used_check.py` is 37 — and restoring the cap
#: re-creates the 31.49% catch-22 that is the defect being fixed. The class is
#: unguarded by design at the identifier level; the CELL IDS carrying these
#: names remain fully caught by the family branch (126 of the 126 cell ids
#: `git ls-files` yields from tracked PATHS — see the harvest definition in
#: `enhancement_emit.py`; contents are excluded because this commit's own tests
#: add cell-id literals and a contents-inclusive count would measure itself).
#: The floor is here so the NEXT change cannot lower it without saying so.
#:
#: SCOPE — this constant pins the DIGIT-SHAPE rule's residue, NOT the
#: run-length cap that this commit authored. All 8 survivors are refused with
#: "benchmark-leaf-name shape"; replace `if len(longest) > 30:` with
#: `if False:` and this is still 8, because no raw CVDP leaf-name has an
#: unbroken run over 30 characters — the six the cap freed are 31-38 chars only
#: in TOTAL. A green `_CVDP_LEAF_FLOOR` is therefore no evidence at all about
#: the run-length cap; `_CVDP_LEAF_RUN_FLOOR` below is.
_CVDP_LEAF_FLOOR = 8

#: #798 — the floor that the RUN-LENGTH CAP itself owns, and the reason it is
#: measured on the separator-STRIPPED corpus: strip the separators and the six
#: freed names become unbroken runs again (`writethroughdatadirectmappedcache`
#: is 33 characters), which is exactly the concatenation the cap exists to
#: refuse. Counted by RULE ATTRIBUTION — only refusals whose message says
#: "unbroken alphanumeric run" count — so a broadening of the digit-shape rule
#: can never silently satisfy this floor on the run-length rule's behalf.
#: Deleting the cap takes it 3 -> 0.
_CVDP_LEAF_RUN_FLOOR = 3

#: #798 — the same separator-stripped corpus counted in aggregate: 14
#: digit-shape + the 3 above. Held at its origin/main value of 17 (there the 3
#: came from the total-length cap), which is what makes it the non-weakening
#: pin for concatenation. Deleting the run-length cap takes it 17 -> 14.
_CVDP_LEAF_CONCAT_FLOOR = 17


def _repo_root():
    """The Git checkout that carries the plugin source being tested.

    Published benchmark data is now a separate checkout, so the presence of
    ``benchmark-data/evaluation`` can no longer identify the Vibe source tree.
    Ask Git instead; this keeps the source half of the measured union visible
    when the corpus is supplied through ``VIBE_IC_BENCHMARK_DATA``.
    """
    import subprocess as _sp
    probe = _sp.run(
        ["git", "-C", str(Path(__file__).resolve().parent),
         "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=30)
    if probe.returncode != 0 or not probe.stdout.strip():
        return None
    return Path(probe.stdout.strip()).resolve()


# ── WHERE THE BENCHMARK CORPORA LIVE NOW ────────────────────────────────────
# The datasets these negative controls are measured against — the VerilogEval-v2
# problem list, the RTLLM `pass_at_1.json` runs, and the tracked paths that
# carry CVDP cell ids — moved out of this repository with the rest of the
# published benchmark data (vibeic/benchmark-data). Nothing about the FLOORS
# changed: they are still counted over the same names, so they are resolved
# here through `_published_corpus` instead of through this checkout alone.
#
# MEASURED on this branch, which is why the harvest is a UNION of the two trees
# rather than a swap of one for the other — the ids live on BOTH sides, in
# plugin source comments and fixtures as well as in benchmark run dirs:
#
#     tracked-PATH cvdp cell ids   vibe-ic  96   benchmark-data  63   union 126
#     cvdp design leaf-names       vibe-ic 226   benchmark-data 182   union 229
#
# The published repository may intentionally withdraw obsolete or untrustworthy
# run directories.  Such a withdrawal must not silently shrink these security
# negative controls.  The exact 126 path ids and 229 leaf names measured at the
# two commits named below are therefore retained as immutable TEST INPUT in
# ``fixtures/cvdp_negative_control_population.json``.  It is not benchmark
# evidence and cannot make a benchmark run PASS.
def _corpus_tree():
    """The published benchmark-data tree, or None when there is none here."""
    return corpus_root()


def _harvest_trees():
    """Every distinct git tree to harvest cvdp ids from: this checkout, plus
    the benchmark-data corpus when it is a SEPARATE checkout (in a tree that
    still carries the corpus in-repo, `git ls-files` already covers it and
    listing it twice would only walk the same files again)."""
    trees = []
    repo = _repo_root()
    if repo is not None:
        trees.append(repo)
    corpus = _corpus_tree()
    if corpus is not None:
        inside = repo is not None and (
            corpus == repo or repo in corpus.resolve().parents)
        if not inside:
            trees.append(corpus)
    return trees


def _verilogeval_problem_lists():
    """The canonical versioned problem list, proving siblings agree.

    ``problems.list`` belongs to a benchmark RUN now, not to the family
    directory.  Selecting one version by name would replace one stale path
    with another; require every published copy to agree byte-for-byte and then
    return that common body.
    """
    corpus = _corpus_tree()
    sources = sorted(
        (corpus / "evaluation/verilogeval_v2").glob("v*/problems.list"))
    assert sources, (
        f"the published benchmark corpus is present at {corpus} but the "
        "versioned VerilogEval-v2 problem lists are missing")
    bodies = {source.read_bytes() for source in sources}
    assert len(bodies) == 1, (
        "published VerilogEval-v2 runs disagree on their problem population: "
        f"{[str(p.relative_to(corpus)) for p in sources]}")
    return next(iter(bodies)).decode(errors="replace")


def _verilogeval_leaf_names():
    import re as _re2
    probs = [line.strip() for line in _verilogeval_problem_lists().splitlines()
             if line.strip()]
    return probs, [_re2.sub(r"^Prob\d+_", "", p) for p in probs]


def _cvdp_negative_control_population():
    """Load and authenticate the historical CVDP negative-control inputs.

    The cardinalities, source commits and hashes are fixed deliberately: a
    corpus cleanup may remove published run artefacts, but it may not erase the
    adversarial names that prove this guard still catches the original class.
    """
    expected_sources = {
        "benchmark_data_commit": "ac2ae519f484bd9835bb2df5f563da0b2cec0925",
        "vibe_ic_commit": "c8c2ab0f75",
    }
    expected = {
        "design_leaf_names": (
            229,
            "bffe64d4ab162e491a36c86160760d5ecbd10ad6166c63172020dbe7e725ae9a"),
        "tracked_path_cell_ids": (
            126,
            "ed8f0e49eb695bc31f457d1359e0fd9090a0b795ba9802b5a35bf7a96b8bc649"),
    }
    data = json.loads(_CVDP_NEGATIVE_CONTROL_FIXTURE.read_text())
    assert data.get("schema_version") == 1, "unexpected CVDP fixture schema"
    assert data.get("sources") == expected_sources, (
        "CVDP negative-control fixture source commits changed")
    for field, (count, digest) in expected.items():
        values = data.get(field)
        assert isinstance(values, list), f"CVDP fixture {field} is not a list"
        assert values == sorted(set(values)), (
            f"CVDP fixture {field} must be sorted and unique")
        assert len(values) == count, (
            f"CVDP fixture {field} has {len(values)} entries, expected {count}")
        actual = hashlib.sha256(("\n".join(values) + "\n").encode()).hexdigest()
        assert data.get(f"{field}_sha256") == digest == actual, (
            f"CVDP fixture {field} digest mismatch: {actual}")
    return data


def _cvdp_design_leaf_names():
    """Cell id minus its `cvdp_<track>_` prefix and `_NNNN` ordinal — the
    DESIGN name, which is what a leaking author writes when the record is
    about the design rather than the dataset row."""
    import re as _re4, subprocess as _sp
    trees = _harvest_trees()
    if not trees:
        pytest.skip("benchmark-data/ not in this checkout (plugin-only install)")
    # Harvest over every GIT-TRACKED file, not just benchmark-data/: these ids
    # also appear in plugin source comments and fixtures, and scoping the sweep
    # narrower than the reported measurement would pin a floor against a
    # different corpus than the one the change was measured on (182 vs 229).
    cell = _re4.compile(r"cvdp_(?:copilot|agentic)_([A-Za-z0-9_]*?)_\d{4}")
    leaves = set(_cvdp_negative_control_population()["design_leaf_names"])
    for root in trees:
        try:
            # 30s, not 120: `ci_harness_timeout_ceiling_check` caps an inner
            # subprocess bound at harness//3 = 60s, because a longer one
            # outlives the 180s pytest harness and kills the SESSION instead of
            # the test. Measured here: 0.01s for 21216 tracked files.
            tracked = _sp.run(["git", "-C", str(root), "ls-files"],
                              capture_output=True, text=True,
                              timeout=30).stdout.split()
        except (OSError, _sp.SubprocessError):  # pragma: no cover - env-dependent
            pytest.skip("git not available to enumerate the tracked corpus")
        if not tracked:
            pytest.skip("not a git checkout — cannot enumerate the tracked corpus")
        for rel in tracked:
            leaves.update(cell.findall(rel))
            f = root / rel
            try:
                if f.is_file() and f.stat().st_size <= 4_000_000:
                    leaves.update(cell.findall(f.read_text(errors="ignore")))
            except OSError:
                pass
    return sorted(x for x in leaves if x)












#: #798 — the tracked-PATHS cell-id corpus size at the sha that authored this
#: change. A FLOOR, not an equality: the tree gains benchmark run dirs, so this
#: number only ever grows, and the claim that survives corpus growth is the
#: ratio, not the count. Present so the cardinal quoted in `enhancement_emit.py`
#: is re-derived by RUNNING the suite instead of trusted as prose.
_CVDP_CELL_ID_PATH_CORPUS_FLOOR = 126


def _cvdp_cell_ids_in_tracked_paths():
    """The harvest definition quoted in `enhancement_emit.py`, executable.
    PATHS ONLY — including file contents makes the corpus self-referential,
    since this module itself contains cell-id literals."""
    import re as _re5, subprocess as _sp2
    trees = _harvest_trees()
    if not trees:
        pytest.skip("benchmark-data/ not in this checkout (plugin-only install)")
    rx = _re5.compile(r"cvdp_(?:copilot|agentic)_[A-Za-z0-9_]*?_\d{4}")
    ids: set[str] = set(
        _cvdp_negative_control_population()["tracked_path_cell_ids"])
    for root in trees:
        try:
            tracked = _sp2.run(["git", "-C", str(root), "ls-files"],
                               capture_output=True, text=True,
                               timeout=30).stdout.split()
        except (OSError, _sp2.SubprocessError):  # pragma: no cover - env-dependent
            pytest.skip("git not available to enumerate the tracked corpus")
        if not tracked:
            pytest.skip("not a git checkout — cannot enumerate the tracked corpus")
        for rel in tracked:
            ids.update(rx.findall(rel))
    return sorted(ids)








def test_vocabulary_allowlist_categories_are_pinned():
    """#798 — the digit-shape rule's false positives are cleared HERE rather
    than by narrowing the rule, so these two categories are load-bearing.
    Literals plus set equality: deleting an entry must break this test rather
    than silently delete its own coverage."""
    import yaml as _yaml
    data = _yaml.safe_load(
        (_PROGRAMS_DIR / "industry_tech_allowlist.yaml").read_text())
    cats = data["categories"]
    assert set(cats["protocol_generation"]["entries"]) == {
        "ahb3", "ahb5", "apb3", "apb4", "arinc429", "axi3", "axi4",
        "ddr3", "ddr4", "ddr5", "gddr6", "hbm3", "jesd204", "lpddr4",
        "lpddr5", "milstd1553", "pcie3", "pcie4", "pcie5", "psi5", "rs485",
        "usb2", "usb3", "usb4",
    }, "protocol_generation changed without updating this pin"
    assert set(cats["encoding_and_width"]["entries"]) == {
        "base64", "bf16", "crc8", "crc16", "crc32", "crc64",
        "float16", "float32", "float64", "fp8", "fp16", "fp32",
        "int8", "int16", "int32", "int64", "md5", "sha1", "sha256", "sha512",
        "uint8", "uint16", "uint32", "utf8", "utf16", "utf32",
    }, "encoding_and_width changed without updating this pin"
