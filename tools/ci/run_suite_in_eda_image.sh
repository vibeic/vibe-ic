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
# subject and never the root. `programs/scratch_root_guard.py` DECLARES such a
# root by name; this harness never creates one.
#
# HOW MANY IT COSTS IS NOT WRITTEN HERE, DELIBERATELY. This comment said "six"
# and was wrong by the time anyone read it: `test_issue146_collect_external_
# outputs.py` grew a `volatile_dir` fixture in fc32402c8 and stopped costing
# its 4, while `test_issue1446_scratch_root_guard.py` was costing 6 and had
# never been counted (measured on ded6aa231a68: 8, not 6). The count lives in
# `_VOLATILE_ADVISORY` in the guard, where
# `test_every_line_of_this_cost_table_fires` re-measures it every run.
#
# IT IS NOW 0, AND THE GUARD NO LONGER REFUSES ON IT (re-measured 4b3843f22c:
# every test that exercises the gate pins its own volatile subject, so none of
# them depends on where `tmp_path` lands). THIS HARNESS STILL PINS ITS OWN
# SCRATCH ROOT, and the reason is no longer the count: `--scratch` is a shape
# this harness GUARANTEES to whatever runs inside it, not an environment it
# inherited, and it costs the caller one argument to satisfy. That is a
# different argument from the guard's, written down here so the two are not
# confused — the guard adjudicates an operator's environment and now declares
# rather than refuses; this adjudicates its own parameter.
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
# THE DIGEST IS READ, NEVER COPIED. `tools/ci/hermetic_candidate_runner.py`
# pins the runtime image as `IMAGE`, and that is the one place the fleet moves
# when the image moves. This file used to carry its OWN literal of the same
# digest, and the two drifted: measured 2026-09-06, the owner had ruled the
# image forward to the 0.3.47-era build while this line still named 0.3.6 —
# forty patch releases behind — so every operator who did not pass `--image`
# measured a toolchain nobody had pinned, and said nothing about it.
#
# Parsed with `ast`, not imported: this must not run that module's imports, and
# it must not execute anything to learn a constant. A read that fails is a
# REFUSAL, never a fallback literal, because a fallback is how the second copy
# comes back.
#
# TWO constants are read now, not one, because the pin was split: the DIGEST is
# the identity and the REPOSITORY is deployment configuration. This composes them
# exactly as `hermetic_candidate_runner.image_reference()` does -- same env, same
# default -- so the harness and the runner cannot disagree about which bytes are
# demanded, and a host that reaches those bytes at a different registry sets
# VIBEIC_EDA_IMAGE_REPO instead of editing either file.
_PIN_SRC="$REPO_ROOT/tools/ci/hermetic_candidate_runner.py"
_PIN_PARTS="$(python3 - "$_PIN_SRC" <<'PY' || true
import ast, sys
WANTED = ("IMAGE_DIGEST", "IMAGE_REPO_DEFAULT")
try:
    tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    sys.exit(1)
found = {}
for node in tree.body:
    if not isinstance(node, ast.Assign):
        continue
    for target in node.targets:
        name = getattr(target, "id", "")
        if name in WANTED and name not in found:
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                sys.exit(1)
            if not isinstance(value, str) or not value:
                sys.exit(1)
            found[name] = value
if len(found) != len(WANTED):
    sys.exit(1)
print(found["IMAGE_DIGEST"])
print(found["IMAGE_REPO_DEFAULT"])
PY
)"
_PIN_DIGEST="$(printf '%s\n' "$_PIN_PARTS" | sed -n 1p)"
_PIN_REPO_DEFAULT="$(printf '%s\n' "$_PIN_PARTS" | sed -n 2p)"
_PIN_REPO="${VIBEIC_EDA_IMAGE_REPO:-$_PIN_REPO_DEFAULT}"
if [ -n "$_PIN_DIGEST" ] && [ -n "$_PIN_REPO" ]; then
  IMAGE_DEFAULT="${_PIN_REPO}@${_PIN_DIGEST}"
else
  IMAGE_DEFAULT=""
fi
case "$IMAGE_DEFAULT" in
  *"@sha256:"*) ;;
  *) die "cannot read the pinned runtime image (IMAGE_DIGEST + IMAGE_REPO_DEFAULT) from $_PIN_SRC.
    That constant is the single place this repo pins the runtime, and this
    harness reads it rather than keeping a copy that can drift. Fix the pin, or
    pass --image explicitly; there is deliberately no fallback literal here." ;;
esac
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
    matches exactly those four prefixes and nothing else, and this harness PINS
    the scratch root rather than inheriting one, so it will not silently run
    under a shape it does not guarantee.
    WHAT A NON-VOLATILE ROOT COSTS IS NOT WRITTEN HERE, deliberately — the
    comment block at the top of this file says why, and the two lines that used
    to stand here are why it says it: they named
    test_issue146_collect_external_outputs.py for 4 failures fc32402c8 had
    already fixed, and test_project_outputs_in_tree_check.py for 2 the v1.16.85
    landing had already fixed. Both were 0 and this text went on quoting them.
    The number lives in _VOLATILE_ADVISORY in
    vibe-ic-marketplace/plugins/vibe-ic/programs/scratch_root_guard.py, where
    test_every_line_of_this_cost_table_fires re-measures it every run, and
    where it is currently 0 — which is why the GUARD declares this condition
    and does not refuse on it.
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

# The HOME this harness supplies must carry the image's own `.bashrc`.
# `/dockerstartup/scripts/ui_startup.sh:34` is `source "$HOME/.bashrc"` under
# `set -e`, and it runs BEFORE the `--skip` branch at line 37 — so an empty HOME
# makes the entrypoint exit before it ever looks at the command, with
# `line 34: <home>/.bashrc: No such file or directory`. Taken FROM THE IMAGE
# rather than written here, for the same reason /etc/passwd above is: the file
# the image ships is the one its own startup expects to source.
if [ ! -f "$HOME_IN/.bashrc" ]; then
  "${DOCKER_BIN:-docker}" run --rm --entrypoint /bin/cat "$IMAGE" \
    /headless/.bashrc > "$HOME_IN/.bashrc.tmp" 2>/dev/null \
    || die "cannot read /headless/.bashrc from $IMAGE, which the image's own
    entrypoint sources before it will run anything"
  mv "$HOME_IN/.bashrc.tmp" "$HOME_IN/.bashrc"
fi

DOCKER_ARGS=(
  --rm --platform linux/amd64
  --user "$UID_NOW:$GID_NOW"
  -v "$REPO_ROOT:$REPO_ROOT"
  -v /tmp:/tmp
  -v "$PASSWD:/etc/passwd:ro"
  -w "$REPO_ROOT/vibe-ic-marketplace/plugins/vibe-ic"
  -e "HOME=$HOME_IN"
  -e "TMPDIR=$SCRATCH/tmp"
  -e "VIBEIC_SUITE_NSS=$SCRATCH"
  -e PYTHONDONTWRITEBYTECODE=1
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  -e GIT_CONFIG_GLOBAL=/dev/null
  -e GIT_CONFIG_NOSYSTEM=1
  # THE ONE CONFIG POINT, FORWARDED — the variable, never the address.
  #
  # This harness already resolves the pin with `${VIBEIC_EDA_IMAGE_REPO:-...}`
  # on the HOST, and then started a container that could not see it. MEASURED
  # 2026-09-07 on 8hd-3 (lane czto12, reproduced here through this script): a
  # nested resolve INSIDE the harness reported
  #     VIBEIC_EDA_IMAGE_REPO = None
  #     ghcr.io/vibeic/vibeic-eda@sha256:8da785a8… -> IMAGE_NOT_PRESENT
  # while the identical resolve on the host names the fleet registry and finds
  # the image. A deployment that serves the pinned bytes from somewhere else
  # could configure the host and still have everything inside the harness fall
  # back to a repository it cannot reach.
  #
  # The BARE `-e NAME` form is deliberate and is the reason no address appears
  # here: docker copies the value from this process's environment when it is
  # set, and does NOT create the variable at all when it is not — verified both
  # ways on this host — so an unset host env cannot inject an empty value that
  # would shadow the default inside the container.
  -e VIBEIC_EDA_IMAGE_REPO
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
  if ! "$DOCKER_BIN" run "${DOCKER_ARGS[@]}" "$IMAGE" --skip bash \
        -c 'command -v docker >/dev/null && docker version --format "{{.Server.Version}}"' \
        >"$SCRATCH/engine-probe.txt" 2>&1; then
    sed 's/^/    /' "$SCRATCH/engine-probe.txt" >&2
    die "the container could not reach the Docker engine (see above). No test
    was run: a suite that cannot start the arms reports NORECORD, and NORECORD
    is not a test verdict."
  fi
  echo "$PROG: engine inside the container: server $(cat "$SCRATCH/engine-probe.txt")" >&2
fi

# THROUGH THE IMAGE'S OWN ENTRYPOINT, and `--skip` FIRST because the entrypoint's
# own help says that flag is ignored anywhere else.
#
# This used to be `--entrypoint /bin/sh`, which starts the container without ever
# running the image's setup. The image's `ENV` layer survives that, so `PATH` and
# a one-entry `PYTHONPATH` looked right and the bypass was invisible. What the
# entrypoint ADDS, measured 2026-09-07 on 8HD-9 by diffing `env | sort` between
# the two shapes on digest 06537f7e (label 0.3.46), 29 variables against 57:
#
#   PYTHONPATH   gains /opt/vibeic-forks/cocotb/src, /opt/vibeic-forks/pyuvm/src,
#                /foss/tools/klayout/pymod and the dist-packages chain. THE FORKED
#                cocotb AND pyuvm ARE NOT IMPORTABLE WITHOUT IT.
#   PDK          ihp-sg13g2, with PDKPATH, STD_CELL_LIBRARY and SPICE_USERINIT_DIR
#   LD_LIBRARY_PATH  klayout, ngspice, iverilog, openems, kactus2, gtkwave, kepler-formal
#   KLAYOUT_HOME / KLAYOUT_PATH, CPATH and LIBRARY_PATH for ghdl,
#   PYTHONPYCACHEPREFIX, USER, XDG_*, and FOSS_INIT_DONE=1 — the sentinel that
#   says the setup ran at all.
#
# A suite must run in the environment the image ships. Anything measured through
# the bypass was measured against a different one.
#
# AND THEN IT TAKES ITS OWN COPY OF THE nss_wrapper FILES, which is not a
# bypass — it runs entirely AFTER the entrypoint, on what the entrypoint wrote.
#
# `generate_container_user.sh:17` HARDCODES `NSS_WRAPPER_PASSWD=/tmp/passwd`
# (a preset value is overwritten, so `-e` cannot move it) and line 21 is
# `install -m 0644 /etc/passwd /tmp/passwd`. This harness binds the HOST's
# `/tmp` at its own path, so `/tmp/passwd` is one shared mutable file and the
# last container to start wins it — for every lane on the box, not just ours.
#
# MEASURED 2026-09-07 on 8HD-9, and it is not theoretical: an A/B of this suite
# through the entrypoint against `--entrypoint /bin/sh`, same tree, same 377
# nodes, moved ELEVEN nodes from passed to skipped, all of them in
# `test_issue1446_scratch_root_guard.py`, all with one reason —
#     "cannot resolve the host account home: [Errno 2] ... '/var/tmp/czh_pr1'"
# `/var/tmp/czh_pr1` was ANOTHER container of this lane, started seconds
# earlier. The session resolved its account home out of a file a different run
# owned, and eleven checks about the account home reported SKIPPED rather than
# saying they had been handed someone else's answer.
#
# So the session copies the entrypoint's own output to a per-run path under the
# scratch and re-points nss_wrapper at the copy, then CHECKS that the home it
# resolves is the one this run supplied and refuses by name if it is not. A
# later writer to /tmp/passwd can no longer change what this session sees.
"${DOCKER_BIN:-docker}" run "${DOCKER_ARGS[@]}" "$IMAGE" \
  --skip bash -c '
    set -e
    # THE passwd COMES FROM /etc/passwd, NOT FROM /tmp/passwd. Both carry the
    # same designer line when nothing has raced; only one of them CANNOT be
    # raced. /etc/passwd is the file THIS harness bind-mounts read-only a few
    # lines above, carrying the account home this run supplied, so taking it
    # here closes the window entirely rather than narrowing it. The GROUP is
    # taken from the entrypoint, which is where the designers line is
    # appended, and a group carries no per-run state to corrupt.
    # NOTE FOR ANYONE EDITING THIS BLOCK: it is inside a single-quoted
    # bash -c body. An apostrophe here ends the string.
    # NAMED nss-passwd / nss-group, NOT passwd / group: $VIBEIC_SUITE_NSS is
    # $SCRATCH, and $SCRATCH/passwd is the very file this harness bind-mounts
    # AT /etc/passwd. Copying onto it is cp refusing "the same file".
    cp /etc/passwd "$VIBEIC_SUITE_NSS/nss-passwd"
    cp "$NSS_WRAPPER_GROUP"  "$VIBEIC_SUITE_NSS/nss-group"
    export NSS_WRAPPER_PASSWD="$VIBEIC_SUITE_NSS/nss-passwd"
    export NSS_WRAPPER_GROUP="$VIBEIC_SUITE_NSS/nss-group"
    got=$(python3 -c "import os,pwd; print(pwd.getpwuid(os.getuid()).pw_dir)")
    if [ "$got" != "$HOME" ]; then
      echo "run_suite_in_eda_image.sh: REFUSED — the account home this session" >&2
      echo "    resolves is $got, but this run supplied HOME=$HOME." >&2
      echo "    This should be unreachable: the passwd this session uses is" >&2
      echo "    copied from the read-only /etc/passwd this harness mounts, not" >&2
      echo "    from the shared /tmp/passwd. NOTHING WAS" >&2
      echo "    RUN: a suite whose account home belongs to another run is not a" >&2
      echo "    verdict about this tree." >&2
      exit 2
    fi
    exec python3 -m pytest "$@"' bash "$@"
EXIT_RC=$?
exit "$EXIT_RC"
