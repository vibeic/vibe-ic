#!/usr/bin/env python3
"""Apply the field(foundry-handoff hollow chip GDS) candidate to a `programs/` directory.

Scripted rather than a diff so it re-applies cleanly across a moving main
(measured: the lane's base was 2041 commits behind origin/main; every anchor
below is byte-identical on both, but a context diff would not have been).
Every anchor is asserted to occur EXACTLY once — a moved anchor is a hard stop,
never a silent no-op.

    python3 apply_candidate.py <path-to-programs-dir>
"""
import pathlib
import sys

GATE_RESOLVER = '''# ── shared resolver: "is there a chip GDS a handoff kit could describe?" ──
# field (foundry-handoff hollow chip GDS) — the PRODUCER side of this gate had no chip-GDS predicate at
# all, and this gate had only a name-and-non-zero-size one. MEASURED on two
# benchmark runs (spm_gf180mcuD_20260831_a1, subservient_gf180mcuD_20260831_d1):
# PnR FAILed, so `step_gds` never ran, so NO .gds exists anywhere in either tree
# — and `foundry_handoff_pack_gen` still wrote a complete mask spec, WAT probe
# plan and ATE corner-vector kit for that absent die. Its only refusal (#654)
# keys on `antenna.json:routing_incomplete`, which both runs record as FALSE:
# routing COMPLETED, with a residual violation. So the one guard was silent on
# exactly the case it exists for.
#
# And the expensive form, measured end to end on a copy of the real spm run
# tree: a structurally valid GDSII stream of 108 bytes — HEADER, BGNLIB,
# LIBNAME, UNITS, a top structure carrying the design's own name, ENDSTR,
# ENDLIB, and NOT ONE geometry record — was packaged and signed off by this gate
# as PASS, "all 4 required artefacts present + chip GDS 'spm.gds'".
#
# A packager that launders an absent or hollow die into a deliverable is worse
# than no packager. The resolver lives HERE, in the gate that owns the "what
# counts as the chip GDS" question, so the producer and the gate cannot drift
# apart on the naming rules (`_find_chip_gds` / `_SCRIBE_LINE_GDS_HINTS` / the
# three search roots).
#
# The geometry predicate is the SAME one the hardmacro gate uses —
# `analog_a5_layout_check._gds_geometry_count`, imported the way
# `analog_hardmacro_check._gds_geometry_records` imports it — so "carries
# geometry" means one thing across the flow. A 0-byte GDS never reaches it:
# `_find_chip_gds` already skips `st_size <= 0`, so an empty file lands in the
# ABSENT arm and keeps the rule step 35 already emits for it.
# The module's own directory is put on sys.path first. The bare
# `from _atomic_artefact import ...` at the top of this file already assumes
# programs/ is importable, but THIS import decides a verdict: if it silently
# failed the gate would report GEOMETRY_PREDICATE_UNAVAILABLE on every project,
# which is a corpus-wide red bought for nothing. A gate invoked through a copy
# or a symlink elsewhere gets sys.path[0] = that other directory, so make it
# explicit rather than inherited.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # pragma: no cover - programs/ is on sys.path by the line above
    from analog_a5_layout_check import _gds_geometry_count
except ImportError:
    _gds_geometry_count = None  # type: ignore[assignment]

RULE_NO_CHIP_GDS = 'FOUNDRY_HANDOFF_NO_CHIP_GDS_TO_PACKAGE'
RULE_HOLLOW_CHIP_GDS = 'FOUNDRY_HANDOFF_HOLLOW_CHIP_GDS'
RULE_GEOMETRY_PREDICATE_UNAVAILABLE = (
    'FOUNDRY_HANDOFF_GEOMETRY_PREDICATE_UNAVAILABLE')


def gds_files_on_disk(project):
    """EVERY `*.gds` under the three roots — any size, any name, frame or die.

    Distinct from `_any_real_gds`, deliberately. It answers "did stream-out
    write anything at all here", which is the question that separates "this flow
    has not reached stream-out yet" from "this flow streamed something and what
    it streamed is not a die". The producer refuses on the second and not the
    first; the GATE refuses on both, and already did on the first.
    """
    project = Path(project)
    out = []
    for root in (project / "phase3/stage4/foundry_handoff/gds",
                 project / "phase3/stage4/gds",
                 project / "gds"):
        if root.is_dir():
            out.extend(sorted(root.glob("*.gds")))
    return out


def _any_real_gds(project):
    """Non-empty, non-scribe .gds files under the three roots `_find_chip_gds`
    searches. Used when L1.ic_name is absent, so a project that never ran
    phase 1 is still measured on whether a die was streamed at all rather than
    silently treated as packageable."""
    out = []
    for root in (project / "phase3/stage4/foundry_handoff/gds",
                 project / "phase3/stage4/gds",
                 project / "gds"):
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.gds")):
            if any(h in f.stem.lower() for h in _SCRIBE_LINE_GDS_HINTS):
                continue
            try:
                if f.stat().st_size > 0:
                    out.append(f)
            except OSError:
                continue
    return out


def packageable_chip_gds(project):
    """Return (gds_path_or_None, rule_or_None, detail).

    `rule` is None only when a real, geometry-carrying chip GDS is on disk.
    Every other return NAMES the rule the caller must refuse under — never a
    bare False, so a refusal always says which predicate decided it.

    An unavailable geometry parser is its OWN named refusal, not a skipped
    predicate: a packager that cannot evaluate "is this die hollow" must refuse
    to package, never pack on the strength of a check it could not run.
    """
    project = Path(project)
    ic_name = _read_l1_ic_name(project)
    chip_gds, scribe_only, physical_tops = _find_chip_gds(project, ic_name)
    if chip_gds is None:
        # No L1.ic_name is not a licence to package: fall back to "did the flow
        # stream ANY non-scribe, non-empty die?" before concluding absence.
        fallback = [] if ic_name else _any_real_gds(project)
        if not fallback:
            where = ("only scribe-line / frame GDS present"
                     if scribe_only else "no .gds present")
            return None, RULE_NO_CHIP_GDS, (
                f"{where} under phase3/stage4/foundry_handoff/gds/ or "
                f"phase3/stage4/gds/ or gds/ "
                f"(L1.ic_name={ic_name!r}, physical PnR top(s)="
                f"{physical_tops or '(none resolved)'}). There is no die to "
                f"describe, so a mask spec / WAT plan / ATE vector kit written "
                f"now would describe nothing.")
        chip_gds = fallback[0]
    if _gds_geometry_count is None:
        return chip_gds, RULE_GEOMETRY_PREDICATE_UNAVAILABLE, (
            "analog_a5_layout_check._gds_geometry_count could not be imported, "
            "so whether {} carries geometry cannot be evaluated".format(
                chip_gds.name))
    try:
        records = _gds_geometry_count(chip_gds.read_bytes())
    except OSError as exc:
        return chip_gds, RULE_HOLLOW_CHIP_GDS, (
            f"{chip_gds.name}: unreadable ({exc})")
    if records <= 0:
        return chip_gds, RULE_HOLLOW_CHIP_GDS, (
            f"{chip_gds.name}: the GDS stream carries no BOUNDARY/PATH/SREF/"
            f"AREF/BOX record — a hollow die is not a deliverable")
    return chip_gds, None, (
        f"{chip_gds.name}: {records} GDS geometry/placement record(s)")


'''

GATE_CLAUSE = '''    # field (foundry-handoff hollow chip GDS) — SUBSTANCE, not merely presence. `_find_chip_gds`
    # accepts any non-empty file with the right name, so a structurally valid
    # GDSII stream carrying ZERO geometry records — 108 bytes — satisfied the
    # v1.6.162 chip-GDS requirement and this gate PASSED the kit around it.
    #
    # WHY IT IS IN THE GATE AND NOT ONLY IN THE PRODUCER, measured: with the
    # producer-side refusal alone, the hollow case moved from rc=0 PASS to rc=2
    # SKIP, and `flow_compliance_check` reads rc=2 as VACUOUS_PASS. The same
    # green in a different exit code is not a fix. A producer-only refusal is
    # also deletable — hand-write the four kit JSONs beside a hollow GDS and
    # nothing looks at the die. Keyed here, on the artefact, no choice of writer
    # evades it.
    #
    # It fires ONLY when a chip GDS was actually identified: an absent GDS is
    # already FOUNDRY_HANDOFF_CHIP_GDS_MISSING above, and re-reporting it here
    # would double-count one defect.
    if chip_gds is not None and chip_gds_finding is None:
        _pkg_gds, _pkg_rule, _pkg_detail = packageable_chip_gds(project)
        if _pkg_rule in (RULE_HOLLOW_CHIP_GDS,
                         RULE_GEOMETRY_PREDICATE_UNAVAILABLE):
            chip_gds_finding = {
                "severity": "ERROR",
                "rule": _pkg_rule,
                "message": (
                    f"{_pkg_detail}. A chip GDS that carries no geometry is "
                    f"not a deliverable: the handoff kit describes a die that "
                    f"does not exist. Step 35 PASS requires a chip-named GDS "
                    f"whose stream carries layout records."),
            }

'''

PACK_CLAUSE = '''    # field (foundry-handoff hollow chip GDS) — the SECOND refusal, and the one #654 could not reach.
    # #654 keys on `antenna.json:routing_incomplete`. MEASURED on the two
    # benchmark runs this was written from (spm_gf180mcuD_20260831_a1 and
    # subservient_gf180mcuD_20260831_d1), that key is FALSE — detailed routing
    # COMPLETED, with one residual violation, which is why `pnr` is FAIL and NOT
    # why routing is incomplete. So #654 stayed silent while this generator
    # wrote a full mask spec, WAT probe plan and ATE corner-vector kit for a
    # chip whose GDS does not exist anywhere in the tree (`step_gds` never ran:
    # the runner gates stream-out on `pnr.status == "PASS"`, correctly).
    #
    # The kit exists to describe ONE artefact — the die. Writing it for a
    # streamed non-die is the laundering this program must not do, so the
    # predicate is asked BEFORE the handoff directory is created: a refusal
    # leaves NO half-kit on disk for the next reader to mistake for a
    # deliverable.
    #
    # SCOPE, stated because the narrower rule was a deliberate choice and the
    # wider one was MEASURED: this refuses when stream-out HAS written a .gds
    # and what it wrote is not a die (0-byte, hollow, frame-only). It does NOT
    # refuse a tree with no .gds at all. Two reasons. (1) That tree is already
    # rc=1 FAIL `FOUNDRY_HANDOFF_CHIP_GDS_MISSING` at the gate — no false green
    # to close, only a skeleton the gate has already refused. (2) The wider rule
    # was implemented and reddened 38 tests across 9 files whose fixtures run
    # this generator on a bare project to check its FIELD DERIVATION (design_top
    # from L1.ic_name, pdk from L19, cell counts, TODO semantics); making all
    # nine plant a GDS would rewrite what those tests are about to buy a
    # property the gate already holds.
    #
    # It does NOT soften the gate either: `foundry_handoff_package_check`
    # evaluates `chip_gds_finding` BEFORE its `missing -> SKIP (rc=2)` branch,
    # so an absent kit still exits rc=1 FAIL rather than the VACUOUS_PASS the
    # flow runner reads rc=2 as. Verified end to end on a copy of the spm run
    # tree.
    _gds, _rule, _detail = _fhpc.packageable_chip_gds(project)
    if _rule is not None and (_rule != _fhpc.RULE_NO_CHIP_GDS
                              or _fhpc.gds_files_on_disk(project)):
        print(f"VACUOUS_PASS: {_rule}: {_detail} Refusing to write a foundry "
              f"handoff pack. Produce the sign-off GDS first (canonical step "
              f"37 stream-out), then re-run.", file=sys.stderr)
        return 2

'''

FIXTURE_NOTE = '''
# field (foundry-handoff hollow chip GDS) — the chip GDS in this fixture must
# carry GEOMETRY. A four-byte GDSII BOUNDARY record header (length 4, record
# type 0x08) is the smallest thing that makes
# `analog_a5_layout_check._gds_geometry_count` read 1 rather than 0. Without it
# this fixture models a HOLLOW die, which `foundry_handoff_pack_gen` now refuses
# to package and `foundry_handoff_package_check` now FAILs — so the fixture
# would stop standing for the real run it was written from.
_GDS_BOUNDARY_RECORD = b"\\x00\\x04\\x08\\x00"
'''


def sub(path, old, new, count=1):
    p = pathlib.Path(path)
    s = p.read_text()
    n = s.count(old)
    assert n == count, f"{path}: anchor found {n}x, expected {count}:\n{old[:120]}"
    p.write_text(s.replace(old, new))


def main():
    prog = pathlib.Path(sys.argv[1]).resolve()
    t = prog / "tests"

    # 1. the gate: resolver + the hollow-die ERROR
    sub(prog / "foundry_handoff_package_check.py",
        "def main(argv=None):\n    parser = argparse.ArgumentParser()",
        GATE_RESOLVER + "def main(argv=None):\n    parser = argparse.ArgumentParser()")
    sub(prog / "foundry_handoff_package_check.py",
        "    # ORGANIC-20260606 #433(d) — 0-byte member hard-fail",
        GATE_CLAUSE + "    # ORGANIC-20260606 #433(d) — 0-byte member hard-fail")

    # 2. the gate's rationale constant: a false sentence, emitted under EVERY
    #    verdict, that sent a real investigation after a program that exists.
    sub(prog / "foundry_handoff_package_check.py",
        "Default rationale when SKIP: Foundry-handoff kit assembler not shipped.",
        "Default rationale when SKIP: the kit is incomplete — required members are\n"
        "absent. (It used to read \"Foundry-handoff kit assembler not shipped.\", which\n"
        "was false and cost a real investigation: the assembler IS shipped and IS wired\n"
        "— `foundry_handoff_pack_gen`, in `phase3_one_shot_runner.\n"
        "_DERIVED_ARTEFACT_GENERATORS`. Worse, this key is emitted on EVERY verdict,\n"
        "PASS and FAIL included, so a FAIL report carried a sentence saying the producer\n"
        "did not exist. It is a constant, never a statement about the run.)")
    sub(prog / "foundry_handoff_package_check.py",
        "_WAIVER_RATIONALE = 'Foundry-handoff kit assembler not shipped.'",
        "# NOT a statement about the run: this key is written into the report under every\n"
        "# verdict, PASS and FAIL included. Its old text — \"Foundry-handoff kit assembler\n"
        "# not shipped.\" — was also FALSE (the assembler is shipped and wired), and a FAIL\n"
        "# report carrying it was read as \"the producer is missing\", sending an\n"
        "# investigation after a program that already exists. The text now names the only\n"
        "# thing a SKIP from this gate actually means.\n"
        "_WAIVER_RATIONALE = ('Foundry-handoff kit incomplete: required member(s) absent '\n"
        "                     'and the step is not waived.')")

    # 3. the producer: import the shared resolver, then refuse
    sub(prog / "foundry_handoff_pack_gen.py",
        "import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)",
        "import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)\n"
        "# ONE resolver for \"what is the chip GDS\", shared with the Step-35 gate that\n"
        "# grades this kit, so producer and gate cannot drift apart (field: foundry-handoff hollow chip GDS).\n"
        "import foundry_handoff_package_check as _fhpc  # noqa: E402")
    sub(prog / "foundry_handoff_pack_gen.py",
        "    handoff_dir = _pl.foundry_handoff_dir(project)\n"
        "    handoff_dir.mkdir(parents=True, exist_ok=True)",
        PACK_CLAUSE
        + "    handoff_dir = _pl.foundry_handoff_dir(project)\n"
          "    handoff_dir.mkdir(parents=True, exist_ok=True)")

    # 4. three fixtures whose "chip GDS" was a text placeholder (a hollow die)
    fixtures = [
        (t / "test_v0_2_76_handoff_pack_chip_specific.py",
         '    (p / "phase3" / "stage4" / "gds" / f"{name}.gds").write_bytes(\n'
         '        b"\\x00\\x06\\x00\\x02" + name.encode())',
         '    (p / "phase3" / "stage4" / "gds" / f"{name}.gds").write_bytes(\n'
         '        _GDS_BOUNDARY_RECORD + b"\\x00\\x06\\x00\\x02" + name.encode())'),
        (t / "test_v0_2_81_pending_foundry_semantics.py",
         '    (gds / "alpha.gds").write_bytes(b"\\x00\\x06\\x00\\x02alpha")',
         '    (gds / "alpha.gds").write_bytes(\n'
         '        _GDS_BOUNDARY_RECORD + b"\\x00\\x06\\x00\\x02alpha")'),
        (t / "test_signoff_medlow_backlog_gaps.py",
         '    (gds_dir / f"{ic_name}.gds").write_bytes(b"HEADER\\x00chip layout\\n" * 32)',
         '    (gds_dir / f"{ic_name}.gds").write_bytes(\n'
         '        _GDS_BOUNDARY_RECORD + b"HEADER\\x00chip layout\\n" * 32)'),
        (t / "test_signoff_medlow_backlog_gaps.py",
         '        (gds_dir / name).write_bytes(b"HEADER\\x00layout\\n" * 8)',
         '        (gds_dir / name).write_bytes(\n'
         '            _GDS_BOUNDARY_RECORD + b"HEADER\\x00layout\\n" * 8)'),
        (t / "test_foundry_handoff_corners_are_measured_not_canned.py",
         '    (p / "phase3/stage4/gds/chip_top.gds").write_bytes(b"\\x00\\x06\\x00\\x02alph")',
         '    (p / "phase3/stage4/gds/chip_top.gds").write_bytes(\n'
         '        _GDS_BOUNDARY_RECORD + b"\\x00\\x06\\x00\\x02alph")'),
        (t / "test_foundry_handoff_names_its_owner.py",
         '    (p / "phase3/stage4/gds" / name).write_bytes(b"\\x00\\x06\\x00\\x02alph")',
         '    (p / "phase3/stage4/gds" / name).write_bytes(\n'
         '        _GDS_BOUNDARY_RECORD + b"\\x00\\x06\\x00\\x02alph")'),
    ]
    for path, old, new in fixtures:
        sub(path, old, new)
    for name in ("test_v0_2_76_handoff_pack_chip_specific.py",
                 "test_v0_2_81_pending_foundry_semantics.py",
                 "test_signoff_medlow_backlog_gaps.py",
                 "test_foundry_handoff_corners_are_measured_not_canned.py",
                 "test_foundry_handoff_names_its_owner.py"):
        p = t / name
        s = p.read_text()
        assert "_GDS_BOUNDARY_RECORD =" not in s.split("def ")[0], name
        lines = s.splitlines(keepends=True)
        last = max(i for i, ln in enumerate(lines)
                   if ln.startswith(("import ", "from ")))
        lines.insert(last + 1, FIXTURE_NOTE)
        p.write_text("".join(lines))

    print("applied to", prog)


if __name__ == "__main__":
    main()
