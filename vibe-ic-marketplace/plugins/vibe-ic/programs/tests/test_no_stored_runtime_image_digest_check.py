#!/usr/bin/env python3
"""The runtime image's identity is RESOLVED from the host, never STORED here.

A stored digest makes "adopt a newer runtime image" an edit to this repository.
The coupling was removed once by name and quietly re-grew in three files — the
plugin's pin module, the CI hermetic runner, and the landing register — each as
a plain module-level constant. Measured before that removal: the literal moved
ONCE in ten days while eighteen image versions shipped, nothing in the release
loop touched it, and the drift test bound the copies to EACH OTHER rather than
to any image that exists, so every host tracking the current release mismatched
from day zero through no operator error.

This file holds `no_stored_runtime_image_digest_check` to BOTH directions, which
is the only way an absence assertion is worth anything:

  POSITIVE  the defect is reconstructed — as a module-level constant in each
            scanned venue, and as every shape ONE hunk could turn the corrected
            resolver back into — and the checker must FAIL and NAME file and
            line.
  NEGATIVE  the corrected shape, a digest under a name that is not about the
            image, a BARE checksum, a digest that appears only in a comment or a
            docstring, and a digest inside test/fixture evidence must all PASS.

THREE COLUMNS THIS SUITE EXISTS TO KEEP HONEST:

  BINDING SITE  the shape the fix INSTALLED is a FUNCTION, so a guard that reads
                only assignments is blind to its own regression. One hunk turning
                `resolved_image_digest()`'s `raise` into `return "<digest>"`
                restores the coupling in full — that hunk is an arm below, and so
                are the `__getattr__`, `except` and `match` spellings of it.
  PROSE         a comment and a docstring are records. A guard that fires on
                those is a guard someone deletes, taking the real rule with it.
                `_eda_pin.py`'s own module docstring carries a real digest today.
  DOMAIN        this repository designs silicon AND implements SHA-2 cores. `PIN`
                is BOTH the likeliest regression spelling of the guarded file and
                a chip pin — measured, 733 of the 1053 image-ish assignment names
                in the venue match only via the PIN family. What keeps the two
                apart is the VALUE, not the vocabulary: a golden vector is
                written BARE and a registry reference carries its `sha256:`.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import no_stored_runtime_image_digest_check as M  # noqa: E402

#: Built at runtime, never written out, so this file cannot be mistaken for a
#: place the identity is stored — and so no real image is named here.
BARE = "ab12cd34" * 8
DIGEST = "sha256:" + BARE

#: The venues. One of the three real copies was in the plugin's `programs`, two
#: were under `tools/`; the other two trees hold the same runtime's launchers.
PLUGIN_VENUE = "vibe-ic-marketplace/plugins/vibe-ic/programs"
TOOLS_VENUE = "tools/ci"


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _venues(root: Path) -> None:
    """Every declared venue present, so a run is never a REFUSE by accident."""
    for v in M.DEFAULT_VENUES:
        (root / v).mkdir(parents=True, exist_ok=True)


def _run(root: Path, capsys, *extra):
    rc = M.main([str(root), *extra])
    return rc, capsys.readouterr()


# ── POSITIVE: the defect, reconstructed ─────────────────────────────────────

def test_POSITIVE_a_module_level_constant_is_a_finding(tmp_path, capsys):
    """The exact shape that was removed: a module-level constant holding the
    digest, wrapped in parentheses across two lines."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           '"""the pin module."""\n'
           "\n"
           "IMAGE_DIGEST = (\n"
           f'    "{DIGEST}"\n'
           ")\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    # NAMED, not merely counted: file and line, or the finding is unactionable.
    assert f"{PLUGIN_VENUE}/_pin.py:3" in out.out, out.out
    assert "IMAGE_DIGEST" in out.out, out.out


@pytest.mark.parametrize("rel", [
    f"{PLUGIN_VENUE}/_pin.py",
    f"{TOOLS_VENUE}/runner.py",
    "vibe-ic-marketplace/plugins/vibe-ic/tools/vibeic-eda/run.py",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/launch.py",
])
def test_POSITIVE_every_declared_venue_is_actually_read(rel, tmp_path, capsys):
    """A venue defined as "the two trees the copies happened to live in" would
    let a fourth copy be written one directory over and still report a clean
    bill. Each declared tree is held to reading its source."""
    _venues(tmp_path)
    _write(tmp_path, rel, f'RUNNER_IMAGE_DIGEST = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{rel}:1" in out.out, out.out


def test_POSITIVE_both_trees_at_once_are_both_reported(tmp_path, capsys):
    """Two copies are two findings. A gate that stops at the first one turns a
    three-file removal into three rounds."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", f'IMAGE_DIGEST = "{DIGEST}"\n')
    _write(tmp_path, f"{TOOLS_VENUE}/runner.py",
           f'IMAGE_DIGEST = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:1" in out.out, out.out
    assert f"{TOOLS_VENUE}/runner.py:1" in out.out, out.out


def test_POSITIVE_a_resolver_stubbed_back_to_a_literal(tmp_path, capsys):
    """THE VACUITY THIS ROUND CLOSED, written as the one hunk that reaches it.

    The three files were changed INTO a function. A guard that inspects only
    assignments says PASS while the thing it exists to prevent has fully
    regressed: replacing `resolved_image_digest()`'s `raise` with a `return` of
    the literal restores the coupling completely, in ONE hunk, and is exactly
    what someone tired of `ImageNotResolvable` reaches for first.
    """
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           "class ImageNotResolvable(RuntimeError):\n"
           "    pass\n"
           "\n"
           "\n"
           "def resolved_image_digest(env=None) -> str:\n"
           '    """Ask this host which runtime image it holds."""\n'
           "    for step in _steps(env):\n"
           "        got = step()\n"
           "        if got:\n"
           "            return got\n"
           f'    return "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:11" in out.out, out.out
    assert "resolved_image_digest" in out.out, out.out


def test_POSITIVE_a_module_getattr_returning_a_literal(tmp_path, capsys):
    """The OTHER half of the real fix. `hermetic_candidate_runner` keeps the
    spelling `IMAGE_DIGEST` readable through PEP 562's module `__getattr__`, so
    the name the value is served FOR is in the `if` test and not in the
    function's own name. Stub that branch back to a literal and the identity is
    stored again under the same name every caller still reads."""
    _venues(tmp_path)
    _write(tmp_path, f"{TOOLS_VENUE}/runner.py",
           "def __getattr__(name):\n"
           '    if name == "IMAGE_DIGEST":\n'
           f'        return "{DIGEST}"\n'
           "    raise AttributeError(name)\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{TOOLS_VENUE}/runner.py:3" in out.out, out.out


def test_NEGATIVE_a_branch_name_does_not_leak_past_its_function(
        tmp_path, capsys):
    """The other direction of the arm above: a branch is about ITS branch, and a
    function is judged by ITS OWN name.

    The string an `if` selected on is carried only into that branch and is
    DROPPED at the next function boundary. Both halves are here: a sibling
    function after the `__getattr__`, and a function DEFINED INSIDE an image-ish
    branch. Without the reset, one `if name == "IMAGE_DIGEST"` anywhere in a
    module would judge every literal in every function under it — the
    scope-leak defect class that has cost this checker two rounds.
    """
    _venues(tmp_path)
    _write(tmp_path, f"{TOOLS_VENUE}/runner.py",
           "import os\n"
           "\n"
           "\n"
           "def __getattr__(name):\n"
           '    if name == "IMAGE_DIGEST":\n'
           "        return _resolve()\n"
           "    raise AttributeError(name)\n"
           "\n"
           "\n"
           "def golden_vector() -> str:\n"
           f'    return "{DIGEST}"\n'
           "\n"
           "\n"
           'if os.environ.get("EDA_IMAGE_MODE"):\n'
           "    def sha2_core_vector() -> str:\n"
           f'        return "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out


def test_POSITIVE_a_fallback_literal_in_an_except_handler(tmp_path, capsys):
    """"Resolve from the host, fall back to the stored value" is written in
    Python as exactly this. `ast.ExceptHandler` is NOT an `ast.stmt`, so a plain
    "descend into statements" walk skips the whole body in silence."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           "try:\n"
           "    from _resolver import resolved_image_digest\n"
           "except ImportError:\n"
           f'    IMAGE_DIGEST = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:4" in out.out, out.out


def test_POSITIVE_a_literal_in_a_match_case(tmp_path, capsys):
    """Same mechanism as the arm above: `ast.match_case` is not an `ast.stmt`
    either."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           "def pick(kind):\n"
           "    match kind:\n"
           '        case "eda":\n'
           f'            IMAGE_DIGEST = "{DIGEST}"\n'
           "    return IMAGE_DIGEST\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:4" in out.out, out.out


def test_POSITIVE_the_prefix_split_one_token_away_is_the_same_defect(
        tmp_path, capsys):
    """`"sha256:" + "<64 hex>"` is the same stored identity as the plain
    literal, one line apart — and if the two had different verdicts, the ONE
    LINE between them would be a way to buy green with the defect left live."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           f'IMAGE_DIGEST = "sha256:" + "{BARE}"\n'
           "\n"
           "IMPLICIT = (\n"
           '    "sha256:"\n'
           f'    "{BARE}"\n'
           ")\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:1" in out.out, out.out


def test_POSITIVE_a_digest_parked_under_an_image_key_in_a_dict(
        tmp_path, capsys):
    """Moving the literal into a CONFIG dict is one line and stores the same
    identity; the key is as much "the surrounding name" as an identifier is."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           "CFG = {}\n"
           f'CFG["eda_image"] = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:2" in out.out, out.out


@pytest.mark.parametrize("name", ["_FALLBACK_PIN", "PIN_DIGEST", "PINNED_ID",
                                  "_PIN"])
def test_POSITIVE_the_pin_family_is_in_the_vocabulary(name, tmp_path, capsys):
    """The guarded file is `_eda_pin.py` and the constant a test module already
    stores this identity under is `PINNED_ID`. An earlier round dropped the PIN
    family for a measured benefit of zero and silenced the single most likely
    regression spelling of the very file this rule guards."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", f'{name} = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert name in out.out, out.out


# ── NEGATIVE / CONTROL: the corrected shape, and the legitimate neighbours ──

def test_NEGATIVE_the_corrected_shape_passes(tmp_path, capsys):
    """What the three files were changed INTO: the identity is asked for."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           "def resolved_image_digest() -> str:\n"
           '    """Ask this host which runtime image it holds."""\n'
           "    return _newest_local_runtime().digest\n"
           "\n"
           "\n"
           "def image_reference() -> str:\n"
           '    return f"{image_repo()}@{resolved_image_digest()}"\n')
    _write(tmp_path, f"{TOOLS_VENUE}/runner.py",
           "import _pin\n"
           "\n"
           "\n"
           "def __getattr__(name):\n"
           '    if name == "IMAGE_DIGEST":\n'
           "        return _pin.resolved_image_digest()\n"
           "    raise AttributeError(name)\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out
    assert "[PASS]" in out.out, out.out


def test_NEGATIVE_a_digest_under_a_name_that_is_not_the_image(
        tmp_path, capsys):
    """A content hash is a MEASUREMENT OF BYTES, not the identity of a runtime.

    These are the LIVE shapes on this tree — `_ppa/provenance.py:93` and
    `step_write_ledger.py:197` both store the sha256 of the empty file, spelled
    WITH its prefix. Measured: switch the NAME predicate off and those two files
    are what turns red. A rule that cannot tell them apart reddens a clean tree.
    """
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/provenance.py",
           f'EMPTY_FILE_SHA256 = "{DIGEST}"\n'
           f'_EMPTY_SHA = "{DIGEST}"\n'
           f'_LANDING_SCRIPT_SHA256 = "{DIGEST}"\n'
           f'EXPECTED_BUNDLE_SHA256 = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out


def test_NEGATIVE_an_image_named_constant_holding_something_else(
        tmp_path, capsys):
    """The other half of the conjunction: an image-named constant is not a
    finding unless it actually stores a digest."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           'IMAGE_REPO_DEFAULT = "registry.invalid/org/runtime"\n'
           'IMAGE_REPO_ENV = "RUNTIME_IMAGE_REPO"\n'
           'IMAGE_DIGEST_RE = r"sha256:[0-9a-f]{64}"\n'
           'CONTAINER_NAME_ENV = "RUNTIME_CONTAINER"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out


def test_NEGATIVE_a_bare_checksum_is_a_measurement_not_an_identity(
        tmp_path, capsys):
    """The VALUE predicate is what makes the PIN family safe in a repository
    that also designs silicon. A 256-bit golden vector, a tarball checksum, a
    manifest hash — all written BARE, and a bare run is not a registry
    reference no matter what it is called. Measured on this tree: 733 of the
    1053 image-ish assignment names match only via PIN, and NONE holds a bare
    64-hex today; this arm is what keeps that safe if one ever does.
    """
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/vectors.py",
           f'PIN_TABLE_SHA = "{BARE}"\n'
           f'_EXTERNAL_IO_PINS_SHA256 = "{BARE}"\n'
           f'CONTAINER_TARBALL_SHA256 = "{BARE}"\n'
           f'IMAGE_MANIFEST_FILE_SHA256 = "{BARE}"\n'
           f'IMAGE_BUILD_INPUTS = {{"dockerfile_sha256": "{BARE}"}}\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out


def test_NEGATIVE_adding_a_comment_cannot_flip_the_verdict(tmp_path, capsys):
    """A guard that a comment can satisfy — or trip — is not a guard.

    The same file is judged twice: once as clean source, once with the whole
    defect written out in a comment AND in a docstring. Both verdicts must be
    PASS, or an honest record of which image a measurement was taken on becomes
    a CI failure and the guard gets deleted. `_eda_pin.py:15` carries exactly
    such a record today, in prose between double backticks.
    """
    _venues(tmp_path)
    clean = ("def resolved_image_digest() -> str:\n"
             "    return _ask_the_host()\n")
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", clean)
    rc_before, out_before = _run(tmp_path, capsys)
    assert rc_before == 0, out_before.out

    prose = (
        '"""History, not a pointer.\n'
        "\n"
        f"The pin every landing site named was ``{DIGEST}``, and that copy was\n"
        "removed; the measurement below was taken on that image.\n"
        '"""\n'
        f'# MEASURED on {DIGEST}: IMAGE_DIGEST = "{DIGEST}"\n'
        + clean
    )
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", prose)
    rc_after, out_after = _run(tmp_path, capsys)
    assert rc_after == 0, out_after.out


def test_NEGATIVE_a_docstring_inside_an_image_named_function_is_still_prose(
        tmp_path, capsys):
    """The `return` binding site is judged by its function's NAME, and NOTHING
    ELSE in the body is. A resolver whose docstring honestly records which image
    a measurement was taken on is the live shape on this tree; if the function
    name leaked onto every literal in the body, prose immunity would have died
    the moment `return` became a binding site."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py",
           "def resolved_image_digest() -> str:\n"
           f'    """Measured against {DIGEST} on the reference host."""\n'
           f'    # the removed copy read: return "{DIGEST}"\n'
           f'    _note = "measured on {DIGEST}"\n'
           "    return _ask_the_host()\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out


@pytest.mark.parametrize("rel", [
    f"{PLUGIN_VENUE}/tests/test_provenance.py",
    f"{PLUGIN_VENUE}/tests/fixtures/recorded_runtime.py",
    f"{TOOLS_VENUE}/gate_fixtures/a_synthetic_runtime.py",
    f"{TOOLS_VENUE}/conftest.py",
    f"{TOOLS_VENUE}/runner_test.py",
])
def test_NEGATIVE_evidence_venues_are_data_not_configuration(
        rel, tmp_path, capsys):
    """THE EXEMPTION, stated as VENUE rather than as a list of files.

    A fixture and a test legitimately name the image a past run used: that is
    data describing something that happened, not configuration anything reads
    to decide what to run. Listing today's files would be wrong the moment a
    sixth is written, so the SHAPE is what is exempt. Measured on the live tree:
    switch this off and two real evidence files redden —
    `programs/tests/test_container_image_provenance.py:25 PINNED_ID` and
    `mcp-eda/test/test_restart_eda_pinned_default.py:250`.
    """
    _venues(tmp_path)
    _write(tmp_path, rel, f'RUNTIME_IMAGE_DIGEST = "{DIGEST}"\n')
    # ...and one real source file, so the run is not vacuous.
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", "X = 1\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out
    assert "exempt by venue" in out.out, out.out


@pytest.mark.parametrize("rel,text", [
    (f"{PLUGIN_VENUE}/manifest.json", '{"image": "<D>"}\n'),
    (f"{TOOLS_VENUE}/DELIVERY.md", "The run used `<D>`.\n"),
    (f"{TOOLS_VENUE}/run.sh", 'EDA_IMAGE_DIGEST="<D>"\n'),
])
def test_NEGATIVE_only_python_is_read(rel, text, tmp_path, capsys):
    """KNOWN CONSERVATISM, pinned as behaviour so it cannot be mistaken for
    coverage. A record is not opened, and neither is shell: a `.sh` has no AST
    here, so prose immunity would have to be rebuilt from a quote-tracking text
    stripper — and in this venue the house style embeds whole Python programs in
    quoted here-documents. Both sides of that trade were measured in earlier
    rounds; this arm says out loud which side was taken."""
    _venues(tmp_path)
    _write(tmp_path, rel, text.replace("<D>", DIGEST))
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", "X = 1\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out


def test_NEGATIVE_this_program_does_not_need_to_hide_from_itself(
        tmp_path, capsys):
    """An earlier draft skipped its own file by path and justified it with a
    test that did not exist. Measured, the exclusion suppressed ZERO findings —
    every digest in this program is a placeholder or a regex, and none is bound
    to an image-ish name. So the file is scanned like any other, and THIS is the
    arm that keeps that true: a permanent blind spot inside the venue is not
    worth a saving of nothing.
    """
    _venues(tmp_path)
    me = Path(M.__file__).resolve()
    _write(tmp_path, f"{PLUGIN_VENUE}/{me.name}",
           me.read_text(encoding="utf-8"))
    _write(tmp_path, f"{PLUGIN_VENUE}/tests/{Path(__file__).name}",
           Path(__file__).read_text(encoding="utf-8"))
    rc, out = _run(tmp_path, capsys)
    assert rc == 0, out.out
    assert out.out.count("[PASS]") == 1, out.out


def test_this_programs_own_source_holds_no_finding_to_be_hidden_from():
    """The MEASUREMENT the removed self-exclusion rested on, made an assertion.

    Re-adding `if path.resolve() == me: continue` cannot be caught by any
    behavioural arm — by construction it only ever skips a file that has nothing
    to report. What CAN be asserted is the fact that made it dead. If that ever
    stops being true, this arm reddens and the question "hide, or rewrite the
    example?" gets asked out loud instead of settled by a path comparison.
    """
    me = Path(M.__file__).resolve()
    findings = M.scan_python(me.name, me.read_text(encoding="utf-8"))
    assert findings == [], "\n".join(f.line_of() for f in findings)


# ── REFUSE: "I could not look" never shares an exit code with "it is clean" ──

def test_REFUSE_a_root_that_is_not_a_directory(tmp_path, capsys):
    rc, out = _run(tmp_path / "nope", capsys)
    assert rc == 2
    assert "[REFUSE]" in out.out + out.err


def test_REFUSE_a_declared_venue_that_is_absent(tmp_path, capsys):
    """A venue that is not there was not searched. Answering PASS over the
    three that happened to exist is the false certificate this program refuses;
    the missing one is NAMED so the caller can fix the root or the --venue."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", "X = 1\n")
    import shutil
    shutil.rmtree(tmp_path / "tools")
    rc, out = _run(tmp_path, capsys)
    assert rc == 2
    assert "tools" in out.out + out.err


def test_REFUSE_a_venue_with_no_source_file_is_not_a_clean_bill(
        tmp_path, capsys):
    """The failure mode this exists to avoid: a mis-rooted invocation printing
    the same sentence as a full sweep of a clean tree."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/README.md", "nothing executable here\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 2
    assert "no Python source file was read" in out.out + out.err


def test_REFUSE_a_source_that_will_not_parse_was_never_searched(
        tmp_path, capsys):
    """Breaking a file must not be a way to go green: a file that cannot be
    parsed was never searched, and that is a REFUSE, not a PASS."""
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/broken.py", "def (:\n")
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", "X = 1\n")
    rc, out = _run(tmp_path, capsys)
    assert rc == 2
    assert "could not be read or parsed" in out.out + out.err


def test_a_real_finding_outranks_a_file_it_could_not_parse(tmp_path, capsys):
    """rc 1 is a FINDING and rc 2 is "no verdict". A tree that carries both has
    a finding, and burying it under a refusal would hide the thing that matters.
    """
    _venues(tmp_path)
    _write(tmp_path, f"{PLUGIN_VENUE}/broken.py", "def (:\n")
    _write(tmp_path, f"{PLUGIN_VENUE}/_pin.py", f'IMAGE_DIGEST = "{DIGEST}"\n')
    rc, out = _run(tmp_path, capsys)
    assert rc == 1, out.out
    assert f"{PLUGIN_VENUE}/_pin.py:1" in out.out, out.out


@pytest.mark.parametrize("build,rc_want,verdict_want", [
    (lambda t: _write(t, f"{PLUGIN_VENUE}/_pin.py", "X = 1\n"), 0, "PASS"),
    (lambda t: _write(t, f"{PLUGIN_VENUE}/_pin.py",
                      f'IMAGE_DIGEST = "{DIGEST}"\n'), 1, "FAIL"),
    (lambda t: _write(t, f"{PLUGIN_VENUE}/README.md", "nothing\n"), 2, "REFUSE"),
])
def test_the_json_record_distinguishes_refuse_from_pass(
        build, rc_want, verdict_want, tmp_path, capsys):
    """A reader of the JSON saw `findings: []` for BOTH "clean" and "I never
    looked". An empty finding list is not a verdict; the verdict is."""
    _venues(tmp_path)
    build(tmp_path)
    dest = tmp_path / "record.json"
    rc, _ = _run(tmp_path, capsys, "--json", str(dest))
    assert rc == rc_want
    record = json.loads(dest.read_text(encoding="utf-8"))
    assert record["verdict"] == verdict_want, record
    if verdict_want == "REFUSE":
        assert record["refused_because"], record
        assert not record["findings"], record


# ── the predicates, both directions ─────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "IMAGE_DIGEST", "RUNNER_IMAGE_DIGEST", "EDA_IMAGE", "edaImageDigest",
    "eda-image-digest", "CONTAINER_DIGEST", "RUNTIME_REF", "DOCKER_IMAGE",
    "TOOLCHAIN_IMAGE", "IMG_REF", "_NAMED_CONTAINER", "IMAGES", "oci_ref",
    "podman_image", "PINNED_IMAGE",
    # the PIN family: the guarded file is `_eda_pin.py`, and `PINNED_ID` is the
    # name a live test module already stores this identity under.
    "_PIN", "PIN_DIGEST", "PINNED_ID", "_FALLBACK_PIN", "container_pins",
])
def test_the_name_predicate_recognises_a_runtime_image_name(name):
    assert M.name_refers_to_the_runtime_image(name), name


@pytest.mark.parametrize("name", [
    # names a LIVE source file on this tree stores a digest under; each measures
    # BYTES — a source checksum, an adjudication decision, a bundle, an empty
    # file. Measured: with the NAME predicate off, these turn a clean tree red.
    "EMPTY_FILE_SHA256", "_EMPTY_SHA", "_LANDING_SCRIPT_SHA256",
    "_LANDING_EXECUTION_PREFIX_SHA256", "_SEMANTIC_DRIVER_SHA256",
    "EXPECTED_BUNDLE_SHA256", "decision_digest", "GOLDEN_SHA256",
    "ARTEFACT_CHECKSUM", "MEDIAN_DELAY", "REPORT_HASH", "BASELINE_DIGEST",
    "SOURCE_SHA",
    # and the words that merely BEGIN with a container word. Segments are
    # compared WHOLE, so a prefix match cannot drag these in.
    "PING_PAYLOAD_SHA256", "PINOUT_SHA256", "EDAT_HASH", "IMGUI_BLOB_SHA",
    "CONTAINERD_LOG_SHA", "IMAGERY_INDEX",
])
def test_the_name_predicate_leaves_byte_measurements_alone(name):
    assert not M.name_refers_to_the_runtime_image(name), name


@pytest.mark.parametrize("expr,found", [
    (f'"{DIGEST}"', True),
    (f'"reg.invalid/x@{DIGEST}"', True),
    (f'"sha256:" + "{BARE}"', True),            # the prefix, one token away
    (f'("sha256:" "{BARE}")', True),            # implicit concatenation
    # a dict does NOT reassemble: its KEYS join in source order between the
    # halves, so `{"d": "sha256:", "v": "<bare>"}` never spells a reference.
    (f'{{"d": "sha256:", "v": "{BARE}"}}', False),
    (f'"{BARE}"', False),                       # a CHECKSUM: written bare
    (f'"sha256:" + BARE_NAME', False),          # not a literal: conservatism
    (f'f"sha256:{{x}}"', False),                # ditto
    ('"sha256:[0-9a-f]{64}"', False),           # a pattern, not a value
    ('"sha256:abc123"', False),                 # too short to be a digest
    (f'"{BARE}ff"', False),                     # too long to be one
    ('""', False),
])
def test_the_value_predicate_both_directions(expr, found):
    """Literals are CONCATENATED in source order before matching: that is the
    whole of the rule, and it is what stops one line — `"sha256:" + "<hex>"` —
    from being a way around the plain form. It promotes nothing: a bare run
    joins to itself and still carries no `sha256:`."""
    node = ast.parse(expr, mode="eval").body
    assert (M.digest_in(node) is not None) is found, expr


# ── the live pin ────────────────────────────────────────────────────────────

def _repository_root():
    """The nearest ancestor holding ALL scanned venues, or None.

    Found by SEARCHING rather than by a fixed `parents[n]`: a hard-coded depth
    is a bet on where this file is installed, and it raises IndexError — a
    RED test — the first time the bet is wrong, which says nothing about the
    property under test.
    """
    for cand in [PROGRAMS, *PROGRAMS.parents]:
        if all((cand / v).is_dir() for v in M.DEFAULT_VENUES):
            return cand
    return None


def test_the_shipped_tree_stores_no_runtime_image_digest():
    """THE POINT OF THE FILE. The three copies are gone; this is what stops a
    fourth. Skipped only where the repository layout is not present, and a skip
    is VISIBLE — unlike a PASS over nothing."""
    repo = _repository_root()
    if repo is None:
        pytest.skip(f"no ancestor of {PROGRAMS} holds every scanned venue")
    findings, stats = M.scan(str(repo))
    assert int(stats["files_scanned"]) > 0, stats
    assert findings == [], "\n".join(f.line_of() for f in findings[:20])


def test_the_live_pin_would_see_a_fourth_copy_in_the_shipped_tree(tmp_path):
    """REACHABILITY for the arm above. An absence assertion over a real tree is
    worth nothing unless a defect planted in that tree would turn it red — and
    the shape planted here is the one a guard that reads only assignments was
    MEASURED to miss: a resolver stubbed back to a literal.
    """
    _venues(tmp_path)
    planted = tmp_path / PLUGIN_VENUE / "_planted_resolver.py"
    planted.write_text("def resolved_image_digest() -> str:\n"
                       f'    return "{DIGEST}"\n', encoding="utf-8")
    findings, stats = M.scan(str(tmp_path))
    assert int(stats["files_scanned"]) > 0, stats
    assert [f for f in findings if f.path.endswith("_planted_resolver.py")], \
        [f.line_of() for f in findings]
