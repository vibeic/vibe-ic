#!/usr/bin/env python3
"""The DELIVERY PATH decides what an ABSENT design-for-ECO declaration means.

THE HOLE THIS CLOSES
====================
The `eco_readiness` axis refuses a candidate that does not carry the spare/ECO
population its design DECLARED. That left one hole, and it was the whole hole:
the declaration was opt-in, so a tape-out-bound run that simply omitted it got
NOT_APPLICABLE -- the pre-fix behaviour, silently. The gate had moved the
problem rather than solved it.

The predicate that closes it must be one a design cannot accidentally omit, and
the obvious ones are all wrong:

    a GDS exists            an IP/hardmacro delivery streams a GDS too
    the PDK is a real one   every design in this corpus targets a real PDK
    a new declaration       a new thing to forget, which is the same hole
                            wearing a different name

The flow already answers it. Step `0.5ic` routes every design down exactly one
of three routes and writes exactly one router artefact to say which. A design
on the CHIP path (0.5ic -> 15.5ic -> 26.5ic -> 37.5ic) is tape-out-bound; one
that terminates at `37.5ip` is a hardmacro delivery and is not.

    CHIP path, no declaration   -> [CANNOT CHECK], candidate UNDETERMINED
    IP path, no declaration     -> NOT_APPLICABLE, and the record says which
    route not established       -> UNDETERMINED. A design that has not been
                                   SHOWN to be an IP delivery is not one.

And the third rule survives all of it: an OPT-OUT, an UNREADABLE artefact and a
REAL ZERO are three findings and never share a verdict.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import delivery_path as DP  # noqa: E402
from _ppa import feasibility as F  # noqa: E402
import _submission_template as ST  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402
from test_ppa_eco_readiness_axis import (DECL, VIEW, axis_of, cand,  # noqa: E402
                                         clean_nine, spares)

CHECK = _PROGRAMS / "ppa_feasibility_check.py"
SPACE = _PROGRAMS / "ppa_pnr_search_space.py"


# ---------------------------------------------------------------------------
# tree builders -- the router artefacts, spelled from the modules that own them
# ---------------------------------------------------------------------------
def _tree(root, pdk="sky130A"):
    (root / ST.INGEST_DIR_REL).mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "project.json").write_text(json.dumps({"pdk": pdk}))
    return root


def chip_tree(root):
    _tree(root)
    (root / TD.SELF_TAPEOUT_REL).write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    return root


def shuttle_tree(root):
    _tree(root)
    d = root / ST.SLOTS_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / "1x1.yaml").write_text("SLOT: 1x1\nDIE_AREA: [0, 0, 100.0, 80.0]\n")
    return root


def ip_tree(root):
    _tree(root)
    (root / ST.NO_TEMPLATE_REL).write_text(ST.NO_TEMPLATE_MARKER + "\n")
    return root


def unrouted_tree(root):
    return _tree(root)


def both_tree(root):
    chip_tree(root)
    (root / ST.NO_TEMPLATE_REL).write_text(ST.NO_TEMPLATE_MARKER + "\n")
    return root


def policy_with(route, declaration=None):
    doc = {"required_views": [dict(VIEW)]}
    if declaration is not None:
        doc["eco_readiness"] = declaration
    if route is not None:
        doc["delivery_path"] = route
    return F.policy_from_document(doc)


# ---------------------------------------------------------------------------
# POSITIVE -- the route is read from the route, by the flow's own predicate
# ---------------------------------------------------------------------------
def test_positive_the_self_tapeout_and_shuttle_routes_are_both_the_chip_path(
        tmp_path):
    """Two of the three routes out of 0.5ic land on the chip terminal, and
    both are tape-out-bound. A predicate that recognised only one of them
    would let a shuttle die through."""
    assert DP.resolve(chip_tree(tmp_path / "a"))["path"] == DP.PATH_CHIP
    assert DP.resolve(shuttle_tree(tmp_path / "b"))["path"] == DP.PATH_CHIP
    assert DP.is_tapeout_bound(DP.PATH_CHIP)


def test_positive_the_hardmacro_terminal_is_not_tapeout_bound(tmp_path):
    r = DP.resolve(ip_tree(tmp_path / "ip"))
    assert r["path"] == DP.PATH_IP
    assert not DP.is_tapeout_bound(r["path"])


def test_positive_the_predicate_is_the_flows_own_and_is_run_not_retyped():
    """The route is decided by driving `flow_compliance_check._check_condition`
    over the conditions of steps 37.5ic and 37.5ip, read from the flow
    document. This asserts the module really used THOSE conditions -- not a
    private glob that happens to agree today and stops agreeing when a router
    artefact is renamed."""
    pytest.importorskip("yaml")
    import yaml
    flow = yaml.safe_load(
        (_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    by_id = {str(s["id"]): s for s in flow["steps"]}
    conds, why = DP._terminal_conditions()
    assert why is None, why
    assert conds[DP.STEP_CHIP] == (by_id[DP.STEP_CHIP].get("condition") or {})
    assert conds[DP.STEP_IP] == (by_id[DP.STEP_IP].get("condition") or {})


# ---------------------------------------------------------------------------
# NEGATIVE -- the chip path with no declaration is a refusal
# ---------------------------------------------------------------------------
def test_negative_chip_path_with_no_declaration_is_undetermined():
    """THE HOLE. Before the route, this candidate was NOT_APPLICABLE and the
    set passed. It is tape-out-bound and nobody said what ECO readiness it
    needs, so nothing here can say whether the layout is repairable."""
    r = F.promotion_verdict(cand("chip", clean_nine()),
                            policy_with({"path": DP.PATH_CHIP}))
    assert r.verdict == F.UNDETERMINED, r.codes
    assert not r.eligible_for_promotion
    a = axis_of(r)
    assert a.status == F.AXIS_UNDETERMINED
    assert a.codes == (F.C_ECO_NOT_DECLARED_ON_CHIP_PATH,)
    assert a.applicability["delivery_path"] == DP.PATH_CHIP


def test_negative_an_unestablished_route_is_refused_not_read_as_ip():
    """`!= IP`, never `== CHIP`. A tree with no router artefact, a tree
    carrying both, and a flow that could not be read are three ways of NOT
    having established a route, and none of them is evidence of a hardmacro
    delivery."""
    for path in (DP.PATH_NOT_DETERMINED, DP.PATH_BOTH, DP.PATH_UNREADABLE):
        r = F.promotion_verdict(cand("x", clean_nine()),
                                policy_with({"path": path}))
        assert r.verdict == F.UNDETERMINED, path
        assert axis_of(r).codes == (F.C_ECO_PATH_UNDETERMINED,), path


def test_negative_via_the_cli_with_a_real_chip_tree(tmp_path):
    project = chip_tree(tmp_path / "proj")
    doc = {"required_views": [VIEW], "candidates": [cand("c", clean_nine())]}
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "feas.json"
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(p),
                        "--project", str(project), "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_UNDETERMINED, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert "delivery path CHIP" in r.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    axes = {a["axis"]: a["status"] for a in report["candidates"][0]["axes"]}
    assert axes["eco_readiness"] == "UNDETERMINED"
    assert report["policy"]["eco_readiness"]["delivery_path"]["path"] == "CHIP"


# ---------------------------------------------------------------------------
# IP path -- a finding, and the right one
# ---------------------------------------------------------------------------
def test_ip_path_with_no_declaration_is_not_applicable_and_says_why(tmp_path):
    project = ip_tree(tmp_path / "proj")
    doc = {"required_views": [VIEW], "candidates": [cand("c", clean_nine())]}
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "feas.json"
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(p),
                        "--project", str(project), "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_PASS, r.stdout + r.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    row = [a for a in report["candidates"][0]["axes"]
           if a["axis"] == "eco_readiness"][0]
    assert row["status"] == "NOT_APPLICABLE"
    assert row["codes"] == [F.C_ECO_NOT_APPLICABLE_ON_IP_PATH]
    assert "hardmacro" in row["applicability"]["reason"]


def test_the_two_not_applicables_do_not_share_a_code():
    """"this design is a hardmacro delivery", "the design opted out" and
    "nobody asked" are three benign-looking answers with three different
    causes, and a reader who cannot tell them apart cannot act on any of
    them."""
    ip = axis_of(F.promotion_verdict(cand("a", clean_nine()),
                                     policy_with({"path": DP.PATH_IP})))
    opted = axis_of(F.promotion_verdict(cand("b", clean_nine()),
                                        policy_with({"path": DP.PATH_IP},
                                                    {"required": False})))
    unasked = axis_of(F.promotion_verdict(cand("c", clean_nine()),
                                          policy_with(None)))
    assert ip.status == opted.status == unasked.status == F.AXIS_NOT_APPLICABLE
    assert len({ip.codes, opted.codes, unasked.codes}) == 3


def test_an_opt_out_on_the_chip_path_is_visible_but_not_overruled():
    """The move somebody would make to get around this axis. It stays
    NOT_APPLICABLE -- an opt-out is a decision and this module does not
    overrule decisions -- and it gets its own code so a reader can find every
    design that made it."""
    a = axis_of(F.promotion_verdict(cand("c", clean_nine()),
                                    policy_with({"path": DP.PATH_CHIP},
                                                {"required": False})))
    assert a.status == F.AXIS_NOT_APPLICABLE
    assert a.codes == (F.C_ECO_OPTED_OUT_ON_CHIP_PATH,)


# ---------------------------------------------------------------------------
# VACUOUS
# ---------------------------------------------------------------------------
def test_vacuous_no_project_is_not_a_finding_about_the_design():
    r = DP.resolve(None)
    assert r["path"] == DP.PATH_NOT_SUPPLIED
    assert "not a finding" in r["reason"]
    a = axis_of(F.promotion_verdict(cand("c", clean_nine()), policy_with(None)))
    assert a.status == F.AXIS_NOT_APPLICABLE
    assert a.codes == (F.C_ECO_NOT_DECLARED,)


def test_vacuous_a_project_that_is_not_a_directory_is_unreadable(tmp_path):
    f = tmp_path / "not-a-dir"
    f.write_text("x", encoding="utf-8")
    assert DP.resolve(f)["path"] == DP.PATH_UNREADABLE
    assert DP.resolve(tmp_path / "nope")["path"] == DP.PATH_UNREADABLE


def test_vacuous_the_search_space_refuses_a_chip_tree_with_no_declaration(
        tmp_path):
    project = chip_tree(tmp_path / "proj")
    out = tmp_path / "space.json"
    r = subprocess.run([sys.executable, str(SPACE), "--json", str(out),
                        "--project", str(project)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert not out.exists(), (
        "a space was published for a tape-out-bound design whose spare-cell "
        "lever nobody could bound. That is the document the search reads.")


# ---------------------------------------------------------------------------
# MUTATIONS -- each must be RED
# ---------------------------------------------------------------------------
def test_M_PATH_1_the_route_alone_flips_the_verdict():
    """The negative control for the whole mechanism. IDENTICAL records and
    IDENTICAL (absent) declaration; only the route differs. If these two ever
    agree, either the chip path is not refusing or the IP path is."""
    ms = clean_nine()
    chip = F.promotion_verdict(cand("c", ms), policy_with({"path": DP.PATH_CHIP}))
    ip = F.promotion_verdict(cand("c", ms), policy_with({"path": DP.PATH_IP}))
    assert chip.verdict == F.UNDETERMINED
    assert ip.verdict == F.FEASIBLE
    assert chip.verdict != ip.verdict


def test_M_PATH_2_a_gds_and_a_real_pdk_do_not_make_a_design_tapeout_bound(
        tmp_path):
    """The inference the ruling forbids, made impossible rather than avoided.
    This tree has a streamed GDS and a real PDK and NO router artefact. An
    implementation that guessed from either would say CHIP; the route says
    nobody established one, which is the truth."""
    root = unrouted_tree(tmp_path / "proj")
    gds = root / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True)
    (gds / "top.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    assert DP.resolve(root)["path"] == DP.PATH_NOT_DETERMINED
    assert not DP.is_tapeout_bound(DP.resolve(root)["path"])


def test_M_PATH_3_a_tree_holding_both_routers_is_refused_not_picked(tmp_path):
    """No silicon corresponds to a tree on both terminals at once. Picking
    either one would be inventing a route the design never took."""
    r = DP.resolve(both_tree(tmp_path / "proj"))
    assert r["path"] == DP.PATH_BOTH
    assert not DP.is_tapeout_bound(r["path"])


def test_M_PATH_4_the_three_findings_never_share_a_verdict():
    """The rule that survives every state above: an OPT-OUT, an artefact that
    could not be READ, and a population that is genuinely ZERO are three
    findings. Collapsing any pair of them is how one of the three gets acted
    on as if it were another."""
    route = {"path": DP.PATH_CHIP}
    opt_out = F.promotion_verdict(
        cand("opt", clean_nine()), policy_with(route, {"required": False}))
    unreadable = F.promotion_verdict(
        cand("unread", clean_nine() + [
            {"schema": F.METRIC_SCHEMA, "metric": F.ECO_M_COUNT,
             "status": "NOT_MEASURED", "scope": dict(VIEW),
             "reason": "the spare plan could not be read"}]),
        policy_with(route, DECL))
    real_zero = F.promotion_verdict(
        cand("zero", clean_nine() + spares(
            count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
            positions=0, tied=None)),
        policy_with(route, DECL))
    assert opt_out.verdict == F.FEASIBLE
    assert unreadable.verdict == F.UNDETERMINED
    assert real_zero.verdict == F.INFEASIBLE
    assert len({opt_out.verdict, unreadable.verdict, real_zero.verdict}) == 3


def test_M_PATH_5_the_two_path_vocabularies_agree():
    """`_ppa/feasibility.py` re-declares three path strings rather than
    importing them, so the promotion gate never acquires a dependency on a
    module that walks a filesystem. That decoupling is only safe while the two
    spellings match, and a comment saying they do is not a check."""
    assert F.PATH_CHIP == DP.PATH_CHIP
    assert F.PATH_IP == DP.PATH_IP
    assert F.PATH_NOT_SUPPLIED == DP.PATH_NOT_SUPPLIED


def test_M_PATH_6_a_declaration_still_wins_on_either_path():
    """The route decides what an ABSENT declaration means and nothing else. A
    design that stated a requirement is held to it wherever it is going --
    including an IP that wants spares in its own macro."""
    ms = clean_nine() + spares(
        count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
        positions=0, tied=None)
    for path in (DP.PATH_CHIP, DP.PATH_IP, DP.PATH_NOT_DETERMINED):
        r = F.promotion_verdict(cand("c", ms), policy_with({"path": path}, DECL))
        assert r.verdict == F.INFEASIBLE, path
        assert axis_of(r).status == F.AXIS_VIOLATED, path


def test_M_PATH_7_the_space_still_publishes_for_a_proven_ip_delivery(tmp_path):
    """The other half of the space's refusal. If it refused every project it
    would be a program nobody could use, and the refusal would prove nothing.
    Only a design PROVEN to terminate at the hardmacro delivery gets the
    unbounded lever."""
    project = ip_tree(tmp_path / "proj")
    out = tmp_path / "space.json"
    r = subprocess.run([sys.executable, str(SPACE), "--json", str(out),
                        "--project", str(project)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    space = json.loads(out.read_text(encoding="utf-8"))
    assert space["delivery_path"]["path"] == DP.PATH_IP
    lever = [l for l in space["levers"]
             if l["lever"] == "spare_cell_density"][0]
    assert lever["eco_floor"]["bounds_this_lever"] is False


# ---------------------------------------------------------------------------
# BAD INVOCATION -- 3, and never 2, for both CLIs the route reached
# ---------------------------------------------------------------------------
#: §1 gives 2 to "I could not look" and 3 to "you asked wrongly", and the two
#: are easy to confuse in exactly the way that matters: a caller that skips on 2
#: reads a misspelled flag as a step with nothing to check. `--project` is a new
#: flag on two programs, so it gets the arm both of them already have.
def test_bad_invocation_project_with_no_value_is_3_not_2(tmp_path):
    for prog, base in ((CHECK, ["--candidates", str(tmp_path / "x.json")]),
                       (SPACE, [])):
        r = subprocess.run([sys.executable, str(prog), *base, "--project"],
                           capture_output=True, text=True, cwd=str(tmp_path))
        assert r.returncode == 3, (
            f"{prog.name} exited {r.returncode} on `--project` with no value; "
            f"§1 says a bad invocation is 3 and 2 would be read as "
            f"'nothing to check'.\n{r.stderr[-300:]}")


def test_bad_invocation_help_documents_project_on_both(tmp_path):
    """A flag nobody can find is a flag nobody passes, and this one decides
    what an ABSENT ECO declaration means. Asserted on the OUTPUT rather than
    the exit code, because one of the two CLIs gets that code wrong -- see
    below."""
    for prog in (CHECK, SPACE):
        r = subprocess.run([sys.executable, str(prog), "--help"],
                           capture_output=True, text=True, cwd=str(tmp_path))
        assert "--project" in r.stdout, prog.name


def test_bad_invocation_help_exits_0_on_the_search_space(tmp_path):
    """The opposite mistake, and it is the one the obvious fix invites: asking
    a program what its flags are is not a bad invocation."""
    r = subprocess.run([sys.executable, str(SPACE), "--help"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0


@pytest.mark.xfail(
    strict=True,
    reason="PRE-EXISTING, and NOT this branch's to fix. "
           "`ppa_feasibility_check.py --help` exits 3 instead of 0 -- asking a "
           "program what its flags are is not a bad invocation. It is measured "
           "on origin/main, its one-line fix is `_ppa/cli_exit.parse_or_refuse` "
           "(which this CLI does not use for its own parse), and "
           "`test_ppa_layer_exit_contract._XFAIL_HELP` already pins it "
           "strict=True under a stated contract: the fix and the pin's removal "
           "land together, by the lane that owns them. Fixing it here would "
           "turn that file red and leave someone else's pin to clean up. This "
           "arm exists so that a suite which ADDED a flag to that CLI says the "
           "defect out loud instead of quietly asserting around it.")
def test_bad_invocation_help_is_0_on_the_feasibility_cli_too(tmp_path):
    r = subprocess.run([sys.executable, str(CHECK), "--help"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0


def test_bad_invocation_a_project_that_is_a_file_is_2_not_3(tmp_path):
    """And the distinction in the other direction. A `--project` that names a
    FILE is a well-formed invocation pointing at something unusable: that is
    [CANNOT CHECK], not a usage error, and the two must not swap."""
    f = tmp_path / "not-a-dir"
    f.write_text("x", encoding="utf-8")
    out = tmp_path / "space.json"
    r = subprocess.run([sys.executable, str(SPACE), "--json", str(out),
                        "--project", str(f)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr
