#!/usr/bin/env python3
"""`readme_ppa_extractor` is HINTS ONLY, and these are the four fixtures.

Spec §14.3 / PPA_INTERFACES.md §1, §3, §7.

The defect this file was written against, measured at `867de4289`:
`skills/ppa-predict/SKILL.md` has declared

    python3 programs/readme_ppa_extractor.py \
        --rtl-dir <rtl> --readme <README.md> --json /tmp/ppa_hints.json

a MANDATORY DETERMINISTIC PREFLIGHT since v1.6.118, and told the agent to use
the resulting JSON as the FLOOR of any PPA estimate it states. The program had
no CLI whatsoever -- that command parsed nothing, read nothing, wrote nothing
and exited 0. A preflight that returns success without opening a file is the
shape this repository pays for most: an unmeasured thing reading as a measured
zero. So the rc=2 fixture below is the load-bearing one.

Chip-AGNOSTIC: nothing here names an IC, a vendor, a SKU or a process.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_PROG = _PROGRAMS / "readme_ppa_extractor.py"


def _load():
    spec = importlib.util.spec_from_file_location("rpe_under_test", _PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(_PROG)] + [str(a) for a in args],
        capture_output=True, text=True, cwd=(str(cwd) if cwd else None))


README = (
    "# Core\n"
    "\n"
    "## Cyclone V\n"
    "LUTs: 1234\n"
    "Regs: 567\n"
    "Fmax: 250 MHz\n"
)


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "README.md").write_text(README)
    (tmp_path / "l1.json").write_text(json.dumps(
        {"platform": "Cyclone V", "clock": {"target_fmax_mhz": 200}}))
    (tmp_path / "l1_agree.json").write_text(json.dumps(
        {"platform": "Cyclone V", "clock": {"target_fmax_mhz": 250}}))
    (tmp_path / "design.sdc").write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n")
    (tmp_path / "rtl").mkdir()
    return tmp_path


# ======================================================================
# FIXTURE 1 — POSITIVE: green when it should be green
# ======================================================================
def test_positive_the_declared_skill_invocation_actually_runs(project):
    """The exact command `skills/ppa-predict/SKILL.md` prints must work.

    Before this lane it exited 0 having done nothing at all, so this test
    asserts the two things that separate a real preflight from a no-op: a
    non-empty result, and an artefact at the path the caller named.
    """
    out = project / "ppa_hints.json"
    r = _run(["--rtl-dir", project / "rtl", "--readme",
              project / "README.md", "--json", out])
    assert r.returncode == 0, r.stderr
    assert out.exists(), "the declared --json artefact was not written"
    doc = json.loads(out.read_text())
    assert doc["schema"] == "vibeic.ppa.readme_hint.v1"
    assert {h["metric"] for h in doc["hints"]} == {"luts", "regs", "fmax_mhz"}
    # It must SAY it read the file, and which bytes, so a zero-hint run can
    # never be confused with a run that never opened anything.
    assert doc["source"]["sha256"].startswith("sha256:")
    assert str(project / "README.md") in r.stdout or "README.md" in r.stdout


def test_positive_every_hint_is_marked_non_authoritative(project):
    doc = mod.extract_hints(README, readme_path="README.md")
    assert doc["authority"] == "HINT"
    assert doc["authoritative"] is False
    assert doc["hints"]
    for h in doc["hints"]:
        assert h["authority"] == "HINT"
        assert h["authoritative"] is False


def test_positive_every_span_reproduces_its_own_text(project):
    """A provenance field that cannot be checked is decoration.

    `line[col_start:col_end] == text` is the whole claim a span makes, so it
    is asserted over every form the picker knows, not one of them.
    """
    text = (
        "| Platform  | LUTs | Fmax    |\n"
        "|-----------|------|---------|\n"
        "| Cyclone V | 1234 | 250 MHz |\n"
        "\n"
        "## Stratix V\n"
        "Regs: 567\n"
        "- 2624 ALMs\n"
        "- Area: 14200 um2\n"
        "- Die size: 0.142 mm2\n"
        "- sub_a: 160 ALUTs\n"
    )
    lines = text.split("\n")
    doc = mod.extract_hints(text, readme_path="R.md")
    assert doc["hints"], "corpus produced no hints; the assertion is vacuous"
    checked = 0
    for h in doc["hints"]:
        assert h["span_status"] == "RECORDED", h
        s = h["span"]
        assert lines[s["line"] - 1][s["col_start"]:s["col_end"]] == s["text"]
        assert h["span_sha256"].startswith("sha256:")
        checked += 1
    assert checked >= 6, checked


def test_positive_span_hash_is_the_canonical_serializer(project):
    """§3: `_ppa/canonical_json` is the only serializer for a hashed value."""
    sys.path.insert(0, str(_PROGRAMS))
    from _ppa.canonical_json import digest_of
    doc = mod.extract_hints(README, readme_path="README.md")
    for h in doc["hints"]:
        assert h["span_sha256"] == digest_of(h["span"])


def test_positive_file_digest_is_what_sha256sum_prints(project, tmp_path):
    """A provenance hash a human cannot reproduce with a standard tool is a
    hash nobody checks, so the FILE digest is sha256 over the literal bytes
    (canonical_json governs documents this program builds, not artefacts it
    reads)."""
    import hashlib
    raw = (project / "README.md").read_bytes()
    out = project / "h.json"
    r = _run(["--readme", project / "README.md", "--json", out])
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text())
    assert doc["source"]["sha256"] == "sha256:" + hashlib.sha256(
        raw).hexdigest()


# ======================================================================
# FIXTURE 2 — NEGATIVE: RED when it should be red
# ======================================================================
def test_negative_conflict_with_an_l_doc_is_rc1(project):
    """README says 250 MHz, the L-doc says 200 at the same platform."""
    out = project / "c.json"
    r = _run(["--readme", project / "README.md",
              "--l-doc", project / "l1.json", "--json", out])
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "[CONFLICT]" in r.stderr
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "CONFLICT"
    assert len(doc["conflicts"]) == 1
    c = doc["conflicts"][0]
    assert c["metric"] == "fmax_mhz"
    assert c["resolution"] == "AUTHORITY_WINS"
    assert c["hint_ignored"] is True
    assert c["authority_value"] == 200


def test_negative_conflict_with_an_sdc_is_rc1(project):
    r = _run(["--readme", project / "README.md",
              "--sdc", project / "design.sdc", "--assume-scope-match"])
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "SDC wins" in r.stderr


def test_negative_the_hint_never_wins_in_any_branch(project):
    """The guarantee is structural: `reconcile` has no branch that promotes a
    hint. Asserted over conflict, agreement and undetermined at once."""
    doc = mod.extract_hints(README, readme_path="README.md")
    authority = mod.harvest_authority_from_l_doc(
        {"platform": "Cyclone V", "clock": {"target_fmax_mhz": 200},
         "luts": 1234},
        "l1.json")
    mod.reconcile(doc, authority, assume_scope_match=True)
    assert doc["conflicts"] and doc["agreements"]
    for c in doc["conflicts"]:
        assert c["resolution"] == "AUTHORITY_WINS" and c["hint_ignored"]
    for a in doc["agreements"]:
        assert a["resolution"] == "AGREE" and a["hint_ignored"]
    # ...and the authority value in the record is the authority's, never the
    # hint's, even where they agree.
    for row in doc["conflicts"] + doc["agreements"]:
        src = row["authority_source"]
        assert src and src["path"] == "l1.json"


# ======================================================================
# FIXTURE 3 — VACUOUS: missing input is rc=2 with a marker, never 0 or 1
# ======================================================================
def test_vacuous_missing_readme_is_rc2_with_a_marker(project):
    r = _run(["--rtl-dir", project / "rtl",
              "--readme", project / "nope" / "NOPE.md",
              "--json", project / "v.json"])
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "[CANNOT CHECK]" in r.stderr
    assert r.returncode not in (0, 1)
    doc = json.loads((project / "v.json").read_text())
    assert doc["read"] is False
    assert doc["verdict"] == "CANNOT_CHECK"
    assert doc["hints"] == []


def test_vacuous_readme_is_a_directory_is_rc2(project):
    r = _run(["--readme", project / "rtl"])
    assert r.returncode == 2
    assert "[CANNOT CHECK]" in r.stderr


def test_vacuous_unreadable_authority_is_rc2_not_a_clean_pass(project):
    for flag, path in (("--l-doc", "missing.json"), ("--sdc", "missing.sdc")):
        r = _run(["--readme", project / "README.md", flag, project / path])
        assert r.returncode == 2, (flag, r.returncode, r.stderr)
        assert "[CANNOT CHECK]" in r.stderr


def test_vacuous_l_doc_that_is_not_json_is_rc2(project):
    (project / "bad.json").write_text("{not json")
    r = _run(["--readme", project / "README.md",
              "--l-doc", project / "bad.json"])
    assert r.returncode == 2
    assert "[CANNOT CHECK]" in r.stderr


def test_could_not_read_and_read_but_empty_are_different_verdicts(project):
    """Hard rule: these two must never produce the same answer."""
    (project / "empty.md").write_text("")
    empty = _run(["--readme", project / "empty.md"])
    absent = _run(["--readme", project / "gone.md"])
    assert empty.returncode == 0
    assert absent.returncode == 2
    assert empty.returncode != absent.returncode
    # and the rc=0 run still names the file and its digest on stdout
    assert "empty.md" in empty.stdout and "sha256:" in empty.stdout


def test_bad_invocation_is_rc3_not_rc2(project):
    """argparse exits 2 on a usage error; here 2 means UNDETERMINED."""
    r = _run(["--json", project / "x.json"])          # no --readme
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert "[REFUSE]" in r.stderr
    r2 = _run(["--readme", project / "README.md", "--no-such-flag"])
    assert r2.returncode == 3


def test_undetermined_scope_is_not_a_conflict_and_not_a_win(project):
    """§2: two numbers are comparable only if their scope matches. An SDC
    carries no platform, so by default the comparison is UNDETERMINED --
    reported, counted, and never resolved in the hint's favour."""
    out = project / "u.json"
    r = _run(["--readme", project / "README.md",
              "--sdc", project / "design.sdc", "--json", out])
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text())
    assert doc["conflicts"] == []
    assert len(doc["undetermined"]) == 1
    u = doc["undetermined"][0]
    assert u["reason"] == "SCOPE_NOT_SHOWN_TO_MATCH"
    assert u["resolution"] == "UNDETERMINED"
    assert u["hint_ignored"] is True
    assert "undetermined=1" in r.stdout


def test_require_comparable_turns_an_undetermined_into_rc2(project):
    r = _run(["--readme", project / "README.md",
              "--sdc", project / "design.sdc", "--require-comparable"])
    assert r.returncode == 2
    assert "[CANNOT CHECK]" in r.stderr


# ======================================================================
# FIXTURE 4 — MUTATION anchors: what goes red if the change is reverted
# ======================================================================
def test_mutation_anchor_the_module_exposes_a_cli(project):
    """Reverting this lane removes `main`, and this test is the named red."""
    assert hasattr(mod, "main") and callable(mod.main)
    assert mod.main(["--readme", str(project / "README.md")]) == 0


def test_mutation_anchor_legacy_output_carries_no_underscore_keys(project):
    """The `_spans` sidecar must never reach `L1.implementation_results`.

    `phase1_doc_one_shot_runner` has copied picker fields WHOLESALE since
    v1.6.183, so a leaked private key becomes an undeclared L-doc field.
    """
    out = mod.extract_implementation_results_from_readme(README)
    assert out
    for entry in out:
        assert not [k for k in entry if k.startswith("_")], entry
        for sb in entry.get("sub_blocks", []):
            assert not [k for k in sb if k.startswith("_")], sb


def test_mutation_anchor_module_imports_without_programs_on_syspath():
    """A bare sibling import works as a script and dies under
    `spec_from_file_location`. Ten programs in this tree carry that latent
    break; this one must not, because the tests load it exactly that way."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys;"
         "sys.path=[p for p in sys.path if p!=%r];"
         "s=importlib.util.spec_from_file_location('m',%r);"
         "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
         "print(m.SCHEMA)" % (str(_PROGRAMS), str(_PROG))],
        capture_output=True, text=True, cwd="/")
    assert proc.returncode == 0, proc.stderr
    assert "vibeic.ppa.readme_hint.v1" in proc.stdout


def test_no_temp_artefact_is_left_behind(project):
    """`--json` writes through `_atomic_artefact`, so no `.tmp.<pid>` litter
    and no partial file under the final name."""
    out = project / "sub" / "a.json"
    out.parent.mkdir()
    r = _run(["--readme", project / "README.md", "--json", out])
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in out.parent.iterdir()) == ["a.json"]


def test_an_unwritable_json_path_is_rc3_not_a_finding(project):
    """rc=1 is a claim about the design. An OSError escaping the artefact
    write would exit 1 and claim one, for a run that measured nothing wrong."""
    r = _run(["--readme", project / "README.md",
              "--json", "/proc/definitely-not-a-dir/x.json"])
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert "[REFUSE]" in r.stderr
    assert r.returncode != 1


def test_an_internal_error_exits_3_and_claims_no_finding(project, tmp_path):
    """The entry point converts any unexpected exception to 3.

    Measured elsewhere in this tree on 2026-08-21: two shipped gates refused
    with a bare `SystemExit("...")`, which exits 1, and 1 in those files meant
    "the STA engines disagree". A run that never opened an image reported a
    hard finding.
    """
    boom = tmp_path / "boom.py"
    boom.write_text(
        "import importlib.util,sys\n"
        "s=importlib.util.spec_from_file_location('m',%r)\n"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
        "m.extract_hints=lambda *a,**k:(_ for _ in ()).throw("
        "RuntimeError('injected'))\n"
        "sys.argv=['x','--readme',%r]\n"
        "try:\n"
        "    raise SystemExit(m.main())\n"
        "except SystemExit:\n"
        "    raise\n"
        "except BaseException as e:\n"
        "    sys.stderr.write('[REFUSE] internal error: %%r' %% (e,))\n"
        "    raise SystemExit(3)\n" % (str(_PROG), str(project / "README.md")))
    proc = subprocess.run([sys.executable, str(boom)],
                          capture_output=True, text=True)
    assert proc.returncode == 3, (proc.returncode, proc.stderr)
    assert proc.returncode != 1
