"""test_issue904_standin_disclosure_refuted_by_native_pdk.py — vibe-ic#904.

THE DEFECT. `analog_corner_lib_realism_lint` downgraded a LEVEL=1 standin from
ERROR to advisory WARNING whenever a disclosure SENTENCE was present, and never
asked whether that sentence was true. The sentence it accepts is a falsifiable
claim about the host — that the declared target process ships no public ngspice
corner library. Measured on the published tree, a deck asserting exactly that
bought `[WARN] … rc 0` while the PDK it named was installed and shipping
sectioned corner libraries for every device class.

THE CLAIM IS WRONG, NOT THE WORLD. So the disclosure is now refutable: a
POSITIVE native resolution of the L19-declared target (with real ngspice model
libs enumerated) takes the excuse away.

WHAT THESE TESTS ASK. Every assertion reads the PROGRAM — its `--json` report
and its exit code, over subprocess — never a local re-computation of the rule.

  test_refuted            the moving test. Must FAIL against origin/main.
  test_not_installed      GUARD. Same deck, target resolves nowhere → the
                          disclosure stands, WARN/rc 0, byte-for-byte the old
                          behaviour. Stops "fix" == "fail every disclosure".
  test_probe_unreachable  GUARD. Same deck, no probe at all → WARN/rc 0.
  test_undisclosed_*      GUARD. No disclosure → still ERROR/rc 1 (unchanged).
  test_clean_deck_*       GUARD. No standin → PASS/rc 0 even with the native
                          PDK present: the probe must never invent a finding.
  test_live_waiver_*      GUARD. An attributable human waiver still silences.
  test_every_disclosure_token_is_refutable
                          the vocabulary is SCRAPED from the program
                          (`_DISCLOSURE_TOKENS`), not typed here, so a token
                          added later is covered without editing this file.

Chip-AGNOSTIC: the target family is an invented string, the fixture PDK tree is
built by these tests, and no real foundry/process/design name appears.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "analog_corner_lib_realism_lint.py")

_TIMEOUT_S = 60          # harness ceiling
_TARGET = "fabnode9x"    # invented family — matches no real foundry


def _module():
    """The program itself, for the vocabulary it owns (rule: discover, never
    enumerate)."""
    spec = importlib.util.spec_from_file_location("_aclrl_904", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PROG.parent))
    spec.loader.exec_module(mod)
    return mod


_LEVEL1_BODY = """.subckt amp vdd vss vin vout
mn1 vout vin vss vss nm w=8u l=1u
.ends
.model nm nmos (LEVEL=1 VTO=0.42 KP=70u)
.model pm pmos (LEVEL=1 VTO=-0.47 KP=28u)
"""


def _deck(disclosure: str | None) -> str:
    head = "* modulator core\n"
    if disclosure:
        head += f"* HONEST DISCLOSURE: {disclosure}\n"
    return head + _LEVEL1_BODY


def _mk_project(tmp_path: Path, deck_text: str, *, declare: bool = True,
                block: str = "amp0") -> Path:
    proj = tmp_path / "proj"
    d = proj / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{block}.sp").write_text(deck_text)
    if declare:
        g = proj / "phase1" / "generated_docs"
        g.mkdir(parents=True, exist_ok=True)
        (g / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"pdk_target": _TARGET}}))
    return proj


def _mk_pdks_root(tmp_path: Path, *, install_target: bool) -> Path:
    """A PDK install root. `install_target` decides whether the DECLARED target
    is among the installed families — i.e. whether the disclosure's premise is
    true. Either way the root is listable, so the probe succeeds."""
    root = tmp_path / "pdks"
    other = root / "othernode4k" / "libs.tech" / "ngspice"
    other.mkdir(parents=True)
    (other / "othernode.lib").write_text(".subckt o d g s b\n.ends\n")
    if install_target:
        ng = root / _TARGET / "libs.tech" / "ngspice" / "models"
        ng.mkdir(parents=True)
        (ng / "cornerMOS.lib").write_text(
            ".LIB mos_tt\n.include devs_mod.lib\n.ENDL mos_tt\n"
            ".LIB mos_ss\n.include devs_mod.lib\n.ENDL mos_ss\n")
        (ng / "devs_mod.lib").write_text(".subckt dev_n d g s b\n.ends\n")
    return root


def _run(proj: Path, pdks_root: Path | None):
    """Ask the PROGRAM. Returns (CompletedProcess, report dict).

    argv is IDENTICAL on both arms of the control — the probe root travels by
    environment, which the unfixed program simply ignores. So a guard here
    exercises the same invocation before and after the fix, and an argument
    parser difference can never masquerade as a behaviour difference."""
    out = proj.parent / "r.json"
    cmd = [sys.executable, str(PROG), str(proj), "--json", str(out)]
    env = dict(os.environ)
    # No ambient container may leak in and make the probe non-deterministic.
    env.pop("EDA_CONTAINER", None)
    env.pop("VIBEIC_EDA_CONTAINER", None)
    env.pop("VIBEIC_PDKS_ROOT", None)
    if pdks_root is not None:
        env["VIBEIC_PDKS_ROOT"] = str(pdks_root)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=_TIMEOUT_S, env=env)
    return r, json.loads(out.read_text())


# ── the moving test ────────────────────────────────────────────────────────

def test_refuted_disclosure_does_not_downgrade_a_standin(tmp_path: Path):
    """Declared target IS installed with real ngspice model libs → the deck's
    'no public ngspice corner lib' disclosure is refuted and buys nothing."""
    proj = _mk_project(tmp_path, _deck(
        "this PDK has NO public ngspice corner lib. Models are DOCUMENTED "
        "LEVEL=1 STANDIN = MODELED, not silicon sign-off."))
    root = _mk_pdks_root(tmp_path, install_target=True)

    r, rpt = _run(proj, root)

    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert rpt["verdict"] == "FAIL", rpt["verdict"]
    assert rpt["findings"], "a LEVEL=1 deck must still produce findings"
    for f in rpt["findings"]:
        assert f["severity"] == "ERROR", f
        assert f["disclosure_refuted"] is True, f
        assert f["rule"] == "CORNER_LIB_STANDIN_DISCLOSURE_REFUTED", f

    # The verdict must be auditable: the report carries what was measured.
    ev = rpt["native_pdk_evidence"]
    assert ev, "the refutation must publish its evidence"
    assert ev["target"] == _TARGET
    assert ev["model_lib_count"] >= 1
    assert all(str(root) in p for p in ev["model_libs"]), ev["model_libs"]


def test_project_staged_pdk_refutes_with_no_probe_configured(tmp_path: Path):
    """Rung 1 is a LOCAL-FILESYSTEM fact and needs no container, so this is the
    one refutation that fires with no probe configuration at all. Stated
    explicitly rather than left as a side effect: a project that STAGES its own
    SPICE model libs under input/pdk/ has the models, so its standin is
    unjustified wherever the lint runs."""
    proj = _mk_project(tmp_path, _deck(
        "no public ngspice corner lib; documented level=1 standin"))
    staged = proj / "input" / "pdk" / "spice"
    staged.mkdir(parents=True)
    (staged / "devices.lib").write_text(
        ".subckt dev_n d g s b\n.ends\n.subckt dev_p d g s b\n.ends\n")

    r, rpt = _run(proj, None)          # no --pdks-root, no container

    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "FAIL", rpt["verdict"]
    ev = rpt["native_pdk_evidence"]
    assert ev and ev["rung"] == 1, ev
    assert ev["source"] == "project_custom_pdk", ev


def test_waiver_survives_refutation_but_the_record_says_which_held(
        tmp_path: Path):
    """A waiver AND a refuted disclosure on the same deck: the verdict is still
    advisory (the waiver holds), but the record must not read as though the
    disclosure did the holding."""
    proj = _mk_project(tmp_path, _deck(
        "no public ngspice corner lib; documented level=1 standin"))
    (proj / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "corner_lib-standin", "status": "approved",
        "rule": "corner_lib", "reason": "accepted for this bring-up"}]}))
    root = _mk_pdks_root(tmp_path, install_target=True)

    r, rpt = _run(proj, root)

    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "WARN", rpt["verdict"]
    for f in rpt["findings"]:
        assert f["severity"] == "WARNING", f
        assert f["disclosure_refuted"] is True, f
        assert "LIVE PROJECT WAIVER" in f["message"], f["message"]


def test_every_disclosure_token_is_refutable(tmp_path: Path):
    """The disclosure vocabulary is the PROGRAM's, not this file's. Whichever
    phrase a deck uses, a host that supplies the models refutes it."""
    tokens = _module()._DISCLOSURE_TOKENS
    assert tokens, "the program must expose a disclosure vocabulary"
    root = _mk_pdks_root(tmp_path, install_target=True)
    for i, tok in enumerate(tokens):
        proj = _mk_project(tmp_path / f"t{i}", _deck(f"note: {tok} applies"),
                           block=f"amp{i}")
        r, rpt = _run(proj, root)
        assert rpt["verdict"] == "FAIL", f"token {tok!r} still downgraded"
        assert r.returncode == 1, f"token {tok!r} rc={r.returncode}"


# ── paired guards: these must NOT change ───────────────────────────────────

def test_guard_target_not_installed_still_warns(tmp_path: Path):
    """Probe SUCCEEDS and finds the target nowhere → the disclosure is true,
    it stands, and the verdict is the pre-#904 advisory WARN."""
    proj = _mk_project(tmp_path, _deck(
        "this PDK has NO public ngspice corner lib. DOCUMENTED LEVEL=1 "
        "STANDIN, MODELED, not silicon sign-off."))
    root = _mk_pdks_root(tmp_path, install_target=False)

    r, rpt = _run(proj, root)

    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "WARN", rpt["verdict"]
    # `.get` on purpose: the key is NEW, and a guard must assert the same
    # invariant on both arms of the control.
    assert rpt.get("native_pdk_evidence") is None
    for f in rpt["findings"]:
        assert f["severity"] == "WARNING", f
        assert f["rule"] == "CORNER_LIB_STANDIN_DISCLOSED", f


def test_guard_no_probe_at_all_still_warns(tmp_path: Path):
    """No --pdks-root, no container, and (below) no L19 declaration either:
    nothing was measured, so nothing may be refuted."""
    proj = _mk_project(tmp_path, _deck(
        "no public ngspice corner lib for this process; documented level=1 "
        "standin"), declare=False)

    r, rpt = _run(proj, None)

    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "WARN", rpt["verdict"]
    assert rpt.get("native_pdk_evidence") is None


def test_guard_undisclosed_standin_still_fails(tmp_path: Path):
    """The original silent-substitution FAIL is untouched — and it is still the
    ORIGINAL rule, not the new one."""
    proj = _mk_project(tmp_path, _deck(None))
    root = _mk_pdks_root(tmp_path, install_target=False)

    r, rpt = _run(proj, root)

    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "FAIL"
    for f in rpt["findings"]:
        assert f["rule"] == "CORNER_LIB_IDEAL_MODEL", f
        assert f.get("disclosure_refuted", False) is False, f


def test_guard_clean_deck_passes_even_with_native_pdk(tmp_path: Path):
    """A deck with no standin at all must stay PASS. The probe is not allowed
    to manufacture a finding out of an installed PDK."""
    proj = _mk_project(tmp_path,
                       "* real foundry deck\n"
                       ".include /pdk/models/cornerMOS.lib\n"
                       ".subckt amp vdd vss vin vout\n"
                       "xm1 vout vin vss vss dev_n w=8 l=1\n.ends\n")
    root = _mk_pdks_root(tmp_path, install_target=True)

    r, rpt = _run(proj, root)

    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "PASS", rpt["verdict"]
    assert rpt["findings"] == []


def test_guard_live_project_waiver_still_silences(tmp_path: Path):
    """A waiver is an attributable human acceptance, not a claim about the
    host — it is deliberately NOT refutable, and still downgrades."""
    proj = _mk_project(tmp_path, _deck(None))
    (proj / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "corner_lib-standin", "status": "approved",
        "rule": "corner_lib", "reason": "accepted for this bring-up"}]}))
    root = _mk_pdks_root(tmp_path, install_target=True)

    r, rpt = _run(proj, root)

    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"
    assert rpt["verdict"] == "WARN", rpt["verdict"]
    for f in rpt["findings"]:
        assert f["severity"] == "WARNING", f
