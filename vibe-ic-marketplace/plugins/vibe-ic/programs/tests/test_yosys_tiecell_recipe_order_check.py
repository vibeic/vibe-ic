"""Tests for yosys_tiecell_recipe_order_check.py.

Covers the two v0.1.98 load-bearing tie-cell recipe ordering rules:
  RULE 1 — `setundef -zero` BEFORE `hilomap`
  RULE 2 — no `opt_clean` / `clean -purge` AFTER `hilomap`

PASS, FAIL (both rules), and edge cases (missing file, non-synth script,
synth script without hilomap, json output).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "yosys_tiecell_recipe_order_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _write(tmp_path, body, name="synth.ys"):
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_pyosys_identity_accepts_native_banner_but_not_descriptive_prose():
    from yosys_tiecell_recipe_order_check import _native_pyosys_wrapper

    command = ("yosys -y /tools/synthesize.py -- --config-in config.json "
               "--extra-in extra.json --output build")
    banner = f"-- Running command `{command}' --"
    for journal in (command, banner, f"  {banner}  "):
        assert _native_pyosys_wrapper(journal)["command"] == command
    for prose in (f"not {banner}", f"example: {banner}",
                  f"the command was not run: {command}"):
        assert _native_pyosys_wrapper(prose) is None


# ---- the correct v0.1.98 recipe (PASS) ------------------------------------
_GOOD = """read_verilog -defer rtl/top.v
hierarchy -top top
proc
opt
techmap
dfflibmap -liberty lib
abc -liberty lib
techmap
setundef -zero
hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO
splitnets
clean
write_verilog out.v
"""

# ---- RULE 1 broken: no setundef -zero (the v0.1.95 insufficient recipe) ----
_NO_SETUNDEF = """read_verilog rtl/top.v
synth -top top
dfflibmap -liberty lib
abc -liberty lib
techmap
hilomap -hicell TIEHI HI -locell TIELO LO
splitnets
clean
write_verilog out.v
"""

# ---- RULE 1 broken: setundef present but missing -zero ---------------------
_SETUNDEF_NO_ZERO = """synth -top top
abc -liberty lib
techmap
setundef -undriven
hilomap -hicell TIEHI HI -locell TIELO LO
clean
write_verilog out.v
"""

# ---- RULE 1 broken: setundef -zero AFTER hilomap ---------------------------
_SETUNDEF_AFTER = """synth -top top
abc -liberty lib
techmap
hilomap -hicell TIEHI HI -locell TIELO LO
setundef -zero
clean
write_verilog out.v
"""

# ---- RULE 2 broken: opt_clean AFTER hilomap (the HDLC DRT-0305 bug) --------
_OPT_CLEAN_AFTER = """synth -top top
abc -liberty lib
techmap
setundef -zero
hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO
opt_clean
write_verilog out.v
"""

# ---- RULE 2 broken: clean -purge AFTER hilomap -----------------------------
_CLEAN_PURGE_AFTER = """synth -top top
abc -liberty lib
techmap
setundef -zero
hilomap -hicell TIEHI HI -locell TIELO LO
clean -purge
write_verilog out.v
"""

# ---- both rules broken -----------------------------------------------------
_BOTH_BROKEN = """synth -top top
abc -liberty lib
techmap
hilomap -hicell TIEHI HI -locell TIELO LO
opt_clean
write_verilog out.v
"""

# ---- non-synth script (should SKIP, exit 0) --------------------------------
_NON_SYNTH = """read_verilog flat.v
flatten
write_verilog flat_out.v
"""

# ---- synth script with no hilomap (SKIP_NO_HILOMAP, exit 0) ----------------
_NO_HILOMAP = """synth -top top
dfflibmap -liberty lib
abc -liberty lib
clean
write_verilog out.v
"""


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "tie-cell" in out.lower()


# ===== PASS =================================================================
def test_good_recipe_passes(tmp_path):
    f = _write(tmp_path, _GOOD)
    code, out, err = _run(["--ys-file", f])
    assert code == 0, err
    assert "CLEAN" in out


# ===== FAIL — RULE 1 ========================================================
def test_missing_setundef_zero_fails(tmp_path):
    f = _write(tmp_path, _NO_SETUNDEF)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err


def test_setundef_without_zero_fails(tmp_path):
    f = _write(tmp_path, _SETUNDEF_NO_ZERO)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err
    assert "-zero" in err


def test_setundef_zero_after_hilomap_fails(tmp_path):
    f = _write(tmp_path, _SETUNDEF_AFTER)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err
    assert "AFTER" in err


# ===== FAIL — RULE 2 ========================================================
def test_opt_clean_after_hilomap_fails(tmp_path):
    f = _write(tmp_path, _OPT_CLEAN_AFTER)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE2_no_opt_clean_after_hilomap" in err


def test_clean_purge_after_hilomap_fails(tmp_path):
    f = _write(tmp_path, _CLEAN_PURGE_AFTER)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE2_no_opt_clean_after_hilomap" in err


def test_both_rules_broken_reports_both(tmp_path):
    f = _write(tmp_path, _BOTH_BROKEN)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err
    assert "RULE2_no_opt_clean_after_hilomap" in err


# ===== EDGE =================================================================
def test_missing_file_exits_2(tmp_path):
    code, out, err = _run(["--ys-file", str(tmp_path / "gone.ys")])
    assert code == 2
    assert "NOT_CHECKED" in out + err
    assert "file not found" in out + err
    assert "VACUOUS_PASS:" in err


def test_non_synth_script_is_vacuous_not_pass(tmp_path):
    # CHANGED from rc 0 to rc 2. A script this gate did not judge is the
    # VACUOUS tier, not the PASS tier: `flow_compliance_check` decides tier
    # membership purely from the exit code, so rc 0 here credited "examined
    # nothing" as "examined the design and found it correct" — the exact
    # substitution `_vacuous_exit` exists to stop.
    f = _write(tmp_path, _NON_SYNTH)
    code, out, err = _run(["--ys-file", f])
    assert code == 2
    assert "SKIP" in out + err
    assert "VACUOUS_PASS:" in err          # the rc-independent disclosure


def test_synth_without_hilomap_is_vacuous_not_pass(tmp_path):
    # Presence-of-hilomap is enforced by yosys_hilomap_required_check.py;
    # this program should not double-flag it — but it must not report a PASS
    # over a recipe whose two ordering rules it never got to apply either.
    f = _write(tmp_path, _NO_HILOMAP)
    code, out, err = _run(["--ys-file", f])
    assert code == 2
    assert "SKIP_NO_HILOMAP" in out + err
    assert "VACUOUS_PASS:" in err


def test_plain_clean_after_hilomap_is_ok(tmp_path):
    # plain `clean` (no -purge) after hilomap is the recommended recipe, OK.
    f = _write(tmp_path, _GOOD)
    code, out, err = _run(["--ys-file", f])
    assert code == 0


def test_json_report_written(tmp_path):
    f = _write(tmp_path, _OPT_CLEAN_AFTER)
    jpath = tmp_path / "rep.json"
    code, out, err = _run(["--ys-file", f, "--json", str(jpath)])
    assert code == 1
    data = json.loads(jpath.read_text())
    assert data["verdict"] == "VIOLATION"
    assert any(v["rule"] == "RULE2_no_opt_clean_after_hilomap"
               for v in data["violations"])


def test_neither_project_dir_nor_ys_file_is_a_usage_error():
    code, out, err = _run([])
    assert code == 2
    assert "project_dir" in err or "--ys-file" in err


def _native_project(tmp_path, commands, *, receipt=True):
    project = tmp_path / "native"
    folder = project / "phase3/librelane/06-yosys-synthesis"
    folder.mkdir(parents=True)
    (folder / "COMMANDS").write_text(commands)
    if receipt:
        state = folder / "state_out.json"
        state.write_text("{}\n")
        import hashlib
        commands_digest = hashlib.sha256(
            (folder / "COMMANDS").read_bytes()).hexdigest()
        (folder / "vibeic_receipt.json").write_text(json.dumps({
            "input": {"step": "Yosys.Synthesis"},
            "sha256": {"state_out.json": hashlib.sha256(
                state.read_bytes()).hexdigest(),
                "COMMANDS": commands_digest},
        }))
    return project


def _native_pyosys_project(tmp_path, *, recorded_root, output_name="top.nl.v",
                           recorded_output_parent=None):
    """A receipt-bound pyosys run copied beneath a different project root."""
    project = tmp_path / "adopted"
    rel = Path("phase3/librelane/06-yosys-synthesis")
    folder = project / rel
    folder.mkdir(parents=True)
    original = Path(recorded_root) / rel
    output_parent = (Path(recorded_output_parent)
                     if recorded_output_parent is not None else original)
    commands = (
        "yosys -y /tools/synthesize.py -- "
        f"--config-in {original / 'config.json'} "
        f"--extra-in {original / 'extra.json'} "
        f"--output {output_parent / output_name}\n"
    )
    files = {
        "COMMANDS": commands,
        "config.json": json.dumps({"SYNTH_TIE_UNDEFINED": "low"}) + "\n",
        "extra.json": "{}\n",
        output_name: "module top; endmodule\n",
        "invocation.log": (
            "Yosys\n"
            "Executing DFFLIBMAP pass\n"
            "Executing ABC pass\n"
            "Executing SETUNDEF pass\n"
            "Executing HILOMAP pass\n"
            "Executing CLEAN pass\n"
        ),
    }
    for name, text in files.items():
        (folder / name).write_text(text)
    import hashlib
    (folder / "vibeic_receipt.json").write_text(json.dumps({
        "input": {"step": "Yosys.Synthesis"},
        "sha256": {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in files
        },
    }))
    return project


def test_receipt_bound_pyosys_run_survives_project_root_relocation(tmp_path):
    project = _native_pyosys_project(
        tmp_path, recorded_root="/producer/original-project")

    code, out, err = _run([str(project)])

    assert code == 0, out + err
    assert "CLEAN" in out


def test_relocated_pyosys_run_rejects_output_outside_recorded_step(tmp_path):
    project = _native_pyosys_project(
        tmp_path, recorded_root="/producer/original-project",
        recorded_output_parent="/producer/foreign-step")

    code, out, err = _run([str(project)])

    assert code == 2
    assert "wrapper does not name current step inputs" in out + err


def test_native_receipt_and_commands_win_over_legacy_recipe(tmp_path):
    project = _native_project(tmp_path, _GOOD)
    legacy = project / "phase2/stage2/synth/legacy.ys"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_NO_SETUNDEF)

    code, out, err = _run([str(project)])

    assert code == 0, out + err
    report = json.loads((project / "report.json").read_text()) \
        if (project / "report.json").is_file() else None
    # The CLI has no implicit report path; inspect through its public helper so
    # this assertion cannot pass by reading a legacy gate output.
    import importlib.util
    spec = importlib.util.spec_from_file_location("tiecell", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.audit_project(project)
    assert report["mode"] == "native_pyosys"
    assert report["verdict"] == "CLEAN"
    assert report["summary"]["reason"] == "native_pyosys_receipt"


def test_native_trace_without_receipt_is_not_measured_and_never_uses_legacy(
        tmp_path):
    project = _native_project(tmp_path, _NO_SETUNDEF, receipt=False)
    (project / "phase3/librelane/native_commands.jsonl").write_text('{}\n')
    legacy = project / "phase2/stage2/synth/legacy.ys"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_GOOD)

    import importlib.util
    spec = importlib.util.spec_from_file_location("tiecell", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.audit_project(project)
    assert report["mode"] == "native_pyosys"
    assert report["verdict"] == "NOT_CHECKED"
    assert report["summary"]["reason"] == "native_command_journal_without_receipt"


def test_native_receipt_without_current_commands_is_not_measured(tmp_path):
    project = _native_project(tmp_path, "", receipt=True)
    (project / "phase2/stage2/synth/legacy.ys").parent.mkdir(parents=True)
    (project / "phase2/stage2/synth/legacy.ys").write_text(_GOOD)

    import importlib.util
    spec = importlib.util.spec_from_file_location("tiecell", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.audit_project(project)
    assert report["mode"] == "native_pyosys"
    assert report["verdict"] == "NOT_CHECKED"
    assert report["summary"]["reason"] == "native_receipt_without_recipe"


def test_unrelated_native_receipt_does_not_shadow_legacy_recipe(tmp_path):
    project = tmp_path / "legacy"
    folder = project / "phase3/librelane/13-openroad-floorplan"
    folder.mkdir(parents=True)
    (folder / "vibeic_receipt.json").write_text(json.dumps({
        "input": {"step": "OpenROAD.Floorplan"}, "sha256": {},
    }))
    legacy = project / "phase2/stage2/synth/legacy.ys"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_NO_SETUNDEF)

    import importlib.util
    spec = importlib.util.spec_from_file_location("tiecell", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.audit_project(project)
    assert report["mode"] == "ys_script"
    assert report["verdict"] == "VIOLATION"


# ===== PROJECT MODE (the wiring shape flow Step 14 declares) ================
#
# The gate used to accept ONLY `--ys-file`, while the flow YAML invokes every
# Step-14 gate as `<project_dir> --json <out>`. Measured on the pristine tree:
#
#   $ yosys_tiecell_recipe_order_check.py <project> --json /tmp/x.json
#   error: the following arguments are required: --ys-file        -> rc 2
#
# and `flow_compliance_check._check_program_exit_zero` maps rc 2 to a
# VACUOUS_PASS. Wiring the flag-only form would therefore have been
# permanently, silently green — the same defect moved. These tests pin the
# project-dir shape so that cannot come back.

_INLINE_TMPL = "-- Running command `{cmd}' --\n"

_REAL_PDK_DIRTY = ("read_verilog -sv a.v; synth -top t -flatten; "
                   "dfflibmap -liberty /p/lib.lib; abc -liberty /p/lib.lib; "
                   "hilomap -hicell HI Y -locell LO Y; clean; "
                   "write_verilog out.v")
_REAL_PDK_CLEAN = ("read_verilog -sv a.v; synth -top t -flatten; "
                   "dfflibmap -liberty /p/lib.lib; abc -liberty /p/lib.lib; "
                   "setundef -zero; hilomap -hicell HI Y -locell LO Y; "
                   "splitnets; clean; write_verilog out.v")
_SIM_ONLY = ("read_verilog -sv -DSIMULATION a.v; synth -top t -flatten; "
             "hilomap -hicell HI Y -locell LO Y; write_verilog out.v")

_STRUCTURAL_NETLIST = """module top (input a, output y);
  BUF _0_ (.A(a), .Y(y));
endmodule
"""


def _project(tmp_path, inline_cmd=None, netlist=False, ys=None):
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True, exist_ok=True)
    if inline_cmd is not None:
        (synth / "synth.log").write_text(_INLINE_TMPL.format(cmd=inline_cmd))
    if netlist:
        (synth / "netlist.v").write_text(_STRUCTURAL_NETLIST)
    if ys is not None:
        name, body = ys
        d = tmp_path / "scripts"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)
    return str(tmp_path)


def test_project_mode_inline_violation_is_rc1(tmp_path):
    p = _project(tmp_path, inline_cmd=_REAL_PDK_DIRTY, netlist=True)
    code, out, err = _run([p])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err


def test_project_mode_inline_clean_is_rc0(tmp_path):
    p = _project(tmp_path, inline_cmd=_REAL_PDK_CLEAN, netlist=True)
    code, out, err = _run([p])
    assert code == 0, err
    assert "CLEAN" in out


def test_project_mode_simulation_only_is_waived_not_failed(tmp_path):
    # A sim-only synth binds no Liberty library, maps to generic gates and
    # needs no tie cells — the same waiver the two sibling Step-14 gates
    # implement. Without it a sim-only command carrying hilomap false-fires.
    p = _project(tmp_path, inline_cmd=_SIM_ONLY)
    code, out, err = _run([p])
    assert code == 2
    assert "only_simulation_only_synth" in out + err


def test_project_mode_netlist_without_recipe_is_not_checked(tmp_path):
    # THE COVERAGE CASE. A project that published a mapped netlist and no
    # readable recipe was NOT audited. Reporting PASS here is what turns
    # "15 of 16 unjudgeable" into "15 clean" — the false clean bill.
    p = _project(tmp_path, netlist=True)
    code, out, err = _run([p])
    assert code == 2
    assert "netlist_published_but_no_readable_recipe" in out + err
    assert "NOT a clean bill" in out + err


def test_project_mode_lec_ys_does_not_shadow_the_inline_recipe(tmp_path):
    # A LEC script whose NAME contains 'synth' must not be selected as THE
    # synthesis script and silently skip the inline path (which is the only
    # branch that judges anything on the published corpus).
    p = _project(tmp_path, inline_cmd=_REAL_PDK_DIRTY,
                 ys=("lec_post_top_synth.ys",
                     "read_verilog gate.v\nequiv_make g gate e\n"
                     "equiv_status -assert\n"))
    code, out, err = _run([p])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err


def test_project_mode_json_carries_the_denominator(tmp_path):
    p = _project(tmp_path, inline_cmd=_REAL_PDK_DIRTY, netlist=True)
    jpath = tmp_path / "rep.json"
    code, out, err = _run([p, "--json", str(jpath)])
    assert code == 1
    data = json.loads(jpath.read_text())
    assert data["verdict"] == "VIOLATION"
    assert data["mode"] == "inline_yosys_p"
    assert data["summary"]["judged"] == 1
    assert data["netlists_published"] == ["phase2/stage2/synth/netlist.v"]


def test_comments_ignored(tmp_path):
    # An opt_clean mentioned only in a comment must NOT trigger RULE 2.
    body = """synth -top top
abc -liberty lib
techmap
setundef -zero
hilomap -hicell TIEHI HI -locell TIELO LO
# do NOT opt_clean here
clean
write_verilog out.v
"""
    f = _write(tmp_path, body)
    code, out, err = _run(["--ys-file", f])
    assert code == 0, err
    assert "CLEAN" in out
