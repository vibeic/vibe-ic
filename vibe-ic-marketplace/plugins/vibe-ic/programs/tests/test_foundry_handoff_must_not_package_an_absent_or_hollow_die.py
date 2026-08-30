"""field (foundry-handoff hollow chip GDS) — the foundry-handoff packager had no predicate for the die itself.

MEASURED on two benchmark runs on 192.168.1.121, 2026-08-31:

    spm_gf180mcuD_20260831_a1          subservient_gf180mcuD_20260831_d1
      pnr  FAIL  ROUTE_NOT_CONVERGED     pnr  FAIL  ROUTE_DRC_METRIC_DISAGREEMENT
      drc  SKIP  "GDS missing"           drc  SKIP  "GDS missing"
      lvs  SKIP  "upstream pnr is FAIL"  lvs  SKIP  "upstream pnr is FAIL"
      `find -iname '*.gds'` -> 0 files   `find -iname '*.gds'` -> 0 files

and in BOTH, a complete foundry handoff kit on disk — mask spec, WAT probe plan,
ATE corner-vector kit — written by `foundry_handoff_pack_gen` for a die that does
not exist. The generator's ONE refusal (#654) keys on
`antenna.json:routing_incomplete`, and both runs record it as **false**: routing
COMPLETED, with a residual violation. So the guard was silent on exactly the case
it exists for, because "the router gave up" and "there is no die" are different
facts and only the first had a predicate.

THE NEGATIVE CONTROL, run end to end on a copy of the real spm run tree
(`A_foundry_handoff/falsify_base.sh` vs `falsify.sh`):

    case                    PRE-FIX                      POST-FIX
    no GDS at all           packs;  gate FAIL            REFUSES; gate FAIL
    real 2.8 MB spm.gds     packs;  gate PASS            packs;   gate PASS
    hollow GDS, 108 bytes   packs;  gate **PASS**        REFUSES; gate FAIL
    0-byte GDS              packs;  gate FAIL            REFUSES; gate FAIL

The hollow row is the finding. A structurally valid GDSII stream — HEADER,
BGNLIB, LIBNAME, UNITS, a top structure carrying the design's own name, ENDSTR,
ENDLIB, and not one geometry record — was packaged and signed off by step 35 as
"all 4 required artefacts present + chip GDS 'spm.gds'".

THE DEFECT THIS TEST FILE FOUND IN THE FIRST ATTEMPT AT THE FIX, kept as an
assertion below: with the refusal in the PRODUCER only, the hollow case moved
from gate rc=0 PASS to gate rc=2 SKIP — and `flow_compliance_check` reads rc=2 as
VACUOUS_PASS. The same green in a different exit code is not a fix. A
producer-only refusal is also deletable: hand-write four JSON files next to a
hollow GDS and nothing looks at the die. The predicate therefore lives in the
GATE as well, keyed on the artefact, where no choice of writer can evade it.

CORPUS SWEEP (zero false positives): the geometry predicate was run over every
`.gds` under `/home/reyerchu/vibeic-designs` on 192.168.1.121 — 76 files,
0 with zero geometry. This ERROR cannot redden an existing real artefact.
"""
from __future__ import annotations

import json
import pathlib
import struct
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import foundry_handoff_package_check as G  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────────
def _gds_record(rtype, dtype, payload=b""):
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _hollow_gds(top: str) -> bytes:
    """A structurally VALID GDSII stream carrying zero geometry records.

    Not a corrupt file and not padding: HEADER..ENDLIB with a properly named
    top structure. Everything a name-and-size check looks at is correct; the
    only thing missing is the layout. That is what makes it the launderable
    artefact rather than an obviously broken one."""
    stamp = struct.pack(">12h", *([2026, 8, 31, 0, 0, 0] * 2))
    return (_gds_record(0x00, 0x02, struct.pack(">h", 600))
            + _gds_record(0x01, 0x02, stamp)
            + _gds_record(0x02, 0x06, f"{top}.db".encode())
            + _gds_record(0x03, 0x05, struct.pack(">dd", 1e-3, 1e-9))
            + _gds_record(0x05, 0x02, stamp)
            + _gds_record(0x06, 0x06, top.encode())
            + _gds_record(0x07, 0x00)
            + _gds_record(0x04, 0x00))


def _real_gds(top: str) -> bytes:
    """The same stream with ONE BOUNDARY record — the minimum that makes the
    die real. The accept case must be this narrow: a fix that only ever
    refuses is not a fix."""
    stamp = struct.pack(">12h", *([2026, 8, 31, 0, 0, 0] * 2))
    xy = struct.pack(">10i", 0, 0, 0, 100, 100, 100, 100, 0, 0, 0)
    boundary = (_gds_record(0x08, 0x00)
                + _gds_record(0x0D, 0x02, struct.pack(">h", 1))
                + _gds_record(0x0E, 0x02, struct.pack(">h", 0))
                + _gds_record(0x10, 0x03, xy)
                + _gds_record(0x11, 0x00))
    return (_gds_record(0x00, 0x02, struct.pack(">h", 600))
            + _gds_record(0x01, 0x02, stamp)
            + _gds_record(0x02, 0x06, f"{top}.db".encode())
            + _gds_record(0x03, 0x05, struct.pack(">dd", 1e-3, 1e-9))
            + _gds_record(0x05, 0x02, stamp)
            + _gds_record(0x06, 0x06, top.encode())
            + boundary
            + _gds_record(0x07, 0x00)
            + _gds_record(0x04, 0x00))


_TOP = "spm"


def _project(tmp_path, gds: bytes | None, kit: bool = False):
    """A run tree carrying L1.ic_name and, optionally, a streamed chip GDS at
    the canonical step-37 path, and optionally a hand-written kit."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": _TOP}))
    if gds is not None:
        d = tmp_path / "phase3" / "stage4" / "gds"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_TOP}.gds").write_bytes(gds)
    if kit:
        # The kit hand-written by SOMETHING OTHER than the generator — the
        # evasion the gate-side predicate exists to close.
        h = tmp_path / "phase3" / "stage4" / "foundry_handoff"
        h.mkdir(parents=True, exist_ok=True)
        for name in ("mask_spec.json", "wat_plan.json",
                     "corner_test_vectors.json"):
            (h / name).write_text(json.dumps({"pdk": "gf180mcuD",
                                              "cell_count": 1}))
        (h / "scribe_line_layout.PENDING_FOUNDRY.txt").write_text(
            "foundry-supplied frame")
    return tmp_path


# ── the shared resolver ───────────────────────────────────────────────────
def test_the_geometry_parser_is_the_one_the_hardmacro_gate_uses():
    """ONE definition of "carries geometry" flow-wide. If this import ever
    stops resolving, the predicate silently becomes unavailable, so the fact
    that it resolves is itself an assertion."""
    assert G._gds_geometry_count is not None
    from analog_a5_layout_check import _gds_geometry_count as shared
    assert G._gds_geometry_count is shared


def test_no_gds_at_all_names_the_absent_rule(tmp_path):
    gds, rule, detail = G.packageable_chip_gds(_project(tmp_path, None))
    assert gds is None
    assert rule == G.RULE_NO_CHIP_GDS
    assert "no .gds present" in detail


def test_a_zero_byte_gds_is_absent_not_hollow(tmp_path):
    """A 0-byte file is not a hollow die, it is no die: `_find_chip_gds`
    already refuses `st_size <= 0`, so it must land in the ABSENT arm and be
    reported under the rule step 35 already emits for it."""
    gds, rule, _ = G.packageable_chip_gds(_project(tmp_path, b""))
    assert gds is None and rule == G.RULE_NO_CHIP_GDS


def test_a_hollow_gds_names_the_hollow_rule(tmp_path):
    gds, rule, detail = G.packageable_chip_gds(
        _project(tmp_path, _hollow_gds(_TOP)))
    assert gds is not None, "the file IS found — that is what makes it hollow"
    assert rule == G.RULE_HOLLOW_CHIP_GDS
    assert "no BOUNDARY/PATH/SREF/AREF/BOX record" in detail


def test_a_real_gds_is_packageable(tmp_path):
    """THE ACCEPT CASE. One BOUNDARY record is enough."""
    gds, rule, detail = G.packageable_chip_gds(
        _project(tmp_path, _real_gds(_TOP)))
    assert gds is not None and rule is None
    assert "1 GDS geometry/placement record" in detail


def test_a_scribe_frame_alone_is_not_a_chip_gds(tmp_path):
    """The foundry-supplied frame is not the die. Named-after-the-frame files
    must not satisfy the predicate, or the packager would happily describe a
    reticle border as a chip."""
    p = _project(tmp_path, None)
    d = p / "phase3" / "stage4" / "gds"
    d.mkdir(parents=True, exist_ok=True)
    (d / "scribe_line_layout.gds").write_bytes(_real_gds("scribe_line_layout"))
    gds, rule, detail = G.packageable_chip_gds(p)
    assert gds is None and rule == G.RULE_NO_CHIP_GDS
    assert "only scribe-line / frame GDS present" in detail


def test_a_project_without_L1_is_still_measured(tmp_path):
    """No L1.ic_name is not a licence to package. `_find_chip_gds` returns
    None whenever ic_name is None — reading that as "packageable" would let
    any project that skipped phase 1 ship a kit for nothing."""
    (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
    gds, rule, _ = G.packageable_chip_gds(tmp_path)
    assert gds is None and rule == G.RULE_NO_CHIP_GDS
    # ...and the same project WITH a real die is packageable again, so the
    # fallback is a measurement and not a blanket refusal.
    (tmp_path / "phase3" / "stage4" / "gds" / f"{_TOP}.gds").write_bytes(
        _real_gds(_TOP))
    gds2, rule2, _ = G.packageable_chip_gds(tmp_path)
    assert gds2 is not None and rule2 is None


# ── the producer refuses ──────────────────────────────────────────────────
def _pack(project):
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "foundry_handoff_pack_gen.py"),
         str(project), "--top", _TOP],
        # 30s: `ci_harness_timeout_ceiling_check` caps an inner bound at 60 —
        # a longer bound kills the SESSION rather than the call.
        capture_output=True, text=True, timeout=30)


def test_the_packager_refuses_a_streamed_non_die_and_leaves_no_half_kit(
        tmp_path):
    """Stream-out ran and what it wrote is not a die: a 0-byte GDS at the
    canonical path. Refuse, and leave NOTHING — the predicate is asked before
    the handoff directory is created, so a refusal cannot leave a partial kit
    on disk for the next reader to mistake for a deliverable."""
    p = _project(tmp_path, b"")
    r = _pack(p)
    assert r.returncode == 2, r.stdout[-400:] + r.stderr[-400:]
    assert G.RULE_NO_CHIP_GDS in r.stderr
    assert not (p / "phase3/stage4/foundry_handoff").exists()


def test_the_packager_still_packs_a_tree_that_never_reached_streamout(
        tmp_path):
    """SCOPE, asserted so a later widening is a deliberate act and not a
    drift. A tree with NO .gds at all is not refused by the producer: the gate
    already exits rc=1 FAIL `FOUNDRY_HANDOFF_CHIP_GDS_MISSING` on it (asserted
    in `test_an_absent_die_still_reports_the_missing_rule_not_the_hollow_one`),
    so there is no false green to close — and refusing here was implemented and
    MEASURED to redden 38 tests across 9 files whose fixtures run this
    generator on a bare project to check its field derivation."""
    p = _project(tmp_path, None)
    r = _pack(p)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    assert (p / "phase3/stage4/foundry_handoff/mask_spec.json").is_file()
    # ...and the GATE is the one that refuses it, loudly, at rc=1.
    rc, data = _gate(p)
    assert rc == 1 and data["verdict"] == "FAIL"


def test_the_packager_refuses_a_hollow_die(tmp_path):
    r = _pack(_project(tmp_path, _hollow_gds(_TOP)))
    assert r.returncode == 2, r.stdout[-400:] + r.stderr[-400:]
    assert G.RULE_HOLLOW_CHIP_GDS in r.stderr


def test_the_packager_packs_a_real_die(tmp_path):
    """THE ACCEPT CASE, run for real. If this refused too the fix would be
    "never hand off", which is not a fix — and the 11 converged spm runs
    measured on 192.168.1.121 all take this path."""
    p = _project(tmp_path, _real_gds(_TOP))
    r = _pack(p)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]
    for name in ("mask_spec.json", "wat_plan.json",
                 "corner_test_vectors.json"):
        assert (p / "phase3/stage4/foundry_handoff" / name).is_file(), name


def test_the_packager_is_actually_wired_to_the_predicate():
    """WIRING. A predicate nothing calls leaves the packaging exactly as it
    was, which is the whole finding. Asserted on the source the way #654's
    own wiring test does."""
    src = (_PROGRAMS / "foundry_handoff_pack_gen.py").read_text(
        encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "packageable_chip_gds(project)" in body


# ── the gate refuses too: the producer-side refusal is deletable ──────────
def _gate(project):
    out = project / "audit.json"
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "foundry_handoff_package_check.py"),
         str(project), "--json", str(out)],
        capture_output=True, text=True, timeout=30)
    data = json.loads(out.read_text()) if out.is_file() else {}
    return r.returncode, data


def test_the_gate_fails_a_hand_written_kit_around_a_hollow_die(tmp_path):
    """THE ANTI-EVASION, and the assertion that decides whether the fix is
    real. Four JSON files written by anything at all, beside a hollow GDS:
    PRE-FIX this was rc=0 PASS, "all 4 required artefacts present + chip GDS".
    """
    rc, data = _gate(_project(tmp_path, _hollow_gds(_TOP), kit=True))
    assert rc == 1, data
    assert data["verdict"] == "FAIL"
    assert [f["rule"] for f in data["findings"]][0] == G.RULE_HOLLOW_CHIP_GDS


def test_the_gate_passes_the_same_kit_around_a_real_die(tmp_path):
    """THE ACCEPT CASE for the gate. Same kit, same paths, real die."""
    rc, data = _gate(_project(tmp_path, _real_gds(_TOP), kit=True))
    assert rc == 0, data
    assert data["verdict"] == "PASS"


def test_an_absent_die_still_reports_the_missing_rule_not_the_hollow_one(
        tmp_path):
    """One defect, one rule. An absent GDS is CHIP_GDS_MISSING and must not
    ALSO be reported as hollow — a gate that double-counts one fact makes its
    own finding list unreadable."""
    rc, data = _gate(_project(tmp_path, None, kit=True))
    assert rc == 1
    rules = [f["rule"] for f in data["findings"]]
    assert rules[0] == "FOUNDRY_HANDOFF_CHIP_GDS_MISSING"
    assert G.RULE_HOLLOW_CHIP_GDS not in rules


def test_the_hollow_verdict_is_rc1_not_rc2(tmp_path):
    """LOAD-BEARING, and the defect the first attempt at this fix had.
    `flow_compliance_check` reads rc=2 as VACUOUS_PASS. With the refusal in
    the producer alone, the hollow case reached the gate with an EMPTY kit
    dir and exited rc=2 SKIP — green. The clause is ordered ahead of the
    `missing -> SKIP` branch precisely so an incomplete kit cannot silence a
    substance defect the gate has already proved."""
    rc, data = _gate(_project(tmp_path, _hollow_gds(_TOP), kit=False))
    assert rc == 1, (rc, data)
    assert data["verdict"] == "FAIL"
