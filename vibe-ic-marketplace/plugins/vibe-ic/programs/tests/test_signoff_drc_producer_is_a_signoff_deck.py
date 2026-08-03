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
import importlib
import io
import json
import contextlib

import pytest

drc_report_check = importlib.import_module("drc_report_check")
eda_report_audit = importlib.import_module("eda_report_audit")
provenance_check = importlib.import_module("provenance_check")
signoff_ladder_run = importlib.import_module("signoff_ladder_run")
_sdf = importlib.import_module("_signoff_drc_format")
runner = importlib.import_module("phase3_one_shot_runner")


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


def project(tmp_path, report_text, *, gds_stem=None, name="p"):
    proj = tmp_path / name
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "drc_signoff.rpt").write_text(report_text)
    if gds_stem:
        d = proj / "phase3" / "stage3" / "pnr"
        d.mkdir(parents=True)
        (d / f"{gds_stem}.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    return proj


def gate(proj, *extra, under="reports/phase3/drc_signoff.rpt"):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = drc_report_check.run([str(proj), "--mode", "drc",
                                   "--under", under, *extra])
    try:
        payload = json.loads(out.getvalue())
    except ValueError:
        payload = {}
    return rc, payload, err.getvalue()


def prov(proj, tools):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = provenance_check.main([str(proj), "--output",
                                        "reports/phase3/drc_signoff.rpt",
                                        "--tool", tools])
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


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
    proj = project(tmp_path, klayout_rdb(top="top"), gds_stem="top")
    rc, payload, err = gate(proj, "--signoff")
    assert rc == 0, err
    assert payload["passed"] is True
    assert payload["summary"]["layout_evidence_tier"] == "on_disk"
    assert payload["summary"]["layout_topcell_match"] is True


def test_declared_tier_is_accepted_and_disclosed(tmp_path):
    proj = project(tmp_path, klayout_rdb(top="top"))
    (proj / "provenance.jsonl").write_text(json.dumps({
        "tool": "magic", "exit_code": 0, "timestamp": "2020-01-01T00:00:00Z",
        "outputs": {"phase3/stage3/pnr/top.gds": "sha256:" + "0" * 64}}) + "\n")
    rc, payload, err = gate(proj, "--signoff")
    assert rc == 0, err
    assert payload["summary"]["layout_evidence_tier"] == "declared"
    # the DISCLOSURE is the point: `declared` is a weaker claim than
    # `invocation` and the artefact must say which one this run earned.
    assert payload["summary"]["layout_evidence_witness"] == \
        "phase3/stage3/pnr/top.gds"


def test_violations_still_fail_under_signoff(tmp_path):
    """`--signoff` adds requirements; it never relaxes the existing count."""
    proj = project(tmp_path, klayout_rdb(top="top", items=3), gds_stem="top")
    rc, payload, _ = gate(proj, "--signoff")
    assert rc == 1
    assert payload["summary"]["real_violation_total"] == 3


# --------------------------------------------------------------------------
# 3. THE ATTRIBUTION (the half that makes the allow-list mean anything)
# --------------------------------------------------------------------------
def test_provenance_attribution_comes_from_the_artefact(tmp_path):
    proj = project(tmp_path, signoff_alias("pnr/routed.drc.rpt", "openroad",
                                           router_projection(0)))
    declared = runner._v1_6_620_append_pv_signoff_provenance(proj, "top")
    assert declared == ["reports/phase3/drc_signoff.rpt"]
    entry = json.loads((proj / "provenance.jsonl").read_text().splitlines()[0])
    assert entry["tool"] == "openroad"
    assert "klayout" not in entry["command"]
    assert prov(proj, "klayout,magic,svrfdrc")[0] == 1
    assert prov(proj, "klayout,magic")[0] == 1


def test_negative_control_the_hardcoded_attribution_defeats_every_allowlist(
        tmp_path, monkeypatch):
    """NEGATIVE CONTROL — the pre-fix attribution, executed.

    With the tool hardcoded to `klayout` (what the function did before), the
    router projection passes the provenance gate under EVERY list, including
    one with `openroad` removed. This is the measurement that says the
    allow-list edit alone closes nothing.
    """
    monkeypatch.setattr(runner, "_signoff_drc_tool",
                        lambda p: ("klayout", "klayout -b -r drc (sign-off DRC)"))
    proj = project(tmp_path, signoff_alias("pnr/routed.drc.rpt", "openroad",
                                           router_projection(0)))
    runner._v1_6_620_append_pv_signoff_provenance(proj, "top")
    for tools in ("klayout,magic,openroad", "klayout,magic,svrfdrc",
                  "klayout,magic"):
        assert prov(proj, tools)[0] == 0, tools


def test_an_unattributable_report_is_declared_unknown_never_guessed(tmp_path):
    """§4.05 — a guess is worse than a gap, but silence is worse than a gap too.

    The ledger records the artefact and its real digest; `unknown` is in no
    allow-list, so the gate still FAILs — with a reason that says the producer
    was not determined, rather than one that reads as "never produced".
    """
    proj = project(tmp_path, "nothing recognisable here\n" * 300)
    assert runner._v1_6_620_append_pv_signoff_provenance(proj, "top") == [
        "reports/phase3/drc_signoff.rpt"]
    entry = json.loads((proj / "provenance.jsonl").read_text().splitlines()[0])
    assert entry["tool"] == "unknown"
    rc, out = prov(proj, "klayout,magic,svrfdrc")
    assert rc == 1
    assert "not in allowed" in out


def test_attribution_is_corrected_in_place_when_the_artefact_changes(tmp_path):
    """The stamp used to be append-if-the-PATH-is-absent, so the FIRST record
    for a path was the last one ever written — and the one producer that
    rewrites an existing sign-off report (the SVRF force-refresh) was
    guaranteed a stale digest.
    """
    proj = project(tmp_path, signoff_alias("pnr/routed.drc.rpt", "openroad",
                                           router_projection(0)))
    assert runner._v1_6_620_append_pv_signoff_provenance(proj, "top")
    (proj / "reports" / "phase3" / "drc_signoff.rpt").write_text(
        signoff_alias("reports/drc_svrf.rpt", "svrfdrc", svrf_report(0, 40)))
    again = runner._v1_6_620_append_pv_signoff_provenance(proj, "top")
    assert again == ["reports/phase3/drc_signoff.rpt"], (
        "the ledger did not follow the artefact")
    entries = [json.loads(l) for l in
               (proj / "provenance.jsonl").read_text().splitlines() if l.strip()]
    assert [e["tool"] for e in entries] == ["openroad", "svrfdrc"]
    assert entries[-1]["supersedes"]["tool"] == "openroad"
    assert prov(proj, "klayout,magic,svrfdrc")[0] == 0


def test_re_stamping_an_unchanged_artefact_is_still_a_no_op(tmp_path):
    proj = project(tmp_path, klayout_rdb(top="top"))
    assert runner._v1_6_620_append_pv_signoff_provenance(proj, "top")
    assert runner._v1_6_620_append_pv_signoff_provenance(proj, "top") == []


def test_a_backfill_never_supersedes_a_measured_invocation(tmp_path):
    """The correction must not become its own laundering route.

    When the newest declaration came from a real, observed tool run, a changed
    artefact must keep FAILing on `hash mismatch` — "this is not the file the
    measured run produced" is a far stronger verdict than a fresh back-fill
    carrying the current digest, which would silently turn that FAIL into a
    PASS.
    """
    proj = project(tmp_path, klayout_rdb(top="top"))
    rel = "reports/phase3/drc_signoff.rpt"
    (proj / "provenance.jsonl").write_text(json.dumps({
        "record": "invocation", "measured": True, "tool": "klayout",
        "exit_code": 0, "timestamp": "2020-01-01T00:00:00Z",
        "command": "klayout -b -r /pdk/deck.lydrc -rd input=top.gds",
        "outputs": {rel: "sha256:" + "1" * 64}}) + "\n")
    assert runner._v1_6_620_append_pv_signoff_provenance(proj, "top") == []
    rc, out = prov(proj, "klayout,magic,svrfdrc")
    assert rc == 1
    assert "hash mismatch" in out


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


def test_svrfdrc_needs_the_new_allowlist_and_fails_the_old_one(tmp_path):
    proj = project(tmp_path, svrf_report(fails=0), gds_stem="top")
    runner._v1_6_620_append_pv_signoff_provenance(proj, "top")
    entry = json.loads((proj / "provenance.jsonl").read_text().splitlines()[0])
    assert entry["tool"] == "svrfdrc"
    assert prov(proj, "klayout,magic,svrfdrc")[0] == 0      # the new list
    assert prov(proj, "klayout,magic,openroad")[0] == 1     # the old one


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
                                   "--under", "reports/phase3/drc_router.rpt"])
    payload = json.loads(out.getvalue())
    assert rc == 1
    assert payload["summary"]["real_violation_total"] == 14   # 7 in each report
    assert payload["summary"]["tool_authentic"] is True
    assert "signoff_scope" not in payload["summary"]

    clean = router_projection(0)
    (proj / "phase3" / "stage3" / "pnr" / "routed.drc.rpt").write_text(clean)
    (proj / "reports" / "phase3" / "drc_router.rpt").write_text(clean)
    out2, err2 = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
        rc2 = drc_report_check.run([str(proj), "--mode", "drc",
                                    "--under", "phase3/stage3/pnr",
                                    "--under", "reports/phase3/drc_router.rpt"])
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
