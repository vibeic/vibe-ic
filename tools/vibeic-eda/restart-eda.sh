#!/usr/bin/env bash
#
# restart-eda.sh — recreate the `vibeic-eda` MCP-EDA container on a chosen image
# tag, faithfully preserving the existing container's mounts / cmd / user /
# workdir. Swaps ONLY the image; everything else is carried over verbatim.
#
# Why this exists: the eda-tools MCP server (.mcp.json) binds the container by
# NAME (`vibeic-eda`), not by image tag — so "use the newest image" means
# `docker rm -f` the old container and `docker run` a new one on the desired
# tag. A `docker run` container is pinned to the image ID that the tag resolved
# to AT CREATION, so moving `latest` to a new build does NOT update a running
# container — you must recreate. This script is that recreate, done safely.
#
# The MCP server process itself needs NO restart: it drives the container via
# `docker exec <name> ...` on every call, so it re-attaches to the new
# same-named container automatically.
#
# Usage:
#   ./restart-eda.sh                      # recreate on the newest vibeic-eda image this host holds, BY DIGEST
#   ./restart-eda.sh 0.2.11               # bare tag  -> vibeic/vibeic-eda:0.2.11
#   ./restart-eda.sh vibeic/vibeic-eda:latest   # full ref honored as-is (explicit floating opt-in)
#   FORCE=1 ./restart-eda.sh              # recreate even if an EDA job is running
#
# Env overrides:
#   NAME=vibeic-eda            container name to manage
#   IMAGE_REPO=vibeic/vibeic-eda   repo prepended to a bare tag argument
#   DESIGNS_DIR=/path/to/your/designs   existing designs dir mounted at /foss/designs (fresh-container fallback only; must already exist)
#   RESTART_EDA_PRINT_IMAGE=1  print the resolved image ref and exit (no docker)
#
# After a successful recreate, confirm the toolchain from Claude Code with the
# MCP tool `eda_doctor` (skip_versions=false) — expect "14/14 checks passed".
#
set -euo pipefail

NAME="${NAME:-vibeic-eda}"
IMAGE_REPO="${IMAGE_REPO:-vibeic/vibeic-eda}"

# EDA tool process names used for the in-flight-job guard.
EDA_PROCS='openroad|yosys|magic|netgen|klayout|iverilog|verilator|ngspice|fault|tclsh'

die() { echo "restart-eda: $*" >&2; exit "${2:-1}"; }

# --- resolve requested image ref -------------------------------------------
# The no-arg default is a DIGEST, asked of `_eda_image.py` — never a floating
# `latest`, because a stale local `latest` would silently recreate the container
# on an outdated toolchain. Floating tags stay available by passing them
# explicitly.
#
# It used to be `$(cat VERSION)` — vibeic-eda's version number stored in this
# repo, which charged a PR here per image release. That file is gone. The helper
# is SHELLED OUT TO rather than reimplemented here: "which image" is one rule,
# and a bash second opinion is how the two copies drift.
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  arg="$1"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  RESOLVER=""
  probe="${SCRIPT_DIR}"
  while [[ "$probe" != "/" ]]; do
    cand="${probe}/vibe-ic-marketplace/plugins/vibe-ic/programs/_eda_image.py"
    [[ -f "$cand" ]] && { RESOLVER="$cand"; break; }
    probe="$(dirname "$probe")"
  done
  [[ -n "$RESOLVER" ]] || die \
    "no tag argument and no _eda_image.py above ${SCRIPT_DIR} — pass a tag explicitly"
  arg="$(python3 "$RESOLVER" --judged)" || die \
    "no tag argument and ${RESOLVER} could not name an image on this host — pass a tag explicitly"
  [[ -n "$arg" ]] || die "${RESOLVER} --judged printed nothing — pass a tag explicitly"
fi
if [[ "$arg" == *:* || "$arg" == */* ]]; then
  IMAGE="$arg"                    # a full ref (repo[:tag] or repo/path) — honor as-is
else
  IMAGE="${IMAGE_REPO}:${arg}"    # a bare tag — prepend the repo
fi
if [[ "${RESTART_EDA_PRINT_IMAGE:-0}" == "1" ]]; then
  echo "$IMAGE"; exit 0           # resolution-only mode (used by the regression tests)
fi
echo "== target image : ${IMAGE}"

command -v docker >/dev/null 2>&1 || die "docker CLI not found on PATH"

# --- the image must exist locally (never silently pull) --------------------
docker image inspect "$IMAGE" >/dev/null 2>&1 || die \
  "image '${IMAGE}' not found locally. Build or pull it first, e.g.:
       docker pull ${IMAGE}
   (available local tags:)
$(docker images "${IMAGE_REPO}" --format '       {{.Repository}}:{{.Tag}} {{.ID}}' 2>/dev/null | sort -u)" 1
TARGET_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
echo "   image id     : ${TARGET_ID}"

# --- capture existing container config (or fall back to canonical defaults) --
declare -a BINDS=() CMD=()
USER_SPEC="" WORKDIR=""

if docker container inspect "$NAME" >/dev/null 2>&1; then
  OLD_IMG="$(docker inspect "$NAME" --format '{{.Config.Image}}')"
  echo "== existing container '${NAME}' found (image: ${OLD_IMG}) — cloning its config"

  # in-flight EDA job guard (skip idle sleep/startup/VNC).
  if docker top "$NAME" -o args 2>/dev/null | grep -iqE "$EDA_PROCS"; then
    if [[ "${FORCE:-0}" != "1" ]]; then
      echo "-- an EDA tool process is running inside '${NAME}':" >&2
      docker top "$NAME" -o pid,args 2>/dev/null | grep -iE "$EDA_PROCS" >&2 || true
      die "refusing to recreate mid-job. Re-run with FORCE=1 to override." 2
    fi
    echo "-- FORCE=1: recreating despite a running EDA job."
  fi

  while IFS= read -r b; do [[ -n "$b" ]] && BINDS+=( -v "$b" ); done \
    < <(docker inspect "$NAME" --format '{{range .HostConfig.Binds}}{{println .}}{{end}}')
  USER_SPEC="$(docker inspect "$NAME" --format '{{.Config.User}}')"
  WORKDIR="$(docker inspect "$NAME"  --format '{{.Config.WorkingDir}}')"
  while IFS= read -r c; do [[ -n "$c" ]] && CMD+=( "$c" ); done \
    < <(docker inspect "$NAME" --format '{{range .Config.Cmd}}{{println .}}{{end}}')
else
  echo "== no existing container '${NAME}' — using canonical vibeic-eda defaults"
  # Path-portability: NEVER default a designs dir under $HOME — docker would
  # create a missing bind-mount source root-owned (the phantom-directory bug).
  # With no existing container to preserve, require the user to name an EXISTING
  # directory via DESIGNS_DIR (or VIBEIC_DESIGNS); refuse rather than invent one.
  DESIGNS_DIR="${DESIGNS_DIR:-${VIBEIC_DESIGNS:-}}"
  [[ -n "$DESIGNS_DIR" ]] || die \
    "no existing '${NAME}' container to preserve, and neither DESIGNS_DIR nor VIBEIC_DESIGNS is set — point one at your existing designs dir, e.g.  DESIGNS_DIR=/path/to/your/designs ${0##*/} ${1:-<tag>}"
  [[ "$DESIGNS_DIR" == /* ]] || die \
    "DESIGNS_DIR must be an absolute path (got '${DESIGNS_DIR}') — a relative path would become a docker named volume, not a bind mount"
  [[ -d "$DESIGNS_DIR" ]] || die \
    "DESIGNS_DIR '${DESIGNS_DIR}' does not exist — create it deliberately first (the installer never creates a workspace for you)"
  BINDS=( -v "${DESIGNS_DIR}:${DESIGNS_DIR}" -v "${DESIGNS_DIR}:/foss/designs" )
  USER_SPEC="$(id -u)"
  WORKDIR="/foss/designs"
  CMD=( --skip sleep infinity )
fi

echo "   binds        : ${BINDS[*]:-<none>}"
echo "   user/workdir : ${USER_SPEC:-<image default>} / ${WORKDIR:-<image default>}"
echo "   cmd          : ${CMD[*]:-<image default>}   (entrypoint stays image-baked)"

# --- recreate --------------------------------------------------------------
echo "== removing old container (if any)"
docker rm -f "$NAME" >/dev/null 2>&1 || true

# --- memory ceiling --------------------------------------------------------
# MEASURED 2026-08-19 across a seven-machine fleet: 45 EDA containers were
# running with `HostConfig.Memory == 0`. A container with no cgroup limit does
# not share the host's memory, it IS the host's memory, and `ulimit -v` inside
# the image is `unlimited`, so a tool never gets an allocation failure it can
# report. On two of those machines a yosys took the whole box — 54 GB apiece
# for two siblings, then 109 GB for the survivor once the kernel had killed its
# twin and freed the room — and what actually died was the desktop session,
# because the OOM killer picks by oom_score_adj, not by who caused it.
#
# The ceiling comes from programs/_docker_memory.py so the shell and the Python
# `docker run` callers cannot drift apart. Exit 2 from that helper means it
# could not determine a ceiling; that is a REFUSAL, never a fallback to
# unbounded — a safety guard whose failure mode is "no guard" reports success
# while leaving exactly the configuration that took a host down.
#
#   VIBEIC_DOCKER_MEMORY=48g   explicit ceiling
#   VIBEIC_DOCKER_MEMORY=0     opt out on purpose
_MEMTOOL="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/../../vibe-ic-marketplace/plugins/vibe-ic/programs/_docker_memory.py"
declare -a MEMFLAGS=()
if [[ -f "$_MEMTOOL" ]]; then
  if _memout="$(python3 "$_MEMTOOL" --flags 2>&1)"; then
    while IFS= read -r _f; do [[ -n "$_f" ]] && MEMFLAGS+=( "$_f" ); done <<< "$_memout"
  else
    die "could not determine a container memory ceiling: ${_memout}"
  fi
else
  die "missing ${_MEMTOOL} — refusing to create '${NAME}' with no memory ceiling.
   Set VIBEIC_DOCKER_MEMORY=<size> to name one, or VIBEIC_DOCKER_MEMORY=0 to opt out."
fi
echo "   memory       : ${MEMFLAGS[*]:-<unlimited — opted out>}"

declare -a RUN=( docker run -d --name "$NAME" )
[[ -n "$USER_SPEC" ]] && RUN+=( -u "$USER_SPEC" )
[[ -n "$WORKDIR"  ]] && RUN+=( -w "$WORKDIR" )
[[ ${#MEMFLAGS[@]} -gt 0 ]] && RUN+=( "${MEMFLAGS[@]}" )
RUN+=( "${BINDS[@]}" "$IMAGE" )
[[ ${#CMD[@]} -gt 0 ]] && RUN+=( "${CMD[@]}" )

echo "== ${RUN[*]}"
"${RUN[@]}" >/dev/null

# --- verify ----------------------------------------------------------------
NEW_ID="$(docker inspect "$NAME" --format '{{.Image}}')"
echo
docker ps --filter "name=^/${NAME}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
if [[ "$NEW_ID" == "$TARGET_ID" ]]; then
  echo "== OK: container image id matches ${IMAGE}"
else
  die "container image id ${NEW_ID} != target ${TARGET_ID}" 3
fi
echo
echo "Next: in Claude Code run the MCP tool  eda_doctor (skip_versions=false)"
echo "      — expect '14/14 checks passed' before driving the flow."
