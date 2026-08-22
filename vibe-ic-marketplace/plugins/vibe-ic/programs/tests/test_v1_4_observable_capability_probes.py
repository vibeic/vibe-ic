"""Batch 2 of the wording-gate retirement: verdict classification + capability probes.

FIVE MORE SITES where control decisions keyed on tool WORDING:

  (1) HIGH  `lec_run.py` `_FRONTEND_PARSE_ABORT_RE` — the RESIDUAL HALF of the
      bug fixed in ea13744db. Frontend SELECTION moved to the observable there,
      but the VERDICT classification (INCONCLUSIVE vs FAIL on a zero-miter run)
      still keyed on an allow-list of phrasings. A miss restores the false FAIL
      that cascade-marks 24 downstream steps MISSING.
  (2) `synth_frontend.read_slang_is_builtin` — probed a capability by reading an
      error phrase instead of by exercising the capability.
  (3) `phase3_one_shot_runner._openroad_supports_postroute_spef_repair` —
      scraped `help estimate_parasitics` text to gate OUR OWN FORK's post-route
      SPEF repair; a help-format change silently disables it.
  (4) `phase3_one_shot_runner._LVS_EXT_ERROR_RE` — the count had to PRECEDE the
      word "error", so a reworded summary silently dropped the extraction-
      collapse guard entirely.
  (5) `lec_post_layout_check._FUNC_READ_LIB_ABORT_RE` — selects between a SOUND
      and an UNSOUND equivalence recipe.

THE OBSERVABLES:
  (1) STAGE PROGRESS. yosys numbers and announces every pass it dispatches, so
      "only frontend passes ran" is positive evidence the read is where it
      stopped — no elaborated design was ever produced.
  (2)(3)(5) A CAPABILITY PROBE SHOULD PROBE — try the capability on a tiny
      fixture and observe whether it worked, rather than parsing help/error text.
      (3) additionally self-calibrates against a deliberately-invalid control
      flag, so it needs no knowledge of how a rejection is phrased.
  (4) order-agnostic extraction, plus an explicit UNMEASURED signal so the
      guard's absence can never again be silent.

§4.05 — the direction of safety is NOT uniform across these sites, and the tests
below pin each direction separately:
  * (1) INCONCLUSIVE is the LESS blocking outcome, so widening it is the
    dangerous direction. It therefore requires POSITIVE stage evidence, and both
    "yosys never ran" and "died after elaborating" stay HARD FAIL.
  * (5) the fallback recipe is UNSOUND (it can false-PASS NAND=NOR), so widening
    what selects it widens what can PASS. A missing/empty liberty is classified
    as an INPUT defect and is explicitly denied the fallback.
  * (2)(3) fail-safe defaults are unchanged; a failed probe costs only a
    recoverable fallback.
"""
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import lec_run as LR                      # noqa: E402
import lec_post_layout_check as LP        # noqa: E402
import synth_frontend as SF               # noqa: E402
import phase3_one_shot_runner as P3       # noqa: E402


CONTAINER = "vibeic-eda"

# vibe-ic#1283 — the probe below used to be `except Exception: return False`,
# which reports a probe that TIMED OUT as a container that is not there. That
# is not a hypothetical here: measured on 1adbf3444 with a `docker` shim that
# never answers, this file skipped FIVE tests with "vibeic-eda container not
# available" on a host where `docker exec vibeic-eda true` returned 0 — the
# container was up the whole time, and the run was green either way. `probe`
# routes a lost race to NOT_VERIFIED/PROBE UNANSWERED instead of to a claim.
from not_verified_tier import (PROBE_PRESENT, probe,  # noqa: E402
                               probe_skip_reason)

RUN_REMEDY = "bash tools/vibeic-eda/restart-eda.sh"
_CONTAINER_STATE, _CONTAINER_DETAIL = probe(["docker", "exec", CONTAINER, "true"])


#: 60 s, not 180: 180 IS the harness item bound, so this bound could never fire
#: — `--timeout-method=thread` would have taken the session down first.
#: MEASURED with the container up (37 passed in 24.54 s): 5 real `docker exec`
#: calls through here, worst single call 0.579 s, so 60 s is ~100x the worst
#: case. Invisible to `ci_harness_timeout_ceiling_check` until vibe-ic#1277.
def _dexec(cmd: str, timeout: int = 60):
    r = subprocess.run(["docker", "exec", CONTAINER, "bash", "-lc", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + "\n" + (r.stderr or "")


requires_container = pytest.mark.skipif(
    _CONTAINER_STATE != PROBE_PRESENT,
    reason=probe_skip_reason(_CONTAINER_STATE, _CONTAINER_DETAIL,
                             "vibeic-eda container not available", RUN_REMEDY))


# ═══════════════════════════════════════════════════════════════════════════
# (1) HIGH — verdict classification by STAGE PROGRESS, not by wording
# ═══════════════════════════════════════════════════════════════════════════

# REAL transcripts captured from the vibeic-eda image. These are not invented
# rewordings — they are what the tools actually printed, and every one of them
# is MISSED by the wording allow-list, so each produced a false FAIL.
REAL_SLANG_ABORTS = {
    "undeclared identifier": (
        "1. Executing SLANG frontend.\n"
        "../../tmp/ab/a.sv:1:43: error: use of undeclared identifier "
        "'undefined_func'\n"
        "Build failed: 1 error, 0 warnings\n"
        "ERROR: Compilation failed\n"),
    "unknown module": (
        "1. Executing SLANG frontend.\n"
        "../../tmp/ab/b.sv:1:32: error: unknown module 'missing_child'\n"
        "Build failed: 1 error, 0 warnings\n"
        "ERROR: Compilation failed\n"),
    "no member in package": (
        "1. Executing SLANG frontend.\n"
        "../../tmp/ab/c.sv:2:44: error: no member named 'NOT_THERE' in "
        "package 'p'\n"
        "Build failed: 1 error, 0 warnings\n"
        "ERROR: Compilation failed\n"),
}

# Real transcript: the read succeeded and HIERARCHY ran, then it died.
REAL_POST_FRONTEND_FAILURE = (
    "1. Executing Verilog-2005 frontend: /tmp/lec_obs/good.v\n"
    "2. Executing HIERARCHY pass (managing design hierarchy).\n"
    "ERROR: Module `nonexistent' not found!\n")

# A crash before yosys produced any pass at all.
REAL_CRASH_NO_PASSES = (
    "docker: Error response from daemon: container vibeic-eda is not running\n")


@pytest.mark.parametrize("name", sorted(REAL_SLANG_ABORTS))
def test_real_aborts_missed_by_wording_are_caught_by_the_observable(name):
    """Each of these is a REAL frontend abort the allow-list does not match —
    the false FAIL. The stage observable catches all of them."""
    text = REAL_SLANG_ABORTS[name]
    assert LR.is_frontend_parse_abort(text) is False, (
        "fixture no longer demonstrates the wording gap")
    aborted, evidence = LR.frontend_aborted_before_elaboration(text)
    assert aborted is True, evidence
    assert "no design-building pass" in evidence


@pytest.mark.parametrize("name", sorted(REAL_SLANG_ABORTS))
def test_real_aborts_classify_inconclusive_not_fail(name):
    """End-to-end through the verdict classifier: INCONCLUSIVE, not a false
    FAIL that cascade-marks 24 downstream steps MISSING."""
    p = LR.parse_equiv_output(REAL_SLANG_ABORTS[name])
    assert p["parse_error"] is True
    assert p["verdict"] == "INCONCLUSIVE"
    assert p["equivalent"] is False          # never a vacuous pass


def test_classification_is_invariant_across_wording():
    """Hold the stage evidence fixed, vary only the error text — the verdict
    must not move. A wording allow-list cannot satisfy this."""
    verdicts = set()
    for tail in ("ERROR: syntax error, unexpected TOK_PACKAGE",
                 "error: unknown module 'x'",
                 "error: no member named 'Q' in package 'p'",
                 "Build failed: 1 error, 0 warnings",
                 "ERROR: Compilation failed",
                 ""):
        text = f"1. Executing SLANG frontend.\n{tail}\n"
        verdicts.add(LR.parse_equiv_output(text)["verdict"])
    assert verdicts == {"INCONCLUSIVE"}


# ── §4.05 NEGATIVES for (1): the asymmetry is preserved ────────────────────

def test_crash_with_no_frontend_evidence_stays_hard_fail():
    """THE LOAD-BEARING NEGATIVE the earlier fix deliberately imposed. A yosys /
    docker crash produced NO pass at all, so there is no evidence the frontend
    is where it stopped. INCONCLUSIVE is the LESS blocking outcome, so it must
    NOT be reachable without positive stage evidence."""
    aborted, evidence = LR.frontend_aborted_before_elaboration(
        REAL_CRASH_NO_PASSES)
    assert aborted is False
    assert "no yosys pass executed" in evidence
    p = LR.parse_equiv_output(REAL_CRASH_NO_PASSES)
    assert p["verdict"] == "FAIL"
    assert "NOT re-classified as INCONCLUSIVE" in p["verdict_explanation"]


def test_failure_after_elaboration_stays_hard_fail():
    """The run got PAST the read — a design WAS elaborated — so whatever failed
    later is not a frontend abort and must stay a blocking FAIL."""
    aborted, evidence = LR.frontend_aborted_before_elaboration(
        REAL_POST_FRONTEND_FAILURE)
    assert aborted is False
    assert "got PAST the read" in evidence
    assert LR.parse_equiv_output(REAL_POST_FRONTEND_FAILURE)["verdict"] == "FAIL"


def test_a_real_mismatch_is_never_reclassified():
    """A miter that RAN and left points unequal is a real result: it must FAIL
    regardless of anything in this change (parse_error is False, so the
    re-classification is unreachable)."""
    mismatch = (
        "1. Executing Verilog-2005 frontend: /p/rtl/x.v\n"
        "2. Executing HIERARCHY pass (managing design hierarchy).\n"
        "3. Executing EQUIV_STATUS pass.\n"
        "Found 71 $equiv cells in equiv:\n"
        "  Of those cells 60 are proven and 11 are unproven.\n")
    p = LR.parse_equiv_output(mismatch)
    assert p["parse_error"] is False
    assert p["verdict"] != "INCONCLUSIVE"
    assert p["equivalent"] is not True


def test_yosys_executed_passes_parses_real_transcripts():
    assert LR.yosys_executed_passes(REAL_POST_FRONTEND_FAILURE) == [
        "Verilog-2005 frontend: /tmp/lec_obs/good.v",
        "HIERARCHY pass (managing design hierarchy).",
    ]
    assert LR.yosys_executed_passes("") == []
    # sub-numbered passes ("1.8. Executing PROC_CLEAN pass") are real yosys output
    assert LR.yosys_executed_passes(
        "1.8. Executing PROC_CLEAN pass (remove empty switches).\n") == [
            "PROC_CLEAN pass (remove empty switches)."]


# ═══════════════════════════════════════════════════════════════════════════
# (2) read_slang — a capability probe that PROBES
# ═══════════════════════════════════════════════════════════════════════════

def test_slang_probe_command_exercises_the_capability():
    """The probe must READ a fixture, not just invoke the command bare — the
    question is 'can this image read SystemVerilog?', not 'how does it
    complain?'."""
    assert "read_slang" in SF.SLANG_PROBE_CMD
    assert SF._SLANG_PROBE_MODULE in SF.SLANG_PROBE_CMD
    assert ".sv" in SF.SLANG_PROBE_CMD
    assert "stat" in SF.SLANG_PROBE_CMD


def test_slang_capability_decided_by_the_elaborated_fixture():
    """Positive evidence = the probe module came out the other side."""
    out = (f"1. Executing SLANG frontend.\n2. Printing statistics.\n"
           f"=== {SF._SLANG_PROBE_MODULE} ===\n        0 cells\n")
    assert SF.read_slang_is_builtin(out) is True
    assert SF.slang_load_prefix(out) == ""
    # …and it survives a total rewording of every diagnostic around it.
    assert SF.read_slang_is_builtin(
        f"gibberish\n=== {SF._SLANG_PROBE_MODULE} ===\n") is True


def test_slang_absent_still_gets_the_plugin_load():
    absent = ("-- Running command `read_slang' --\n"
              "ERROR: No such command: read_slang (type 'help' for a command "
              "overview)\n")
    assert SF.read_slang_is_builtin(absent) is False
    assert SF.slang_load_prefix(absent) == "plugin -i slang; "


@requires_container
def test_slang_probe_against_the_real_image():
    rc, blob = _dexec(SF.SLANG_PROBE_CMD)
    assert SF._SLANG_PROBE_MODULE in blob, "probe fixture did not elaborate"
    assert SF.read_slang_is_builtin(blob) is True
    assert SF.slang_load_prefix(blob) == ""


@requires_container
def test_slang_probe_negative_against_the_real_image():
    """PROVEN NEGATIVE: an image whose read command does NOT exist must still
    get the plugin load. Simulated with a genuinely-absent command name so the
    tool produces its real not-found behaviour."""
    rc, blob = _dexec("export PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH "
                      "&& yosys -p 'read_bogus_frontend /tmp/x.sv; stat'")
    absent = blob.replace("read_bogus_frontend", "read_slang")
    assert SF.read_slang_is_builtin(absent) is False
    assert SF.slang_load_prefix(absent) == "plugin -i slang; "


# ═══════════════════════════════════════════════════════════════════════════
# (3) OpenROAD post-route SPEF repair — DIFFERENTIAL capability probe
# ═══════════════════════════════════════════════════════════════════════════

_OR_PROBE_TCL = (
    "openroad -no_init -no_splash -exit <<'EOF' 2>&1\n"
    "if {[catch {estimate_parasitics %s} e]} {"
    " puts \"VIBEIC_PROBE_REAL: $e\" } else {"
    " puts \"VIBEIC_PROBE_REAL: <accepted>\" }\n"
    "if {[catch {estimate_parasitics -vibeic_probe_unknown_control_flag} e]} {"
    " puts \"VIBEIC_PROBE_CTRL: $e\" } else {"
    " puts \"VIBEIC_PROBE_CTRL: <accepted>\" }\n"
    "EOF")


def test_differential_probe_is_wording_independent():
    """The decision is 'does the real flag behave DIFFERENTLY from a flag we
    KNOW is invalid?'. The control calibrates the probe at run time, so no
    phrasing of either rejection is ever consulted."""
    # capable: real flag got past arg parsing and failed later for another reason
    assert P3._flag_accepted_vs_control(
        "VIBEIC_PROBE_REAL: Error: no network has been linked.\n"
        "VIBEIC_PROBE_CTRL: STA-0562\n") is True
    # …and the same conclusion under completely different phrasings
    assert P3._flag_accepted_vs_control(
        "VIBEIC_PROBE_REAL: no design loaded, cannot estimate\n"
        "VIBEIC_PROBE_CTRL: ERR-9999 unrecognised option\n") is True


def test_differential_probe_negative_identical_rejections():
    """PROVEN NEGATIVE: on a build WITHOUT the flag, the real flag is rejected
    exactly like the bogus control → not capable → the measure-only path runs
    (byte-identical to the pre-fix behaviour, and stock never segfaults)."""
    assert P3._flag_accepted_vs_control(
        "VIBEIC_PROBE_REAL: STA-0562\n"
        "VIBEIC_PROBE_CTRL: STA-0562\n") is False


def test_differential_probe_fail_safe_on_garbage():
    for blob in ("", "no markers here",
                 "VIBEIC_PROBE_REAL: something\n",       # control missing
                 "VIBEIC_PROBE_CTRL: something\n",       # real missing
                 "VIBEIC_PROBE_REAL: \nVIBEIC_PROBE_CTRL: \n"):
        assert P3._flag_accepted_vs_control(blob) is False


def test_differential_probe_rejects_a_non_discriminating_control():
    """If the tool ACCEPTED a flag we know is invalid, the probe is not
    discriminating and must not be trusted, however the real flag behaved."""
    assert P3._flag_accepted_vs_control(
        "VIBEIC_PROBE_REAL: Error: no network has been linked.\n"
        "VIBEIC_PROBE_CTRL: <accepted>\n") is False


@requires_container
def test_openroad_differential_probe_against_the_real_image():
    rc, blob = _dexec(_OR_PROBE_TCL % "-detailed_routing")
    assert "VIBEIC_PROBE_REAL:" in blob and "VIBEIC_PROBE_CTRL:" in blob
    assert P3._flag_accepted_vs_control(blob) is True, blob


@requires_container
def test_openroad_differential_probe_negative_against_the_real_image():
    """PROVEN NEGATIVE with the real tool: a flag that genuinely does not exist
    (what stock OpenROAD looks like for -detailed_routing) → not capable."""
    rc, blob = _dexec(_OR_PROBE_TCL % "-vibeic_flag_that_does_not_exist")
    assert P3._flag_accepted_vs_control(blob) is False, blob


# ═══════════════════════════════════════════════════════════════════════════
# (4) ext2spice extraction-collapse guard — order-agnostic + never silent
# ═══════════════════════════════════════════════════════════════════════════

def test_error_count_parsed_in_either_order():
    """The count used to have to PRECEDE the word 'error'; a reworded summary
    silently dropped the whole collapse guard."""
    for text, want in (
        ("Magic: 106,250,195 errors were encountered", 106250195),
        ("errors: 106250195", 106250195),
        ("error count = 42", 42),
        ("Errors : 7", 7),
        ("0 errors", 0),
    ):
        assert P3._parse_ext2spice_error_count(text) == want, text


def test_error_count_max_across_lines_is_preserved():
    assert P3._parse_ext2spice_error_count(
        "0 errors\nlater...\nerrors: 900000\n") == 900000


def test_unmeasured_count_is_reported_not_silent():
    """The honesty backstop: a log that TALKS about errors but yields no count
    is UNMEASURED, which must be distinguishable from measured-clean."""
    assert P3._ext2spice_error_count_unmeasured(
        "extraction finished with errors") is True
    assert P3._ext2spice_error_count_unmeasured("0 errors") is False
    assert P3._ext2spice_error_count_unmeasured("all clean") is False
    assert P3._ext2spice_error_count_unmeasured("") is False


def test_unmeasured_never_itself_fails_a_run():
    """§4.05: the UNMEASURED signal is a WARNING only — the FAIL still requires
    a real parsed count above the ceiling, so this cannot fail a clean run."""
    assert P3._parse_ext2spice_error_count("extraction finished with errors") \
        is None


# ═══════════════════════════════════════════════════════════════════════════
# (5) functional read_liberty — probe, with the safety direction INVERTED
# ═══════════════════════════════════════════════════════════════════════════

def test_sound_recipe_selected_when_the_probe_succeeds():
    ok, why = LP.functional_read_liberty_supported(0, True, True)
    assert ok is True
    assert "SOUND" in why


def test_capability_gap_falls_back_and_says_it_is_unsound():
    ok, why = LP.functional_read_liberty_supported(1, True, True)
    assert ok is False
    assert "UNSOUND" in why
    assert LP.liberty_input_is_usable(True, True) is True   # fallback allowed


def test_input_defect_is_denied_the_unsound_fallback():
    """§4.05, INVERTED DIRECTION. The fallback recipe is UNSOUND — it assumes
    matched cells are equal and can false-PASS NAND=NOR — so widening what
    selects it widens what can PASS. A missing or empty liberty is an INPUT
    defect, not a capability gap, and must never buy the unsound compare."""
    for exists, nonempty in ((False, False), (True, False)):
        ok, why = LP.functional_read_liberty_supported(1, exists, nonempty)
        assert ok is False
        assert "INPUT defect" in why
        assert LP.liberty_input_is_usable(exists, nonempty) is False


def test_equivalence_outcome_can_never_select_the_unsound_recipe():
    """The decision now takes a dedicated PROBE rc, not the equiv transcript, so
    no equivalence RESULT — including a genuine mismatch whose log happens to
    contain the old phrase — can reach the unsound recipe."""
    import inspect
    sig = inspect.signature(LP.functional_read_liberty_supported)
    assert list(sig.parameters) == [
        "probe_rc", "liberty_exists", "liberty_nonempty"]
    # …and the runner must actually RUN the probe rather than grep the LEC log.
    src = inspect.getsource(P3._emit_lec_post_layout)
    assert "build_functional_probe_script" in src, "the probe is never run"
    assert "functional_read_liberty_supported" in src
    assert "liberty_input_is_usable" in src, "input defect is not distinguished"
    assert "functional_read_liberty_aborted" not in src, (
        "the retired wording gate is still wired into the recipe decision")


@requires_container
def test_liberty_probe_against_the_real_open_pdks():
    """HONEST FINDING, pinned: on the CURRENT image the functional read_liberty
    aborts for BOTH open PDKs (an integrated clock-gate cell has no function
    attribute), so the sound path is genuinely unavailable and the recorded
    provenance must say `blackbox_lib_fallback`. If a future image gains the
    capability this test's expectation flips to sound — which is the point of
    probing rather than assuming."""
    libs = [
        "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
        "sky130_fd_sc_hd__tt_025C_1v80.lib",
    ]
    for lib in libs:
        rc, _ = _dexec("export PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH"
                       f" && yosys -p 'read_liberty {lib}'")
        ok, why = LP.functional_read_liberty_supported(rc, True, True)
        # Whatever the image supports, the verdict must MATCH the probe rc —
        # that is the invariant, not a hardcoded expectation about the image.
        assert ok is (rc == 0), why


# ═══════════════════════════════════════════════════════════════════════════
# (1-hardening) the frontend PASS-CLASS token, not a substring of the whole
# pass line. Found by a peer review of the sibling LVS wording fix, whose first
# draft matched a whole LINE and so accepted a marker appearing anywhere in it.
# ═══════════════════════════════════════════════════════════════════════════

def test_frontend_class_token_is_not_matched_inside_an_argument():
    """The captured pass name INCLUDES the pass ARGUMENTS — real yosys prints
    "Verilog-2005 frontend: /tmp/frontend/rtl/m.v" — so a bare \\bfrontend\\b
    would also fire on a PATH containing that word.

    That misfires in the DANGEROUS direction: a design-BUILDING pass wrongly
    counted as a frontend pass empties the non-frontend list and buys the
    LENIENT verdict (INCONCLUSIVE) for a run that actually got past the read.
    `frontend` must therefore be the pass-CLASS token — the last word before the
    argument separator, the terminating '.', or end of string."""
    is_fe = LR._yosys_pass_is_frontend
    # real read passes (incl. one whose PATH contains "frontend")
    assert is_fe("Verilog-2005 frontend: /tmp/lec_obs/good.v")
    assert is_fe("Verilog-2005 frontend: /tmp/frontend/rtl/m.v")
    assert is_fe("SLANG frontend.")
    assert is_fe("Liberty frontend: /pdk/x.lib")
    # real design-building / writer passes
    assert not is_fe("HIERARCHY pass (managing design hierarchy).")
    assert not is_fe("TECHMAP pass (map to technology primitives).")
    assert not is_fe("Verilog backend.")
    # THE ADVERSARIAL CASE: a building pass whose ARGUMENT contains "frontend"
    assert not is_fe("SOMEPASS pass (reading /work/frontend/lib.v).")


def test_building_pass_with_frontend_in_its_argument_stays_hard_fail():
    """End-to-end on the adversarial transcript: the run got PAST the read, so
    it must stay a blocking FAIL and must NOT be re-classified."""
    adversarial = (
        "1. Executing Verilog-2005 frontend: /work/frontend/rtl/top.v\n"
        "2. Executing SOMEPASS pass (reading /work/frontend/lib.v).\n"
        "ERROR: died after elaboration\n")
    aborted, evidence = LR.frontend_aborted_before_elaboration(adversarial)
    assert aborted is False, evidence
    assert LR.parse_equiv_output(adversarial)["verdict"] == "FAIL"


def test_nested_frontend_deep_in_the_flow_is_not_a_frontend_abort():
    """REAL yosys behaviour: techmap internally re-enters the Verilog frontend
    ("5.1. Executing Verilog-2005 frontend: .../techmap.v"). A frontend pass
    appearing LATE must not make a fully-elaborated run look like a read abort —
    it does not, because TECHMAP itself is a design-building pass."""
    nested = (
        "1. Executing Verilog-2005 frontend: /tmp/frontend/rtl/m.v\n"
        "5. Executing TECHMAP pass (map to technology primitives).\n"
        "5.1. Executing Verilog-2005 frontend: /share/yosys/techmap.v\n")
    assert LR.frontend_aborted_before_elaboration(nested)[0] is False


def test_unparseable_pass_list_resolves_to_the_blocking_verdict():
    """Fail-safe by ELIMINATION: malformed / empty / unparseable evidence must
    land on FAIL, never on the lenient INCONCLUSIVE — so 'we failed to parse it'
    can never buy the softer verdict."""
    for text in ("", "\x00\x01 garbage", "docker daemon died",
                 "Executing Verilog-2005 frontend: /x.v"):  # no pass NUMBER
        assert LR.frontend_aborted_before_elaboration(text)[0] is False, text
        assert LR.parse_equiv_output(text)["verdict"] == "FAIL", text


def test_class_token_cannot_be_forged_by_a_path_or_a_design_chosen_name():
    """ROUND 2 of the peer review with the LVS wording fix. Requiring `frontend`
    to be followed by ':' / '.' / end was STILL forgeable, because those
    separators occur inside ARGUMENTS too. Their sharper framing generalises past
    LVS: THE DESIGN AND THE ENVIRONMENT NAME THEIR OWN THINGS, so any structural
    token matched against a region containing paths / net names / cell names is a
    token those inputs can forge. (In netgen's case a SystemVerilog escaped
    identifier legally contains SPACES, so a net can spell a verdict phrase
    exactly.) The class token is therefore read ONLY from the class DESCRIPTOR —
    the region yosys writes and the inputs cannot reach."""
    is_fe = LR._yosys_pass_is_frontend
    # forged separators inside an argument — all previously accepted
    assert not is_fe("SOMEPASS pass (reading /work/frontend.)")
    assert not is_fe("SOMEPASS pass (reading /work/frontend: x)")
    assert not is_fe("SOMEPASS pass (reading /work/frontend/lib.v).")
    # a design/env-chosen name that spells the class token outright
    assert not is_fe("SOMEPASS pass (net \\my frontend: fake )")
    # real reads still classify correctly, incl. a path ending in "frontend."
    assert is_fe("Verilog-2005 frontend: /tmp/adv/frontend./m.v")
    assert is_fe("Verilog-2005 frontend: /tmp/frontend/rtl/m.v")
    assert is_fe("SLANG frontend.")
    # real builders/writers with no arguments at all
    assert not is_fe("BMUXMAP pass.")
    assert not is_fe("Verilog backend.")


def test_forged_argument_still_yields_the_blocking_verdict():
    """End-to-end: a building pass whose argument forges the class token must
    still leave the run classified FAIL, not the lenient INCONCLUSIVE."""
    forged = (
        "1. Executing Verilog-2005 frontend: /work/rtl/top.v\n"
        "2. Executing SOMEPASS pass (reading /work/frontend: x)\n"
        "ERROR: died after elaboration\n")
    assert LR.frontend_aborted_before_elaboration(forged)[0] is False
    assert LR.parse_equiv_output(forged)["verdict"] == "FAIL"
