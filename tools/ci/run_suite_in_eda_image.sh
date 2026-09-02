#!/usr/bin/env bash
# run_suite_in_eda_image.sh — run the plugin test suite (or the landing gate)
# inside the digest-pinned EDA image WITH a reachable container engine.
#
# WHY THIS FILE EXISTS
# ====================
# The suite carries a mandatory negative control that DRIVES the container
# engine: `tools/ci/trusted_test_selection.py::CONTROL_TESTS` pins
# `programs/tests/test_landing_merge_verdict.py` into every landing's
# denominator, and 23 of its 138 tests execute `tools/gatekeeper-verify-merge.sh`
# end to end, which launches the hermetic B1/B2/A1/A2 arms through
# `tools/ci/hermetic_candidate_runner.py`.
#
# MEASURED on ae5cc4dbfc3f (tree 954bc27704cb), `ghcr.io/vibeic/vibeic-eda@sha256:
# 66c33ff2…` (tag 0.3.6, image id b8b65ea3af6e):
#
#     command -v docker            ->  (nothing)
#     ls /var/run/docker.sock      ->  No such file or directory
#
# so `Docker.call` raises at its first invocation and the gate prints
#
#     [NORECORD] hermetic candidate: cannot execute Docker CLI:
#         [Errno 2] No such file or directory: 'docker'
#     gatekeeper-verify-merge: B1 arm receipt is NORECORD
#
# for every one of those 23. On the host, the same file is green. The failure is
# a property of WHERE the suite was run, not of the tree — and the answer is NOT
# to skip the file. It exists because a red suite survived five `gh pr merge`
# squashes; a `which("docker")` skip would delete the landing gate's only
# end-to-end proof in the one place it routinely runs.
#
# So this harness makes the engine REACHABLE where the suite runs, instead.
#
# WHY DOCKER-OUT-OF-DOCKER AND NOT DOCKER-IN-DOCKER
# =================================================
# The container this script starts is a HARNESS, not a sandbox. It is the outer
# environment the suite runs in — the stand-in for "the host". The arms the
# suite launches from inside it are the sandbox, and they are untouched: the
# runner still gives them `--network none`, a read-only rootfs, `--cap-drop ALL`,
# `no-new-privileges` and uid 65534, and it still refuses a writable subject
# bind. NOTHING in this file relaxes an arm.
#
# The hermetic ARM itself must never be given this socket. An arm executes
# UNREVIEWED candidate code; handing it the host daemon would give that code
# root on the machine that is judging it, including the ability to rewrite the
# very tree under test. That is the removal of the gate, not a repair of it.
#
# THE IDENTICAL-PATH RULE, AND WHY IT IS A REFUSAL
# ================================================
# With the host socket bound in, `docker run -v A:B` issued from INSIDE this
# container is resolved by the HOST daemon, so `A` is read on the HOST
# filesystem. A path that exists only inside the container does not error: the
# daemon CREATES an empty directory and mounts that. The arm then runs against
# an empty subject and reports something false rather than nothing.
#
# Every path this harness makes visible is therefore mounted at its OWN path —
# host path == container path — and anything that cannot be is a refusal, never
# a remapping.
#
# `/tmp` IS ONE OF THOSE PATHS, AND IT IS NOT OPTIONAL. Sharing the repo and the
# scratch root is not enough:
#
#     tools/ci/hermetic_candidate_runner.py:1840
#         runtime_dir = Path(tempfile.mkdtemp(prefix="vibeic-hermetic-", dir="/tmp"))
#
# `dir="/tmp"` is hardcoded on purpose — that private transport directory must
# not follow `TMPDIR` and must not land under `HOME`. It holds the arm's
# progress plan, the selection and the stdout/stderr sinks, and every one of
# them is handed to the daemon as a bind SOURCE. With only the repo shared, the
# CLI works, the arm gets all the way to container creation, and then:
#
#     [NORECORD] hermetic candidate: candidate container creation failed:
#         invalid mount config for type "bind": bind source path does not
#         exist: /tmp/vibeic-hermetic-dsz78fvv/progress-plan.json
#
# — MEASURED, on this harness, with the socket already working. That is the
# identical-path trap arriving one step later, and it is why the rule is stated
# as "every path", not "the interesting paths".
#
# THE ACCOUNT HOME IS PART OF THE RUNTIME, NOT DECORATION
# =======================================================
# `hermetic_candidate_runner._home_path()` resolves `pwd.getpwuid(os.getuid())`
# strictly and REFUSES every mount when it cannot. The pinned image has no
# passwd entry for uid 1000, so a bare `--user 1000` run NORECORDs before it
# ever looks for the engine (measured: "cannot resolve the host account home:
# 'getpwuid(): uid not found: 1000'"). This harness therefore supplies a passwd
# entry, and puts that home in a SIBLING of the scratch root rather than an
# ancestor of it — a scratch root under the account home is refused by
# `_resolve_mount` for a different reason, which `programs/scratch_root_guard.py`
# documents.
#
# THE SCRATCH ROOT IS PINNED, NOT INHERITED
# =========================================
# `TMPDIR` is set to a directory under a VOLATILE root (`/tmp`, `/var/tmp`,
# `/dev/shm`, `/run`). Tests in this suite build their subject at `tmp_path` and
# ask `programs/project_outputs_in_tree_check.py` to classify it as external
# storage; that gate matches those four prefixes and nothing else, so a scratch
# root anywhere else turns honest passes into failures that name their own
# subject and never the root. `programs/scratch_root_guard.py` refuses such a
# root by name; this harness never creates one.
#
# HOW MANY IT COSTS IS NOT WRITTEN HERE, DELIBERATELY. This comment said "six"
# and was wrong by the time anyone read it: `test_issue146_collect_external_
# outputs.py` grew a `volatile_dir` fixture in fc32402c8 and stopped costing
# its 4, while `test_issue1446_scratch_root_guard.py` was costing 6 and had
# never been counted (measured on ded6aa231a68: 8, not 6). The count lives in
# `_VOLATILE_REFUSAL` in the guard, where
# `test_every_line_of_this_cost_table_fires` re-measures it every run.
#
# --no-engine IS A CONTROL, NOT A MODE
# ====================================
# It withholds the engine on purpose so the 23 can be brought back on demand. A
# repair that cannot be undone into the original failure was not measured.
#
# chip-AGNOSTIC: harness/environment structure only; no design, PDK or vendor
# literal. The two PDK names that appear anywhere near this lane are open ones.
set -uo pipefail

PROG="$(basename "$0")"
die() { echo "$PROG: REFUSED — $*" >&2; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" \
  || die "cannot resolve the repository root"

# The pinned runtime image. Spelled as a DIGEST, the way
# `tools/ci/protected_landing_transition.json` and
# `programs/landing_pytest_runtime_preflight.py` spell it: a floating tag is how
# a host ends up with a runtime nobody pinned.
IMAGE_DEFAULT="ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff"
IMAGE="${VIBEIC_SUITE_IMAGE:-$IMAGE_DEFAULT}"
SCRATCH_DEFAULT="/tmp/vibeic-suite"
SCRATCH="${VIBEIC_SUITE_SCRATCH:-$SCRATCH_DEFAULT}"
ENGINE=1
DOCKER_BIN="${VIBEIC_SUITE_DOCKER_BIN:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image) IMAGE="${2:-}"; shift 2 ;;
    --scratch) SCRATCH="${2:-}"; shift 2 ;;
    --no-engine) ENGINE=0; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) break ;;
  esac
done
[ "$#" -gt 0 ] || die "nothing to run; pass the pytest arguments after --"

# ── the scratch root, checked before anything is created or started ────────
# FIRST, deliberately. This is a fact about a string; asking it before the
# engine probe, before any mkdir and before any container means an operator who
# gets it wrong is told in milliseconds instead of after a 22 GB image has been
# started, and it means the refusal can be driven with no daemon at all.
SCRATCH_ABS="$(readlink -f "$SCRATCH")" || die "cannot resolve --scratch $SCRATCH"
case "$SCRATCH_ABS/tmp/" in
  /tmp/*|/var/tmp/*|/dev/shm/*|/run/*) ;;
  *) die "the scratch root $SCRATCH_ABS/tmp is not under a volatile root
    (/tmp, /var/tmp, /dev/shm, /run). programs/project_outputs_in_tree_check.py
    matches exactly those four prefixes and nothing else, so six tests would
    report a defect that is this path and not the tree:
        programs/tests/test_issue146_collect_external_outputs.py        4
        programs/tests/test_project_outputs_in_tree_check.py            2
    Pass --scratch under one of the four." ;;
esac
SCRATCH="$SCRATCH_ABS"
HOME_IN="$SCRATCH/home"
case "$SCRATCH/tmp" in
  "$HOME_IN"/*) die "the scratch root is under the account home this harness
    supplies; hermetic_candidate_runner._resolve_mount refuses every mount taken
    from there" ;;
esac
mkdir -p "$SCRATCH/tmp" "$HOME_IN" || die "cannot create $SCRATCH"

# ── the engine, on the host, before anything is started ────────────────────
if [ "$ENGINE" = "1" ]; then
  [ -n "$DOCKER_BIN" ] || DOCKER_BIN="$(command -v docker || true)"
  [ -n "$DOCKER_BIN" ] || die \
    "no Docker CLI on this host, so the container cannot be given one. The
    suite's mandatory negative control drives the engine end to end; running it
    without one produces 23 NORECORD failures that describe this host and not
    the tree. Install Docker, or re-run with --no-engine and read the result as
    the control it is."
  # NAMED AND ABSENT is a different fault from NOT NAMED, and it must not be
  # discovered as a bind-mount error thirty seconds later: the CLI is mounted
  # into the container at its own path, and Docker CREATES a bind source that
  # does not exist rather than refusing, so an unexecutable path would arrive
  # inside as an empty directory called `docker`. Asked BEFORE `readlink -f`,
  # which on GNU coreutils fails on a path whose parents do not exist and would
  # answer "cannot resolve" to a question about executability.
  [ -x "$DOCKER_BIN" ] || die \
    "the Docker CLI named for this run is not an executable file:
        $DOCKER_BIN
    It is bind-mounted into the container at its own path, so it has to exist
    on this host. Unset VIBEIC_SUITE_DOCKER_BIN to take the one on PATH."
  DOCKER_BIN="$(readlink -f "$DOCKER_BIN")" || die "cannot resolve the Docker CLI path"
  DOCKER_SOCK="${DOCKER_HOST:-}"
  DOCKER_SOCK="${DOCKER_SOCK#unix://}"
  [ -n "$DOCKER_SOCK" ] || DOCKER_SOCK=/var/run/docker.sock
  [ -S "$DOCKER_SOCK" ] || die \
    "the Docker endpoint $DOCKER_SOCK is not a socket on this host. Only a UNIX
    socket can be handed to the container at its own path; a TCP DOCKER_HOST
    needs no mount and should be passed through instead."
  SOCK_GID="$(stat -c %g "$DOCKER_SOCK")" || die "cannot stat $DOCKER_SOCK"
fi

# The image has no passwd entry for uid 1000. Supply one whose home EXISTS at
# the same path on both sides, so `_home_path()`'s strict resolve succeeds.
PASSWD="$SCRATCH/passwd"
"${DOCKER_BIN:-docker}" run --rm --entrypoint /bin/cat "$IMAGE" /etc/passwd \
  > "$PASSWD.image" 2>/dev/null || die "cannot read /etc/passwd from $IMAGE"
UID_NOW="$(id -u)"; GID_NOW="$(id -g)"
{ grep -v "^designer:" "$PASSWD.image" || true
  echo "designer:x:$UID_NOW:$GID_NOW:designer:$HOME_IN:/bin/bash"; } > "$PASSWD"

DOCKER_ARGS=(
  --rm --platform linux/amd64
  --user "$UID_NOW:$GID_NOW"
  -v "$REPO_ROOT:$REPO_ROOT"
  -v /tmp:/tmp
  -v "$PASSWD:/etc/passwd:ro"
  -w "$REPO_ROOT/vibe-ic-marketplace/plugins/vibe-ic"
  -e "HOME=$HOME_IN"
  -e "TMPDIR=$SCRATCH/tmp"
  -e PYTHONDONTWRITEBYTECODE=1
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  -e GIT_CONFIG_GLOBAL=/dev/null
  -e GIT_CONFIG_NOSYSTEM=1
)
# `/tmp` is already shared above; a scratch root elsewhere needs its own bind at
# its own path, for the same reason.
case "$SCRATCH/" in
  /tmp/*) ;;
  *) DOCKER_ARGS+=(-v "$SCRATCH:$SCRATCH") ;;
esac
if [ "$ENGINE" = "1" ]; then
  DOCKER_ARGS+=(
    -v "$DOCKER_SOCK:$DOCKER_SOCK"
    -v "$DOCKER_BIN:$DOCKER_BIN:ro"
    -e "DOCKER_HOST=unix://$DOCKER_SOCK"
    --group-add "$SOCK_GID"
  )
  echo "$PROG: engine reachable — $DOCKER_BIN over $DOCKER_SOCK (gid $SOCK_GID)" >&2
else
  echo "$PROG: --no-engine — the container has NO container engine. This is the" >&2
  echo "$PROG: CONTROL: the engine-driving negative control is expected to fail" >&2
  echo "$PROG: here, and a green result would mean the control stopped checking." >&2
fi

# The engine is proved reachable FROM INSIDE, not assumed from the host. A
# socket that is bound but unusable (group, SELinux, a stopped daemon) produces
# the identical NORECORD, and "I could not look" must not be reported as red.
if [ "$ENGINE" = "1" ]; then
  if ! "$DOCKER_BIN" run "${DOCKER_ARGS[@]}" --entrypoint /bin/sh "$IMAGE" \
        -c 'command -v docker >/dev/null && docker version --format "{{.Server.Version}}"' \
        >"$SCRATCH/engine-probe.txt" 2>&1; then
    sed 's/^/    /' "$SCRATCH/engine-probe.txt" >&2
    die "the container could not reach the Docker engine (see above). No test
    was run: a suite that cannot start the arms reports NORECORD, and NORECORD
    is not a test verdict."
  fi
  echo "$PROG: engine inside the container: server $(cat "$SCRATCH/engine-probe.txt")" >&2
fi

"${DOCKER_BIN:-docker}" run "${DOCKER_ARGS[@]}" --entrypoint /bin/sh "$IMAGE" \
  -c 'exec python3 -m pytest "$@"' sh "$@"
EXIT_RC=$?
exit "$EXIT_RC"
