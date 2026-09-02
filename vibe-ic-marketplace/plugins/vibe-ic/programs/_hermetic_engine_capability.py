"""The disclosure existed and could not reach the verdict: NORECORD read as FAIL.

MEASURED, on `88a8bcdf4d`, inside the digest-pinned runtime
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…` (tag 0.3.6):

    $ command -v docker   ->  (nothing)
    $ python3 -m pytest -q programs/tests/test_landing_merge_verdict.py
    ...
          --- B1 runner said (this is the CAUSE; the lines below are the symptom):
          [NORECORD] hermetic candidate: cannot execute Docker CLI:
              [Errno 2] No such file or directory: 'docker'
          [NORECORD] hermetic landing arm receipt: cannot resolve runner receipt: ...
    gatekeeper-verify-merge: B1 arm receipt is NORECORD
    23 failed, 115 passed

The gate was ALREADY HONEST. It said, in its own words, "I did not measure
this" — and then the only consumer of that sentence, the assertion three frames
up, read `returncode != 0` and reported FAIL, which says "this code is broken".
Those are different claims about the world and the second one is false. This
module is the missing segment between the two: the piece that carries a named
NORECORD as far as the verdict, so a run that could not look is recorded as
NOT_MEASURED and never as red.

WHY THIS IS NOT A `which("docker")` SKIP
=========================================
A skip that fires for everybody is a deleted test.
`tools/ci/trusted_test_selection.py::CONTROL_TESTS` pins
`programs/tests/test_landing_merge_verdict.py` into EVERY landing's denominator
precisely because a red suite once survived five `gh pr merge` squashes; the 23
tests in question are that control's only end-to-end proof. So the classifier
here refuses on TWO independent readings, and needs both to say NOT_MEASURED:

  1. the run's OWN output names the container engine as unexecutable, in the
     exact words `tools/ci/hermetic_candidate_runner.py:385` builds
     (`Refusal(f"cannot execute Docker CLI: {exc}")`, raised only from `OSError`,
     i.e. the CLI is absent or is not executable at all); AND
  2. an INDEPENDENT probe, issued from this process with the same executable
     name the runner defaults to (`--docker-bin`, default `docker`), confirms
     the engine really is out of reach.

The second reading is the load-bearing one, and it points the only direction
that matters: a run that PRINTS the marker on a host where the engine IS
reachable is `MEASURED` — a defect in the run, reported red, exactly as before.
There is no string a candidate can emit that turns a reachable engine into a
skip. And where the engine is reachable, condition 1 is false anyway, so every
one of the 23 runs, and goes red on a branch that deserves it.

The converse is equally deliberate: an output with no marker is `MEASURED`
whatever the host looks like. "There is no docker here" does not excuse a
failure that never blamed docker.

chip-AGNOSTIC: harness/environment classification only; no design, PDK or
vendor literal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable, Tuple

#: The CAUSE line, verbatim. `tools/gatekeeper-verify-merge.sh` prefixes each
#: runner refusal with `[NORECORD] hermetic candidate: ` and prints it under
#: its own header "this is the CAUSE; the lines below are the symptom", so this
#: is the sentence to key on and the receipt-resolution NORECORD under it is
#: not. Kept as the runner's own words rather than a regex: if the runner ever
#: renames its refusal, this stops matching and the 23 go red again — which is
#: the correct failure for a marker that no longer describes anything.
ENGINE_ABSENT_MARKER = (
    "[NORECORD] hermetic candidate: cannot execute Docker CLI:")

#: The verdict this module produces. Three states, not two: a run that was
#: performed (whatever its outcome — that is the caller's assertion to make),
#: and a run that never happened, which must carry the reason by name.
MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"

#: The same question the runner asks first, asked without the runner. `version`
#: is the cheapest call that needs BOTH halves — an executable CLI and a daemon
#: that answers — and both halves are what "the arms can run" means.
_PROBE_ARGS = ("version", "--format", "{{.Server.Version}}")
_PROBE_TIMEOUT_S = 30.0


def probe_engine(executable: str = "docker",
                 timeout: float = _PROBE_TIMEOUT_S) -> Tuple[bool, str]:
    """(reachable, named reason) for the container engine, measured now.

    `executable` is the name `hermetic_candidate_runner.py`'s `--docker-bin`
    defaults to, so this resolves through the same PATH the arms would use.
    Every non-reachable answer names WHICH half failed; "not reachable" with no
    reason is the shape this whole module exists to refuse.
    """
    try:
        proc = subprocess.run(
            [executable, *_PROBE_ARGS],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        return False, (f"the container engine CLI {executable!r} cannot be "
                       f"executed from this process: {exc}")
    except subprocess.TimeoutExpired:
        return False, (f"the container engine CLI {executable!r} did not answer "
                       f"`{' '.join(_PROBE_ARGS)}` within {timeout:g}s")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().replace("\n", " ")
        return False, (f"the container engine CLI {executable!r} exists but the "
                       f"daemon did not answer (rc={proc.returncode}): "
                       f"{err[:300]}")
    server = proc.stdout.decode("utf-8", "replace").strip()
    return True, (f"the container engine is reachable from this process "
                  f"({executable!r}, server {server or 'unnamed'})")


def classify(output: str,
             executable: str = "docker",
             probe: Callable[[str], Tuple[bool, str]] = None,
             ) -> Tuple[str, str]:
    """Was this run MEASURED, or did it never happen? Reason always named.

    `output` is the run's combined stdout+stderr — the channel the NORECORD was
    already printed on. `probe` is injectable so both directions of the
    classification can be driven deterministically in a test; production passes
    nothing and gets :func:`probe_engine`.
    """
    if ENGINE_ABSENT_MARKER not in output:
        return MEASURED, ("the run named no container-engine absence, so its "
                          "own outcome is the verdict")
    ask = probe or (lambda exe: probe_engine(exe))
    reachable, reason = ask(executable)
    if reachable:
        return MEASURED, (
            "the run reported the container engine as unexecutable, but "
            f"{reason}. A run that blames an engine it could have started is a "
            "defect in the run, not a fact about this host — judged as it "
            "stands.")
    return NOT_MEASURED, (
        f"the hermetic arms never started: {reason}. The run reported "
        f"{ENGINE_ABSENT_MARKER!r} and that is confirmed independently, so "
        "there is no measurement here to pass or fail.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Classify a hermetic-arm run as MEASURED or NOT_MEASURED, "
                    "with the reason named.")
    ap.add_argument("--output-file", help="file holding the run's combined "
                                          "stdout+stderr; default is stdin")
    ap.add_argument("--docker-bin", default="docker",
                    help="engine CLI name, as hermetic_candidate_runner.py "
                         "--docker-bin spells it (default: docker)")
    args = ap.parse_args(argv)
    if args.output_file:
        with open(args.output_file, "r", encoding="utf-8",
                  errors="replace") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    status, reason = classify(text, executable=args.docker_bin)
    print(json.dumps({"status": status, "reason": reason,
                      "marker": ENGINE_ABSENT_MARKER,
                      "marker_seen": ENGINE_ABSENT_MARKER in text}, indent=2))
    return 0 if status == MEASURED else 3


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
