"""tests/test_analog_a4_corner_sweep_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a4_corner_sweep_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _corners(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps(doc))


def _a3_netlist(project: Path, block: str) -> None:
    """A4's declared upstream input. A sweep that produced corner results ran
    on a netlist; the gate's A4_NETLIST_ABSENT rule declines to certify one
    that has none. Fixtures asserting a clean A4 carry it."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{block}.sp").write_text(
        f"* {block} — synthetic block netlist\n"
        f".subckt {block} vdd vss vin vout\n"
        f"xm1 vout vin vss vss nch w=8 l=1\n"
        f"r1 vout vss 100k\n"
        f".ends {block}\n")


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        # WAS: no `design_content` at all. That made this "happy path" the
        # assertion that an artefact declaring simulated corners and refusing
        # to say what circuit produced them is the certifiable shape — which
        # is the pre-disclosure shape, and every stale artefact's shape.
        # A complete run says what it measured; the happy path now does too.
        "design_content": "structure_and_geometry",
        "corners": [
            {"process": "TT", "temp_c": 27, "vdd_v": 1.8,
             "simulator_run": True},
            {"process": "SS", "temp_c": -40, "vdd_v": 1.62,
             "simulator_run": True},
        ],
        "spec_results": [
            {"spec": "vout", "corner": "TT_27C", "status": "PASS"},
        ],
    })
    _a3_netlist(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "ams-sim"


def test_no_simulator_run_fails(tmp_path: Path) -> None:
    """v10632 escape — every corner says simulator_run: false."""
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "corners": [
            {"process": "TT", "simulator_run": False},
            {"process": "SS", "simulator_run": False},
        ],
        "spec_results": [
            {"spec": "vout", "status": "PASS"},  # claim is moot
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NO_SIMULATOR_RUN" in f["rule"]
               for f in rpt["findings"])


def test_spec_fail_at_corner_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "corners": [{"process": "TT", "simulator_run": True}],
        "spec_results": [
            {"spec": "vout", "corner": "SS_125C", "status": "FAIL"},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NO_PASS_SPEC" in f["rule"] for f in rpt["findings"])


def test_no_corners_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {"corners": []})
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NO_CORNERS" in f["rule"] for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"


# --- recorded-sha256 verification ---------------------------------------
# A corner artefact records the sha256 of the netlist (and testbench) it
# measured. Before these tests nothing re-computed it, so the field was a
# claim; a run whose recorded hash disagreed with the file on disk PASSED.

_CLEAN = {
    "design_content": "structure_and_geometry",
    "netlist_provenance": "a3_netlist",
    "corners": [
        {"process": "TT", "temp_c": 27, "vdd_v": 1.8, "simulator_run": True},
        {"process": "SS", "temp_c": -40, "vdd_v": 1.62, "simulator_run": True},
    ],
    "spec_results": [{"spec": "vout", "status": "PASS"}],
}


def _sha_of(project: Path, rel: str) -> str:
    import hashlib
    return hashlib.sha256((project / rel).read_bytes()).hexdigest()


def test_matching_netlist_sha_passes(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    doc = dict(_CLEAN)
    doc["netlist_source"] = "phase3/analog/ldo/ldo.sp"
    doc["netlist_sha256"] = _sha_of(tmp_path, "phase3/analog/ldo/ldo.sp")
    _corners(tmp_path, "ldo", doc)
    assert _run(tmp_path).returncode == 0


def test_stale_netlist_sha_fails(tmp_path: Path) -> None:
    """The measured escape: the netlist was edited after the sweep, so the
    corner verdict certifies a circuit no longer on disk."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    doc = dict(_CLEAN)
    doc["netlist_source"] = "phase3/analog/ldo/ldo.sp"
    doc["netlist_sha256"] = "0" * 64
    _corners(tmp_path, "ldo", doc)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NETLIST_SHA_MISMATCH" in f["rule"] for f in rpt["findings"])


def test_sha_without_a_named_source_and_no_declared_deck_fails(
        tmp_path: Path) -> None:
    """A digest anchored to NOTHING.

    This fixture used to leave `<block>.sp` on disk, because the named-path
    rule was the only one that existed and it failed every unnamed digest.
    `A4_SWEEP_STALE_VS_NETLIST` now answers the unnamed case against the
    FLOW-DECLARED deck — an anchor the artefact cannot move, and therefore a
    stronger check than the name it declined to write. So the state this rule
    still owns, and the state its own words describe, is the one where there
    is genuinely nothing left to check the hash against: no name, and no
    flow-declared deck either. The subject of the test is unchanged; the
    fixture now isolates it instead of overlapping the other rule."""
    _block_list(tmp_path, ["ldo"])
    doc = dict(_CLEAN)
    doc["netlist_sha256"] = "0" * 64
    _corners(tmp_path, "ldo", doc)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_SHA_CLAIM_UNANCHORED" in f["rule"] for f in rpt["findings"])


def test_sha_naming_an_unreadable_source_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    doc = dict(_CLEAN)
    doc["netlist_source"] = "phase3/analog/ldo/does_not_exist.sp"
    doc["netlist_sha256"] = "0" * 64
    _corners(tmp_path, "ldo", doc)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_SHA_SOURCE_UNREADABLE" in f["rule"] for f in rpt["findings"])


def test_stale_testbench_sha_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "ldo" / "tb_ldo.sp").write_text("* tb\n")
    doc = dict(_CLEAN)
    doc["netlist_source"] = "phase3/analog/ldo/ldo.sp"
    doc["netlist_sha256"] = _sha_of(tmp_path, "phase3/analog/ldo/ldo.sp")
    doc["netlist_testbench"] = "phase3/analog/ldo/tb_ldo.sp"
    doc["netlist_testbench_sha256"] = "1" * 64
    _corners(tmp_path, "ldo", doc)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NETLIST_SHA_MISMATCH" in f["rule"] for f in rpt["findings"])


def test_artefact_recording_no_sha_is_left_alone(tmp_path: Path) -> None:
    """Silence is not upgraded to evidence, and it is not newly punished
    here either — other rules judge an artefact that discloses nothing."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    doc = dict(_CLEAN)
    doc["netlist_source"] = "phase3/analog/ldo/ldo.sp"
    _corners(tmp_path, "ldo", doc)
    assert _run(tmp_path).returncode == 0


# ── A4 STALENESS (A4_SWEEP_STALE_VS_NETLIST) ──────────────────────────────
# "Re-run A4 after a netlist change" was an instruction in prose that nothing
# enforced. Every subject-of-measurement rule above is answered ONCE, when the
# artefact is written; none of them notices the deck changing afterwards — and
# changing it is the prescribed thing to do the moment A3 refuses a deck.

def _sha(project: Path, block: str, name: str) -> str:
    import hashlib
    p = project / "phase3" / "analog" / block / name
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _swept(project: Path, block: str, **extra) -> None:
    _corners(project, block, {
        "design_content": "structure_and_geometry",
        "netlist_provenance": "a3_netlist",
        "corners": [{"process": "TT", "temp_c": 27, "simulator_run": True}],
        "spec_results": [{"spec": "vout", "corner": "TT_27C",
                          "status": "PASS"}],
        **extra,
    })


def test_a_sweep_whose_digest_still_recomputes_certifies(
        tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    _swept(tmp_path, "ldo", netlist_sha256=_sha(tmp_path, "ldo", "ldo.sp"))
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_a_sweep_measured_on_a_superseded_netlist_fails(
        tmp_path: Path) -> None:
    """The exact sequence: A3 refuses a deck, the deck is fixed, and the
    corner_results.json beside it keeps certifying A4 on numbers measured on
    the circuit that was replaced."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    _swept(tmp_path, "ldo", netlist_sha256=_sha(tmp_path, "ldo", "ldo.sp"))
    sp = tmp_path / "phase3" / "analog" / "ldo" / "ldo.sp"
    sp.write_text(sp.read_text().replace("r1 vout vss 100k",
                                         "xr1 vout vss res_po w=1u l=10u"))
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    f = next(x for x in rpt["findings"]
             if x["rule"] == "A4_SWEEP_STALE_VS_NETLIST")
    assert f["stale_input"].endswith("ldo.sp"), f
    assert f["declared_sha256"] != f["actual_sha256"], f


def test_a_changed_stimulus_deck_is_a_stale_sweep_too(tmp_path: Path) -> None:
    """The producer stamps `netlist_testbench_sha256` as well, and the same
    argument applies: a sweep is the pair of a circuit and the stimulus that
    drove it."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    tb = tmp_path / "phase3" / "analog" / "ldo" / "tb_ldo.sp"
    tb.write_text("* tb\n.include ldo.sp\nVdd vdd 0 1.8\n.end\n")
    _swept(tmp_path, "ldo",
           netlist_sha256=_sha(tmp_path, "ldo", "ldo.sp"),
           netlist_testbench_sha256=_sha(tmp_path, "ldo", "tb_ldo.sp"))
    assert _run(tmp_path).returncode == 0
    tb.write_text("* tb\n.include ldo.sp\nVdd vdd 0 3.3\n.end\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(x["rule"] == "A4_SWEEP_STALE_VS_NETLIST"
               for x in rpt["findings"]), rpt


def test_an_artefact_that_publishes_no_digest_is_left_alone(
        tmp_path: Path) -> None:
    """Silent without a claim, exactly as `A3_PROVENANCE_REF_MISMATCH` is: a
    skill-authored corner_results.json makes no digest claim, and a rule that
    failed it would punish the ABSENCE of a claim rather than a false one."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    _swept(tmp_path, "ldo")
    sp = tmp_path / "phase3" / "analog" / "ldo" / "ldo.sp"
    sp.write_text(sp.read_text() + "* edited after the sweep\n")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_a_vanished_netlist_is_still_reported_as_absent_not_stale(
        tmp_path: Path) -> None:
    """`A4_NETLIST_ABSENT` owns that case and says it better; two rules
    competing for one condition is how a diagnosis drifts."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    _swept(tmp_path, "ldo", netlist_sha256=_sha(tmp_path, "ldo", "ldo.sp"))
    (tmp_path / "phase3" / "analog" / "ldo" / "ldo.sp").unlink()
    r = _run(tmp_path)
    rpt = json.loads((tmp_path / "report.json").read_text())
    rules = {f["rule"] for f in rpt.get("findings", [])}
    assert "A4_SWEEP_STALE_VS_NETLIST" not in rules, rpt


# ── THE TWO RULES TOGETHER ────────────────────────────────────────────────
# The named-path rule and the flow-declared-path rule are not duplicates, and
# neither is unreachable once the other is present. These pin the join.

def test_a_true_digest_of_a_file_the_artefact_chose_is_still_stale(
        tmp_path: Path) -> None:
    """THE RESIDUAL ESCAPE the named-path rule disclosed about itself, and the
    reason both rules ship.

    `netlist_source` names a DIFFERENT existing file — the stimulus deck —
    and records that file's TRUE digest. The named-path rule re-hashes what it
    is pointed at, finds agreement, and has nothing to say: the artefact chose
    the name, so it can make its own digest true. The deck A3 declares and
    A5/A6 lay out is `<block>.sp`, it is something else entirely, and the
    corner numbers are not about it. Only the flow-declared path catches this,
    because it is the one path the artefact cannot move."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    tb = tmp_path / "phase3" / "analog" / "ldo" / "tb_ldo.sp"
    tb.write_text("* tb\n.include ldo.sp\nVdd vdd 0 1.8\n.end\n")
    doc = dict(_CLEAN)
    # points at the testbench, and the digest of the testbench is honest
    doc["netlist_source"] = "phase3/analog/ldo/tb_ldo.sp"
    doc["netlist_sha256"] = _sha_of(tmp_path, "phase3/analog/ldo/tb_ldo.sp")
    _corners(tmp_path, "ldo", doc)
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    f = next(x for x in rpt["findings"]
             if x["rule"] == "A4_SWEEP_STALE_VS_NETLIST")
    assert f["stale_input"].endswith("ldo.sp"), f
    assert not f["stale_input"].endswith("tb_ldo.sp"), f


def test_one_stale_digest_produces_exactly_one_finding(
        tmp_path: Path) -> None:
    """The named path and the flow-declared path resolve to the same file in
    every honest artefact. When they do, the two rules ask the identical
    question of the identical bytes, and the ladder must answer once — a fact
    reported twice is a fact double-counted."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    doc = dict(_CLEAN)
    doc["netlist_source"] = "phase3/analog/ldo/ldo.sp"
    doc["netlist_sha256"] = _sha_of(tmp_path, "phase3/analog/ldo/ldo.sp")
    _corners(tmp_path, "ldo", doc)
    assert _run(tmp_path).returncode == 0            # negative control
    sp = tmp_path / "phase3" / "analog" / "ldo" / "ldo.sp"
    sp.write_text(sp.read_text() + "* edited after the sweep\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    digest_rules = [f["rule"] for f in rpt["findings"]
                    if f["rule"] in ("A4_NETLIST_SHA_MISMATCH",
                                     "A4_SWEEP_STALE_VS_NETLIST",
                                     "A4_SHA_CLAIM_UNANCHORED",
                                     "A4_SHA_SOURCE_UNREADABLE")]
    # the named-path rule owns it: it quotes the artefact's own words back
    assert digest_rules == ["A4_NETLIST_SHA_MISMATCH"], rpt


def test_an_unnamed_digest_is_answered_by_the_declared_deck_not_punished(
        tmp_path: Path) -> None:
    """The state the two branches judged oppositely, decided in the code and
    pinned here: a digest with no companion path that RECOMPUTES from the deck
    this flow declares is anchored — to a path the artefact could not choose.
    Failing it would punish the absence of a companion claim while the claim
    actually made is verifiable and true."""
    _block_list(tmp_path, ["ldo"])
    _a3_netlist(tmp_path, "ldo")
    doc = dict(_CLEAN)
    doc["netlist_sha256"] = _sha_of(tmp_path, "phase3/analog/ldo/ldo.sp")
    _corners(tmp_path, "ldo", doc)
    assert _run(tmp_path).returncode == 0
    # …and the same shape with a digest that does NOT recompute is caught,
    # by the rule that could answer it — never left unjudged.
    doc["netlist_sha256"] = "0" * 64
    _corners(tmp_path, "ldo", doc)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(f["rule"] == "A4_SWEEP_STALE_VS_NETLIST"
               for f in rpt["findings"]), rpt
