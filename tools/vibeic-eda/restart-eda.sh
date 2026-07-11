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
#   ./restart-eda.sh                      # recreate on the PINNED vibeic/vibeic-eda:$(cat VERSION)
#   ./restart-eda.sh 0.2.11               # bare tag  -> vibeic/vibeic-eda:0.2.11
#   ./restart-eda.sh vibeic/vibeic-eda:latest   # full ref honored as-is (explicit floating opt-in)
#   FORCE=1 ./restart-eda.sh              # recreate even if an EDA job is running
#
# Env overrides:
#   NAME=vibeic-eda            container name to manage
#   IMAGE_REPO=vibeic/vibeic-eda   repo prepended to a bare tag argument
#   DESIGNS_DIR=~/AI_IC_design designs dir mounted at /foss/designs (fresh-container fallback only)
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
# The no-arg default is the PINNED version from the VERSION file next to this
# script (the image's single source of truth), never a floating `latest`: a
# stale local `latest` would silently recreate the container on an outdated
# toolchain. Floating tags stay available by passing them explicitly.
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  arg="$1"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [[ -f "${SCRIPT_DIR}/VERSION" ]] || die \
    "no tag argument and no VERSION file at ${SCRIPT_DIR}/VERSION — pass a tag explicitly"
  arg="$(tr -d '[:space:]' < "${SCRIPT_DIR}/VERSION")"
  [[ -n "$arg" ]] || die "VERSION file ${SCRIPT_DIR}/VERSION is empty — pass a tag explicitly"
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
  # Generic defaults (no host-specific paths): designs dir from $DESIGNS_DIR
  # (created if missing so docker doesn't create it root-owned), $HOME mounted
  # through so in-container paths match the host's.
  [[ -n "${HOME:-}" ]] || die \
    "HOME is not set — run as your normal user (the fallback mounts need it)"
  DESIGNS_DIR="${DESIGNS_DIR:-${HOME}/AI_IC_design}"
  [[ "$DESIGNS_DIR" == /* ]] || die \
    "DESIGNS_DIR must be an absolute path (got '${DESIGNS_DIR}') — a relative path would become a docker named volume, not a bind mount"
  mkdir -p "$DESIGNS_DIR"
  BINDS=( -v "${DESIGNS_DIR}:/foss/designs" -v "${HOME}:${HOME}" )
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

declare -a RUN=( docker run -d --name "$NAME" )
[[ -n "$USER_SPEC" ]] && RUN+=( -u "$USER_SPEC" )
[[ -n "$WORKDIR"  ]] && RUN+=( -w "$WORKDIR" )
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
