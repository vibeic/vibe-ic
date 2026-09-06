#!/usr/bin/env python3
"""The plugin ASKS the image which image it is; it does not remember a version.

WHAT THIS REPLACES, AND WHY IT WAS REPLACED TWICE
=================================================
Round one: the image version was a literal in eleven places, kept in step by
`tools/vibeic-eda/sync_image_version.py --check` and advanced by a PR that
vibeic-eda's daily release opened on this repo, on the stated grounds that the
pinned tag "matches what the plugin was VERIFIED AGAINST". Measured 2026-08-20:
nothing verified that. The literals went; a single ANCHOR FILE stayed, because a
gate that reports FAIL about the image's CONTENTS must not have its verdict moved
by a third party's push (vibe-ic#927).

Round two — this file. `tools/vibeic-eda/VERSION` was still vibeic-eda's version
number stored in the vibe-ic repo, so a vibeic-eda release still needed a PR here.
Measured 2026-08-21 on 8HD-9:

  * the anchor said `0.3.16`; the newest vibeic-eda image on the host was
    `0.3.13`. `docker run …:0.3.16` printed "Unable to find image locally" and
    began a multi-gigabyte pull — inside a hygiene gate. The anchor was not
    protecting a verdict, it was preventing one;
  * `sync_image_version.py --check` was RED on main, and the "live pointer" it
    wanted rewritten was a comment recording which image a yosys measurement had
    been taken on. The coupling was demanding that a record be falsified;
  * of 11 registered install docs, one still carried an X.Y.Z pin. The docs had
    already decoupled themselves.

THE MECHANISM NOW — two facts, both asked of the image, neither stored here:

    DIGEST   `repo@sha256:…`, immutable; what a recorded verdict is replayed with
    VERSION  the image's own `org.opencontainers.image.version` OCI label; what a
             human reads

The label is BELIEVED VERBATIM. Published images today still inherit upstream
iic-osic-tools' `2026.06`; from vibeic-eda 0.3.19 the label is the fork's own
version, and no code here changes when that happens. A shape check to tell the
two apart would be a workaround for one release window and dead code for ever
after, so there is none, and `test_the_version_label_is_believed_verbatim` pins
that there is none.

Properties this file holds, each with a way of quietly coming undone:
  1. NOTHING in the shipped tree reads a vibeic-eda version out of OUR source —
     the rule that stops round two coming back (section 1);
  2. `resolve()` never answers a bare `:latest` — `docker run …:latest` does not
     consult the registry, so it means "whatever this machine pulled, whenever";
  3. `resolve()` and `local_image()` stay DIFFERENT questions — collapsing them
     hands `docker run` a multi-gigabyte fetch where a skip guard expected a
     local check;
  4. RUNNING a tool and JUDGING one stay different questions, and the judging one
     makes no registry call it was not asked to make (vibe-ic#927's property,
     which survives the anchor it was first written against);
  5. a verdict-bearing report cannot be written without both facts, and a gate
     that cannot establish them exits its own NOT-MEASURED code rather than
     reporting about silicon (section 5).
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import shutil
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))
import _eda_image as M  # noqa: E402
import _eda_pin as _pin  # noqa: E402
import not_verified_tier as NV  # noqa: E402

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PINNED = re.compile(r"vibeic-eda:\d+\.\d+\.\d+")


def _code_only(src: str) -> str:
    """`src` with comments and docstrings removed.

    History is not a pointer. This tree is full of honest records — "MEASURED …
    image vibeic-eda:0.2.30" — and a guard that fires on those gets deleted by
    the next person who trips over it, which leaves the real rule unguarded.
    """
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    return re.sub(r'"""(?:.|\n)*?"""', "", body)


# ── 1. nothing remembers a version ──────────────────────────────────────────

_CONSUMERS = (
    "fault_atpg_run.py",
    "fmeda_fault_injection_coverage.py",
    "sta_engine_parity_check.py",
    "pdk_via_patch_meets_layer_min_width_check.py",
    "tests/test_v1_4_21_dft_atpg_liberty_resolver.py",
    "tests/test_extraction_input_capability_check.py",
)


@pytest.mark.parametrize("rel", _CONSUMERS)
def test_the_image_consumers_carry_no_pinned_version(rel):
    """These six decided which image RUNS. A literal left in one of them does
    not fail loudly — it freezes, and keeps running an older toolchain than
    everything around it."""
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    assert not _PINNED.search(_code_only(src)), f"{rel} still pins a version"
    assert "_eda_image" in src, f"{rel} does not ask _eda_image"


def test_no_module_level_constant_freezes_an_image_version():
    """The shape that goes stale silently, stated as a shape rather than a list
    of files — a NEW `DEFAULT_IMAGE = "...:0.3.16"` is caught by the same test."""
    offenders = []
    for path in sorted(_PROGRAMS.rglob("*.py")):
        # SHIPPED programs only. A test may legitimately define a fixture
        # constant (`PINNED = "…:9.9.9"`); a program that runs the toolchain
        # may not, because that one decides which image actually runs.
        if "tests" in path.relative_to(_PROGRAMS).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:                       # module level only
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                    and _PINNED.search(value.value):
                offenders.append(
                    f"{path.relative_to(_PROGRAMS).as_posix()}:{node.lineno}")
    assert not offenders, (
        "module-level constants pinning an image version — ask _eda_image "
        f"instead: {offenders}")


#: Any way a shipped file could reach BACK INTO THIS SOURCE TREE for a
#: vibeic-eda version number. Written as SHAPES, not as a list of filenames, so
#: a new file with the same idea is caught without anyone remembering to add it.
_SOURCE_TREE_VERSION_READS = (
    # the anchor file this change deleted, in every spelling a path can take
    re.compile(r"vibeic[-_]eda['\"]?\s*[/,)\]]?\s*['\"]?\s*VERSION"),
    re.compile(r"VERSION['\"]?\s*\)?\s*\.\s*"
               r"(?:read_text|read|read_bytes|open)\b"),
    re.compile(r"cat\s+\S*vibeic-eda/VERSION"),
    # its propagation machine
    re.compile(r"sync_image_version"),
)


_ASSERTS_ABSENCE = re.compile(r"assert\s+not\b|assert\s+.*\bnot\s+\(")


def _is_a_read(code: str, at: int) -> bool:
    """Is the match at `at` a READ, or a statement that the thing is GONE?

    `assert not (repo / "tools" / "vibeic-eda" / "VERSION").exists()` carries the
    forbidden shape and asserts the opposite of it. Judged on the enclosing LINE,
    which is where the negation lives.
    """
    start = code.rfind("\n", 0, at) + 1
    end = code.find("\n", at)
    line = code[start:end if end != -1 else len(code)]
    return not _ASSERTS_ABSENCE.search(line)


def test_no_shipped_file_reads_a_vibeic_eda_version_from_our_source_tree():
    """THE TEST THAT STOPS THIS COMING BACK. Requirement 5 of the decoupling.

    The owner's instruction was not "delete a file", it was "stop this repo
    holding vibeic-eda's version number, because then every release over there
    needs a PR over here". A deletion satisfies that for exactly as long as
    nobody re-adds a `tools/vibeic-eda/VERSION`, a `plugins/vibe-ic/VERSION`, or
    a helper that walks up looking for one — and each of those would look, in
    review, like a small local convenience.

    So the rule is asserted over CODE, in the whole shipped tree, as a shape.
    Comments and docstrings are stripped first, deliberately: this file and six
    programs EXPLAIN the deleted anchor, and a guard that cannot tell an
    explanation from an implementation is a guard someone deletes.

    The version comes from `org.opencontainers.image.version` on the image, or
    it is NOT_MEASURED. There is no third source.
    """
    offenders = []
    for path in sorted(_PLUGIN.rglob("*.py")) + sorted(_PLUGIN.rglob("*.sh")):
        rel = path.relative_to(_PLUGIN).as_posix()
        # The one file that must contain the shapes it forbids: they are the
        # patterns above. Excluded BY PATH, not by a keyword an offender could
        # also carry, and `test_the_guard_itself_still_bites` below re-proves
        # the guard fires by planting an offender under the same walk.
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        try:
            code = _code_only(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:                              # pragma: no cover
            continue
        for pattern in _SOURCE_TREE_VERSION_READS:
            for m in pattern.finditer(code):
                if not _is_a_read(code, m.start()):
                    continue
                line = code[:m.start()].count("\n") + 1
                offenders.append(f"{rel}:~{line}  {m.group(0)!r}")
                break
    assert not offenders, (
        "a shipped file reads a vibeic-eda version number out of OUR source "
        "tree. That is the coupling this change removed: it makes every "
        "vibeic-eda release need a PR in this repo. Ask the IMAGE instead — "
        "`_eda_image.judged_image()` returns the digest and the image's own "
        f"{M.VERSION_LABEL} label. Offenders: {offenders}")


@pytest.mark.parametrize("planted", [
    'V = up / "tools" / "vibeic-eda" / "VERSION"',
    'ver = (HERE / "VERSION").read_text().strip()',
    'IMG = "ghcr.io/vibeic/vibeic-eda:" + open("VERSION").read()',
    'subprocess.run(["bash", "-c", "cat tools/vibeic-eda/VERSION"])',
])
def test_the_guard_itself_still_bites(planted):
    """The guard above is an ABSENCE assertion, and an absence assertion that
    cannot fire reads exactly like a clean tree. So the four shapes it is written
    against are planted here, one at a time, and each must be caught.

    Without this, deleting a pattern from `_SOURCE_TREE_VERSION_READS` — or
    breaking one while editing it — makes the guard greener, not redder, and
    nothing says so.
    """
    hits = [pat.pattern for pat in _SOURCE_TREE_VERSION_READS
            if pat.search(planted) and _is_a_read(planted, pat.search(planted).start())]
    assert hits, (
        f"no pattern in _SOURCE_TREE_VERSION_READS matches {planted!r}, so a "
        f"shipped file could reintroduce the coupling in that shape and "
        f"test_no_shipped_file_reads_a_vibeic_eda_version_from_our_source_tree "
        f"would stay green")


def test_the_guard_does_not_fire_on_an_ordinary_line():
    """The other direction. A guard that matches everything is a guard that gets
    deleted, and it takes the real rule with it."""
    for benign in (
        'judged = _img.judged_image()',
        'print(f"image {judged.ref} version {judged.version}")',
        'ap.add_argument("--image", default=None)',
        'VERSION_LABEL = "org.opencontainers.image.version"',
        # the shape that says the anchor is GONE — it must not read as the shape
        # that brings it back, or the deletion cannot be asserted anywhere
        'assert not (repo / "tools" / "vibeic-eda" / "VERSION").exists()',
        'assert not (root / "tools" / "vibeic-eda" / "sync_image_version.py").exists()',
    ):
        hits = [p for p in _SOURCE_TREE_VERSION_READS
                if p.search(benign) and _is_a_read(benign, p.search(benign).start())]
        assert not hits, (benign, hits)


def test_the_deleted_anchor_is_actually_gone_from_the_repo():
    """The premise of the test above: it asserts nothing if the file it is about
    is still sitting there being read by something the shapes do not match."""
    repo = _PLUGIN.parents[2]
    assert not (repo / "tools" / "vibeic-eda" / "VERSION").exists(), (
        "tools/vibeic-eda/VERSION is back. Every vibeic-eda release now needs a "
        "PR in this repo again.")
    assert not (repo / "tools" / "vibeic-eda" / "sync_image_version.py").exists()


# ── 2. never a bare :latest ─────────────────────────────────────────────────

def test_resolve_returns_a_digest_not_a_floating_tag(monkeypatch):
    """Still the property; the ANSWER is now the pin rather than whatever the
    registry says `latest` means this minute."""
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: pytest.fail(
        "the run path asked the registry"))
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (_pin.image_reference(env), ""))
    got = M.resolve(env={})
    assert got == f"{M.IMAGE_REPO}@{_pin.IMAGE_DIGEST}"
    assert ":latest" not in got


def test_the_run_path_takes_the_pin_and_not_the_newest_local_tag(monkeypatch, capsys):
    """WHAT THIS TEST USED TO SAY, and why it says something else now.

    It used to assert that an unreachable registry fell back to the newest LOCAL
    TAG, announced on stderr. That ladder was measured on 8hd-3 on 2026-09-07
    and it is the defect: with `VIBEIC_EDA_IMAGE_REPO` exported and the pinned
    0.3.47 present, `judged_image()` answered with the 0.3.16 tag and
    `resolve()` answered with 0.3.46 — two different images, one host, one
    minute, neither of them the pin.

    The honest-fallback property it protected is KEPT and is strictly stronger:
    there is no fallback left to be dishonest about, and the one case that used
    to be silent (a host without the bytes) is announced by name.
    """
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: pytest.fail(
        "the run path asked the registry"))
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.9", "0.3.10"])
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (_pin.image_reference(env), ""))
    got = M.resolve(env={})
    assert got == f"{M.IMAGE_REPO}@{_pin.IMAGE_DIGEST}"
    assert "0.3.9" not in got and "0.3.10" not in got


def test_a_run_on_a_host_without_the_pinned_bytes_SAYS_SO(monkeypatch, capsys):
    """Degrade loudly. The reference returned is still the pinned one — running
    it fetches exactly those bytes — but the operator is told, because a
    multi-gigabyte fetch nobody expected is the other half of this module's
    history."""
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    got = M.resolve(env={})
    assert got == f"{M.IMAGE_REPO}@{_pin.IMAGE_DIGEST}"
    err = capsys.readouterr().err
    assert _pin.IMAGE_NOT_PRESENT in err
    assert "Nothing older is substituted" in err


def test_the_run_path_never_reaches_for_the_legacy_upstream_image(monkeypatch, capsys):
    """A REGRESSION I SHIPPED ONCE, in its current form. Dropping to upstream
    iic-osic-tools hands a DFT step a toolchain with no Fault and no patched
    yosys. It used to be the last rung; it is not a rung at all now, and this is
    the assertion that keeps it from becoming one again."""
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: [])
    got = M.resolve(env={})
    assert got != M.LEGACY_IMAGE
    assert M.LEGACY_IMAGE not in got
    assert _pin.IMAGE_DIGEST in got


@pytest.mark.parametrize("key", ["VIBEIC_EDA_IMAGE", "IIC_EDA_IMAGE"])
def test_an_explicit_override_wins_over_everything(monkeypatch, key):
    monkeypatch.setattr(M, "registry_digest",
                        lambda *a, **k: pytest.fail("must not ask the registry"))
    assert M.resolve(env={key: "my/own:image"}) == "my/own:image"


# ── 3. the two questions stay apart ─────────────────────────────────────────

def test_local_image_never_touches_the_registry(monkeypatch):
    """Collapsing this into `resolve` turns a skip guard's local check into an
    unbounded pull. The question it answers is now "are the PINNED bytes here",
    which is the only version of it a skip guard can act on."""
    monkeypatch.setattr(M, "registry_digest",
                        lambda *a, **k: pytest.fail("local_image asked the registry"))
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.16"])
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (_pin.image_reference(env), ""))
    assert M.local_image(env={}) == f"{M.IMAGE_REPO}@{_pin.IMAGE_DIGEST}"
    assert "0.3.16" not in M.local_image(env={})


def test_local_image_is_None_when_the_machine_has_nothing(monkeypatch):
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    assert M.local_image(env={}) is None


def test_local_tags_are_newest_first_and_ignore_non_semver(monkeypatch):
    out = type("R", (), {"returncode": 0,
                         "stdout": "latest\n0.3.9\n0.3.10\nedge\n0.4.0\n"})()
    monkeypatch.setattr(M, "_run", lambda *a, **k: out)
    assert M.local_tags() == ["0.4.0", "0.3.10", "0.3.9"]


# ── 4. running a tool and judging one are different questions ───────────────
#
# THE ONE THAT KEEPS BEING GOT WRONG. The first cut of the anchor change sent all
# six consumers to `resolve()`, which asks the registry. That is right for
# running a tool and wrong for a gate that reports FAIL about the image's
# CONTENTS: a third party's push would then change a blocking verdict with no
# commit in this tree. vibe-ic#927 had already written that down.
#
# The ANSWER changed — a digest and a label instead of a remembered version — and
# the QUESTION did not.

_VERDICT_BEARING = (
    "sta_engine_parity_check.py",                    # FAILs about the engines IN the image
    "pdk_via_patch_meets_layer_min_width_check.py",  # FAILs about tech LEFs read FROM it
    "pdk_registry_selectable_check.py",              # BLOCKS on assets found inside it
)
_TOOL_RUNNING = (
    "fault_atpg_run.py",
    "fmeda_fault_injection_coverage.py",
)


@pytest.mark.parametrize("rel", _VERDICT_BEARING)
def test_a_gate_that_judges_the_image_asks_judged_image(rel):
    code = _code_only((_PROGRAMS / rel).read_text(encoding="utf-8"))
    assert "judged_image" in code, (
        f"{rel} reports a verdict about the image, so it must ask "
        "_eda_image.judged_image() — which pins a digest and reads the image's "
        "own version label")
    assert "_img.resolve()" not in code, (
        f"{rel} asks the registry. Its verdict would then change whenever "
        "anyone publishes an image, with no commit here (vibe-ic#927)")


@pytest.mark.parametrize("rel", _TOOL_RUNNING)
def test_a_program_that_runs_the_toolchain_takes_the_current_image(rel):
    """The other half. Pinning these would put them back on a version that only
    moves when somebody remembers to move it — the thing this change removed."""
    code = _code_only((_PROGRAMS / rel).read_text(encoding="utf-8"))
    assert "_img.resolve()" in code, f"{rel} should take the current image"


def test_judged_image_makes_no_registry_call_unless_asked(monkeypatch):  # noqa: D401
    """vibe-ic#927's PROPERTY, carried across the mechanism that replaced it.

    The anchor made a blocking verdict independent of the registry by freezing a
    version. `judged_image` does it by preferring the image already on this host:
    a local image cannot be re-pointed while a CI run is in progress, and two
    gates in the same run cannot silently judge two different images. Reaching
    the registry is possible, and it is OPT-IN.
    """
    monkeypatch.setattr(M, "registry_digest",
                        lambda *a, **k: pytest.fail(
                            "judged_image asked the registry without allow_pull"))
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.13"])
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (_pin.image_reference(env), ""))
    monkeypatch.setattr(M, "image_version", lambda ref: ("0.3.47", "local-label", ""))
    j = M.judged_image(env={})
    # The mechanism moved from "the newest local tag" to "the pinned bytes,
    # locally". #927's property is UNCHANGED and better served: a fixed digest
    # cannot be re-pointed by a publish at all, whereas the newest local tag
    # moved the moment anything on the host pulled a newer one.
    assert j.digest == _pin.IMAGE_DIGEST
    assert j.source == "pinned"


def test_with_nothing_local_it_refuses_rather_than_starting_a_pull(monkeypatch):
    """`docker run` on an absent reference FETCHES. Measured 2026-08-21: the
    anchored image was absent on this host and `docker run` began pulling it,
    inside a hygiene gate. A gate that does that gets switched off."""
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: [])
    monkeypatch.setattr(M, "registry_digest",
                        lambda *a, **k: pytest.fail("must not ask without allow_pull"))
    j = M.judged_image(env={})
    assert j.ref is None
    assert "does not pull" in j.why_not
    assert "--allow-pull" in j.why_not


def test_allow_pull_is_the_way_to_reach_the_registry(monkeypatch):
    """And what it reaches for is THE PINNED DIGEST. Opting into a pull is
    opting into fetching the bytes that were pinned; it must not have become
    opting into whichever bytes are newest."""
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    monkeypatch.setattr(M, "image_digest",
                        lambda ref, **k: (_pin.IMAGE_DIGEST, "registry-manifest", ""))
    monkeypatch.setattr(M, "image_version", lambda ref: ("0.3.47", "registry-label", ""))
    j = M.judged_image(env={}, allow_pull=True)
    assert j.ref == f"{M.IMAGE_REPO}@{_pin.IMAGE_DIGEST}"
    assert j.source == "registry"


def test_a_FLOATING_override_is_PINNED_rather_than_passed_through(monkeypatch):
    """A behaviour change worth locking down. The anchor honoured
    `VIBEIC_EDA_IMAGE=…:latest` verbatim and printed a warning that the gate could
    now move under the operator. Resolving it to a digest is strictly better: the
    operator still chose that image, and the verdict recorded against it names
    bytes rather than a name somebody can re-point tomorrow.

    The WARNING was the old design's apology for not being able to do this."""
    monkeypatch.setattr(M, "local_digest",
                        lambda ref: ("sha256:" + "7" * 64, "repo-digest", ""))
    monkeypatch.setattr(M, "image_version", lambda ref: ("2026.06", "local-label", ""))
    j = M.judged_image(env={"VIBEIC_EDA_IMAGE": f"{M.IMAGE_REPO}:latest"})
    assert j.source == "override"
    assert j.ref == f"{M.IMAGE_REPO}@sha256:{'7' * 64}"
    assert ":latest" not in j.ref


def test_an_override_that_cannot_be_identified_is_a_REFUSAL_not_a_guess(monkeypatch):
    """An operator naming an image is a deliberate call, and it still has to be
    an image that can be named again. Passing it through unpinned would put a
    verdict in the report that nobody can reproduce."""
    monkeypatch.setattr(M, "local_digest", lambda ref: (None, "", "not present"))
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: None)
    j = M.judged_image(env={"VIBEIC_EDA_IMAGE": "example.invalid/nope:1.2.3"})
    assert j.ref is None and j.source == "override"
    assert "not reproducible" in j.why_not


# ── 4b. the digest ──────────────────────────────────────────────────────────

def test_local_digest_prefers_the_repo_digest_over_the_image_id(monkeypatch):
    """A RepoDigest is what the registry would also call this image, so a verdict
    recorded against it can be replayed on another host. An `.Id` cannot leave
    this machine, so it is the fallback and it is LABELLED as one."""
    payload = ('["ghcr.io/vibeic/vibeic-eda@sha256:' + "e" * 64 + '"]'
               "\tsha256:" + "f" * 64)
    monkeypatch.setattr(M, "_run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": payload})())
    assert M.local_digest(f"{M.IMAGE_REPO}:0.3.13") == (
        "sha256:" + "e" * 64, "repo-digest", "")


def test_an_image_with_no_repo_digest_falls_back_to_its_id_and_says_so(monkeypatch):
    monkeypatch.setattr(M, "_run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": "[]\tsha256:" + "f" * 64})())
    digest, kind, why = M.local_digest("locally/built:thing")
    assert (digest, kind) == ("sha256:" + "f" * 64, "image-id"), why


def test_an_absent_image_is_a_REASON_not_a_silent_None(monkeypatch):
    monkeypatch.setattr(M, "_run", lambda *a, **k: type(
        "R", (), {"returncode": 1, "stdout": ""})())
    digest, kind, why = M.local_digest(f"{M.IMAGE_REPO}:0.9.9")
    assert digest is None and "not present on this host" in why


def test_a_reference_that_is_already_a_digest_is_taken_as_given(monkeypatch):
    monkeypatch.setattr(M, "_run",
                        lambda *a, **k: pytest.fail("asked docker about a digest"))
    ref = f"{M.IMAGE_REPO}@sha256:{'b' * 64}"
    assert M.image_digest(ref) == ("sha256:" + "b" * 64, "given", "")


# ── 4c. the version label ───────────────────────────────────────────────────

def test_the_version_label_is_believed_verbatim(monkeypatch):
    """NO SHAPE CHECK, DELIBERATELY, AND THIS TEST IS WHY THERE IS NONE.

    Published images today inherit upstream iic-osic-tools' `2026.06`; from
    vibeic-eda 0.3.19 the label is the fork's own `0.3.19`. A `^\\d+\\.\\d+\\.\\d+$`
    guard to tell "ours" from "inherited" would be correct for one release window
    and dead code that still has to be maintained for ever after. Read the label,
    believe the label — and if a future reader adds the guard, this fails.
    """
    for said in ("2026.06", "0.3.19", "0.3.19-rc1", "anything-at-all"):
        monkeypatch.setattr(M, "_run", lambda *a, _s=said, **k: type(
            "R", (), {"returncode": 0, "stdout": _s + "\n"})())
        assert M.local_version_label("x") == (said, "")


@pytest.mark.parametrize("said", ["", "<no value>"])
def test_an_image_that_does_not_say_is_not_a_version(monkeypatch, said):
    """Go's template prints `<no value>` for a missing key. An ABSENT label and a
    label reading the empty string are both "the image does not say", and neither
    may reach a report as a version."""
    monkeypatch.setattr(M, "_run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": said})())
    version, why = M.local_version_label("x")
    assert version is None and M.VERSION_LABEL in why


def test_the_registry_reader_builds_the_documented_buildx_call(monkeypatch):
    """The buildx path CANNOT be executed on this host — there is no buildx here
    (docker 29.1.3, plugin dir holds only docker-compose and docker-trust), so
    every real run of it on 8HD-9 returns "unknown command". That is exactly why
    it is exercised here against a captured argv: an unrunnable branch nobody has
    ever seen execute is a branch that is wrong the first time it matters.

    Asserted on the COMMAND, not on a mocked answer — the thing that can be wrong
    is the invocation, and `--format` on the wrong subcommand is how it fails.
    """
    seen = {}

    class _R:
        returncode = 0
        stdout = "0.3.19\n"
        stderr = ""

    def _capture(*argv, **kw):
        seen["argv"] = list(argv)
        return _R()

    monkeypatch.setattr(M, "_run", _capture)
    ref = f"{M.IMAGE_REPO}@sha256:{'e' * 64}"
    assert M.registry_version_label(ref) == ("0.3.19", "")
    argv = seen["argv"]
    assert argv[:4] == ["docker", "buildx", "imagetools", "inspect"], argv
    assert ref in argv, argv                        # a DIGEST is accepted here
    assert "--format" in argv, argv
    assert M.VERSION_LABEL in argv[argv.index("--format") + 1], argv


def test_a_registry_reader_that_cannot_run_says_WHY(monkeypatch):
    """The measured case on this host. It must produce a REASON, not an
    exception and not a silent None — `unidentified_reason` prints it."""
    class _R:
        returncode = 125
        stdout = ""
        stderr = "docker: unknown command: docker buildx\n"
    monkeypatch.setattr(M, "_run", lambda *a, **k: _R())
    version, why = M.registry_version_label("x")
    assert version is None
    assert "unknown command" in why and "rc=125" in why, why


def test_the_label_is_read_locally_before_the_registry(monkeypatch):
    """buildx is a CLI PLUGIN and is not always installed: measured 2026-08-21 on
    8HD-9, `docker buildx version` is "unknown command" on docker 29.1.3 with
    only docker-compose and docker-trust in the plugin directory. A reader that
    only knew buildx would report NOT_MEASURED on every run of this host."""
    monkeypatch.setattr(M, "local_version_label", lambda ref: ("2026.06", ""))
    monkeypatch.setattr(M, "registry_version_label",
                        lambda ref: pytest.fail("went to the registry with a "
                                                "local answer in hand"))
    assert M.image_version("x") == ("2026.06", "local-label", "")


def test_the_registry_answers_for_an_image_this_host_does_not_hold(monkeypatch):
    monkeypatch.setattr(M, "local_version_label", lambda ref: (None, "not present"))
    monkeypatch.setattr(M, "registry_version_label", lambda ref: ("0.3.19", ""))
    assert M.image_version("x") == ("0.3.19", "registry-label", "")


def test_neither_path_answering_carries_BOTH_reasons(monkeypatch):
    """"I could not read it" must say which attempts failed and how. A bare None
    here becomes "no version" one layer up, which is a different claim."""
    monkeypatch.setattr(M, "local_version_label", lambda ref: (None, "not present"))
    monkeypatch.setattr(M, "registry_version_label",
                        lambda ref: (None, "no buildx"))
    version, source, why = M.image_version("x")
    assert version is None and source == ""
    assert "not present" in why and "no buildx" in why


# ── 4d. a report that cannot name its image is not a report ─────────────────

_GOOD = M.JudgedImage(f"{M.IMAGE_REPO}@sha256:{'a' * 64}", "sha256:" + "a" * 64,
                      "repo-digest", "local", "", "2026.06", "local-label", "")


def test_a_complete_identity_writes_both_facts():
    body = M.verdict_report("prog", _GOOD, {"findings": []})
    assert body["image_digest"] == "sha256:" + "a" * 64
    assert body["image_version"] == "2026.06"
    assert body["image_version_source"] == "local-label"


@pytest.mark.parametrize("missing,expect", [
    ({"digest": None}, "no usable digest"),
    ({"ref": None, "why_not": "nothing here"}, "nothing here"),
    ({"version": None, "version_why_not": "no label"}, "would not say which version"),
])
def test_a_report_that_cannot_name_its_image_is_REFUSED(missing, expect):
    """Not warned about — refused. A finding that says "these two STA engines
    disagree" without saying which bytes were read can be neither replayed nor
    attributed, and the reader cannot tell a regressed image from a regressed
    change. That is the whole property the deleted anchor stood in for, so it is
    enforced in one place rather than remembered by each caller."""
    with pytest.raises(M.UnidentifiedImage) as exc:
        M.verdict_report("prog", _GOOD._replace(**missing), {})
    assert expect in str(exc.value)


# ── 5. the four fixture kinds, end to end, against a CONTROLLED image ───────
#
# WHY A FAKE `docker` AND NOT A MOCK. These four arms have to exercise the real
# programs: their argv construction, their output parsing, their exit codes and
# the report they write. Monkeypatching `_probe` or `stage_from_image` would
# prove the code under test with the code under test removed.
#
# So the FIXTURE is the image, delivered the only way these programs can see one
# — a `docker` on PATH that answers. Every arm below runs the real program as a
# subprocess with nothing patched. The arms differ only in what that image says
# about itself, which is exactly the variable each arm is about.
#
# And it means the arms run on a host with no image and no network, which the
# arms that need a REAL image (`test_..._on_the_real_image`, further down) cannot.

#: Written with an ABSOLUTE interpreter on the shebang, not `/usr/bin/env
#: python3`: these arms hand the child a PATH containing ONE directory, so
#: `/usr/bin/env python3` would search that directory and fail. Measured — the
#: first cut of this fixture failed every arm with "no image present on this
#: host", which is what a `docker` that cannot start looks like from up here.
_FAKE_DOCKER = r'''#!__PYTHON__
"""A `docker` that answers for one image, configured by environment."""
import json, os, re, sys

A = sys.argv[1:]
DIGEST = os.environ["FAKE_DIGEST"]
LABEL = os.environ["FAKE_LABEL"]          # "" means the label is absent
STA_HAS = os.environ.get("FAKE_STA_HAS", "1") == "1"
STA_SLACK = os.environ.get("FAKE_STA_SLACK", "8.738484850")
LEF = os.environ.get("FAKE_LEF", "")


def out(s):
    sys.stdout.write(s if s.endswith("\n") else s + "\n")
    raise SystemExit(0)


if A[:2] == ["image", "inspect"]:
    fmt = A[A.index("--format") + 1] if "--format" in A else ""
    if "RepoDigests" in fmt:
        # The repository half is DEPLOYMENT CONFIGURATION, so the fixture reads
        # it the same way the code under test does. A literal here would make
        # every arm fail on a host that reaches the same bytes elsewhere.
        repo = os.environ.get("VIBEIC_EDA_IMAGE_REPO") or "ghcr.io/vibeic/vibeic-eda"
        out(json.dumps([repo + "@" + DIGEST]) + "\t" + DIGEST)
    if "Config.Labels" in fmt:
        out(LABEL if LABEL else "<no value>")
    out(DIGEST)

if A[:1] == ["images"]:
    out("0.9.9")

if A[:1] == ["run"]:
    entry = A[A.index("--entrypoint") + 1] if "--entrypoint" in A else ""
    host = ""
    for i, a in enumerate(A):
        if a == "-v" and ":/w" in A[i + 1]:
            host = A[i + 1].split(":/w")[0]
    if entry == "bash":
        # the tech-LEF copy-out `pdk_via_patch...stage_from_image` performs
        if not LEF:
            out("")
        out("###LEF /foss/pdks/fake/techlef/fake.tlef\n" + open(LEF).read())
    script = A[-1]
    body = ""
    if host and script.startswith("/w/"):
        body = open(os.path.join(host, os.path.basename(script))).read()
    if "EQ_MAX" in body:
        slack = STA_SLACK if entry == "sta" else "8.738484850"
        out("EQ_MAX %s\nEQ_MIN 0.337911181" % slack)
    m = re.search(r"set cmds \{([^}]*)\}", body)
    cmds = (m.group(1).split() if m else [])
    have = STA_HAS or entry != "sta"
    out("\n".join(("HAVE " if have else "MISS ") + c for c in cmds))

sys.exit(0)
'''

#: A tech LEF whose one via patch is EXACTLY its layer's declared minimum. The
#: negative arm narrows the patch and nothing else, so the finding it produces
#: cannot come from anywhere but the mutation.
_LEF_CLEAN = """LAYER met5
  TYPE ROUTING ;
  WIDTH 1.6 ;
END met5

VIA M4M5_PR DEFAULT
  LAYER met5 ;
  RECT -0.8 -0.8 0.8 0.8 ;
END M4M5_PR
"""
_LEF_NARROW = _LEF_CLEAN.replace("RECT -0.8 -0.8 0.8 0.8 ;",
                                 "RECT -0.71 -0.71 0.71 0.71 ;")

#: THE FIXTURE IMAGE IS THE PINNED IMAGE, and it has to be.
#:
#: This was an arbitrary digest, which worked while `judged_image()` took
#: whatever the newest local tag resolved to. It resolves the PIN now — the
#: fleet-wide defect that change fixed was a gate judging a 0.3.16 tag while the
#: operator believed it had pinned 0.3.47 — so a fake image wearing some other
#: digest is exactly what the gate must now refuse, and these arms would be
#: testing the refusal instead of the four fixture kinds they are about.
#:
#: The arms vary the LABEL, the STA answers and the tech LEF. The digest was
#: never the variable, and binding it to the pin keeps it from becoming one.
_FIXTURE_DIGEST = _pin.IMAGE_DIGEST
_FIXTURE_LABEL = "0.3.19"


def _stage(tmp_path, *, label=_FIXTURE_LABEL, sta_has=True,
           sta_slack="8.738484850", lef=_LEF_CLEAN, programs=None, with_docker=True):
    """`(programs_dir, env)` for one arm."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if with_docker:
        fake = bindir / "docker"
        fake.write_text(_FAKE_DOCKER.replace("__PYTHON__", sys.executable),
                        encoding="utf-8")
        fake.chmod(0o755)
    leffile = tmp_path / "fake.tlef"
    leffile.write_text(lef, encoding="utf-8")
    env = {
        "PATH": str(bindir), "HOME": os.environ.get("HOME", str(tmp_path)),
        "FAKE_DIGEST": _FIXTURE_DIGEST, "FAKE_LABEL": label,
        "FAKE_STA_HAS": "1" if sta_has else "0",
        "FAKE_STA_SLACK": sta_slack, "FAKE_LEF": str(leffile),
    }
    return (programs or _PROGRAMS), env


def _run_gate(prog, argv, tmp_path, **kw):
    programs, env = _stage(tmp_path, **kw)
    r = _pr.run([sys.executable, str(pathlib.Path(programs) / prog), *argv],
                       capture_output=True, text=True, env=env)
    return r


@pytest.fixture(autouse=True, scope="module")
def _the_fake_docker_is_the_only_docker():
    """The arms below are only meaningful if the real docker is unreachable from
    them. `PATH=<one dir>` is asserted, not assumed: a stray `docker` elsewhere
    would make every arm silently measure this host's real image instead of the
    fixture, and the arms would still pass."""
    probe = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "_jd_no_such_dir"
    assert shutil.which("docker", path=str(probe)) is None


# ---- POSITIVE: the digest resolves, a verdict is computed, both are recorded

def test_POSITIVE_sta_parity_records_the_digest_and_the_version(tmp_path):
    out = tmp_path / "sta.json"
    r = _run_gate("sta_engine_parity_check.py", ["--json", str(out)], tmp_path)
    assert r.returncode == 0, r.stderr[-600:]
    rep = json.loads(out.read_text())
    assert rep["image_digest"] == _FIXTURE_DIGEST
    assert rep["image_version"] == _FIXTURE_LABEL
    assert rep["image"].endswith("@" + _FIXTURE_DIGEST)
    # NOT VACUOUS: the run has to have probed something and compared something.
    # A gate that returns 0 having looked at zero commands is the shape this
    # whole program exists to reject, and it would pass every assertion above.
    assert rep["probed"] == 10 and rep["openroad_present"] == 10
    assert rep["equivalent"] is True and len(rep["equivalence"]) == 2


def test_POSITIVE_via_patch_records_the_digest_and_the_version(tmp_path):
    out = tmp_path / "via.json"
    r = _run_gate("pdk_via_patch_meets_layer_min_width_check.py",
                  ["--from-image", "--json", str(out)], tmp_path)
    assert r.returncode == 0, r.stderr[-600:] + r.stdout[-600:]
    rep = json.loads(out.read_text())
    assert rep["image_digest"] == _FIXTURE_DIGEST
    assert rep["image_version"] == _FIXTURE_LABEL
    assert rep["verdict"] == "PASS"
    assert len(rep["tech_lefs_checked"]) == 1, rep["tech_lefs_checked"]


# ---- NEGATIVE: a genuinely bad image, and the ONLY change is the image

def test_NEGATIVE_a_divergent_sta_engine_is_a_FINDING_not_a_pass(tmp_path):
    """Same program, same argv, same fixture — one thing differs: in this image
    the standalone `sta` does not carry the superset commands. That is
    vibeic-eda#8's actual defect, and it must be rc 1."""
    out = tmp_path / "sta.json"
    r = _run_gate("sta_engine_parity_check.py", ["--json", str(out)], tmp_path,
                  sta_has=False)
    assert r.returncode == 1, (r.returncode, r.stderr[-600:])
    rep = json.loads(out.read_text())
    assert rep["only_openroad"] and not rep["only_sta"]
    assert rep["sta_present"] == 0 and rep["openroad_present"] == 10
    # the red has to be attributable to the IMAGE, by name, in the failure text
    assert _FIXTURE_DIGEST in r.stderr
    assert "not about the change under test" in r.stderr


def test_NEGATIVE_two_engines_that_disagree_on_TIMING_is_also_a_finding(tmp_path):
    """Command PRESENCE is not equivalence — vibeic-eda#8 measured 20/20 names
    matching while one of them behaved differently. Every name matches here."""
    r = _run_gate("sta_engine_parity_check.py", [], tmp_path,
                  sta_slack="7.000000000")
    assert r.returncode == 1, (r.returncode, r.stderr[-600:])
    assert "DIFFERENT timing" in r.stderr


def test_NEGATIVE_a_narrow_via_patch_in_the_image_is_a_FINDING(tmp_path):
    out = tmp_path / "via.json"
    r = _run_gate("pdk_via_patch_meets_layer_min_width_check.py",
                  ["--from-image", "--json", str(out)], tmp_path,
                  lef=_LEF_NARROW)
    assert r.returncode == 1, (r.returncode, r.stdout[-600:])
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL" and len(rep["open_findings"]) == 1
    f = rep["open_findings"][0]
    assert (f["patch_x_um"], f["layer_min_width_um"]) == (1.42, 1.6)
    assert rep["image_digest"] == _FIXTURE_DIGEST      # a FINDING names its image
    assert _FIXTURE_DIGEST in r.stdout


# ---- VACUOUS: no docker -> rc 2 with the marker, and NOT rc 0 and NOT rc 1

@pytest.mark.parametrize("prog,argv,marker", [
    ("sta_engine_parity_check.py", [], "[CANNOT CHECK]"),
    ("pdk_via_patch_meets_layer_min_width_check.py", ["--from-image"], "[REFUSE]"),
])
def test_VACUOUS_no_docker_is_rc2_with_the_marker(prog, argv, marker, tmp_path):
    """v1.11.8's behaviour, which must not regress. rc 1 means a FINDING ABOUT
    SILICON — "the STA engines disagree", "a via patch is narrower than its
    layer's minimum" — and a run that never opened an image has found neither.
    rc 0 is the other direction of the same defect.

    "I could not read it" and "I read it and it was bad" must never produce the
    same verdict, and of the two directions this one is worse: it invents a
    finding."""
    r = _run_gate(prog, argv, tmp_path, with_docker=False)
    assert r.returncode == 2, (
        f"{prog} answered rc={r.returncode} with no docker at all. 2 is its word "
        f"for 'nothing was measured'; 1 is a finding about the design and 0 is a "
        f"clean bill. stderr: {r.stderr[-400:]}")
    assert marker in r.stderr, r.stderr[-400:]
    assert "Nothing was measured" in r.stderr


@pytest.mark.parametrize("prog,argv,marker", [
    ("sta_engine_parity_check.py", [], "[CANNOT CHECK]"),
    ("pdk_via_patch_meets_layer_min_width_check.py", ["--from-image"], "[REFUSE]"),
])
def test_VACUOUS_an_image_that_will_not_say_its_version_is_rc2(
        prog, argv, marker, tmp_path):
    """The other half of NOT_MEASURED, and the one the OCI-label mechanism adds.
    docker answers, the digest resolves, the image runs — and it carries no
    `org.opencontainers.image.version`. The version is not guessed from a tag and
    not inferred: the gate says it could not establish which release it looked
    at, and returns its own not-measured code."""
    r = _run_gate(prog, argv, tmp_path, label="")
    assert r.returncode == 2, (r.returncode, r.stderr[-400:])
    assert marker in r.stderr
    assert M.VERSION_LABEL in r.stderr or "would not say which version" in r.stderr


# ---- MUTATION: remove the digest-recording and a test fails BY NAME

_MUTATIONS = {
    "drop the digest from the report":
        ('"image_digest": self.digest,', '"image_digest": None,'),
    "drop the version from the report":
        ('"image_version": self.version,', '"image_version": None,'),
    "stop refusing an image that will not say its version":
        ('    if not judged.version:', '    if False:'),
}


@pytest.mark.parametrize("what", sorted(_MUTATIONS))
def test_MUTATION_breaking_the_recording_is_CAUGHT_BY_NAME(what, tmp_path):
    """A guard nobody has watched fail is a guard nobody knows is connected.

    Each mutation below removes one thing this change added, in a copy of
    `programs/`, and re-runs the arm above that is supposed to notice. The test
    fails if the arm still passes — i.e. if the assertion it is named after was
    decorative.

    MEASURED, not asserted: the previous version of this file had a guard that
    bit on a test that was itself vacuous, so the guard proved nothing. The arms
    re-run here are the POSITIVE and VACUOUS ones above, whose own assertions
    already pin `probed == 10` and `tech_lefs_checked == 1`, so the mutated run
    cannot pass by measuring nothing.
    """
    staged = tmp_path / "programs"
    shutil.copytree(_PROGRAMS, staged,
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    src = (staged / "_eda_image.py").read_text(encoding="utf-8")
    old, new = _MUTATIONS[what]
    assert src.count(old) == 1, (
        f"the mutation {what!r} no longer matches _eda_image.py, so this guard "
        f"is testing nothing. Update it or delete it.")
    (staged / "_eda_image.py").write_text(src.replace(old, new), encoding="utf-8")

    if what.startswith("stop refusing"):
        r = _run_gate("sta_engine_parity_check.py", [], tmp_path,
                      label="", programs=staged)
        assert r.returncode != 2, (
            "the mutation did not change behaviour, so the refusal it removes "
            "was not the thing producing rc 2")
        return

    out = tmp_path / "m.json"
    r = _run_gate("sta_engine_parity_check.py", ["--json", str(out)], tmp_path,
                  programs=staged)
    assert r.returncode == 0, r.stderr[-400:]
    rep = json.loads(out.read_text())
    field = "image_digest" if "digest" in what else "image_version"
    assert rep[field] is None, (
        f"{what}: the mutation did not take effect, so this guard proves "
        f"nothing about test_POSITIVE_sta_parity_records_the_digest_and_the_version")


# ---- and the same two gates against the REAL image, when this host has one

def _real_image():
    j = M.judged_image()
    return j if j.ref and not M.unidentified_reason(j) else None


# THE SENTINEL, BUILT BY THE TIER INSTEAD OF TYPED OUT.
#
# This reason was already the right SENTENCE — it opened with the sentinel and it
# named a remedy — and it was still invisible to the machinery that reads the
# tier, because that machinery looks for a call to a reason BUILDER, not for a
# string that happens to start with the same eleven characters. So
# `test_not_verified_tier::test_no_new_undeclared_infrastructure_skip_appears`
# counted this file as a NEW undeclared infrastructure-absent skip, which is
# exactly the report it should give for a hand-typed stamp: a copied prefix is
# what the tier looks like right up until somebody copies it slightly wrong.
# `not_verified_reason` composes the identical text from the same constants the
# roll-up reads.
@pytest.mark.skipif(
    _real_image() is None,
    reason=NV.not_verified_reason(
        "no identifiable vibeic-eda image on this host",
        remedy="docker pull ghcr.io/vibeic/vibeic-eda:latest"))
def test_the_real_image_resolves_to_a_digest_and_names_its_own_version():
    """The fixture arms prove the PROGRAMS behave; this proves the RESOLVER meets
    a real registry-published image. Skipped, never faked, when the host has
    none — and it says so under the NOT_VERIFIED tier rather than passing."""
    j = _real_image()
    assert M.DIGEST_RE.match(j.digest), j
    assert j.ref.endswith("@" + j.digest)
    assert j.version, j.version_why_not
    assert j.version_source in ("local-label", "registry-label")
