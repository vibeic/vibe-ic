"""Universal protocol-detector no-misfire guard (captured v0.1.93).

THE COMPOUNDING ARTIFACT of the Tier-D/E/F protocol sweeps. Instead of a
hand-written per-tier sweep for each new batch (test_tier_d/e/f_*), this test
AUTO-DISCOVERS every module-level ``is_<stem>`` detector exported by a
``<stem>_protocol_synth.py`` and asserts each fires ONLY on its own benchmark's
content. Any future protocol that follows the convention (module-level
``is_<stem>`` in ``<stem>_protocol_synth.py``) is covered with ZERO new test code.

Why this exists — the v0.1.89 KEY LESSON, re-earned in v0.1.93:
  A content-only protocol detector can silently over-fire on a FOREIGN benchmark
  because the runner enumerates a generic bus vocabulary (``AXI/APB/AHB/Wishbone/
  Avalon/TileLink/OCP/...``) and L9 interface_types regexes that inject protocol
  NAME tokens into other docs' generated L-docs. A detector keyed on a name-token
  alone then fires on docs that merely *list* it as a candidate interface, and —
  because the synth force-overwrites to 0 gated — parity (which excludes
  SHAPE_MISMATCH per R28 and lists per R32) never reveals it. The v0.1.93 sweep
  caught ``is_avalon`` firing on ethercat/hdlc/modbus exactly this way. A
  full-content no-misfire sweep is the only thing that catches it.

Coverage note (honest, v0.2.32 / ORGANIC-20260531 CLOSED for importability):
EVERY ``<stem>_protocol_synth.py`` now exports a module-level ``is_<stem>``
predicate (pinned by ``test_all_protocol_synth_detectors_importable.py``), so
this guard auto-DISCOVERS all of them — the old "~47 inline, not importable"
gap is gone. v0.2.34 then HARDENED the last 34 ordering-dependent detectors
standalone-clean (foreign-primary-defer, general structural signatures only),
so the residual partition (see the banner below) is now EMPTY: EVERY discovered
detector is held to the STRICT no-foreign-fire assertion across all three blob
models, with 0 foreign fires on the real corpus.

THE BLOB HAS A SPECIFIED BYTE LAYOUT (vibe-ic#1444)
---------------------------------------------------
Until this was fixed, ``_blob_for`` joined two RAW ``glob.glob`` results. That
call does not sort, so the blob's byte layout was whatever the filesystem
returned — and three of the discovered detectors ask a question about
``low[:3500]``. A head-window predicate over an unsorted concatenation answers a
question about readdir order, not about the documents, so WHICH misfires this
sweep caught was decided per host. Measured on the real corpus at the time of
the fix: ``glob.glob`` output was NOT sorted here, and PR #1435's genuine
MDIO-on-EtherCAT misfire was invisible to this sweep on this machine while
being red on another, at the same commit.

Sorting alone would only have frozen the lottery into one arbitrary draw, so
this guard now does BOTH:

  * the sweep runs over a PINNED ordering (both groups name-sorted, which makes
    ``_blob_for`` byte-identical to the canonical program
    ``protocol_detector_no_misfire_matrix.blob_for`` — the two had silently
    diverged) and again REVERSED, failing if EITHER misfires; and
  * the detectors that can actually notice the order — decided by reading their
    BYTECODE, not their comments — are bracketed EXHAUSTIVELY: every document
    that a directory read could put first gets to lead, and a foreign fire under
    ANY of them fails.

Measured when that arm was added: sorted and reversed each report ZERO misfires
on this corpus, while the exhaustive bracket reaches ``is_mdio`` on ``ethercat``
under 4 of 24 leading documents (PR #1435's bug) and on ``ethernet`` under 12 of
24 (#1329's bug). Two canonical orderings are a coin flip; the bracket is not.
"""
import glob
import importlib
import os
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent
from _plugin_tree import repo_path_or_missing  # noqa: E402
# The canonical program for this matrix: it owns the ordering model and the
# order-sensitivity classifier so the guard and the CLI cannot drift apart
# (vibe-ic#1444 was exactly that drift — the program sorted, the guard did not).
import protocol_detector_no_misfire_matrix as _matrix  # noqa: E402

# This module, for the tests that need to rebind BP onto a tmp corpus.
_this = sys.modules[__name__]
# flow #486: benchmark_phase1/ is a repo-root-only private corpus absent on
# the flattened cache; resolve defensively (non-existent path there) so the
# synthetic-fixture fallback / skipif guards take over instead of IndexError.
# The real private corpus, when present.
_REAL_BP = repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")
# A small, self-contained synthetic corpus committed under tests/fixtures/ so this
# guard ACTUALLY RUNS (fires-on-own + no-misfire-on-foreign) without the private
# benchmark_phase1/. The real dir wins when it exists; otherwise we fall back to the
# synthetic one (a handful of representative protocols, chip-AGNOSTIC structural specs).
_SYNTHETIC_BP = Path(__file__).resolve().parent / "fixtures" / "synthetic_benchmark_phase1"
BP = _REAL_BP if _REAL_BP.is_dir() else _SYNTHETIC_BP


def _discover_detectors():
    """{stem: callable} for every <stem>_protocol_synth.py exposing is_<stem>."""
    found = {}
    for p in sorted(PROGRAMS_DIR.glob("*_protocol_synth.py")):
        stem = p.name[: -len("_protocol_synth.py")]
        try:
            mod = importlib.import_module(f"{stem}_protocol_synth")
        except Exception:
            continue
        fn = getattr(mod, f"is_{stem}", None)
        if callable(fn):
            found[stem] = fn
    return found


def _doc_groups(b: str):
    """(head_group, tail_group) for benchmark ``b`` — both NAME-SORTED.

    vibe-ic#1444: the blob is the concatenation of two globs, and a directory
    read may permute the members WITHIN each group but can never interleave the
    two. So the blob HEAD — what a ``low[:3500]`` subject-dominance check reads
    — is drawn from the first non-empty group, and sorting is what turns "the
    layout the filesystem happened to give us" into a stated one.

    The input_doc glob stays ``*`` (not ``*.txt``/``*.md``): this sweep is
    deliberately the strictest SUPERSET blob. On the real corpus every
    input_doc file is a ``.txt``, so the sorted result is byte-identical to
    ``protocol_detector_no_misfire_matrix.blob_for(..., "superset")`` — pinned
    by ``test_blob_matches_the_canonical_program_builder`` below.
    """
    inp = sorted(glob.glob(str(BP / b / "phase1" / "input_doc" / "*")))
    gen = sorted(glob.glob(str(BP / b / "phase1" / "generated_docs" / "*.json")))
    if not inp:
        # No source spec at all: the generated L-docs ARE the head group, and
        # the head is whichever one readdir returns first. The "input_doc-FIRST,
        # so the head is the source spec's title/abstract" premise the
        # head-window detectors cite does not hold for these benchmarks.
        return gen, []
    return inp, gen


def _blob_for(b: str, lead: str = None, reverse: bool = False) -> str:
    """The content-superset blob, in a SPECIFIED byte layout (vibe-ic#1444).

    ``lead`` hoists one document of the head group to the front — the single
    degree of freedom a directory read has over the blob head. ``reverse`` reads
    both groups in descending name order. Neither changes the file SET.
    """
    head, tail = _doc_groups(b)
    if reverse:
        head, tail = head[::-1], tail[::-1]
    if lead is not None and lead in head:
        head = [lead] + [p for p in head if p != lead]
    parts = []
    for p in head + tail:
        try:
            parts.append(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)


def _runner_blob_for(b: str) -> str:
    """The runner's ACTUAL detection blob: L1+L2 generated docs plus the
    input_doc augmentation (the ``_spi_blob``/``_t3_blob``/``_tc_aug`` the
    inline detectors saw). Far narrower than the ``_blob_for`` superset — used
    only for the own-fire fallback so an ordering-dependent detector whose
    own-fire depends on the narrow blob (its sibling-MUTEX defers under the
    token-injected superset) still proves it fires on its own benchmark."""
    parts = []
    for n in ("L1_DATASHEET.json", "L2_FRS.json"):
        q = BP / b / "phase1" / "generated_docs" / n
        if q.is_file():
            try:
                parts.append(q.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    idir = BP / b / "phase1" / "input_doc"
    if idir.is_dir():
        for f in sorted(idir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".txt", ".md", ".json"):
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
    return "\n".join(parts)


DETECTORS = _discover_detectors()

# Known DERIVED-SIBLING cross-fires (documented force-overwrite-ordering pairs).
# A derived protocol shares its parent's structural base, so the parent's
# content-only detector LEGITIMATELY fires on the derived benchmark; the runner
# resolves this by running the derived synth AFTER the parent synth and
# force-overwriting (the cross-protocol force-overwrite doctrine — cf.
# NVMe-on-PCIe, I3C-extends-I2C, SAS⟂SATA, QSPI⟂SPI).
# CANONICAL SOURCE: protocol_detector_lib.DERIVED_SIBLING_CROSS_FIRES (v0.1.95)
# — do not duplicate; the Tier-E guard imports the same set.
from protocol_detector_lib import (  # noqa: E402
    DERIVED_SIBLING_CROSS_FIRES as KNOWN_DERIVED_SIBLING_CROSS_FIRES,
)

# ---------------------------------------------------------------------------
# ORGANIC-20260531 partition — CLOSED (v0.2.34).
#
# The v0.1.93 .. v0.1.94 detectors that ship a module-level ``is_<stem>`` were
# each authored standalone-clean: they pass this STRICT superset+isolation sweep
# (input_doc + every generated L-doc, each benchmark in isolation, no runner
# ordering) with ZERO foreign fires. Verified: the original 40 module-level
# detectors have 0 foreign fires on the real ``benchmark_phase1/`` corpus.
#
# ORGANIC-20260531 lifted the remaining ~46 detectors out of the runner's INLINE
# branches into importable module-level ``is_<stem>`` so this guard could cover
# them too (and so the registry guard
# ``test_all_protocol_synth_detectors_importable.py`` can pin the 1:1 invariant).
# 12 of those were immediately superset-standalone-clean; the other 34 were
# ORDERING-DEPENDENT — runner-safe via force-overwrite, but as STANDALONE superset
# predicates they over-fired because the runner's generic interface vocabulary
# injects sibling tokens into foreign benchmarks' generated L-docs.
#
# v0.2.34 HARDENED ALL 34 standalone-clean (the ``is_mipi`` / ``is_avalon``
# subject-dominance + sibling-MUTEX pattern): each grew a foreign-primary-defer
# keyed on the dominant subject's GENERAL structural signature (protocol tokens,
# frame/register/channel names, relative density counts — ZERO benchmark-name /
# chip / SKU literals, adversarially grep-verified). The two gold-model residuals
# that surfaced on top of the superset sweep were resolved correctly: ddr's
# DDR4/DDR5 generation sibling-MUTEX (dominant-density defer) and cxl's UCIe-primary
# defer; (ace, ace_chi) is a correct same-subject gold fire (ace_chi's gold subject
# IS the ACE coherency protocol) and is allowlisted in
# protocol_detector_no_misfire_matrix.ACCEPTABLE_GOLD_SUBCLAUSE_FIRES.
#
# The partition is now EMPTY (below): EVERY discovered detector is held to the
# STRICT no-foreign-fire assertion on all three blob models. 0 foreign fires
# across the real ``benchmark_phase1/`` corpus.
# ---------------------------------------------------------------------------
# The ordering-dependent set is now EMPTY — kept as a named symbol (imported by
# the matrix guard) so a FUTURE newly-lifted detector that is not yet
# standalone-clean can be parked here again, but every current detector is held
# strictly.
# ORGANIC-20260531 residual CLOSED (v0.2.34): all 36 formerly ordering-dependent
# detectors were hardened STANDALONE-CLEAN — each grew a foreign-primary-defer
# (mirroring is_mipi) keyed on the dominant subject's GENERAL structural signature
# (protocol tokens, frame/register/channel names, density counts; ZERO
# benchmark-name / chip / SKU literals — adversarially grep-verified). The
# partition is now EMPTY: EVERY discovered detector is held to the STRICT
# no-foreign-fire assertion below, on all three blob models (superset / generated
# / gold). Verified 0 foreign fires across the real benchmark_phase1/ corpus.
NEWLY_LIFTED_ORDERING_DEPENDENT: set = set()


def test_at_least_the_known_module_level_detectors_are_discovered():
    # Tier-E + Tier-F shipped module-level detectors; guard against an import
    # regression silently emptying the discovery set (which would make the
    # no-misfire test vacuously pass).
    expected = {
        "flexray", "displayport", "jesd204", "smbus_pmbus",   # Tier-E
        "sas", "avalon", "hyperbus", "qspi_ospi", "mipi_spmi_rffe",  # Tier-F
    }
    missing = expected - set(DETECTORS)
    assert not missing, f"expected module-level detectors not discovered: {missing}"


def test_every_detector_is_callable_and_empty_safe():
    for stem, fn in DETECTORS.items():
        assert fn("") is False, f"is_{stem}('') should be False"
        assert fn(None) is False, f"is_{stem}(None) should be False"  # type: ignore[arg-type]


def _ensure_synthetic_corpus():
    """Materialize the committed synthetic corpus if it was cleaned (defensive)."""
    if _REAL_BP.is_dir() or _SYNTHETIC_BP.is_dir():
        return
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
        from synthetic_protocol_blobs import build_synthetic_benchmark_phase1
        build_synthetic_benchmark_phase1(_SYNTHETIC_BP)
    except Exception:
        pass


_ensure_synthetic_corpus()


def _all_blobs(reverse: bool = False):
    """{benchmark: blob} for every benchmark that has any content.

    Built in ONE pass — the pre-#1444 sweep built each blob twice (once to test
    it was non-empty, once to keep it), and the sweep is the slowest item in
    this file against a 180 s harness bound.
    """
    out = {}
    for d in sorted(os.listdir(BP)):
        if not (BP / d).is_dir():
            continue
        blob = _blob_for(d, reverse=reverse)
        if blob:
            out[d] = blob
    return out


def _present_benchmarks():
    """Benchmarks that carry at least one document (no blob read needed)."""
    out = []
    for d in sorted(os.listdir(BP)):
        if not (BP / d).is_dir():
            continue
        head, tail = _doc_groups(d)
        if head or tail:
            out.append(d)
    return out


def _foreign_fires(blobs, detectors=None):
    """(detector, benchmark) pairs where a detector fires on someone else's
    content, minus the two documented allowlists."""
    detectors = DETECTORS if detectors is None else detectors
    misfires = []
    for stem, fn in detectors.items():
        for b, blob in blobs.items():
            if b == stem or not fn(blob):
                continue
            if (stem, b) in KNOWN_DERIVED_SIBLING_CROSS_FIRES:
                # Documented derived-sibling: parent detector legitimately
                # fires on the derived benchmark; resolved by synth ordering.
                continue
            if stem in NEWLY_LIFTED_ORDERING_DEPENDENT:
                # ORGANIC-20260531 open residual: ordering-dependent
                # detector — runner-safe via force-overwrite, not yet
                # standalone-clean. Tracked, not asserted (see banner).
                continue
            misfires.append((stem, b))
    return sorted(misfires)


# Both canonical orderings are swept and BOTH must be clean — the fix for
# vibe-ic#1444 is not "sort it", it is "stop letting the filesystem pick".
CANONICAL_BLOB_ORDERINGS = ("sorted", "reversed")

# ...and each ordering is split across several pytest ITEMS. This is a harness
# constraint, not a style choice: one full 86x87 sweep measured 108 s quiet and
# 165 s under load on the real corpus, against a CI bound of
# ``--timeout=180 --timeout-method=thread`` — a bound that does not fail the
# TEST, it kills the SESSION and every other file in the subset loses its
# verdict unnamed. Three shards keep the worst item near a third of that.
# The partition is pinned below so a sharding slip cannot silently drop a
# detector out of the sweep.
SWEEP_SHARDS = 3


def _shard_detectors(shard: int):
    return {k: DETECTORS[k] for k in sorted(DETECTORS)[shard::SWEEP_SHARDS]}


def test_sweep_shards_partition_every_discovered_detector():
    """The shards must cover the fleet exactly once — a sweep that quietly
    stopped examining a third of the detectors would still print all-green."""
    covered = []
    for s in range(SWEEP_SHARDS):
        covered.extend(_shard_detectors(s))
    assert sorted(covered) == sorted(DETECTORS), (
        "sweep shards do not partition the discovered detectors: "
        f"{len(covered)} covered vs {len(DETECTORS)} discovered")
    assert len(set(covered)) == len(covered), "a detector is swept twice"


@pytest.mark.skipif(not BP.is_dir(),
                    reason="neither benchmark_phase1/ nor synthetic fixtures present")
@pytest.mark.parametrize("ordering", CANONICAL_BLOB_ORDERINGS)
@pytest.mark.parametrize("shard", range(SWEEP_SHARDS))
def test_no_detector_fires_on_a_foreign_benchmark(shard, ordering):
    """Each auto-discovered detector must fire ONLY on its own benchmark.

    Content SUPERSET (input_doc + every generated L-doc) — stricter than the
    runner's actual blob — so zero foreign fires here ⇒ zero in the runner.

    Swept under BOTH pinned orderings (vibe-ic#1444). Neither is the
    filesystem's: the layout is stated, so this test's verdict is the same on
    every host, and a misfire visible under either one fails.

    Runs against the real private ``benchmark_phase1/`` when present, else against
    the committed synthetic per-protocol fixture (``tests/fixtures/...``) — so the
    no-misfire-on-foreign sweep executes in the shipped tree too.
    """
    blobs = _all_blobs(reverse=(ordering == "reversed"))
    assert blobs, "no benchmark blob could be built — the sweep would be vacuous"
    detectors = _shard_detectors(shard)
    assert detectors, f"shard {shard} is empty — it would pass by examining nothing"
    misfires = _foreign_fires(blobs, detectors)
    assert not misfires, (
        f"protocol detector mis-fires (foreign benchmark, {ordering} blob order) "
        "among the standalone-clean set — a NEW regression, not an "
        f"ORGANIC-20260531 residual: {misfires}"
    )


@pytest.mark.skipif(not BP.is_dir(),
                    reason="neither benchmark_phase1/ nor synthetic fixtures present")
def test_every_detector_fires_on_its_own_benchmark():
    """Each detector whose own benchmark dir is present must self-fire — in
    force for EVERY discovered detector, ordering-dependent or not.

    Own-fire may hold under either pinned superset ordering OR the runner's
    actual narrow blob (L1+L2 + input_doc): an ordering-dependent detector's
    sibling-MUTEX can legitimately defer under the token-injected superset while
    still firing on the runner's real blob (e.g. ahb_apb's AXI-primary defer,
    cxl / nvlink's PCIe-PHY defer). Requiring own-fire under *some* real runner
    blob keeps the honesty check for everyone without a superset-model false
    fail. Accepting EITHER ordering is deliberate: the pre-#1444 sweep accepted
    whichever single layout the filesystem produced, so demanding own-fire under
    one specific layout would be a NEW tightening this fix did not measure.
    """
    present = set(_present_benchmarks())
    for stem, fn in DETECTORS.items():
        if stem not in present:
            continue
        ok = (fn(_blob_for(stem))
              or fn(_blob_for(stem, reverse=True))
              or fn(_runner_blob_for(stem)))
        assert ok, f"is_{stem} failed to fire on its own benchmark"


# ---------------------------------------------------------------------------
# THE HEAD-WINDOW LOTTERY, ENUMERATED INSTEAD OF SAMPLED (vibe-ic#1444)
# ---------------------------------------------------------------------------
# Pinning the order stops the verdict moving between hosts, but on its own it
# would just freeze ONE draw of the lottery. So the detectors that can notice
# the order at all get the complete treatment: every document a directory read
# could put first gets to lead, and a foreign fire under ANY of them counts.
#
# MEASURED when this was written, on the real 87-benchmark corpus: the sorted
# and reversed sweeps above each find ZERO misfires, while this bracket reaches
# TWO — and both are already-filed bugs that the two-ordering sweep cannot see:
#
#   is_mdio on ethercat   4 of 24 leading documents   (PR #1435)
#   is_mdio on ethernet  12 of 24 leading documents   (vibe-ic#1329)
#
# They are enumerated here, not silenced: this arm is strictly ADDITIVE (before
# it, the sweep caught NEITHER on this host), and any THIRD pair fails. The
# entries come out as their issues land — they are the work list, not a waiver.
# Keyed (detector, benchmark), same shape as the allowlists above.
HEAD_WINDOW_LEAD_DEPENDENT_MISFIRES = {
    ("mdio", "ethercat"),   # PR #1435 — MDIO-on-EtherCAT
    ("mdio", "ethernet"),   # vibe-ic#1329 — MDIO-on-Ethernet
}


def _order_sensitive_detectors():
    """{stem: reason} — detectors whose verdict can move with the byte layout.

    Delegates to the canonical program so there is ONE classifier. It reads
    BYTECODE and fails SENSITIVE on anything it cannot resolve, so a detector
    is never excluded from the bracket because a comment said it was safe.
    """
    return _matrix.positional_detectors(DETECTORS)


def test_order_sensitive_classifier_is_live_and_conservative():
    """The bracket below is only worth anything if the classifier actually
    finds the head-window family — and only safe if it errs toward including.

    Both directions, on purpose-built controls: a slicing predicate, one that
    slices via a helper, one that uses a position-revealing method, and one that
    is opaque, must all be flagged; a pure token-membership predicate must not.
    """
    def _helper(low):
        return "x" in low[:100]

    def slices(blob):
        return "x" in blob.lower()[:3500]

    def slices_via_helper(blob):
        return _helper(blob.lower())

    def uses_position(blob):
        return blob.lower().find("x") < 3500

    def token_only(blob):
        return "x" in blob.lower() and blob.lower().count("y") > 2

    import sys as _s
    _mod = _s.modules[__name__]
    for fn in (slices, slices_via_helper, uses_position):
        assert _matrix.positional_reason(fn, _mod), (
            f"{fn.__name__} reads a POSITION and must be classed order-sensitive")
    assert _matrix.positional_reason(len), (
        "an opaque callable must fail SENSITIVE, not be silently cleared")
    assert not _matrix.positional_reason(token_only, _mod), (
        "a pure token-membership predicate is permutation-invariant; flagging it "
        "would make the exhaustive bracket cost 86 detectors instead of a handful")

    # ... and it must find the real family, or the bracket is vacuous.
    found = _order_sensitive_detectors()
    assert found, (
        "no discovered detector was classed order-sensitive — the head-window "
        "bracket below would pass by examining nothing")


@pytest.mark.skipif(not BP.is_dir(),
                    reason="neither benchmark_phase1/ nor synthetic fixtures present")
def test_no_order_sensitive_detector_fires_under_any_reachable_leading_document():
    """No head-window detector may fire on a foreign benchmark under ANY
    document order a directory read could produce.

    The bracket is complete for the degree of freedom that matters: the two
    globs are always concatenated in the same GROUP order, so the only thing a
    readdir can change about the blob head is which member of the head group
    comes first — and every one of them is tried.
    """
    sensitive = _order_sensitive_detectors()
    assert sensitive, "classifier found nothing — bracket would be vacuous"
    reachable = {}
    examined = 0
    for b in _present_benchmarks():
        head, _tail = _doc_groups(b)
        if len(head) < 2:
            continue  # one candidate => no freedom => the sweeps above cover it
        for lead in head:
            blob = _blob_for(b, lead=lead)
            examined += 1
            for stem in sensitive:
                if stem == b or (stem, b) in KNOWN_DERIVED_SIBLING_CROSS_FIRES:
                    continue
                if DETECTORS[stem](blob):
                    reachable.setdefault((stem, b), []).append(Path(lead).name)
    assert examined, (
        "no benchmark had more than one candidate leading document — the "
        "bracket examined nothing and its PASS carries no information")
    new = {k: v for k, v in reachable.items()
           if k not in HEAD_WINDOW_LEAD_DEPENDENT_MISFIRES}
    assert not new, (
        "protocol detector mis-fires that a directory order can REACH, outside "
        "the enumerated set — the sweep's verdict on these pairs is decided by "
        f"which document the filesystem returns first: "
        f"{ {k: sorted(v) for k, v in new.items()} } "
        f"(examined {examined} leading-document layouts across "
        f"{len(sensitive)} order-sensitive detector(s): {sorted(sensitive)})"
    )


def test_head_window_residual_names_real_detectors():
    """The enumerated lead-dependent set must name real, discovered detectors —
    so a typo cannot quietly widen it into a blanket waiver."""
    stray = {s for s, _b in HEAD_WINDOW_LEAD_DEPENDENT_MISFIRES
             if s not in DETECTORS}
    assert not stray, (
        f"residual names detectors that are not discovered (stale entries): {stray}")


def test_blob_layout_is_independent_of_directory_iteration_order(tmp_path,
                                                                 monkeypatch):
    """THE REGRESSION TEST for vibe-ic#1444 itself.

    ``_blob_for`` used to join two RAW ``glob.glob`` results, so its output was
    whatever order the filesystem returned. This drives the same directory
    through several iteration orders and requires the blob to come back
    BYTE-IDENTICAL. It fails on the pre-fix builder (which simply echoed the
    order it was handed) and needs no private corpus to do so.
    """
    b = "demo"
    idir = tmp_path / b / "phase1" / "input_doc"
    gdir = tmp_path / b / "phase1" / "generated_docs"
    idir.mkdir(parents=True)
    gdir.mkdir(parents=True)
    for n in ("a_spec.txt", "b_spec.txt", "c_spec.txt"):
        (idir / n).write_text(f"SOURCE {n}\n")
    for n in ("L1_DATASHEET.json", "L2_FRS.json", "L9_INTEGRATION_SPEC.json"):
        (gdir / n).write_text('{"doc": "%s"}\n' % n)

    monkeypatch.setattr(_this, "BP", tmp_path)
    real_glob = glob.glob
    seen = []
    for rotate in range(4):
        def fake_glob(pattern, _r=rotate):
            hits = real_glob(pattern)
            # every readdir order is legal; rotate + reverse to sample several
            hits = hits[_r % max(len(hits), 1):] + hits[:_r % max(len(hits), 1)]
            return hits[::-1] if _r % 2 else hits
        monkeypatch.setattr(glob, "glob", fake_glob)
        seen.append(_blob_for(b))
    assert len(set(seen)) == 1, (
        "the blob's byte layout changed with directory iteration order — a "
        "head-window detector run against it is answering a question about "
        f"readdir, not about the documents. layouts seen: {len(set(seen))}")
    assert seen[0].index("SOURCE a_spec.txt") < seen[0].index("SOURCE c_spec.txt")
    assert seen[0].index("SOURCE c_spec.txt") < seen[0].index("L1_DATASHEET"), (
        "input_doc must still lead the blob — the runner's auto-dispatch order")


@pytest.mark.skipif(not _REAL_BP.is_dir(), reason="private corpus absent")
def test_blob_matches_the_canonical_program_builder():
    """This guard and ``protocol_detector_no_misfire_matrix`` build the SAME
    blob — the program's docstring already claimed ``--blob superset`` "matches
    the pytest guard" while the guard was building an unsorted one.

    A benchmark that ever puts a non-``.txt``/``.md`` file in ``input_doc``
    would break the equality; the assertion is here so that shows up as a named
    divergence instead of two sweeps quietly measuring different things.
    """
    mismatched = [b for b in _present_benchmarks()
                  if _blob_for(b) != _matrix.blob_for(BP, b, "superset")]
    assert not mismatched, (
        "the guard's blob and the canonical program's blob have diverged for: "
        f"{mismatched}")


def test_ordering_dependent_residual_is_a_subset_of_discovered():
    """The ORGANIC-20260531 residual set must name only real, discovered
    detectors — so it cannot silently mask a typo'd / dropped detector, and it
    shrinks (never grows beyond the discovered fleet) as each is hardened."""
    stray = NEWLY_LIFTED_ORDERING_DEPENDENT - set(DETECTORS)
    assert not stray, (
        f"residual names detectors that are not discovered (stale entries): {stray}"
    )
