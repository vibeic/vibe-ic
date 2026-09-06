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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# EDA tool process names used for the in-flight-job guard.
EDA_PROCS='openroad|yosys|magic|netgen|klayout|iverilog|verilator|ngspice|fault|tclsh'

die() { echo "restart-eda: $*" >&2; exit "${2:-1}"; }

# The same script is shipped in two layouts:
#
#   repository: <repo>/tools/vibeic-eda/restart-eda.sh
#   installed:  <plugin>/tools/vibeic-eda/restart-eda.sh
#
# Find a plugin program in either layout.  Keeping this lookup here means the
# shipped remediation exercises the same image and memory policy as the source
# checkout instead of becoming a standalone copy that silently drifts.
find_plugin_program() {
  local filename="$1" probe="$SCRIPT_DIR" candidate
  while [[ "$probe" != "/" ]]; do
    for candidate in \
      "$probe/programs/$filename" \
      "$probe/vibe-ic-marketplace/plugins/vibe-ic/programs/$filename"; do
      [[ -f "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    done
    probe="$(dirname "$probe")"
  done
  return 1
}

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
  RESOLVER="$(find_plugin_program _eda_image.py || true)"
  [[ -n "$RESOLVER" ]] || die \
    "no tag argument and no plugin programs/_eda_image.py above ${SCRIPT_DIR} — pass a tag explicitly"
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
#
# MOUNTS ARE DECLARED IN TWO PLACES, NOT ONE. A container created with `-v`
# records its declarations in `.HostConfig.Binds`; a container created with
# `--mount` records them in `.HostConfig.Mounts` and leaves `Binds` NULL. This
# script used to read `Binds` alone, so recreating a `--mount`-declared
# container produced an EMPTY mount array. Measured 2026-09-06 on a fleet host:
# a container declaring two writable binds (`binds=0 mounts=2`) was replaced by
# one with none — silently, while cmd, user, workdir and the memory ceiling were
# all carried over correctly, and the health check still reported healthy because
# it does not look at mounts. Both declaration forms are cloned now, deduplicated
# by DESTINATION, retaining read-only and propagation settings.
declare -a BINDS=() CMD=()
declare -a MOUNT_SRC=() MOUNT_DST=() MOUNT_RO=() MOUNT_TYPE=()
USER_SPEC="" WORKDIR="" HAVE_OLD=0

# add_mount SOURCE DESTINATION OPTS [TYPE] — first declaration of a destination
# wins, so a legacy Bind and a structured Mount naming the same target produce
# one argument rather than two conflicting ones.
add_mount() {
  local src="$1" dst="$2" opts="$3" type="${4:-bind}" i
  [[ -n "$dst" ]] || return 0
  for ((i = 0; i < ${#MOUNT_DST[@]}; i++)); do
    [[ "${MOUNT_DST[i]}" == "$dst" ]] && return 0
  done
  MOUNT_SRC+=( "$src" ); MOUNT_DST+=( "$dst" ); MOUNT_TYPE+=( "$type" )
  if [[ ",${opts}," == *",ro,"* ]]; then MOUNT_RO+=( ro ); else MOUNT_RO+=( rw ); fi
  if [[ "$type" == "tmpfs" ]]; then
    BINDS+=( --tmpfs "$dst" )
  elif [[ -n "$opts" ]]; then
    BINDS+=( -v "${src}:${dst}:${opts}" )
  else
    BINDS+=( -v "${src}:${dst}" )
  fi
}

if docker container inspect "$NAME" >/dev/null 2>&1; then
  HAVE_OLD=1
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

  # legacy `-v` declarations: SOURCE:DESTINATION[:OPTIONS]
  while IFS= read -r b; do
    [[ -n "$b" ]] || continue
    _bsrc="${b%%:*}"; _brest="${b#*:}"; _bdst="${_brest%%:*}"
    if [[ "$_brest" == *:* ]]; then _bopts="${_brest#*:}"; else _bopts=""; fi
    add_mount "$_bsrc" "$_bdst" "$_bopts" bind
  done < <(docker inspect "$NAME" --format '{{range .HostConfig.Binds}}{{println .}}{{end}}')

  # structured `--mount` declarations, which leave `Binds` null.
  while IFS='|' read -r _mtype _msrc _mdst _mro _mprop; do
    [[ -n "$_mdst" ]] || continue
    _mopts=""
    [[ "$_mro" == "true" ]] && _mopts="ro"
    if [[ -n "$_mprop" && "$_mprop" != "<no value>" ]]; then
      _mopts="${_mopts:+${_mopts},}${_mprop}"
    fi
    add_mount "$_msrc" "$_mdst" "$_mopts" "${_mtype:-bind}"
  done < <(docker inspect "$NAME" --format '{{range .HostConfig.Mounts}}{{.Type}}|{{.Source}}|{{.Target}}|{{.ReadOnly}}|{{if .BindOptions}}{{.BindOptions.Propagation}}{{end}}{{println}}{{end}}')

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
  add_mount "$DESIGNS_DIR" "$DESIGNS_DIR" "" bind
  add_mount "$DESIGNS_DIR" "/foss/designs" "" bind
  USER_SPEC="$(id -u)"
  WORKDIR="/foss/designs"
  CMD=( --skip sleep infinity )
fi

echo "   binds        : ${BINDS[*]:-<none>}"
echo "   mounts       : ${#MOUNT_DST[@]} declared"
for ((_i = 0; _i < ${#MOUNT_DST[@]}; _i++)); do
  printf '                  %s -> %s (%s, %s)\n' \
    "${MOUNT_SRC[_i]:-<anonymous>}" "${MOUNT_DST[_i]}" "${MOUNT_TYPE[_i]}" "${MOUNT_RO[_i]}"
done
echo "   user/workdir : ${USER_SPEC:-<image default>} / ${WORKDIR:-<image default>}"
echo "   cmd          : ${CMD[*]:-<image default>}   (entrypoint stays image-baked)"

# --- PREFLIGHT: everything that can refuse must refuse BEFORE anything is
# destroyed. The memory ceiling used to be derived AFTER `docker rm -f`, so a
# refusal there left the host with no container at all.
for ((_i = 0; _i < ${#MOUNT_DST[@]}; _i++)); do
  [[ "${MOUNT_TYPE[_i]}" == "bind" ]] || continue   # named volumes/tmpfs have no host path
  _msrc="${MOUNT_SRC[_i]}"
  [[ "$_msrc" == /* ]] || continue                  # a bare name is a named volume
  [[ -e "$_msrc" ]] || die \
    "mount source '${_msrc}' (for ${MOUNT_DST[_i]}) does not exist — refusing to recreate '${NAME}'. Nothing was stopped or removed." 4
done

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
_MEMTOOL="$(find_plugin_program _docker_memory.py || true)"
declare -a MEMFLAGS=()
if [[ -n "$_MEMTOOL" && -f "$_MEMTOOL" ]]; then
  if _memout="$(python3 "$_MEMTOOL" --flags 2>&1)"; then
    while IFS= read -r _f; do [[ -n "$_f" ]] && MEMFLAGS+=( "$_f" ); done <<< "$_memout"
  else
    die "could not determine a container memory ceiling: ${_memout}"
  fi
else
  die "missing ${_MEMTOOL:-plugin programs/_docker_memory.py} — refusing to create '${NAME}' with no memory ceiling.
   Set VIBEIC_DOCKER_MEMORY=<size> to name one, or VIBEIC_DOCKER_MEMORY=0 to opt out."
fi
echo "   memory       : ${MEMFLAGS[*]:-<unlimited — opted out>}"

declare -a RUN=( docker run -d --name "$NAME" )
[[ -n "$USER_SPEC" ]] && RUN+=( -u "$USER_SPEC" )
[[ -n "$WORKDIR"  ]] && RUN+=( -w "$WORKDIR" )
[[ ${#MEMFLAGS[@]} -gt 0 ]] && RUN+=( "${MEMFLAGS[@]}" )
[[ ${#BINDS[@]} -gt 0 ]] && RUN+=( "${BINDS[@]}" )
RUN+=( "$IMAGE" )
[[ ${#CMD[@]} -gt 0 ]] && RUN+=( "${CMD[@]}" )

# --- recreate, keeping the old container until readback passes --------------
ROLLBACK=""
restore_rollback() {
  [[ -n "$ROLLBACK" ]] || return 0
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rename "$ROLLBACK" "$NAME" >/dev/null 2>&1 || true
  docker start "$NAME" >/dev/null 2>&1 || true
  echo "-- rolled back: the previous '${NAME}' container was restored" >&2
}

if [[ "$HAVE_OLD" == "1" ]]; then
  ROLLBACK="${NAME}-rollback-$$"
  docker rm -f "$ROLLBACK" >/dev/null 2>&1 || true
  docker rename "$NAME" "$ROLLBACK" >/dev/null || die \
    "could not rename existing '${NAME}' aside — nothing was destroyed" 5
  docker stop "$ROLLBACK" >/dev/null 2>&1 || true
  echo "== old container kept as '${ROLLBACK}' until readback passes"
else
  docker rm -f "$NAME" >/dev/null 2>&1 || true
fi

echo "== ${RUN[*]}"
if ! "${RUN[@]}" >/dev/null; then
  restore_rollback
  die "docker run failed" 6
fi

# --- verify ----------------------------------------------------------------
# The readback checks the MOUNTS as well as the image id. An image-id check that
# passes while every mount is gone is exactly how the 2026-09-06 loss reached a
# host: `== OK: container image id matches` was printed over an empty mount set.
NEW_ID="$(docker inspect "$NAME" --format '{{.Image}}')"
echo
docker ps --filter "name=^/${NAME}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'

READBACK_FAIL=""
_fail() { READBACK_FAIL="${READBACK_FAIL:+${READBACK_FAIL}; }$*"; }
[[ "$NEW_ID" == "$TARGET_ID" ]] || _fail "container image id ${NEW_ID} != target ${TARGET_ID}"

declare -A GOT_SRC=() GOT_RW=()
while IFS='|' read -r _gdst _gsrc _grw; do
  [[ -n "$_gdst" ]] || continue
  GOT_SRC["$_gdst"]="$_gsrc"; GOT_RW["$_gdst"]="$_grw"
done < <(docker inspect "$NAME" --format '{{range .Mounts}}{{.Destination}}|{{.Source}}|{{.RW}}{{println}}{{end}}')

for ((_i = 0; _i < ${#MOUNT_DST[@]}; _i++)); do
  _d="${MOUNT_DST[_i]}"
  if [[ -z "${GOT_SRC[$_d]+x}" ]]; then
    _fail "declared mount ${_d} is absent from the recreated container"
    continue
  fi
  if [[ "${MOUNT_TYPE[_i]}" == "bind" && "${MOUNT_SRC[_i]}" == /* \
        && "${GOT_SRC[$_d]}" != "${MOUNT_SRC[_i]}" ]]; then
    _fail "mount ${_d} came back from '${GOT_SRC[$_d]}', not '${MOUNT_SRC[_i]}'"
  fi
  _want_rw=true; [[ "${MOUNT_RO[_i]}" == "ro" ]] && _want_rw=false
  if [[ -n "${GOT_RW[$_d]}" && "${GOT_RW[$_d]}" != "$_want_rw" ]]; then
    _fail "mount ${_d} came back RW=${GOT_RW[$_d]}, expected ${_want_rw}"
  fi
done

if [[ -n "$READBACK_FAIL" ]]; then
  restore_rollback
  die "readback failed: ${READBACK_FAIL}" 3
fi

echo "== OK: container image id matches ${IMAGE}"
echo "== OK: all ${#MOUNT_DST[@]} declared mount(s) present after readback"
if [[ -n "$ROLLBACK" ]]; then
  docker rm -f "$ROLLBACK" >/dev/null 2>&1 || true
fi
echo
echo "Next: in Claude Code run the MCP tool  eda_doctor (skip_versions=false)"
echo "      — expect '14/14 checks passed' before driving the flow."
