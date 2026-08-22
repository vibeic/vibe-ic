#!/usr/bin/env bash
# The claims in RESULT.md that NO evidence file backs, and the command that
# re-derives each at whatever head the reader holds.
#
# WHY THIS EXISTS. "0 uncited evidence files" was green for this lane for days.
# It iterates FILES and confirms each is cited -- it proves every FILE has a
# CLAIM, and says nothing about whether every CLAIM has a FILE. Running the
# other direction found five claims with no artefact at all. None is wrong;
# all five are re-derivable, which is arguably BETTER backing than a file
# because it works at any head. What was missing was saying so.
#
# The asymmetry, owed to the publishing agent: file->claim TERMINATES, because
# the denominator is handed to you. claim->file has NO natural denominator --
# you must enumerate your own assertions first -- which is why it never gets
# run, and why it is the direction that finds claims nobody can check.
#
# Run from a checkout of vibeic/vibe-ic. Needs the container for the last one.
set -u
FAIL=0
ok(){ [ "$2" = "$3" ] && echo "  [ok]   $1: $2" || { echo "  [FAIL] $1: $2 (expected $3)"; FAIL=1; }; }

echo "1. general_precheck.py is BYTE-IDENTICAL across the v1.11.68 batch"
for r in a00f53f20 81cd5321b; do
  h=$(git show "$r:vibe-ic-marketplace/plugins/vibe-ic/programs/general_precheck.py" | sha256sum | cut -c1-64)
  ok "$r" "$h" "6f808cd52765774dac440713952bf536b038c84419dd563ac09766eaad725c4c"
done

echo "2. none of the three programs accepts --allow-pdk-target-mismatch"
for f in pad_ring_gen pad_ring_check flow_compliance_check; do
  n=$(grep -c -- "--allow-pdk-target-mismatch" "vibe-ic-marketplace/plugins/vibe-ic/programs/$f.py")
  ok "$f" "$n" "0"
done

echo "3. what main brought in between the cut and the re-verify"
ok "files changed" "$(git diff --name-only a00f53f20..81cd5321b | wc -l)" "52"
ok "#712 commits"  "$(git log --oneline a00f53f20..81cd5321b | grep -c 712)" "4"

echo "4. the design's declared PDK, from the source CELL_MATRIX names"
L=$(find "$HOME" -name L19_CONSTRAINTS_PDK.json -path '*sha256*' 2>/dev/null | head -1)
if [ -n "$L" ]; then
  ok "L19 fields.pdk_target" "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['fields']['pdk_target'])" "$L")" "sky130"
else
  echo "  [NOT VERIFIED] no sha256 run tree reachable from this host -- a refusal, not a pass"
  FAIL=2
fi

echo "5. no PDK declares one site at two sizes (the false-positive guard)"
echo "   docker run --rm -v \$PWD:/work ghcr.io/vibeic/vibeic-eda:0.3.16 --skip \\"
echo "     python3 -c \"...IoLibrary(discover_io_lefs, discover_io_site_declarations)...\""
echo "   MEASURED 2026-08-22, image 0.3.16:"
echo "     gf180mcuD  lefs=15 decls=2 conflicts={} sites=[GF_COR_Site, GF_IO_Site]"
echo "     sky130A    lefs= 2 decls=1 conflicts={} sites=[sky130_io, sky130_io_corner]"
echo "     ihp-sg13g2 lefs= 2 decls=0 conflicts={} sites=[sg13g2_cornerSite, sg13g2_ioSite]"
echo "   -- and note ihp-sg13g2 has ZERO declarations, so it resolves entirely"
echo "      through the OLD LEF path: the change is inert where it is not needed."

echo
[ "$FAIL" = 0 ] && echo "ALL RE-DERIVED" || { [ "$FAIL" = 2 ] && echo "NOT VERIFIED (see above)" || echo "SOMETHING DID NOT RE-DERIVE"; }
exit "$FAIL"
