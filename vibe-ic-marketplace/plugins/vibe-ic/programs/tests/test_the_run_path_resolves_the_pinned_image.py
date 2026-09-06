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


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
