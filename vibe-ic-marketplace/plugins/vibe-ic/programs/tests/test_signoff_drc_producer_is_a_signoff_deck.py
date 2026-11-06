"""The Step-31 sign-off DRC certificate must not be produced by the ROUTER.

THE DEFECT, measured on a real Phase-3 run and reproduced here as fixtures.
The runner re-stages a DRC report to `reports/phase3/drc_signoff.rpt` and, when
no rule-deck report exists, the source it re-stages is OpenROAD's own
detailed-route DRC projection. Three separate mechanisms then credited it:

  1. `drc_report_check --mode drc --under reports/phase3/drc_signoff.rpt`
     returned rc 0 / `passed:true` / `tool_authentic:true` over a project
     containing ZERO GDS files.
  2. `_v1_6_620_append_pv_signoff_provenance` stamped that artefact
     `tool:"klayout"`, `command:"klayout -b -r drc (sign-off DRC)"` — an
     invocation that never happened — so the Step-31 provenance ALLOW-LIST
     passed it under every tool list tried, `openroad` present or not.
  3. `signoff_ladder_run.check_tier_1_drc`, a RELEASE-GATING tier named "Full
     DRC (KLayout/Magic)", returned PASS from the same router log.

Each test below carries its own NEGATIVE CONTROL: the pre-fix behaviour is
executed, not described, so a regression re-reddens this file rather than
quietly restoring the hole.

chip-AGNOSTIC and NDA-clean: every fixture is synthesised from report GRAMMAR.
No design name, PDK SKU, foundry or part number appears here.
"""
import hashlib
import importlib
import io
import json
import time
import contextlib

import pytest

drc_report_check = importlib.import_module("drc_report_check")
eda_report_audit = importlib.import_module("eda_report_audit")
signoff_ladder_run = importlib.import_module("signoff_ladder_run")
_sdf = importlib.import_module("_signoff_drc_format")
runner = importlib.import_module("phase3_one_shot_runner")
_gdsii = importlib.import_module("_gdsii")


# --------------------------------------------------------------------------
# fixtures — report GRAMMAR only
# --------------------------------------------------------------------------
def router_projection(violations: int = 0) -> str:
    """The runner's projection of OpenROAD detailed_route DRC.

    Padded past the auditor's 2048-byte stub floor with real message-code
    lines, because a report below that floor is rejected for a DIFFERENT
    reason and would not demonstrate this defect.
    """
    clean = "YES" if violations == 0 else "NO"
    head = (
        "# OpenROAD detailed_route DRC summary -- emitted by\n"
        "# the runner's canonicalize_artefacts step.\n"
        "# Tool: openroad detailed_route (drt)\n"
        "#\n"
        "openroad / drt-pass: detailed_route invoked\n"
        f"violation report: {violations}\n"
        f"violation count summary: {violations} violation(s) found\n"
        f"DRC clean: {clean}\n"
        "tool: openroad\n\n"
    )
    body = "".join(
        f"[INFO DRT-{2000 + i:04d}] layer region query size = {i * 71}.\n"
        for i in range(120))
    return head + body


def signoff_alias(source_rel: str, tool: str, body: str) -> str:
    """The 4-line alias banner the runner prepends when re-staging."""
    return (f"# Sign-off DRC report (Step 31 alias).\n"
            f"# Source: {source_rel}\n"
            f"# Tool: {tool}\n"
            f"#\n") + body


def klayout_rdb(top: str = "top", items: int = 0, deck: bool = True) -> str:
    """A KLayout report database, padded past the auditor's 2048-byte stub
    floor with real `<category>` records — a real deck's report carries one per
    rule, so the padding is the format, not filler."""
    gen = ("  <generator>drc: script='/pdk/tech/klayout/drc/deck.lydrc'"
           "</generator>\n" if deck else "")
    body = "".join("  <item><category>'m2.1'</category></item>\n"
                   for _ in range(items))
    cats = "".join(
        f"    <category><name>'m{2 + i % 4}.{i}'</name>"
        f"<description>metal spacing width density antenna via enclosure "
        f"rule {i}</description></category>\n" for i in range(24))
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<report-database>\n"
            "  <description>DRC runset</description>\n"
            "  <original-file/>\n"
            f"{gen}"
            f"  <top-cell>{top}</top-cell>\n"
            "  <categories>\n" + cats + "  </categories>\n"
            "  <items>\n" + body + "  </items>\n"
            "</report-database>\n")


def svrf_report(fails: int = 0, passes: int = 4533) -> str:
    lines = ["# SVRF-native DRC via KLayout",
             f"# 224 layers, 15911 derivations, {fails + passes} rules",
             ""]
    lines += [f"PASS  R_pass_{i}   EXTERNAL a/b < 0.1 -> 0" for i in range(passes)]
    lines += [f"FAIL  R_fail_{i}   INTERNAL c < 0.2 -> {i + 3}"
              for i in range(fails)]
    return "\n".join(lines) + "\n"


def project(tmp_path, report_text, *, gds_stem=None, name="p", gds_cell=None):
    """A project with a sign-off DRC report, and optionally a streamed layout.

    THE LAYOUT IS A REAL GDSII STREAM, and it has to be. This fixture used to
    write six bytes (`b"\x00\x06\x00\x02\x00\x07"`), which was adequate while
    only the FILENAME mattered. `drc_report_check` now binds a sign-off report to
    its layout by CONTENT: `_recorded_layout_evidence` parses the bound stream's
    top cells and refuses a binding whose tops do not equal the report's declared
    top — and that refusal deliberately does NOT fall through to the filename
    probe ("cannot fall back to a coincidentally matching filename"), which is
    the anti-laundering property
    `test_a_pdk_or_macro_gds_is_not_the_design_layout` asserts below. MEASURED on
    live main 131f80f99: `gds_top_cells(stub) == []`, the witness read
    `recorded layout top cells [] differ from report top 'top'`, and the on-disk
    probe ALONE would have answered `{'tier': 'on_disk', 'topcell_match': True}`
    — it was never reached. So the two positive cases below were red against a
    PROGRAM that was right.

    `gds_cell` defaults to `gds_stem`, which is what a streamed design looks
    like: the file is `<top>.gds` and its top structure is `<top>`. Pass it
    explicitly to stream a layout whose top cell is something else — the
    negative direction.

    Built with `_gdsii`, the shared minimal-stream builder the rest of this
    suite already uses, so there is ONE notion of "a real GDSII stream" and not
    a second one written into this file.
    """
    proj = tmp_path / name
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "drc_signoff.rpt").write_text(report_text)
    if gds_stem:
        d = proj / "phase3" / "stage3" / "pnr"
        d.mkdir(parents=True)
        _gdsii.write_gdsii(d / f"{gds_stem}.gds",
                           cell=gds_cell if gds_cell is not None else gds_stem)
    return proj


def gate(proj, *extra, under="reports/phase3/drc_signoff.rpt"):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = drc_report_check.run([str(proj), "--mode", "drc",
                                   "--under", under, "--subject", under, *extra])
    try:
        payload = json.loads(out.getvalue())
    except ValueError:
        payload = {}
    return rc, payload, err.getvalue()




def measured_klayout_receipt(proj, gds_rel="phase3/stage3/pnr/top.gds"):
    """Carry what a real step-31 run carries beside a clean RDB.

    v1.20.61 is right that an RDB with an empty <items> certifies nothing by
    itself -- the sha256 sign-off shipped exactly that shape and was never
    measured. A real run does not stop at the RDB: the KLayout runner writes
    its transcript and an append-only invocation record binding GDS input,
    RDB and transcript by digest, and `_measured_klayout_receipt_files` credits
    a zero only through that record. The RDB and GDS must already be on disk,
    because the receipt digests both.
    """
    report = proj / "reports" / "phase3" / "drc_signoff.rpt"
    transcript = report.with_suffix(".log")
    transcript.write_text("KLayout completed deck execution\n")
    gds = proj / gds_rel
    sha = lambda q: "sha256:" + hashlib.sha256(q.read_bytes()).hexdigest()
    rel = lambda q: q.relative_to(proj).as_posix()
    record = {"record": "invocation", "measured": True, "tool": "klayout",
              "exit_code": 0,
              "inputs": {rel(gds): sha(gds)},
              "outputs": {rel(report): sha(report), rel(transcript): sha(transcript)}}
    with (proj / "provenance.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def rules(payload):
    return [f["rule"] for f in payload.get("findings", [])]


# --------------------------------------------------------------------------
# 1. THE PRODUCER
# --------------------------------------------------------------------------
def test_router_projection_passes_the_gate_without_signoff(tmp_path):
    """NEGATIVE CONTROL — the hole, executed.

    A router projection re-staged to the sign-off path, in a project with NO
    layout at all, is a full PASS on the Step-31 substance gate as the gate is
    invoked WITHOUT `--signoff`. If this test ever goes red, either the
    fixture stopped reproducing the defect or something else started catching
    it — and the tests below stop proving what they claim.
    """
    proj = project(tmp_path, signoff_alias("pnr/routed.drc.rpt", "openroad",
                                           router_projection(0)))
    assert not list(proj.rglob("*.gds"))
    rc, payload, _ = gate(proj)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["summary"]["tool_authentic"] is True
    assert payload["summary"]["determined_files"] == 1
    assert payload["summary"]["real_violation_total"] == 0


def test_signoff_refuses_the_router_as_its_own_producer(tmp_path):
    proj = project(tmp_path, signoff_alias("pnr/routed.drc.rpt", "openroad",
                                           router_projection(0)))
    rc, payload, err = gate(proj, "--signoff")
    assert rc == 1
    assert payload["passed"] is False
    assert "DRC_SIGNOFF_PRODUCER_NOT_A_SIGNOFF_DECK" in rules(payload)
    assert payload["summary"]["signoff_producers"][0]["producer"] == "openroad"
    assert payload["summary"]["signoff_producers"][0]["is_signoff_deck"] is False


def test_producer_is_decided_by_content_not_by_the_banner(tmp_path):
    """A router body wearing a `# Tool: klayout` banner is still the router.

    The banner is written by the same code path that re-stages the report, so
    it is a claim ABOUT the file, never evidence FROM it.
    """
    proj = project(tmp_path, signoff_alias("reports/drc.rpt", "klayout",
                                           router_projection(0)),
                   gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert "DRC_SIGNOFF_PRODUCER_NOT_A_SIGNOFF_DECK" in rules(payload)


def test_unrecognised_producer_is_refused_not_guessed(tmp_path):
    text = ("some report that mentions klayout and a via and a spacing rule\n"
            "total violations: 0\n" + "filler line\n" * 400)
    proj = project(tmp_path, text, gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert "DRC_SIGNOFF_PRODUCER_UNRECOGNISED" in rules(payload)


def test_klayout_rdb_without_a_declared_deck_is_refused(tmp_path):
    """A report database naming no rule set certifies nothing in particular.

    The fixture keeps a `klayout` tool signature (in `<description>`) so the
    BASE audit still reaches a PASS — otherwise it would be refused one layer
    earlier, for a different reason, and this test would not be exercising the
    rule it names.
    """
    rdb = klayout_rdb(top="top", deck=False).replace(
        "<description>DRC runset</description>",
        "<description>KLayout DRC runset</description>")
    assert "<generator>" not in rdb
    proj = project(tmp_path, rdb, gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert "DRC_SIGNOFF_PRODUCER_DECK_UNNAMED" in rules(payload)


# --------------------------------------------------------------------------
# 2. THE LAYOUT
# --------------------------------------------------------------------------
def test_no_layout_evidence_is_refused(tmp_path):
    proj = project(tmp_path, klayout_rdb(top="top"))
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE" in rules(payload)
    assert payload["summary"]["layout_evidence_tier"] == "none"


def test_a_pdk_or_macro_gds_is_not_the_design_layout(tmp_path):
    """Anti-laundering: `a .gds exists` is not `the design was streamed`."""
    proj = project(tmp_path, klayout_rdb(top="top"))
    macro = proj / "input" / "macros"
    macro.mkdir(parents=True)
    (macro / "hardmacro.gds").write_bytes(b"\x00\x06")
    pdk = proj / "phase3" / "stage3" / "pnr"
    pdk.mkdir(parents=True)
    (pdk / "cell_library.gds").write_bytes(b"\x00\x06")   # right place, wrong cell
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE" in rules(payload)


def test_positive_a_deck_report_over_a_streamed_layout_passes(tmp_path):
    """The PASS is what this case is for, and it is unchanged.

    THE TIER MOVED, `on_disk` -> `invocation`, and it moved because the fixture
    was repaired rather than because the gate changed its mind. `on_disk` was
    only ever reachable here while the staged layout was six bytes of non-GDS:
    the measured receipt bound the report to it, `_recorded_layout_evidence`
    parsed its top cells, got `[]`, and returned an INVALID binding — which
    deliberately does not fall through, so the whole probe collapsed to
    NO_LAYOUT_EVIDENCE. Over a layout that really is one, the same receipt is a
    VALID binding and earns the strongest tier. Measured lattice (lane icslot6):
      real GDS + receipt              rc 0  invocation
      real GDS, no receipt            rc 1  on_disk    + DRC_ZERO_NOT_MEASURED
      real GDS + provenance, receipt  rc 0  invocation
      real GDS + provenance, none     rc 1  declared   + DRC_ZERO_NOT_MEASURED
    `on_disk` and `declared` therefore belong to rc-1 fixtures, and they get
    their own cases below rather than being asserted from a passing run.
    """
    proj = project(tmp_path, klayout_rdb(top="top"), gds_stem="top")
    measured_klayout_receipt(proj)
    rc, payload, err = gate(proj, "--signoff")
    assert rc == 0, err
    assert payload["passed"] is True
    assert payload["summary"]["layout_evidence_tier"] == "invocation"
    assert payload["summary"]["layout_topcell_match"] is True


def test_on_disk_tier_is_what_a_streamout_alone_earns(tmp_path):
    """The tier the case above used to claim, now exercised by the fixture that
    actually reaches it: a real streamout and NO invocation binding the report.

    It does not pass, and the reason is the OTHER ruling: v1.20.61's empty-RDB
    zero is unmeasured without the receipt. Asserted by NAME so this case says
    which concern owns the rc, and so a future change that started refusing the
    on-disk tier itself could not hide behind the same rc 1."""
    proj = project(tmp_path, klayout_rdb(top="top"), gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert payload["summary"]["layout_evidence_tier"] == "on_disk"
    assert payload["summary"]["layout_topcell_match"] is True
    assert "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE" not in rules(payload)
    assert "DRC_ZERO_NOT_MEASURED" in rules(payload)


def test_a_streamed_layout_whose_top_cell_is_not_the_reports_is_refused(tmp_path):
    """The negative direction the repaired fixture makes expressible.

    A parseable GDS in the right place with the right FILENAME, whose top
    structure is a different cell, is not this report's layout — and the bound
    receipt must be refused rather than accepted on the strength of the name.
    This is the same anti-laundering rule as
    `test_a_pdk_or_macro_gds_is_not_the_design_layout`, one level deeper: there
    the file was the wrong file, here it is the right file with the wrong
    contents."""
    proj = project(tmp_path, klayout_rdb(top="top"), gds_stem="top",
                   gds_cell="some_other_cell")
    measured_klayout_receipt(proj)
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert payload["summary"]["layout_evidence_tier"] == "none"
    assert payload["summary"]["layout_topcell_match"] is False
    assert "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE" in rules(payload)


def test_declared_tier_is_accepted_and_disclosed(tmp_path):
    # Two rulings compose here and neither overrides the other. 8d0e3e23f
    # answers "is there a layout?": a provenance DECLARATION is a real tier,
    # ranked below `invocation`, and it is ACCEPTED -- and DISCLOSED. v1.20.61
    # answers "was the ZERO measured?": an RDB whose <items> is empty certifies
    # nothing by itself, so a clean run must also carry the digest-bound KLayout
    # receipt a real step-31 run writes.
    #
    # THE OLD FIXTURE ASSERTED A COMBINATION THAT IS NOT REACHABLE (lane
    # icslot6). It carried the receipt AND expected `rc 0` with tier `declared`,
    # on the stated reasoning that the receipt "names the GDS as the deck's
    # INPUT, not as a streamout, so it does not promote the layout tier". That
    # reasoning is contradicted by the code: `_recorded_layout_evidence` looks
    # for a canonical streamout AMONG THE INPUTS and a valid one yields
    # `invocation`. It only ever read as `declared` because the staged layout was
    # six bytes of non-GDS, which made the binding INVALID -- and an invalid
    # binding does not fall through, so the run actually reached
    # NO_LAYOUT_EVIDENCE, not `declared`. Measured: with a real layout the
    # receipt promotes the tier every time, so `declared` and `rc 0` cannot
    # co-exist.
    #
    # WHAT THIS CASE IS FOR SURVIVES INTACT, and is what it now asserts: the
    # declaration IS accepted as layout evidence -- the gate does not raise
    # NO_LAYOUT_EVIDENCE over it -- and the weaker tier IS disclosed. The rc is 1
    # for the OTHER ruling's reason, and that reason is named here so a reader
    # cannot mistake which concern owns it.
    proj = project(tmp_path, klayout_rdb(top="top"), gds_stem="top")
    gds = proj / "phase3" / "stage3" / "pnr" / "top.gds"
    (proj / "provenance.jsonl").write_text(json.dumps({
        "tool": "magic", "exit_code": 0, "timestamp": "2020-01-01T00:00:00Z",
        "outputs": {"phase3/stage3/pnr/top.gds":
                    "sha256:" + hashlib.sha256(gds.read_bytes()).hexdigest()}})
        + "\n")
    rc, payload, err = gate(proj, "--signoff")
    assert payload["summary"]["layout_evidence_tier"] == "declared"
    # ACCEPTED: the declaration answers "is there a layout?" on its own.
    assert "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE" not in rules(payload), err
    # the DISCLOSURE is the point: `declared` is a weaker claim than
    # `invocation` and the artefact must say which one this run earned.
    assert payload["summary"]["layout_evidence_witness"] == \
        "phase3/stage3/pnr/top.gds"
    # and the rc belongs to the zero-measurement ruling, not to this one
    assert rc == 1
    assert "DRC_ZERO_NOT_MEASURED" in rules(payload)


def test_violations_still_fail_under_signoff(tmp_path):
    """`--signoff` adds requirements; it never relaxes the existing count."""
    proj = project(tmp_path, klayout_rdb(top="top", items=3), gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert payload["summary"]["real_violation_total"] == 3


# --------------------------------------------------------------------------
# 3. THE ATTRIBUTION (the half that makes the allow-list mean anything)
# --------------------------------------------------------------------------












# --------------------------------------------------------------------------
# 4. THE SVRF TIER — why the two edits must land together
# --------------------------------------------------------------------------
def test_clean_foundry_deck_signoff_is_readable_and_passes(tmp_path):
    """Before this change the HIGHEST-authority producer was the one the gate
    could not read: `determined_files:0` → rc 1, while the router's projection
    measured rc 0. Promoting `svrfdrc` into the provenance allow-list without
    this half would have promoted a tier that dies at the sibling sub-gate.
    """
    proj = project(tmp_path, svrf_report(fails=0), gds_stem="top")
    rc, payload, err = gate(proj, "--signoff")
    assert rc == 0, err
    assert payload["summary"]["determined_files"] == 1
    assert payload["summary"]["real_violation_total"] == 0


def test_a_firing_foundry_rule_still_fails(tmp_path):
    proj = project(tmp_path, svrf_report(fails=2), gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert payload["summary"]["real_violation_total"] == 2




# --------------------------------------------------------------------------
# 5. SCOPE — step 21 must not move
# --------------------------------------------------------------------------
def test_step21_router_gate_is_untouched(tmp_path):
    """Step 21's argv, on a router report. The router IS the right producer
    there; `--signoff` is this step's policy and must not leak into it.
    """
    proj = tmp_path / "s21"
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (proj / "reports" / "phase3").mkdir(parents=True)
    body = router_projection(7)
    (proj / "phase3" / "stage3" / "pnr" / "routed.drc.rpt").write_text(body)
    (proj / "reports" / "phase3" / "drc_router.rpt").write_text(body)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = drc_report_check.run([str(proj), "--mode", "drc",
                                   "--under", "phase3/stage3/pnr",
                                   "--under", "reports/phase3/drc_router.rpt",
                                    "--subject", "phase3/stage3/pnr/routed.drc.rpt",
                                    "--subject", "reports/phase3/drc_router.rpt"])
    payload = json.loads(out.getvalue())
    assert rc == 1
    # ONE measurement, filed twice. The runner writes a single body to both
    # of these paths ("Mirror to reports/phase3/ where the gate's --json
    # output lands"), so the pair is two inodes carrying identical bytes and
    # the router ran once. This literal was 14 with the comment "7 in each
    # report" — the count multiplied by how many times the flow had written
    # it down. See test_report_audit_symlink_dedup::
    # test_an_independent_byte_identical_copy_is_one_measurement.
    assert payload["summary"]["real_violation_total"] == 7
    assert payload["summary"]["tool_authentic"] is True
    assert "signoff_scope" not in payload["summary"]

    clean = router_projection(0)
    (proj / "phase3" / "stage3" / "pnr" / "routed.drc.rpt").write_text(clean)
    (proj / "reports" / "phase3" / "drc_router.rpt").write_text(clean)
    out2, err2 = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
        rc2 = drc_report_check.run([str(proj), "--mode", "drc",
                                    "--under", "phase3/stage3/pnr",
                                    "--under", "reports/phase3/drc_router.rpt",
                                    "--subject", "phase3/stage3/pnr/routed.drc.rpt",
                                    "--subject", "reports/phase3/drc_router.rpt"])
    assert rc2 == 0, "step 21 must still credit a clean router DRC"


def test_signoff_is_consumed_by_the_wrapper_not_forwarded():
    """NEGATIVE CONTROL for a 100%-outage failure mode.

    `_report_check_argv._split` forwards every unrecognised option verbatim
    and `eda_report_audit`'s parser rejects an unknown one with SystemExit(2),
    which this wrapper maps to "NOT CHECKED", rc 1 — on every project. The
    anti-drift test that derives VALUE_FLAGS from the real parser is a SUBSET
    assertion and structurally cannot catch a wrapper-only flag.
    """
    present, rest = drc_report_check.take_wrapper_flags(
        ["--signoff", "--under", "x", "--json", "y"])
    assert present == {"--signoff"}
    assert rest == ["--under", "x", "--json", "y"]
    import argparse
    parser = argparse.ArgumentParser()
    known = {o for a in parser._actions for o in a.option_strings}
    assert "--signoff" not in known  # not an eda_report_audit option


# --------------------------------------------------------------------------
# 6. THE OTHER CONSUMER — a release-gating tier named for its producer
# --------------------------------------------------------------------------
def test_ladder_tier1_refuses_the_router_log(tmp_path):
    proj = project(tmp_path, signoff_alias("pnr/routed.drc.rpt", "openroad",
                                           router_projection(0)))
    tier = signoff_ladder_run.check_tier_1_drc(proj)
    assert tier.release_gating is True
    assert tier.verdict == "NOT_RUN", tier
    assert tier.details.get("producer") == "openroad"


def test_ladder_tier1_reads_the_foundry_deck(tmp_path):
    clean = project(tmp_path, svrf_report(fails=0), name="clean")
    assert signoff_ladder_run.check_tier_1_drc(clean).verdict == "PASS"
    dirty = project(tmp_path, svrf_report(fails=3), name="dirty")
    t = signoff_ladder_run.check_tier_1_drc(dirty)
    assert t.verdict == "FAIL" and t.details["violations"] == 3


# --------------------------------------------------------------------------
# 7. the shared classifier, as a pure function
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text,kind", [
    (router_projection(0), "openroad"),
    (signoff_alias("x", "klayout", router_projection(0)), "openroad"),
    (klayout_rdb(), "klayout"),
    (signoff_alias("x", "klayout", klayout_rdb()), "klayout"),
    (svrf_report(0, 10), "svrfdrc"),
    ("Magic 8.3\ndrc count\nDRC errors found: 0\n", "magic"),
    ("nothing here\n", None),
])
def test_classifier(text, kind):
    assert _sdf.classify_text(text).kind == kind


def test_alias_header_does_not_hide_the_container_format():
    """The runner's own 4-line banner makes `text.lstrip()` start with `#`.
    Classification must look through it — see the PR for the separate,
    UNFIXED consequence this has for `_drc_real_violation_count`.
    """
    assert _sdf.strip_alias_header(
        signoff_alias("x", "klayout", klayout_rdb())).startswith("<?xml")
