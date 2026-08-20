#!/usr/bin/env python3
"""The area taxonomy: proxy and physical, and never one standing in for the other.

The negative fixture is the whole reason the lane exists, so it is worth stating
before the code: **a candidate that wins on cell count and loses on post-route
area must not be reported as smaller.** `test_cell_count_win_cannot_beat_a_core_
area_loss` is that sentence.

The numbers used here are not invented. They come from one real completed run,
`/home/reyerchu/_c_cv_spm_run` (spm, gf180mcuD, phase 3 complete):

    synthesis chip area   4703.5296  library area units   phase2/.../stats.json
    post-route core area  12294      um^2                 openroad.log "Design area"
    die area              20164.00   um^2                 routed.def DIEAREA
                                                          142000/1000 squared
    achieved utilisation  59.2       %                    openroad.log DPL-0009 (last)

so the factors the taxonomy protects against (2.61x core, 4.29x die) are
measured, not asserted.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import area as A  # noqa: E402
from _ppa import canonical_json as cj  # noqa: E402

# ── the real run's figures, used as fixture values ───────────────────────────
SYNTH_CELL_AREA = 4703.5296     # lib_area_unit
CORE_UM2 = 12294.0
DIE_UM2 = 20164.0               # (142000/1000)**2
CELL_COUNT = 252

_PHYS_SCOPE = {"stage": "post_route", "corner": "nom", "tool": "openroad"}
_PHYS_SOURCE = {"path": "phase3/stage3/pnr/routed.def", "tool": "openroad",
                "sha256": "sha256:" + "0" * 64, "parser": "test"}
_PROXY_SCOPE = {"stage": "synth_mapped", "tool": "yosys"}
_PROXY_SOURCE = {"path": "phase2/stage2/synth/synth.log", "tool": "yosys",
                 "sha256": "sha256:" + "1" * 64, "parser": "test"}


def _phys(metric, value, scope=None):
    return A.physical_record(metric, A.MEASURED, value=value,
                             scope=scope or _PHYS_SCOPE, source=_PHYS_SOURCE)


def _proxy(metric, value, scope=None):
    return A.proxy_record(metric, A.MEASURED, value=value,
                          scope=scope or _PROXY_SCOPE, source=_PROXY_SOURCE)


# ════════════════════════════════════════════════════════════════════════════
# 1. The taxonomy itself
# ════════════════════════════════════════════════════════════════════════════
class TestTaxonomy:
    def test_every_registered_metric_has_a_known_class_and_a_unit(self):
        """A metric with no class is a metric that can be quietly promoted."""
        assert A.AREA_METRICS
        for name, spec in A.AREA_METRICS.items():
            assert spec.metric_class in A.AREA_CLASSES, name
            assert spec.unit, name
            assert spec.what, name

    def test_only_physical_metrics_are_eligible(self):
        """The eligibility flag is a function of the class and nothing else.

        If this ever becomes conditional on something — a flag, a stage, a
        caller's opinion — the condition is where a proxy gets in.
        """
        for name in A.AREA_METRICS:
            assert A.eligible_for_physical_ppa(name) is A.is_physical(name)

    def test_counts_are_proxies_and_post_route_extents_are_physical(self):
        assert A.classify("area.proxy.cell_count") == A.RTL_PROXY
        assert A.classify("area.proxy.wire_count") == A.RTL_PROXY
        assert A.classify("area.physical.core_um2") == A.PHYSICAL
        assert A.classify("area.physical.die_um2") == A.PHYSICAL

    def test_synthesis_chip_area_is_a_proxy_despite_being_an_area(self):
        """The trap the lane is named after.

        `Chip area for module` is a number with an area unit produced before
        placement exists. On the real run it is 4703.5296 against a post-route
        core of 12294 um^2 — 2.61x out, in a unit the artefact itself declares
        as "cell-library area unit". It is a proxy.
        """
        assert A.classify("area.synth.cell_area") == A.SYNTH_PROXY
        assert A.eligible_for_physical_ppa("area.synth.cell_area") is False
        assert A.unit_of("area.synth.cell_area") == "lib_area_unit"
        assert A.unit_of("area.physical.core_um2") == "um^2"
        assert round(CORE_UM2 / SYNTH_CELL_AREA, 2) == 2.61

    def test_pre_synthesis_estimate_wears_um2_and_is_still_a_proxy(self):
        """The second trap: a proxy in a physical unit."""
        assert A.unit_of("area.estimate.pre_synthesis_um2") == "um^2"
        assert A.classify("area.estimate.pre_synthesis_um2") == A.RTL_PROXY
        assert A.eligible_for_physical_ppa(
            "area.estimate.pre_synthesis_um2") is False

    def test_an_unregistered_metric_is_refused_not_guessed(self):
        """An unknown name is the exact shape of a new proxy arriving."""
        with pytest.raises(A.UnknownAreaMetric):
            A.classify("area.physical.definitely_real_um2")

    def test_metrics_of_class_partitions_the_registry(self):
        seen = []
        for cls in A.AREA_CLASSES:
            seen += A.metrics_of_class(cls)
        assert sorted(seen) == sorted(A.AREA_METRICS)


# ════════════════════════════════════════════════════════════════════════════
# 2. Records — POSITIVE and the ways a record must refuse to be built
# ════════════════════════════════════════════════════════════════════════════
class TestRecords:
    def test_positive_a_measured_physical_record_is_eligible(self):
        rec = _phys("area.physical.core_um2", CORE_UM2)
        assert rec["schema"] == A.SCHEMA
        assert rec["metric_class"] == A.PHYSICAL
        assert rec["eligible_for_physical_ppa"] is True
        assert rec["value"] == CORE_UM2
        assert rec["unit"] == "um^2"
        A.assert_eligible_for_physical_ppa(rec)  # does not raise

    def test_a_measured_proxy_record_is_not_eligible(self):
        rec = _proxy("area.proxy.cell_count", CELL_COUNT)
        assert rec["eligible_for_physical_ppa"] is False
        with pytest.raises(A.IneligibleForPhysicalPPA):
            A.assert_eligible_for_physical_ppa(rec)

    def test_a_proxy_producer_cannot_emit_a_physical_metric(self):
        """Structural, not conventional: the call raises."""
        with pytest.raises(A.IneligibleForPhysicalPPA):
            A.proxy_record("area.physical.core_um2", A.MEASURED,
                           value=1.0, scope=_PHYS_SCOPE, source=_PHYS_SOURCE)

    def test_a_proxy_metric_cannot_be_promoted_through_physical_record(self):
        with pytest.raises(A.IneligibleForPhysicalPPA):
            A.physical_record("area.proxy.cell_count", A.MEASURED,
                              value=1, scope=_PROXY_SCOPE, source=_PROXY_SOURCE)

    def test_not_measured_carries_a_reason_and_no_number(self):
        rec = A.area_record("area.physical.core_um2", A.NOT_MEASURED,
                            reason="the run produced no routed DEF")
        assert "value" not in rec
        assert rec["reason"]
        assert rec["eligible_for_physical_ppa"] is False

    def test_a_zero_is_never_allowed_to_mean_not_measured(self):
        """No numeric sentinels (§2). A 0 must be a real measured 0."""
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.physical.core_um2", A.NOT_MEASURED, value=0,
                          reason="nothing here")

    def test_not_measured_without_a_reason_is_refused(self):
        """'I could not read it' and 'I read it and it was empty' must differ."""
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.physical.core_um2", A.NOT_MEASURED)

    def test_a_measured_number_needs_a_scope_and_a_source(self):
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.physical.core_um2", A.MEASURED, value=1.0,
                          source=_PHYS_SOURCE)
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.physical.core_um2", A.MEASURED, value=1.0,
                          scope=_PHYS_SCOPE)

    def test_derived_must_state_its_formula(self):
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.proxy.cell_count_reduction_pct", A.DERIVED,
                          value=5.0, scope=_PROXY_SCOPE, source=_PROXY_SOURCE)

    def test_a_unit_that_is_not_the_registered_one_is_refused(self):
        """A unit disagreement is a different quantity, not a formatting choice."""
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.synth.cell_area", A.MEASURED,
                          value=SYNTH_CELL_AREA, unit="um^2",
                          scope=_PROXY_SCOPE, source=_PROXY_SOURCE)

    def test_nan_is_not_a_value(self):
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.physical.core_um2", A.MEASURED,
                          value=float("nan"), scope=_PHYS_SCOPE,
                          source=_PHYS_SOURCE)

    def test_estimated_carries_its_value_and_its_assumptions(self):
        rec = A.area_record(
            "area.estimate.pre_synthesis_um2", A.ESTIMATED, value=7560.0,
            scope={"stage": "pre_synthesis", "pdk": "gf180mcuD"},
            assumptions={"formula": "cells * 30.0", "assumes": "a mean cell"})
        assert rec["value"] == 7560.0
        assert rec["assumptions"]
        assert rec["eligible_for_physical_ppa"] is False

    def test_estimated_without_assumptions_is_refused(self):
        with pytest.raises(A.AreaRecordError):
            A.area_record("area.estimate.pre_synthesis_um2", A.ESTIMATED,
                          value=7560.0, scope={"stage": "pre_synthesis"})

    def test_a_physical_metric_can_never_be_estimated(self):
        """§2: ESTIMATED is never final PPA. So the record cannot be built.

        This is what makes a pre-synthesis estimator unadoptable: not a label a
        reader has to check, but a constructor that refuses.
        """
        with pytest.raises(A.IneligibleForPhysicalPPA):
            A.area_record("area.physical.core_um2", A.ESTIMATED, value=7560.0,
                          scope={"stage": "pre_synthesis"},
                          assumptions={"formula": "cells * 30.0"})

    def test_filter_physical_drops_proxies_silently_but_keeps_physicals(self):
        records = [_proxy("area.proxy.cell_count", CELL_COUNT),
                   _phys("area.physical.core_um2", CORE_UM2)]
        kept = A.filter_physical(records)
        assert [r["metric"] for r in kept] == ["area.physical.core_um2"]

    def test_the_digest_goes_through_the_one_serializer(self):
        rec = _phys("area.physical.core_um2", CORE_UM2)
        assert A.digest_of_record(rec) == cj.digest_of(rec)
        assert A.digest_of_record(rec).startswith("sha256:")


# ════════════════════════════════════════════════════════════════════════════
# 3. compare() — comparability is part of the answer
# ════════════════════════════════════════════════════════════════════════════
class TestCompare:
    def test_smaller_larger_equal(self):
        base = _phys("area.physical.core_um2", CORE_UM2)
        assert A.compare(base, _phys("area.physical.core_um2", 12000.0)
                         )["relation"] == A.V_SMALLER
        assert A.compare(base, _phys("area.physical.core_um2", 12500.0)
                         )["relation"] == A.V_LARGER
        assert A.compare(base, _phys("area.physical.core_um2", CORE_UM2)
                         )["relation"] == A.V_EQUAL

    def test_different_metrics_have_no_winner(self):
        r = A.compare(_phys("area.physical.core_um2", CORE_UM2),
                      _phys("area.physical.die_um2", 100.0))
        assert r["relation"] == A.V_UNDETERMINED
        assert r["code"] == A.C_METRIC_MISMATCH

    def test_synthesis_area_is_not_comparable_to_post_route_area(self):
        """The substitution, attempted directly. Same word, different scope."""
        synth = _proxy("area.synth.cell_area", SYNTH_CELL_AREA)
        post = A.proxy_record("area.synth.cell_area", A.MEASURED,
                              value=4000.0,
                              scope={"stage": "post_route", "tool": "yosys"},
                              source=_PROXY_SOURCE)
        r = A.compare(synth, post)
        assert r["relation"] == A.V_UNDETERMINED
        assert r["code"] == A.C_SCOPE_MISMATCH

    def test_scope_equality_is_exact_not_subset(self):
        """A subset rule would make an omitted `stage` key comparable to anything."""
        a = _phys("area.physical.core_um2", CORE_UM2, scope={"stage": "post_route"})
        b = _phys("area.physical.core_um2", 12000.0,
                  scope={"stage": "post_route", "corner": "nom"})
        assert A.scope_matches(a["scope"], b["scope"]) is False
        assert A.compare(a, b)["code"] == A.C_SCOPE_MISMATCH

    def test_an_unmeasured_record_may_not_enter_a_comparison(self):
        base = _phys("area.physical.core_um2", CORE_UM2)
        nm = A.area_record("area.physical.core_um2", A.NOT_MEASURED,
                           reason="no routed DEF")
        r = A.compare(base, nm)
        assert r["relation"] == A.V_UNDETERMINED
        assert r["code"] == A.C_STATUS_NOT_COMPARABLE

    def test_an_estimate_may_not_enter_a_comparison(self):
        base = A.area_record(
            "area.estimate.pre_synthesis_um2", A.ESTIMATED, value=7560.0,
            scope={"stage": "pre_synthesis"}, assumptions={"f": "n*30"})
        cand = A.area_record(
            "area.estimate.pre_synthesis_um2", A.ESTIMATED, value=6000.0,
            scope={"stage": "pre_synthesis"}, assumptions={"f": "n*30"})
        assert A.compare(base, cand)["code"] == A.C_STATUS_NOT_COMPARABLE

    def test_a_record_that_claims_measured_but_carries_no_number(self):
        """Reachable from the CLI, where records are read off disk.

        A hand-written record can say MEASURED and carry nothing. That is an
        UNDETERMINED comparison — not a traceback, and not a finding.
        """
        good = _phys("area.physical.core_um2", CORE_UM2)
        bad = dict(good)
        bad.pop("value")
        r = A.compare(good, bad)
        assert r["relation"] == A.V_UNDETERMINED
        assert r["code"] == A.C_STATUS_NOT_COMPARABLE

    def test_a_record_carrying_a_string_where_a_number_belongs(self):
        good = _phys("area.physical.core_um2", CORE_UM2)
        bad = dict(good, value="12294")
        assert A.compare(good, bad)["code"] == A.C_STATUS_NOT_COMPARABLE

    def test_a_non_positive_baseline_cannot_anchor_a_relative_claim(self):
        base = _phys("area.physical.core_um2", 0.0)
        r = A.compare(base, _phys("area.physical.core_um2", 1.0))
        assert r["code"] == A.C_ZERO_BASELINE


# ════════════════════════════════════════════════════════════════════════════
# 4. area_verdict() — THE NEGATIVE FIXTURE
# ════════════════════════════════════════════════════════════════════════════
class TestVerdict:
    def test_positive_smaller_on_physical_area_is_smaller(self):
        base = [_phys("area.physical.core_um2", CORE_UM2),
                _phys("area.physical.die_um2", DIE_UM2)]
        cand = [_phys("area.physical.core_um2", 11000.0),
                _phys("area.physical.die_um2", 19000.0)]
        doc = A.area_verdict(base, cand)
        assert doc["verdict"] == A.V_SMALLER
        assert doc["code"] == A.C_OK

    def test_cell_count_win_cannot_beat_a_core_area_loss(self):
        """THE negative fixture named in the lane brief.

        The candidate has FEWER CELLS (200 vs 252 — a 20.6% proxy win) and a
        LARGER post-route core (12800 vs 12294 um^2 — a 4.1% physical loss).
        That is a real shape: fewer, bigger cells, or the same logic placed at a
        worse density. It must not be reported as smaller, and the reason must
        name the substitution it refused rather than just saying "no".
        """
        base = [_phys("area.physical.core_um2", CORE_UM2),
                _proxy("area.proxy.cell_count", CELL_COUNT)]
        cand = [_phys("area.physical.core_um2", 12800.0),
                _proxy("area.proxy.cell_count", 200)]

        doc = A.area_verdict(base, cand)

        assert doc["verdict"] != A.V_SMALLER
        assert doc["verdict"] == A.V_LARGER
        assert doc["code"] == A.C_NOT_SMALLER
        # the proxy win was seen, recorded, and refused — not ignored
        proxy = doc["proxy_comparisons_advisory"]
        assert [c["metric"] for c in proxy] == ["area.proxy.cell_count"]
        assert proxy[0]["relation"] == A.V_SMALLER
        assert "area.proxy.cell_count" in doc["reason"]
        assert "substitution" in doc["reason"]

    def test_a_proxy_win_alone_is_undetermined_never_smaller(self):
        """No post-route evidence at all. The answer is "I do not know"."""
        base = [_proxy("area.proxy.cell_count", CELL_COUNT),
                _proxy("area.proxy.wire_count", 226)]
        cand = [_proxy("area.proxy.cell_count", 100),
                _proxy("area.proxy.wire_count", 90)]
        doc = A.area_verdict(base, cand)
        assert doc["verdict"] == A.V_UNDETERMINED
        assert doc["code"] == A.C_PROXY_ONLY
        assert len(doc["proxy_comparisons_advisory"]) == 2
        assert doc["physical_comparisons"] == []

    def test_a_synthesis_area_win_alone_is_also_undetermined(self):
        """The near-miss: an area-shaped proxy is still a proxy."""
        base = [_proxy("area.synth.cell_area", SYNTH_CELL_AREA)]
        cand = [_proxy("area.synth.cell_area", 3000.0)]
        doc = A.area_verdict(base, cand)
        assert doc["verdict"] == A.V_UNDETERMINED
        assert doc["code"] == A.C_PROXY_ONLY

    def test_equal_physical_area_is_not_smaller(self):
        base = [_phys("area.physical.core_um2", CORE_UM2)]
        cand = [_phys("area.physical.core_um2", CORE_UM2)]
        doc = A.area_verdict(base, cand)
        assert doc["verdict"] == A.V_EQUAL
        assert doc["code"] == A.C_NOT_SMALLER

    def test_disagreeing_physical_metrics_are_undetermined(self):
        """Smaller die, bigger core. Two answers is not an answer."""
        base = [_phys("area.physical.core_um2", CORE_UM2),
                _phys("area.physical.die_um2", DIE_UM2)]
        cand = [_phys("area.physical.core_um2", 13000.0),
                _phys("area.physical.die_um2", 19000.0)]
        doc = A.area_verdict(base, cand)
        assert doc["verdict"] == A.V_UNDETERMINED
        assert doc["code"] == A.C_DISAGREEING_PHYSICAL

    def test_no_shared_metric_is_undetermined_not_smaller(self):
        doc = A.area_verdict([_phys("area.physical.core_um2", CORE_UM2)],
                             [_phys("area.physical.die_um2", 1.0)])
        assert doc["verdict"] == A.V_UNDETERMINED
        assert doc["code"] == A.C_NO_PHYSICAL_EVIDENCE

    def test_an_empty_record_set_is_undetermined_not_smaller(self):
        """A read that found nothing is not a pass."""
        doc = A.area_verdict([], [])
        assert doc["verdict"] == A.V_UNDETERMINED
        assert doc["code"] == A.C_NO_PHYSICAL_EVIDENCE

    def test_no_input_can_make_a_proxy_produce_a_smaller_verdict(self):
        """The rule, asserted over the whole proxy half of the registry.

        Every proxy metric, on its own, with the candidate winning by a mile.
        None of them may return SMALLER. If a future metric is added to a proxy
        class and this test still passes, the rule survived the addition.
        """
        proxies = [m for m in A.AREA_METRICS if not A.is_physical(m)]
        assert len(proxies) >= 6
        for metric in proxies:
            scope = {"stage": "whatever", "tool": "t"}
            base = A.proxy_record(metric, A.MEASURED, value=1000.0,
                                  scope=scope, source=_PROXY_SOURCE)
            cand = A.proxy_record(metric, A.MEASURED, value=1.0,
                                  scope=scope, source=_PROXY_SOURCE)
            doc = A.area_verdict([base], [cand])
            assert doc["verdict"] != A.V_SMALLER, metric
            assert doc["verdict"] == A.V_UNDETERMINED, metric


# ════════════════════════════════════════════════════════════════════════════
# 5. The CLI — exit codes, including the VACUOUS fixture
# ════════════════════════════════════════════════════════════════════════════
def _write(tmp_path, name, records):
    p = tmp_path / name
    p.write_text(json.dumps(records), encoding="utf-8")
    return str(p)


def _run(*args):
    """Run the module as a subprocess so the real exit code is observed."""
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "_ppa" / "area.py"), *args],
        capture_output=True, text=True)


class TestCli:
    def test_rc0_when_physically_smaller(self, tmp_path):
        b = _write(tmp_path, "b.json", [_phys("area.physical.core_um2", CORE_UM2)])
        c = _write(tmp_path, "c.json", [_phys("area.physical.core_um2", 11000.0)])
        r = _run("--baseline", b, "--candidate", c)
        assert r.returncode == 0, r.stderr
        assert "SMALLER" in r.stdout

    def test_rc1_is_a_finding_about_the_design(self, tmp_path):
        """A cell-count win with a core-area loss exits 1, not 0."""
        b = _write(tmp_path, "b.json",
                   [_phys("area.physical.core_um2", CORE_UM2),
                    _proxy("area.proxy.cell_count", CELL_COUNT)])
        c = _write(tmp_path, "c.json",
                   [_phys("area.physical.core_um2", 12800.0),
                    _proxy("area.proxy.cell_count", 200)])
        r = _run("--baseline", b, "--candidate", c)
        assert r.returncode == 1
        assert "[REFUSE]" in r.stderr

    def test_rc2_when_only_proxies_are_available(self, tmp_path):
        """No physical evidence is UNDETERMINED, and it says so out loud."""
        b = _write(tmp_path, "b.json", [_proxy("area.proxy.cell_count", 252)])
        c = _write(tmp_path, "c.json", [_proxy("area.proxy.cell_count", 100)])
        r = _run("--baseline", b, "--candidate", c)
        assert r.returncode == 2
        assert "[CANNOT CHECK]" in r.stderr

    def test_vacuous_absent_input_is_rc2_with_a_marker(self, tmp_path):
        """THE VACUOUS FIXTURE. Not rc=0, not rc=1.

        rc=1 in this program means "the design is not smaller". A run that never
        opened a file must never say that, and a run that exits 0 on absent
        input is a gate that cannot fail.
        """
        c = _write(tmp_path, "c.json", [_phys("area.physical.core_um2", 1.0)])
        r = _run("--baseline", str(tmp_path / "nope.json"), "--candidate", c)
        assert r.returncode == 2
        assert "[CANNOT CHECK]" in r.stderr
        assert "no such file" in r.stderr

    def test_an_empty_file_and_an_absent_file_do_not_produce_one_verdict(
            self, tmp_path):
        """Rule 9. They are different facts, so they get different reasons."""
        empty = tmp_path / "empty.json"
        empty.write_text("", encoding="utf-8")
        c = _write(tmp_path, "c.json", [_phys("area.physical.core_um2", 1.0)])
        absent = _run("--baseline", str(tmp_path / "gone.json"), "--candidate", c)
        blank = _run("--baseline", str(empty), "--candidate", c)
        assert absent.returncode == blank.returncode == 2
        assert "no such file" in absent.stderr
        assert "file is empty" in blank.stderr
        assert absent.stderr != blank.stderr

    def test_an_empty_list_is_undetermined_not_pass(self, tmp_path):
        """A file that really does hold zero records still cannot be a PASS."""
        b = _write(tmp_path, "b.json", [])
        c = _write(tmp_path, "c.json", [])
        r = _run("--baseline", b, "--candidate", c)
        assert r.returncode == 2

    def test_bad_invocation_is_rc3_never_a_design_finding(self, tmp_path):
        r = _run("--baseline", str(tmp_path / "x.json"))
        assert r.returncode == 3

    def test_a_malformed_record_file_is_rc2_not_a_finding(self, tmp_path):
        """A file of objects that are not metric records. rc must not be 1."""
        b = _write(tmp_path, "b.json", [{"metric": "area.physical.core_um2",
                                         "status": "MEASURED"}])
        c = _write(tmp_path, "c.json", [{"hello": "world"}])
        r = _run("--baseline", b, "--candidate", c)
        assert r.returncode == 2
        assert "[CANNOT CHECK]" in r.stderr

    def test_a_record_naming_an_unregistered_metric_is_rc2(self, tmp_path):
        rec = {"schema": A.SCHEMA, "metric": "area.physical.invented_um2",
               "status": "MEASURED", "value": 1.0, "unit": "um^2",
               "scope": {"stage": "post_route"}, "source": {"path": "x"}}
        b = _write(tmp_path, "b.json", [rec])
        c = _write(tmp_path, "c.json", [dict(rec, value=0.5)])
        r = _run("--baseline", b, "--candidate", c)
        assert r.returncode == 2

    def test_a_json_file_that_is_not_a_list_is_rc2(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text('{"nope": 1}', encoding="utf-8")
        c = _write(tmp_path, "c.json", [_phys("area.physical.core_um2", 1.0)])
        r = _run("--baseline", str(p), "--candidate", c)
        assert r.returncode == 2
        assert "neither a 'records' nor a 'metrics' list" in r.stderr

    def test_the_json_report_is_written_canonically(self, tmp_path):
        b = _write(tmp_path, "b.json", [_phys("area.physical.core_um2", CORE_UM2)])
        c = _write(tmp_path, "c.json", [_phys("area.physical.core_um2", 11000.0)])
        out = tmp_path / "sub" / "verdict.json"
        r = _run("--baseline", b, "--candidate", c, "--json", str(out))
        assert r.returncode == 0
        doc = json.loads(out.read_text())
        assert doc["schema"] == A.SCHEMA_VERDICT
        assert out.read_text() == cj.dumps(doc)  # sorted, no spaces
        assert not list(tmp_path.glob("**/*.tmp"))  # written through a temp

    def test_the_json_report_is_written_even_when_the_input_is_absent(
            self, tmp_path):
        """A refusal that leaves no artefact is indistinguishable from no run."""
        c = _write(tmp_path, "c.json", [_phys("area.physical.core_um2", 1.0)])
        out = tmp_path / "verdict.json"
        r = _run("--baseline", str(tmp_path / "gone.json"), "--candidate", c,
                 "--json", str(out))
        assert r.returncode == 2
        assert json.loads(out.read_text())["code"] == A.C_ABSENT_INPUT


# ════════════════════════════════════════════════════════════════════════════
# 6. The two programs the lane relabelled
# ════════════════════════════════════════════════════════════════════════════
class TestExistingProgramLabels:
    def test_area_threshold_check_stamps_every_exit_path(self):
        """Including the early NOT_APPLICABLE returns.

        A label that appears only on the happy path is a label a promoter never
        sees, so this drives the gate down its earliest return — no prompt and
        no explicit threshold — and demands the stamp there.
        """
        import ppa_area_threshold_check as m
        rc, report = m.run_ppa_area_threshold(
            original=pathlib.Path("/dev/null"),
            optimized=pathlib.Path("/dev/null"), top="t",
            prompt_text=None, threshold_override=None, metric_override=None,
            container="nonexistent-container-for-a-test")
        assert rc == 0
        assert report["verdict"] == "NOT_APPLICABLE"
        assert report["metric_class"] == A.RTL_PROXY
        assert report["eligible_for_physical_ppa"] is False
        assert "post-route" in report["physical_area_note"]

    def test_area_threshold_checks_metrics_are_all_registered_proxies(self):
        import ppa_area_threshold_check as m
        assert m._PROXY_METRICS
        for name in m._PROXY_METRICS:
            assert A.classify(name) in A.PROXY_CLASSES, name

    def test_area_threshold_check_can_only_emit_proxy_records(self):
        """Its canonical form goes through proxy_record, so promotion raises."""
        import ppa_area_threshold_check as m
        report = {"top": "spm", "container": "vibeic-eda",
                  "original": "orig.v", "optimized": "opt.v",
                  "verdict": "PASS", "reason": "ok",
                  "cells_reduction_pct": 20.6, "wires_reduction_pct": 12.0,
                  "optimized_stat": {"cells": 200, "wires": 199}}
        recs = m.as_metric_records(report)
        assert len(recs) == 4
        for r in recs:
            assert r["metric_class"] in A.PROXY_CLASSES
            assert r["eligible_for_physical_ppa"] is False
            with pytest.raises(A.IneligibleForPhysicalPPA):
                A.assert_eligible_for_physical_ppa(r)

    def test_a_missing_number_becomes_not_measured_and_not_a_zero(self):
        import ppa_area_threshold_check as m
        recs = m.as_metric_records(
            {"top": "t", "verdict": "NOT_APPLICABLE", "reason": "docker absent"})
        assert {r["status"] for r in recs} == {A.NOT_MEASURED}
        assert all("value" not in r for r in recs)
        assert all("docker absent" in r["reason"] or "no " in r["reason"]
                   for r in recs)

    def test_predict_aggregate_is_estimated_with_assumptions(self):
        import ppa_predict_aggregate as m
        d = m.build_estimate(rtl_cell_count=CELL_COUNT, pdk="gf180mcuD"
                             ).as_dict()
        assert d["status"] == A.ESTIMATED
        assert d["eligible_for_physical_ppa"] is False
        # every published number names its assumption
        for key in ("area_um2", "area_mm2", "power_uw", "fmax_hint_mhz"):
            assert key in d["assumptions"], key
            assert d["assumptions"][key]["formula"]
            assert d["assumptions"][key]["assumes"]

    def test_predict_aggregate_records_cannot_be_adopted_as_measurements(self):
        import ppa_predict_aggregate as m
        for rec in m.build_estimate(rtl_cell_count=CELL_COUNT,
                                    pdk="gf180mcuD").as_metric_records():
            assert rec["status"] == A.ESTIMATED
            with pytest.raises(A.IneligibleForPhysicalPPA):
                A.assert_eligible_for_physical_ppa(rec)

    def test_the_estimate_is_measurably_far_from_the_real_number(self):
        """The assumption text claims -38.5% vs core. Check the arithmetic.

        252 cells * 30.0 um^2 = 7560 um^2, against a measured post-route core of
        12294 um^2 and a die of 20164 um^2 on that exact design. The estimate
        being wrong is not the finding; the finding is that it is wrong by a
        factor nobody would tolerate in a result, which is why it may not be
        adopted as one.
        """
        import ppa_predict_aggregate as m
        est = m.build_estimate(rtl_cell_count=CELL_COUNT, pdk="gf180mcuD")
        assert est.area_um2 == 7560.0
        assert round(100.0 * (est.area_um2 - CORE_UM2) / CORE_UM2, 1) == -38.5
        assert round(100.0 * (est.area_um2 - DIE_UM2) / DIE_UM2, 1) == -62.5

    def test_the_markdown_says_estimated_before_it_says_a_number(self):
        import ppa_predict_aggregate as m
        md = m.estimate_to_markdown(
            m.build_estimate(rtl_cell_count=CELL_COUNT, pdk="gf180mcuD"))
        assert md.index("ESTIMATED") < md.index("7560")
        assert "What each number assumed" in md
