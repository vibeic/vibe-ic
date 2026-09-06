"""The RUN path reads the pin, and a run never attaches to another run's container.

TWO DEFECTS, BOTH MEASURED ON 8hd-3 ON 2026-09-07, both against the frozen base
`4fc47b3ef9f9` with `VIBEIC_EDA_IMAGE_REPO` exported and the pinned 0.3.47 image
(`sha256:8da785a8…`) pulled and present.

F1 — THE RUN PATH NEVER READ THE PIN.  `_eda_image` hardcoded its repository and
resolved by LOCAL SEMVER TAG, so on that host::

    judged_image().ref  = ghcr.io/vibeic/vibeic-eda@sha256:f6b09c13…   (0.3.16)
    judged_image().version = 2026.06
    resolve()           = ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…   (0.3.46)

Three different images in one paragraph, none of them the pin, and the gate path
and the run path disagreeing with each other in the same minute on the same host.
`VIBEIC_EDA_IMAGE_REPO` was read by exactly ONE shipped file and by nothing that
runs a tool.  The report named a digest, so it read as reproducible; it was
reproducibly about the wrong toolchain.

F2 — A CONTAINER NAME IS NOT A CONTAINER IDENTITY.  Every `--container` defaulted
to the shared literal `vibeic-eda`.  The container actually holding that name on
8hd-3 was running `sha256:06537f7e…` (0.3.46).  `run_in_container` executed in it
and returned rc=0 with an empty stderr and `describe_result() is None` — image
provenance PASS about the wrong image.

WHAT EACH TEST HERE WOULD MISS IF IT WERE WRITTEN LAZILY is stated on the test.
Every one of them was run in BOTH directions: the assertions below are the ones
that went red against the pre-fix files swapped in by `git show <base>:<path>`,
and green after.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _container_exec as CE  # noqa: E402
import _designs_root as DR  # noqa: E402
import _eda_image as EI  # noqa: E402
import _eda_pin as P  # noqa: E402

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
#: A pinned VERSION — the shape `_eda_image`'s own guards forbid in a shipped
#: program, and the shape this change must not reintroduce while adding a digest.
_PINNED_VERSION = re.compile(r"vibeic-eda:\d+\.\d+\.\d+")


# ── 1. one config point, and it is the same one the landing sites use ────────

def _repo_root() -> pathlib.Path:
    here = _PROGRAMS
    for parent in [here, *here.parents]:
        if (parent / "tools" / "ci" / "hermetic_candidate_runner.py").exists():
            return parent
    pytest.skip("not run from a full checkout; tools/ci is not present")


def _runner_pin() -> dict:
    """The canonical pin, READ from `tools/ci/hermetic_candidate_runner.py`.

    Read by AST rather than copied, for the same reason
    `tools/ci/test_run_suite_in_eda_image.py` reads it that way: a second copy
    of a pinned value is a second definition of it, and that is exactly how the
    harness came to name an image forty patch releases behind the pin.
    """
    src = (_repo_root() / "tools" / "ci"
           / "hermetic_candidate_runner.py").read_text(encoding="utf-8")
    found = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                name = getattr(t, "id", "")
                if name in ("IMAGE_DIGEST", "IMAGE_REPO_DEFAULT", "IMAGE_REPO_ENV") \
                        and name not in found:
                    found[name] = ast.literal_eval(node.value)
    return found


def test_the_plugin_pin_is_the_same_pin_the_landing_runner_uses():
    """The drift test. Two halves of one statement, in two trees that cannot
    import each other — so the binding has to be a test or it is nothing."""
    runner = _runner_pin()
    assert runner.get("IMAGE_DIGEST") == P.IMAGE_DIGEST, (
        "tools/ci/hermetic_candidate_runner.py and programs/_eda_pin.py pin "
        "different runtimes")
    assert runner.get("IMAGE_REPO_DEFAULT") == P.IMAGE_REPO_DEFAULT
    assert runner.get("IMAGE_REPO_ENV") == P.IMAGE_REPO_ENV


def test_the_digest_is_a_digest_and_the_repository_is_configuration():
    assert _DIGEST.match(P.IMAGE_DIGEST), P.IMAGE_DIGEST
    assert P.image_repo({}) == P.IMAGE_REPO_DEFAULT
    assert P.image_repo({"VIBEIC_EDA_IMAGE_REPO": "reg.example/eda"}) == "reg.example/eda"
    # the env moves the PLACE, never the BYTES
    assert P.image_reference({"VIBEIC_EDA_IMAGE_REPO": "reg.example/eda"}) == \
        f"reg.example/eda@{P.IMAGE_DIGEST}"
    assert P.image_reference({}) == f"{P.IMAGE_REPO_DEFAULT}@{P.IMAGE_DIGEST}"


def test_the_pin_is_a_digest_and_never_a_version_literal():
    """A digest is the bytes; a version is a name its publisher can re-point.
    `_eda_image`'s guards forbid the second, and this change must stay on the
    right side of that line while adding the first."""
    for rel in ("_eda_pin.py", "_eda_image.py", "_designs_root.py",
                "_container_exec.py", "landing_pytest_runtime_preflight.py"):
        src = (_PROGRAMS / rel).read_text(encoding="utf-8")
        code = re.sub(r'"""(?:.|\n)*?"""', "",
                      "\n".join(l for l in src.splitlines()
                                if not l.lstrip().startswith("#")))
        assert not _PINNED_VERSION.search(code), f"{rel} pins a VERSION"


def test_no_shipped_program_keeps_a_second_copy_of_the_digest():
    """THE PROPERTY THAT DECAYS SILENTLY. A second literal does not fail — it
    sits there being right, until the pin moves and it is the only thing that
    did not."""
    offenders = []
    body = P.IMAGE_DIGEST.split(":", 1)[1]
    for path in sorted(_PROGRAMS.rglob("*.py")):
        if "tests" in path.relative_to(_PROGRAMS).parts:
            continue
        if path.name == "_eda_pin.py":
            continue                      # the one place it is allowed to be
        if body in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(path.relative_to(_PROGRAMS).as_posix())
    assert not offenders, (
        f"these programs spell the pinned digest instead of reading "
        f"_eda_pin.IMAGE_DIGEST: {offenders}")


def test_the_landing_preflight_reads_the_pin_rather_than_spelling_it():
    import landing_pytest_runtime_preflight as LP
    assert LP.RUNNER_IMAGE == P.image_reference()
    assert "@sha256:" in LP.RUNNER_IMAGE


# ── 2. judged_image resolves by DIGEST, never by local tag ───────────────────

def test_judged_image_takes_the_pinned_digest_not_the_newest_local_tag(monkeypatch):
    """F1, stated as the assertion that went red on the pre-fix file.

    The pre-fix rung asked `local_tags()` and took `[0]`. That is stubbed here
    to a tag that is NOT the pin: if the answer ever comes back carrying it, the
    tag ladder is back.
    """
    monkeypatch.setattr(EI, "local_tags", lambda *a, **k: ["9.9.9"])
    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (P.image_reference(env), ""))
    monkeypatch.setattr(EI, "image_version",
                        lambda ref: ("0.3.47", "local-label", ""))
    j = EI.judged_image(env={})
    assert j.digest == P.IMAGE_DIGEST
    assert j.ref == P.image_reference({})
    assert j.source == "pinned"
    assert "9.9.9" not in (j.ref or "")


def test_a_host_without_the_pinned_bytes_REFUSES_BY_NAME(monkeypatch):
    """"I could not open the pinned image" and "I opened one" are different
    answers. The refusal names the reference so the operator can pull it."""
    monkeypatch.setattr(EI, "local_tags", lambda *a, **k: ["0.3.16", "0.3.13"])
    monkeypatch.setattr(
        P, "pinned_image_present",
        lambda env=None: (None, f"{P.IMAGE_NOT_PRESENT}: {P.image_reference(env)}"))
    j = EI.judged_image(env={})
    assert j.ref is None
    assert P.IMAGE_NOT_PRESENT in j.why_not
    assert P.IMAGE_DIGEST in j.why_not
    # THE HALF THAT MATTERS. A refusal is only a refusal if it did not quietly
    # answer with something else.
    assert "0.3.16" not in j.why_not and "0.3.13" not in j.why_not, (
        "the resolver fell back to a local tag instead of refusing")


def test_the_refusal_does_not_reach_for_the_upstream_image(monkeypatch):
    """The legacy upstream image carries none of the forked tools, so a verdict
    about it is a verdict about the wrong image — and it used to be the last
    rung of both ladders."""
    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    j = EI.judged_image(env={})
    assert j.ref is None
    assert EI.LEGACY_IMAGE not in (j.why_not or "")


def test_judged_image_still_makes_no_registry_call_unless_asked(monkeypatch):
    """vibe-ic#927's property, carried across the mechanism that replaced it —
    and it must survive this change too, not just the last one."""
    monkeypatch.setattr(EI, "registry_digest", lambda *a, **k: pytest.fail(
        "judged_image asked the registry without allow_pull"))
    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    j = EI.judged_image(env={})
    assert j.ref is None
    assert "does not pull" in j.why_not


def test_allow_pull_asks_about_the_PINNED_digest_not_about_latest(monkeypatch):
    """Opting into a pull is opting into fetching the bytes that were pinned. It
    must not become opting into whichever bytes are newest — which is what
    asking the registry for `latest` meant."""
    asked = []

    def _image_digest(ref, *, allow_registry=True):
        asked.append(ref)
        return P.IMAGE_DIGEST, "registry-manifest", ""

    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    monkeypatch.setattr(EI, "image_digest", _image_digest)
    monkeypatch.setattr(EI, "image_version",
                        lambda ref: ("0.3.47", "registry-label", ""))
    j = EI.judged_image(env={}, allow_pull=True)
    assert j.digest == P.IMAGE_DIGEST
    assert asked == [P.image_reference({})], asked


def test_an_explicit_override_is_still_honoured_and_still_pinned(monkeypatch):
    """Every refusal already landed stays. Naming an image by hand is the
    operator's deliberate call, and it is still resolved to a digest so the
    report can name it."""
    monkeypatch.setattr(EI, "local_digest",
                        lambda ref: ("sha256:" + "7" * 64, "repo-digest", ""))
    monkeypatch.setattr(EI, "image_version",
                        lambda ref: ("2026.06", "local-label", ""))
    j = EI.judged_image(env={"VIBEIC_EDA_IMAGE": f"{P.IMAGE_REPO_DEFAULT}:latest"})
    assert j.source == "override"
    assert ":latest" not in j.ref


def test_the_run_path_and_the_gate_path_name_the_same_bytes(monkeypatch):
    """MEASURED PRE-FIX: they did not. `judged_image()` said 0.3.16 and
    `resolve()` said 0.3.46, on one host in one minute. Whatever else changes,
    these two must not be able to disagree again."""
    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (P.image_reference(env), ""))
    monkeypatch.setattr(EI, "image_version",
                        lambda ref: ("0.3.47", "local-label", ""))
    assert EI.resolve(env={}) == EI.judged_image(env={}).ref


def test_local_image_answers_about_the_pinned_bytes_and_never_the_registry(monkeypatch):
    """`resolve()` and `local_image()` stay DIFFERENT questions — collapsing
    them turns a skip guard's local check into an unbounded fetch."""
    monkeypatch.setattr(EI, "registry_digest", lambda *a, **k: pytest.fail(
        "local_image asked the registry"))
    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    assert EI.local_image(env={}) is None
    monkeypatch.setattr(P, "pinned_image_present",
                        lambda env=None: (P.image_reference(env), ""))
    assert EI.local_image(env={}) == P.image_reference({})


def test_pinned_image_present_refuses_an_image_whose_repo_digest_differs(monkeypatch):
    """A resolved reference is not proof. If docker hands back an image whose
    RepoDigests do not contain the pinned reference, that is a refusal that
    names what was found — never a quiet acceptance."""
    monkeypatch.setattr(
        P, "local_repo_digests",
        lambda ref: (("other.example/eda@sha256:" + "b" * 64,), ""))
    ref, why = P.pinned_image_present({})
    assert ref is None
    assert P.IMAGE_NOT_PRESENT in why and "b" * 64 in why


# ── 3. a container name is not a container identity ─────────────────────────

def test_the_default_container_name_derives_from_the_pinned_digest():
    """F2's structural half. Two different pins are two different containers by
    construction, so the collision cannot be reached by default at all."""
    name = P.default_container_name({})
    assert name == "vibeic-eda-" + P.IMAGE_DIGEST.split(":", 1)[1][:12]
    assert name != "vibeic-eda", "the shared literal is back"
    assert DR.DEFAULT_CONTAINER == name


def test_an_explicit_container_name_still_moves_the_NAME_only():
    assert P.default_container_name({"VIBEIC_EDA_CONTAINER": "mine"}) == "mine"


def test_attaching_to_a_container_running_other_bytes_is_REFUSED(monkeypatch):
    """F2, stated as the assertion that went red on the pre-fix file."""
    other = "sha256:" + "0" * 64
    monkeypatch.setattr(P, "container_image_digest", lambda c: (other, ""))
    why = P.container_matches_pin("vibeic-eda", {})
    assert why.startswith(P.CONTAINER_IMAGE_MISMATCH)
    # BOTH digests, because a reader told only that something mismatched cannot
    # tell a stale container from a mis-set repository, and will re-run it.
    assert P.IMAGE_DIGEST in why and other in why
    assert "vibeic-eda" in why


def test_a_container_running_the_pinned_bytes_is_ACCEPTED(monkeypatch):
    monkeypatch.setattr(P, "container_image_digest",
                        lambda c: (P.IMAGE_DIGEST, ""))
    assert P.container_matches_pin("anything", {}) == ""


def test_an_absent_container_and_a_wrong_one_are_DIFFERENT_answers(monkeypatch):
    """"It is not there" and "it is there and it is wrong" must never reach a
    reader as the same verdict."""
    monkeypatch.setattr(
        P, "container_image_digest",
        lambda c: (None, f"{P.CONTAINER_ABSENT}: no container named {c}"))
    why = P.container_matches_pin("gone", {})
    assert P.CONTAINER_ABSENT in why
    assert P.CONTAINER_IMAGE_MISMATCH not in why


@pytest.mark.parametrize("digest,why,state", [
    (None, "no container named x", "UNREADABLE"),
    ("sha256:" + "0" * 64, "", "MISMATCH"),
    (P.IMAGE_DIGEST, "", "MATCH"),
])
def test_the_attach_check_has_THREE_states_not_two(monkeypatch, digest, why, state):
    """THE BUG THIS CHANGE SHIPPED AND THE SUITE CAUGHT.

    The first cut returned MATCH or a refusal, and folded everything else — an
    absent container, a docker that will not run, an image built locally with no
    registry digest — into the refusal. That makes "I could not read it" and "I
    read it and it was the wrong image" the same answer, which is the one thing
    this repo holds every input to. It surfaced as
    `test_hardmacro_magic_is_looked_for_where_it_runs` going red: a stand-in
    container that docker could not describe stopped a `docker exec` that had
    nothing wrong with it.
    """
    monkeypatch.setattr(P, "container_image_digest", lambda c: (digest, why))
    assert P.container_pin_state("x", {})[0] == state


def test_only_a_MEASURED_disagreement_stops_an_attach(monkeypatch):
    """The two halves want different answers, and this is the difference.

    A VERDICT may be PASS only on proof; an ATTACH may be refused only on a
    measured disagreement. Refusing an attach on UNREADABLE would turn "docker
    cannot describe this" into a claim about the image.
    """
    monkeypatch.setattr(P, "container_image_digest",
                        lambda c: (None, "no container named x"))
    assert P.container_attach_refusal("x", {}) == ""      # docker will say so
    assert P.container_matches_pin("x", {}) != ""         # but it cannot PASS

    monkeypatch.setattr(P, "container_image_digest",
                        lambda c: ("sha256:" + "0" * 64, ""))
    assert P.container_attach_refusal("x", {}) != ""      # measured: refuse
    assert P.container_matches_pin("x", {}) != ""


def test_an_unreadable_container_does_not_block_the_command(monkeypatch):
    """The regression arm, at the level the callers use."""
    ran = []
    monkeypatch.setattr(CE._pr, "run", lambda argv, **kw: ran.append(argv) or
                        subprocess.CompletedProcess(argv, 0, "ok", ""))
    monkeypatch.setattr(P, "container_image_digest",
                        lambda c: (None, "no container named eda_ctr"))
    cp = CE.run_in_container("eda_ctr", "echo hi", deadline_s=5)
    assert cp.returncode == 0 and len(ran) == 1


def test_run_in_container_REFUSES_AND_RUNS_NOTHING_on_a_mismatch(monkeypatch):
    """The load-bearing half. A check that computes a refusal and then runs the
    command anyway is not a check."""
    ran = []
    monkeypatch.setattr(CE._pr, "run",
                        lambda *a, **k: ran.append(a) or pytest.fail(
                            "the command was run in a mismatched container"))
    monkeypatch.setattr(P, "container_attach_refusal",
                        lambda c, env=None: f"{P.CONTAINER_IMAGE_MISMATCH}: bad")
    cp = CE.run_in_container("vibeic-eda", "echo hi", deadline_s=5)
    assert cp.returncode == CE.IMAGE_MISMATCH_RC
    assert ran == []
    assert P.CONTAINER_IMAGE_MISMATCH in cp.stderr
    assert cp.stdout == ""
    # a refusal is not the tool's answer, and describe_result must say so
    assert P.CONTAINER_IMAGE_MISMATCH in CE.describe_result(cp, 5)


def test_run_in_container_RUNS_when_the_container_holds_the_pinned_bytes(monkeypatch):
    """The other direction. A guard that refuses everything is a guard that gets
    deleted by the next person who trips over it."""
    seen = {}

    def _run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(CE._pr, "run", _run)
    monkeypatch.setattr(P, "container_attach_refusal", lambda c, env=None: "")
    cp = CE.run_in_container("vibeic-eda-8da785a8d327", "echo hi", deadline_s=5)
    assert cp.returncode == 0 and cp.stdout == "ok"
    assert seen["argv"] == CE.container_deadline_argv(
        "vibeic-eda-8da785a8d327", "echo hi", 5)
    assert CE.describe_result(cp, 5) is None


def test_the_refusal_rc_is_distinct_from_every_other_outcome():
    """A refusal that shares a code with an expired deadline is a refusal a
    caller cannot route."""
    codes = {CE.IMAGE_MISMATCH_RC, CE.TIMEOUT_EXPIRED_RC,
             CE.TIMEOUT_UNAVAILABLE_RC, 0}
    assert len(codes) == 4


# ── 4. every path into a container goes through the guarded builder ─────────
#
# `run_in_container` refused to attach to the wrong bytes from v1.18.18, but it
# was never the only way in: MEASURED 2026-09-07, SIXTY-FIVE argv constructions
# in THIRTY shipped files spelled `["docker", "exec", …]` by hand, and the
# guarantee held on none of them. A guard each caller must remember to call is a
# guard that decays; the guard lives in the constructor now, so there is nothing
# else to call.

_PLUGIN = _PROGRAMS.parent
_SHARED_CONTAINER_LITERAL = "vibeic-eda"


def _shipped_py():
    """Every shipped (non-test) .py under the plugin, as (rel, source).

    DERIVED FROM THE TREE. A hand-written list of "the files that do this" omits
    whatever the tree grows next, which is the whole failure mode these two
    population tests exist to close.
    """
    for path in sorted(_PLUGIN.rglob("*.py")):
        rel = path.relative_to(_PLUGIN)
        if "tests" in rel.parts or "test" in rel.parts or path.name.startswith("test_"):
            continue
        yield rel.as_posix(), path.read_text(encoding="utf-8", errors="replace")


def test_no_shipped_file_hand_builds_a_docker_exec_argv():
    """THE POPULATION TEST for item (b). Sixty-five before, one after — and the
    one is the builder itself, which has to spell the argv or nothing could."""
    offenders = []
    for rel, src in _shipped_py():
        if '"docker"' not in src or '"exec"' not in src:
            continue                              # cheap pre-filter, then AST
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 2:
                a, b = node.elts[0], node.elts[1]
                if isinstance(a, ast.Constant) and a.value == "docker" and \
                        isinstance(b, ast.Constant) and b.value == "exec":
                    offenders.append(f"{rel}:{node.lineno}")
    # The builder's own file is the ONE place the argv may be spelled: it is
    # where it is defined. Assert that positively, so an empty `offenders` --
    # which would mean the scan found nothing at all and is a broken instrument,
    # not a clean tree -- cannot read as a pass.
    assert any(o.startswith("programs/_container_exec.py") for o in offenders), (
        "the scan found no `docker exec` argv anywhere, not even the builder's "
        "own — the instrument is broken, so its zero means nothing")
    outside = [o for o in offenders if not o.startswith("programs/_container_exec.py")]
    assert not outside, (
        "these build a `docker exec` argv by hand, so the attach check does not "
        f"cover them — call _container_exec.docker_exec_argv: {outside}")


def test_no_shipped_file_names_the_shared_container_literal():
    """THE POPULATION TEST for item (a). Forty-two before, one after — and the
    one is `_eda_pin.CONTAINER_NAME_PREFIX`, which is where the name is DEFINED.

    A shared name is not an identity: whichever process got there first is
    holding it, and on 8hd-3 that was a 0.3.46 container while the pin demanded
    0.3.47."""
    offenders = []
    for rel, src in _shipped_py():
        if _SHARED_CONTAINER_LITERAL not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == _SHARED_CONTAINER_LITERAL:
                offenders.append(f"{rel}:{node.lineno}")
    # SAME EMPTY-DENOMINATOR GUARD as the sibling above, and it is here because
    # mutation N7 caught its absence: blinding the scan left THIS test green
    # while the other one went red. A scan that finds nothing has not proved the
    # tree is clean, it has proved nothing.
    assert any(o.startswith("programs/_eda_pin.py") for o in offenders), (
        "the scan found the shared literal nowhere, not even where it is "
        "DEFINED — the instrument is broken, so its zero means nothing")
    outside = [o for o in offenders if not o.startswith("programs/_eda_pin.py")]
    assert not outside, (
        "these name the shared container literal instead of deriving it from "
        f"the pin — call _eda_pin.default_container_name(): {outside}")


def test_docker_exec_argv_builds_exactly_the_argv_it_replaced(monkeypatch):
    monkeypatch.setattr(P, "container_attach_refusal", lambda c, env=None: "")
    assert CE.docker_exec_argv("c", "bash", "-lc", "echo hi") == \
        ["docker", "exec", "c", "bash", "-lc", "echo hi"]
    # flags that must PRECEDE the container are a separate parameter, so the
    # container is always an identified argument and can always be checked
    assert CE.docker_exec_argv("c", "sh", "-c", "x", opts=("-w", "/w")) == \
        ["docker", "exec", "-w", "/w", "c", "sh", "-c", "x"]


def test_docker_exec_argv_REFUSES_a_measured_mismatch(monkeypatch):
    monkeypatch.setattr(P, "container_attach_refusal",
                        lambda c, env=None: f"{P.CONTAINER_IMAGE_MISMATCH}: bad")
    with pytest.raises(CE.ContainerImageMismatch) as exc:
        CE.docker_exec_argv("c", "bash", "-lc", "echo hi")
    assert P.CONTAINER_IMAGE_MISMATCH in str(exc.value)


def test_docker_exec_argv_does_NOT_refuse_an_unreadable_digest(monkeypatch):
    """Ruling 3: an unreadable digest is NOT_MEASURED provenance. Work may
    proceed — docker reports its own failure — it simply cannot be credited."""
    monkeypatch.setattr(P, "container_image_digest",
                        lambda c: (None, "no container named c"))
    assert CE.docker_exec_argv("c", "bash", "-lc", "x")[:3] == ["docker", "exec", "c"]


def test_the_deadline_argv_is_guarded_too(monkeypatch):
    """The deadline path is a `docker exec` like any other and must not be a
    hole in the guard."""
    monkeypatch.setattr(P, "container_attach_refusal",
                        lambda c, env=None: f"{P.CONTAINER_IMAGE_MISMATCH}: bad")
    with pytest.raises(CE.ContainerImageMismatch):
        CE.container_deadline_argv("c", "echo hi", 5)


def test_the_refusal_path_RETURNS_rc_and_never_RAISES(monkeypatch):
    """A REGRESSION I WROTE AND THIS CAUGHT.

    Routing `container_deadline_argv` through the guard made `run_in_container`'s
    refusal branch ask the guard a SECOND time — from inside the very branch
    whose contract is to RETURN `IMAGE_MISMATCH_RC`. It raised instead, turning
    a landed, tested refusal into an exception its callers had never seen.
    """
    monkeypatch.setattr(P, "container_attach_refusal",
                        lambda c, env=None: f"{P.CONTAINER_IMAGE_MISMATCH}: bad")
    cp = CE.run_in_container("c", "echo hi", deadline_s=5)
    assert cp.returncode == CE.IMAGE_MISMATCH_RC
    assert cp.args[:3] == ["docker", "exec", "c"]
    assert P.CONTAINER_IMAGE_MISMATCH in cp.stderr


# ── 5. the pin has FOUR copies and they are all bound ───────────────────────

def test_every_copy_of_the_pinned_digest_is_bound_to_every_other():
    """THE QUESTION I GOT WRONG, answered in one place.

    I reported `tools/ci/protected_landing_transition.py` as an UNBOUND third
    copy of the digest. It was not: `test_manifest_and_runtime_use_one_exact_
    base_owned_image` had bound it to the runner and to the manifest all along.
    The chain is a star around `hermetic_candidate_runner.IMAGE_DIGEST`, and a
    reader should not have to reconstruct it from two files to see that.
    """
    repo = _repo_root()
    runner = _runner_pin()["IMAGE_DIGEST"]
    copies = {"tools/ci/hermetic_candidate_runner.py": runner,
              "programs/_eda_pin.py": P.IMAGE_DIGEST}

    plt = (repo / "tools/ci/protected_landing_transition.py").read_text(
        encoding="utf-8")
    m = re.search(r'"@(sha256:[0-9a-f]{64})"', plt)
    assert m, "protected_landing_transition.py names no digest"
    copies["tools/ci/protected_landing_transition.py"] = m.group(1)

    manifest = json.loads(
        (repo / "tools/ci/protected_landing_transition.json").read_text(
            encoding="utf-8"))
    image = manifest.get("runner", {}).get("image", "")
    assert "@" in image, f"manifest runner image is not digest-pinned: {image!r}"
    copies["tools/ci/protected_landing_transition.json"] = image.split("@", 1)[1]

    assert len(set(copies.values())) == 1, (
        f"the pinned digest has drifted between its copies: {copies}")


# ── 6. the route and the argv are two decisions, composed ───────────────────

def _phase3():
    import importlib
    return importlib.import_module("phase3_one_shot_runner")


def test_the_route_seam_and_the_argv_builder_compose(monkeypatch):
    """TWO LANDINGS, TWO QUESTIONS, ONE CALL — and neither answers the other's.

    v1.18.20 (lane czsubdock) taught `phase3_one_shot_runner._exec_argv` to
    decide WHERE a tool runs: in this image when there is no docker client, in a
    container otherwise. This lane's `_container_exec.docker_exec_argv` decides
    HOW a container is addressed — which bytes it must hold. They met in the
    same three lines and they compose: the seam picks the route, and the
    container branch hands the argv to the one constructor that carries the
    attach check.

    LOCAL MODE REACHES NO CHECK, deliberately. Nothing is being attached to
    there, so there is no container whose image could be wrong; asking would be
    inventing a question the route does not raise.
    """
    R = _phase3()
    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", True)
    assert R._exec_argv("anything", "yosys -V") == ["bash", "-lc", "yosys -V"]

    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", False)
    monkeypatch.setattr(P, "container_attach_refusal", lambda c, env=None: "")
    # the container argv is UNCHANGED from what v1.18.27 built inline, flag
    # placement included — `opts` go between `exec` and the container
    assert R._exec_argv("c", "yosys -V") == [
        "docker", "exec", "-e", "IIC_OSIC_TOOLS_QUIET=1", "c",
        "bash", "-lc", "yosys -V"]


def test_the_route_seam_still_REFUSES_the_wrong_image(monkeypatch):
    """The half that would be lost if the seam ever rebuilt the argv itself."""
    R = _phase3()
    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", False)
    monkeypatch.setattr(P, "container_attach_refusal",
                        lambda c, env=None: f"{P.CONTAINER_IMAGE_MISMATCH}: bad")
    with pytest.raises(CE.ContainerImageMismatch):
        R._exec_argv("someone-elses-container", "yosys -V")


def test_phase3_imports_the_container_helper_under_ONE_alias():
    """One module, one name. The rebase briefly carried both `_cex` (the route
    predicate) and `_ce` (the argv builder) for the same module — two names for
    one thing is how two call sites come to believe they are talking about
    different modules."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    aliases = set(re.findall(r"^import _container_exec as (\w+)", src, re.M))
    assert len(aliases) == 1, f"phase3 imports _container_exec as {aliases}"


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
