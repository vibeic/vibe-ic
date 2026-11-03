#!/bin/bash
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
# `programs/landing_pytest_runtime_preflight.py` spells it: a floating tag is how
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
_PIN_DIR="$REPO_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
# RESOLVED, NOT PARSED. This used to ast.parse hermetic_candidate_runner.py
# for an IMAGE_DIGEST assignment; the identity is no longer a literal
# anywhere -- it is asked of this host at run time -- so a source parse
# finds nothing and the old reader exited 1, which this script turns into
# `die`. Ask the module, which is the only thing that knows.
_PIN_PY='import _eda_pin as p; print(p.resolved_image_digest()); print(p.IMAGE_REPO_DEFAULT)'
# `-B` AND THE ENV VAR, because this import WRITES INTO THE SUBJECT TREE.
# vibe-ic#2008. Importing `_eda_pin` from `$_PIN_DIR` leaves
# `vibe-ic-marketplace/plugins/vibe-ic/programs/__pycache__` behind, and
# `git status` CANNOT SEE IT (.gitignore) while the attestation drift
# instrument can -- so an operator who runs the suite and then the hygiene set
# in the same checkout measures a preflight finding they created by measuring:
#
#   [PREFLIGHT] 1 bytecode/cache artefact(s) already sit under the declared
#   roots ... residue: .../programs/__pycache__
#
# MEASURED on a clone made from zero: 0 __pycache__ dirs before, 1 after this
# one command, `git status --porcelain` 0 lines on both sides. Every other
# caller in this repo already guards it for exactly this reason --
# `tools/gatekeeper-land.sh:984` for the full tier and
# `tools/ci/repo_hygiene_gates.sh` for the hygiene set, both citing #2008 --
# and this line, the FIRST thing the harness does to the subject, did not.
# Belt and braces: the env var covers any child, `-B` covers this interpreter.
_PIN_PARTS="$(cd "$_PIN_DIR" && PYTHONDONTWRITEBYTECODE=1 python3 -B -c "$_PIN_PY" 2>/dev/null || true)"
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
  *) die "cannot resolve the EDA runtime image from $_PIN_DIR.
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

# ── the pinned image, RESOLVED BY DIGEST, before anything is started ───────
# THE SAME COMPOSITION DEFECT AS vibe-ic#2170, ONE CALL SITE OVER. The lines
# above compose `<configured repo>@<pinned digest>` and hand that STRING to
# `docker run`. The digest is the identity; the repository half says only where
# a host was told to fetch the bytes. MEASURED 2026-09-07: 8HD-8 holds the pin
# under both `ghcr.io/vibeic/vibeic-eda` and the fleet mirror, 8HD-9 under the
# mirror alone -- so with no env exported, 8HD-9 does not resolve the composed
# string for an image that is on the machine.
#
# AND HERE IT IS WORSE THAN A REFUSAL. There is no `--pull=never` on the
# `docker run` calls below, so an unresolvable reference does not fail fast: it
# starts fetching a ~22 GB image inside a landing gate. This block asks the
# right question first -- "does this host hold an image whose repo digest IS
# the pin, under ANY repository" -- and answers it from LOCAL metadata only.
#
# NOT WIDENED: only a reference whose digest is the pin is accepted, so a
# different digest is refused exactly as strictly as before, and if nothing
# local carries it this dies rather than pulling.
#
# NOT SILENT: a substitution names BOTH references. An operator who sets
# VIBEIC_EDA_IMAGE_REPO and is quietly served the same bytes from elsewhere has
# been given a knob that does nothing.
#
# AN EXPLICIT --image / VIBEIC_SUITE_IMAGE IS NEVER TOUCHED. That is the
# operator naming a runtime themselves, which is a different act from this
# harness resolving its own pin.
if [ "$ENGINE" = "1" ] && [ "$IMAGE" = "$IMAGE_DEFAULT" ] && [ -n "$_PIN_DIGEST" ]; then
  if ! "${DOCKER_BIN:-docker}" image inspect "$IMAGE" >/dev/null 2>&1; then
    # `-a`: an image pulled BY DIGEST and never tagged is DANGLING, and plain
    # `docker image ls` hides it. Without the flag this finds nothing on exactly
    # the hosts the resolution exists for (#2170).
    _HELD="$("${DOCKER_BIN:-docker}" image ls -a --digests --no-trunc \
               --format '{{.Repository}}@{{.Digest}}' 2>/dev/null \
             | grep -F -- "@$_PIN_DIGEST" | grep -v '^<none>@' | head -n 1)"
    [ -n "$_HELD" ] || die "the pinned runtime is not on this host.
    No local image carries the digest
        $_PIN_DIGEST
    under any repository name, and the configured reference
        $IMAGE
    does not resolve either. This harness will not start a pull: the pinned
    image is roughly 22 GB and there is no --pull=never on the runs below, so a
    fetch begun here would run inside a landing gate. Pull it deliberately, or
    point VIBEIC_EDA_IMAGE_REPO at a repository this host already holds."
    printf '[DISCLOSURE] the configured runtime reference %s is not present on this host; the pinned digest %s was found under %s and that is what will be run\n' \
      "$IMAGE" "$_PIN_DIGEST" "$_HELD" >&2
    IMAGE="$_HELD"
  fi
fi

# ── the selectors, checked on the host, before any container is started ────
# The working directory this harness sets is the PLUGIN directory, not the
# repository root. A caller who types a repo-root-relative selector after --
# therefore hands pytest a path that resolves under the plugin directory, where
# it does not exist. MEASURED 2026-09-07 on 8hd-3 (vibe-ic#2123), pinned image,
# from the repository root:
#
#     ./tools/ci/run_suite_in_eda_image.sh -- -q tools/ci/test_gatekeeper_status_poller.py
#         [PASS] suite_write_guard: this pytest session wrote nothing ...
#         no tests ran in 0.07s
#         ERROR: file or directory not found: tools/ci/test_gatekeeper_status_poller.py
#         rc 4
#
# The last verdict-shaped line in that stream is a PASS, the summary names no
# failure, and a scrape reads the run as clean. Nothing ran.
#
# THIS IS A REFUSAL, NOT A REMAPPING, for the same reason no bind in this file
# is remapped: resolving the string against a second directory gives one path
# two meanings and picks one silently, and the caller never learns which. The
# selector is named back, the directory it was resolved against is named, and
# when the file does exist at the repository root the absolute form to type is
# printed. Nothing is guessed.
#
# ASKED AFTER THE SCRATCH AND ENGINE QUESTIONS, deliberately: those are facts
# about the operator's environment and they keep their precedence, so an
# operator with no engine is told about the engine rather than about a
# placeholder argument. It is still before the first container start, which is
# what "before anything is started" has to mean for an argument.
PLUGIN_DIR="$REPO_ROOT/vibe-ic-marketplace/plugins/vibe-ic"

# ── the OUTPUT paths, checked the same way and for the same reason ─────────
# vibe-ic#2123 refuses a SELECTOR that would collect nothing because "nothing
# ran" reads as a clean run. The mirror image is an OUTPUT path the container
# cannot write, and this harness forwarded those verbatim.
#
# MEASURED on this host, pinned image, the SAME one-file selection both times:
#
#   without --junitxml                    1 failed, 7 passed        rc 1
#   with --junitxml under an unmounted
#     host path                           rc 1, and:
#       `N failed, M passed` final line   ABSENT
#       `short test summary info`         0 lines
#       `FAILED ...` lines                0
#       the junit XML                     never written
#
#     PermissionError: [Errno 13] Permission denied: '<the host dir>'
#       in pytest_sessionfinish -> os.makedirs
#
# The exception is raised in `pytest_sessionfinish` -- AFTER every test has run
# and BEFORE the terminal reporter writes its summary -- so the run's entire
# report is destroyed wholesale. The rc is 1, the SAME rc as a real failure, so
# a caller keying on rc sees "tests failed" and a caller scraping for `N failed`
# finds NOTHING and reads the run as clean. Both readings are wrong and neither
# is disclosed. On an all-green selection it is worse: rc 1 with no failure
# anywhere in the output.
#
# This harness mounts exactly $REPO_ROOT, the git common dir, /tmp, the passwd
# file and (with an engine) the docker socket and CLI. A path anywhere else
# names a directory that does not exist inside the container, and the read-only
# parent the mount created refuses to create it.
#
# REFUSED BY NAME, NEVER REMAPPED -- the identical-path rule at the top of this
# file, and #2123's own reasoning: re-resolving a caller's path against a
# second directory gives one string two meanings and picks one silently.
_refuse_unwritable_output() {   # $1 = option token, $2 = its value
  case "$1" in
    --junitxml|--junit-xml|--log-file|--basetemp) ;;
    *) return 0 ;;
  esac
  [ -n "${2:-}" ] || return 0
  case "$2" in
    /*) _oabs="$2" ;;
    # Relative output paths are resolved by pytest against the working
    # directory this harness sets, exactly as selectors are.
    *)  _oabs="$PLUGIN_DIR/$2" ;;
  esac
  case "$_oabs/" in
    "$REPO_ROOT"/*|/tmp/*|"$SCRATCH"/*) return 0 ;;
  esac
  die "the output path for '$1' is not writable from inside the container.
        $1 $2
    resolved to
        $_oabs
    This harness makes exactly these paths visible, at their own addresses:
        $REPO_ROOT
        /tmp
        $SCRATCH
    and nothing else. pytest creates this file in \`pytest_sessionfinish\` --
    AFTER every test has run and BEFORE the terminal reporter writes its
    summary -- so the mkdir fails there and DESTROYS THE RUN'S ENTIRE REPORT:
    no \`N failed, M passed\` line, no \`short test summary info\`, no
    \`FAILED\` lines and no XML, while the exit code is 1 -- the same rc as a
    real test failure. A caller keying on rc reads 'tests failed'; a caller
    scraping for a failure count finds nothing and reads a clean run. Both are
    wrong, so this refuses BEFORE the tests run rather than after.
    Write it under one of the paths above -- $SCRATCH is the one meant for it
    -- and copy it out afterwards."
}

PYTEST_ARGS=()
_await_value=0
_await_opt=""
for _arg in "$@"; do
  if [ "$_await_value" = 1 ]; then
    _refuse_unwritable_output "$_await_opt" "$_arg"
    PYTEST_ARGS+=("$_arg"); _await_value=0; _await_opt=""; continue
  fi
  case "$_arg" in
    # Options whose SEPARATE value is not a selector. Their value is passed
    # through untouched, so a -k expression or an --ignore-glob PATTERN that
    # happens to look like a path is never read as one. The attached forms
    # (-kEXPR, --tb=short, --ignore-glob=x/*) fall to the -* branch below and
    # need no entry here.
    #
    # --ignore and --deselect are deliberately NOT in this list: their values
    # ARE selectors, and one that names nothing removes nothing, silently. The
    # cost of the list being short somewhere else is a LOUD refusal naming the
    # token, which an operator answers with the attached form or an absolute
    # path. It fails closed, which is the direction this whole file fails in.
    -k|-m|-p|-o|-c|-n|-r|-W|--tb|--maxfail|--durations|--timeout|--rootdir\
      |--basetemp|--junitxml|--junit-xml|--junit-prefix|--override-ini\
      |--log-file|--log-level|--log-cli-level|--capture|--import-mode\
      |--assert|--ignore-glob|--stall-after)
      PYTEST_ARGS+=("$_arg"); _await_value=1; _await_opt="$_arg"; continue ;;
    # The ATTACHED forms (--junitxml=PATH, --log-file=PATH, --basetemp=PATH)
    # never reach the branch above, so they are asked here.
    --*=*) _refuse_unwritable_output "${_arg%%=*}" "${_arg#*=}"
           PYTEST_ARGS+=("$_arg"); continue ;;
    -*) PYTEST_ARGS+=("$_arg"); continue ;;
  esac
  # A node id is <path>::<node>; only the path half is a filesystem question.
  _sel="${_arg%%::*}"
  case "$_sel" in
    /*) PYTEST_ARGS+=("$_arg"); continue ;;   # absolute: the caller has said where
  esac
  if [ -e "$PLUGIN_DIR/$_sel" ]; then
    PYTEST_ARGS+=("$_arg"); continue
  fi
  _where="    It does not exist under the repository root either:
        $REPO_ROOT"
  if [ -e "$REPO_ROOT/$_sel" ]; then
    _where="    It DOES exist under the repository root. Pass it absolute:
        $REPO_ROOT/$_arg"
  fi
  die "the selector '$_arg' names nothing this run could collect.
    Relative selectors are resolved by pytest against the working directory
    this harness sets, which is the PLUGIN directory and not the repository
    root:
        $PLUGIN_DIR
$_where
    NOTHING WAS RUN. Left alone this is pytest exit 4 with a file-or-directory
    not-found error and no test result at all, whose output carries no failure
    for a scrape to find and reads as a clean run (vibe-ic#2123).
    This harness REMAPS NOTHING. A relative path silently re-resolved against a
    second directory is one string with two meanings, which is the same trap the
    identical-path rule at the top of this file refuses for binds."
done
set -- "${PYTEST_ARGS[@]}"

# The image has no passwd entry for uid 1000. Supply one whose home EXISTS at
# the same path on both sides, so `_home_path()`'s strict resolve succeeds.
PASSWD="$SCRATCH/passwd"
"${DOCKER_BIN:-docker}" run --rm "$IMAGE" cat /etc/passwd \
  > "$PASSWD.image" 2>/dev/null || die "cannot read /etc/passwd from $IMAGE"
UID_NOW="$(id -u)"; GID_NOW="$(id -g)"
{ grep -v "^designer:" "$PASSWD.image" || true
  echo "designer:x:$UID_NOW:$GID_NOW:designer:$HOME_IN:/bin/bash"; } > "$PASSWD"

# A LINKED WORKTREE'S `.git` IS A POINTER OUT OF THE MOUNT.
#
# `-v "$REPO_ROOT:$REPO_ROOT"` carries the tree and nothing else. In a linked
# worktree `$REPO_ROOT/.git` is a FILE reading `gitdir: <main>/.git/worktrees/
# <name>`, and that address is not mounted, so every git invocation inside the
# container fails. MEASURED 2026-09-10 on 8HD-8, this script run from the
# worktree $S/cy538 at v1.20.13:
#
#   WRITE_GUARD_NOT_CHECKED: git rev-parse --show-toplevel exited 128:
#   fatal: not a git repository: /home/reyerchu/vibe-ic/.git/worktrees/cy538
#   35 passed
#
# The suite reported 35 passed with `suite_write_guard` NOT RUNNING. It is
# disclosed rather than silent — that part works — but the fleet runs this
# harness from a throwaway worktree as a matter of course, so the guard was off
# for essentially every run, and "35 passed" is exactly as reassuring as it
# looks. Mounting the COMMON git dir restores it; it covers both `<main>/.git`
# and the `worktrees/<name>` directory beneath it, and it is mounted RW because
# `git status` refreshes the index.
#
# Empty for an ordinary checkout, where the common dir is already inside
# REPO_ROOT and this adds no mount at all.
# >>> GIT_COMMON_MOUNT BLOCK (executed verbatim by
# test_worktree_run_still_measures_the_write_guard.py — keep these sentinels)
GIT_COMMON_MOUNT=()
_GIT_COMMON="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute \
                 --git-common-dir 2>/dev/null || true)"
case "$_GIT_COMMON" in
  "" | "$REPO_ROOT"/*) : ;;
  *) GIT_COMMON_MOUNT=(-v "$_GIT_COMMON:$_GIT_COMMON") ;;
esac
# <<< GIT_COMMON_MOUNT BLOCK

DOCKER_ARGS=(
  --rm --platform linux/amd64
  --user "$UID_NOW:$GID_NOW"
  -v "$REPO_ROOT:$REPO_ROOT"
  "${GIT_COMMON_MOUNT[@]}"
  -v /tmp:/tmp
  -v "$PASSWD:/etc/passwd:ro"
  -w "$PLUGIN_DIR"
  -e "HOME=$HOME_IN"
  -e "TMPDIR=$SCRATCH/tmp"
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
    -e "VIBEIC_SUITE_DOCKER_DIR=$(dirname "$DOCKER_BIN")"
    -e "DOCKER_HOST=unix://$DOCKER_SOCK"
    --group-add "$SOCK_GID"
  )
  # The image has no host loader or libc and its PATH is one Nix directory, so a
  # dynamically linked host CLI needs its own libraries and its directory on PATH.
  # A static CLI lists no paths here and adds no mount.
  while read -r _lib; do
    DOCKER_ARGS+=(-v "$_lib:$_lib:ro")
  done < <(ldd "$DOCKER_BIN" 2>/dev/null | grep -oE '/[^ ]+' | sort -u)
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
  if ! "$DOCKER_BIN" run "${DOCKER_ARGS[@]}" "$IMAGE" bash \
        -c 'PATH="$PATH:$VIBEIC_SUITE_DOCKER_DIR"; command -v docker >/dev/null && docker version --format "{{.Server.Version}}"' \
        >"$SCRATCH/engine-probe.txt" 2>&1; then
    sed 's/^/    /' "$SCRATCH/engine-probe.txt" >&2
    die "the container could not reach the Docker engine (see above). No test
    was run: a suite that cannot start the arms reports NORECORD, and NORECORD
    is not a test verdict."
  fi
  echo "$PROG: engine inside the container: server $(cat "$SCRATCH/engine-probe.txt")" >&2
fi

"${DOCKER_BIN:-docker}" run "${DOCKER_ARGS[@]}" "$IMAGE" \
  bash -c '
    set -e
    PATH="$PATH${VIBEIC_SUITE_DOCKER_DIR:+:$VIBEIC_SUITE_DOCKER_DIR}"
    # >>> GIT_OBJECT_PREFLIGHT BLOCK
    # Run inside the actual suite container: host Git may see unmapped alternates.
    if ! git fsck --connectivity-only --no-reflogs --no-dangling HEAD >/dev/null; then
      echo "run_suite_in_eda_image.sh: REFUSED — Git objects are unreadable inside the test container; pytest was not started. Prepare a standalone clone with --dissociate; --no-hardlinks alone is insufficient." >&2
      exit 2
    fi
    # <<< GIT_OBJECT_PREFLIGHT BLOCK
    # ── THE TIME BOUND IS A PRECONDITION, AND IT IS DECLARED ──────────────
    # MEASURED in the pinned image: `import pytest_timeout` -> ModuleNotFoundError
    # (and `import xdist` likewise). pytest then treats every
    # `@pytest.mark.timeout(...)` in the suite as an UNKNOWN MARK: it emits a
    # PytestUnknownMarkWarning and runs the test with NO BOUND AT ALL. Nothing
    # in the session has a time bound, so a wedged test hangs the whole run
    # instead of failing one case -- and the author who wrote the marker has no
    # way to learn that the bound they asked for does not exist.
    #
    # The CALLER-side half of this is already refused: an explicit `--timeout=`
    # is an unrecognized argument, pytest exits 4, and the rc-4 block below
    # names it. The MARKER-side half was silent, which is the whole defect --
    # vibe-ic#1128: a precondition the tests assume must be DECLARED, not
    # assumed. This declares it, in the SAME interpreter that is about to run
    # pytest, so the statement is about the environment that actually runs.
    #
    # IT DECLARES RATHER THAN REFUSES, deliberately and narrowly. Refusing here
    # would stop every run on the image the whole fleet currently uses, for a
    # precondition no caller asked for; and the markers are the TESTS OWN
    # requests, not the caller. Once the image ships the plugin, a refusal
    # becomes the right shape and this line becomes the place to put it.
    # NOTE: this block is inside a single-quoted bash -c body -- an apostrophe
    # here ends the string.
    python3 -c "
import ast, importlib.util as _u, os, re, sys
if _u.find_spec(\"pytest_timeout\") is not None:
    sys.stderr.write(\"[DISCLOSURE] pytest-timeout is present in this image: \"
                     \"@pytest.mark.timeout(...) bounds are ACTIVE\\n\")
else:
    # COUNTED FROM THE AST, NOT FROM A GREP. A regex over the source counts
    # every mark.timeout( in a COMMENT or a DOCSTRING too, and this suite
    # discusses the marker in prose far more often than it uses one: the grep
    # says 49 in 22 files, the AST says 27 call sites in 4. Publishing the
    # grep number would put a figure in a DISCLOSURE that is three times the
    # truth, which is worse than no figure. The regex is kept, but only to
    # PRE-FILTER: parsing 22 candidate files costs nothing, parsing 3836 would.
    _any = re.compile(r\"mark\\.timeout\\(\")
    _f = _t = _b = _z = 0
    for _root, _dirs, _names in os.walk(\"programs/tests\"):
        for _n in _names:
            if not _n.endswith(\".py\"):
                continue
            try:
                _src = open(os.path.join(_root, _n), encoding=\"utf-8\",
                            errors=\"replace\").read()
            except OSError:
                continue
            if not _any.search(_src):
                continue
            try:
                _tree = ast.parse(_src)
            except SyntaxError:
                continue
            _hits = []
            for _node in ast.walk(_tree):
                if (isinstance(_node, ast.Call)
                        and getattr(_node.func, \"attr\", \"\") == \"timeout\"
                        and _node.args):
                    _hits.append(_node.args[0])
            if not _hits:
                continue
            _f += 1
            _t += len(_hits)
            for _a in _hits:
                if isinstance(_a, ast.Constant) and isinstance(_a.value, int):
                    if _a.value:
                        _b += 1
                    else:
                        _z += 1
    sys.stderr.write(
        \"[DISCLOSURE] pytest-timeout is ABSENT from this image: every \"
        \"@pytest.mark.timeout(...) in this session is INERT -- pytest \"
        \"reports it as an unknown mark and runs the test with NO bound. \"
        \"No test in this run has a time bound, so a wedged test hangs the \"
        \"whole session instead of failing one case. MEASURED here, over \"
        \"programs/tests: %d marker(s) in %d file(s), of which %d name a \"
        \"real bound, %d name 0 (no bound asked for) and %d have a \"
        \"non-literal argument this count cannot read -- all of them inert \"
        \"either way. An explicit --timeout= is refused separately (pytest \"
        \"exits 4, unrecognized arguments).\\n\"
        % (_t, _f, _b, _z, _t - _b - _z))
" || true
    exec python3 -m pytest "$@"' bash "$@"
EXIT_RC=$?

# ── THE SUMMARY LINE, AND THE TWO EXIT CODES THAT MEAN NOTHING RAN ────────
# This harness used to end here, handing pytest's exit code back with nothing of
# its own to say. That is what made vibe-ic#2123 readable as clean: the last
# verdict-shaped line in the stream belonged to the in-suite write guard
# ([PASS] suite_write_guard: ...), the summary said "no tests ran", and no line
# in the whole output said the harness itself had produced no verdict.
#
# So every run now ends with ONE line of this harness's own, and the two exit
# codes that mean the session collected nothing are REFUSALS.
#
#     4  pytest's usage error — what a selector naming no file produces
#     5  pytest's EXIT_NO_TESTS_COLLECTED — an empty collection, including one
#        emptied by -k / -m / --deselect after collection
#
# rc 4 IS NOT A HYPOTHETICAL AND IT IS NOT ONLY #2123's OWN REPRODUCER. MEASURED
# 2026-09-07 on 8hd-3, through this harness, on the pinned digest:
#
#     -- -q --timeout=30 <an absolute selector that exists>
#     __main__.py: error: unrecognized arguments: --timeout=30       rc 4
#
# pytest-timeout is not installed in that image, so a CI command line carrying
# `--timeout=` runs NOTHING and, before this block, said so only in a line no
# scrape reads. Stated as a measurement with its date because it is one: if the
# image later ships the plugin, this paragraph is still true about the digest it
# names, and the refusal above claims nothing about any particular option.
#
# Both are non-zero already; being non-zero was never the problem. The problem
# is that their OUTPUT is indistinguishable from a clean run to everything that
# reads it by text, and this stream is read by text:
#
#   tools/core_agent/covered_by.py::classify_run          - FAILED on "no tests ran"
#   tools/ci/gatekeeper_status_poller.py::classify        - error on _NOTHING_RAN
#   programs/pytest_per_file_junit.py::_zero_collect      - rc 5 recorded, never green
#
# Those three already refuse a zero-collect run; they are named here so that the
# harness's own line agrees with them instead of being the one reader that does
# not. `programs/tests/test_bidirectional_controls_are_executed.py` asks the
# same question of a file rather than of a run.
#
# The exit code becomes 2 — this harness's own REFUSED code, the one `die` uses
# — and the original pytest code is named in the text so nothing is lost.
case "$EXIT_RC" in
  4)
    echo "$PROG: REFUSED — pytest exited 4 (usage error): it could not use the" >&2
    echo "    arguments after --, so 0 collected and no tests ran." >&2
    echo "    NOTHING WAS RUN, and a run that ran nothing is not a verdict" >&2
    echo "    about this tree — it is the absence of one. Read the output for" >&2
    echo "    the argument it could not use. TWO SHAPES REACH THIS: an absolute" >&2
    echo "    selector that names no file, and an option this image's pytest does" >&2
    echo "    not have." >&2
    exit 2 ;;
  5)
    echo "$PROG: REFUSED — pytest exited 5 (no tests ran): the selection was" >&2
    echo "    collected and came to 0 collected. NOTHING WAS RUN, and an empty" >&2
    echo "    selection is not a green one — a -k, -m or --deselect that removes" >&2
    echo "    every test leaves exactly this shape, with no failure in the" >&2
    echo "    output for a scrape to find." >&2
    exit 2 ;;
  0)
    echo "$PROG: pytest exited 0 — the selection ran and reported no failure." >&2 ;;
  1)
    echo "$PROG: pytest exited 1 — the selection ran and reported failures." >&2 ;;
  *)
    echo "$PROG: pytest exited $EXIT_RC — not a completed test session; read the" >&2
    echo "    output above before reading this as any kind of verdict." >&2 ;;
esac
exit "$EXIT_RC"
