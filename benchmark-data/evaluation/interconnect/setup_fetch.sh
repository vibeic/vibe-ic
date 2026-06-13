#!/usr/bin/env bash
# Fetch the pinned open interconnect goldens into the gitignored _work/ dir.
# Sources are NOT vendored into the repo (kept lean for v1.0); this clones the
# exact pinned commits from each target's *.manifest.yaml on demand.
#
# Usage:  setup_fetch.sh [ucie|tilelink|aib|litepcie|all]   (default: all)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$HERE/_work"; mkdir -p "$WORK"

# name|repo|commit
TARGETS=(
  "ucie|https://github.com/ucb-bar/uciedigital|db57f8f6a85b20690b512ecdbd76069f401dc076"
  "tilelink|https://github.com/chipsalliance/rocket-chip|55bcad0f59436de98ea510334121de8546b9e9d7"
  "aib|https://github.com/chipsalliance/aib-phy-hardware|a0295cd2b90768c6cfd0795e5754e86dc2b6f747"
  "litepcie|https://github.com/enjoy-digital/litepcie|d1cea9294a7064fdfd777de94627657d53e2198a"
)
want="${1:-all}"
for t in "${TARGETS[@]}"; do
  IFS='|' read -r name repo commit <<<"$t"
  [ "$want" != "all" ] && [ "$want" != "$name" ] && continue
  dst="$WORK/$name"
  if [ -d "$dst/.git" ]; then echo "[$name] present at $dst (skip)"; continue; fi
  echo "[$name] cloning $repo @ ${commit:0:10} ..."
  git clone --filter=blob:none "$repo" "$dst"
  git -C "$dst" checkout -q "$commit"
  echo "[$name] -> $dst @ $(git -C "$dst" rev-parse --short HEAD)"
done
echo "done. (goldens are Chisel for ucie/tilelink — elaborate FIRRTL->Verilog before LEC/PPA)"
