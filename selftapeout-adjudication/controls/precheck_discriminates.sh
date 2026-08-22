#!/bin/bash
# J93 — can the brief's own pre-check return ANYTHING other than NOT_DETERMINED?
#
# All four UNDETERMINED rows rest on `general_precheck` answering NOT_DETERMINED about
# each chip.  A checker that outputs the same thing whatever you show it is not a
# measurement, and NOTHING on this host has ever produced a finished layout -- so the
# question is whether that verdict is about the CHIPS or about the INSTRUMENT.
#
# NEG: a project with no layout        -> must be NOT_DETERMINED
# POS: the same plus ONE file where the pre-check globs.  It is NOT a layout and no
#      claim is made about it; FAIL is the CORRECT answer for it.  The only question
#      is whether the verdict can differ at all.
S=${1:-/tmp/jself_pc}
P=/home/reyerchu/_jself_priv/wt_j80/vibe-ic-marketplace/plugins/vibe-ic/programs
rm -rf "$S"; mkdir -p "$S/neg" "$S/pos/phase3/stage4/gds"
printf 'this is not a GDS. it exists only to occupy a path the pre-check globs.\n' \
  > "$S/pos/phase3/stage4/gds/synthetic_probe.gds"
for t in neg pos; do
  echo "=== $t ==="
  timeout -s INT 300 python3 "$P/general_precheck.py" "$S/$t" 2>&1 \
    | grep -aE '"verdict"|"layouts_found"|"reason"' | head -3
done
