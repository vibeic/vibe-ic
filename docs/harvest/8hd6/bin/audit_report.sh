#!/usr/bin/env bash
# audit_report.sh <RESULT.md> <shard.tsv> -- check the prose against the data.
#
# Every count in a report like this is written by hand at least once, and hand-written counts
# go stale silently whenever the data is re-derived. This run had three of them drift, and
# one was simply wrong from the start ("12 of them KEEP" where the data said 11). A document
# that disagrees with its own table is worth less than no document.
set -uo pipefail
F="${1:?}"; T="${2:?}"; bad=0
chk(){ if [ "$2" = "$3" ]; then printf '  OK   %-38s %s\n' "$1" "$2"
       else printf '  FAIL %-38s doc=%s data=%s\n' "$1" "$2" "$3"; bad=$((bad+1)); fi; }
d(){ grep -v '^#' "$T" | awk -F'\t' "$1" | grep -c ''; }
chk "table rows vs TSV" "$(awk '/^\| checkout \| verdict \| class \| evidence \|/{f=1;next} f&&/^\| `/{n++} END{print n+0}' "$F")" "$(grep -vc '^#' "$T")"
chk "KEEP"   "$(grep -o '\*\*[0-9]* KEEP · [0-9]* DROP\*\*' "$F" | head -1 | grep -o '^..[0-9]*' | grep -o '[0-9]*')" "$(d '$6=="KEEP"')"
chk "DROP"   "$(grep -o '\*\*[0-9]* KEEP · [0-9]* DROP\*\*' "$F" | head -1 | sed 's/.*· \([0-9]*\) DROP.*/\1/')" "$(d '$6=="DROP"')"
chk "volatile rows" "$(grep -o '\*\*[0-9]* rows are marked' "$F" | grep -o '[0-9]*')" "$(d '$14=="yes"')"
chk "KEEP_NOVEL_CONTENT"   "$(awk -F'|' '/^\| `KEEP_NOVEL_CONTENT` \|/{gsub(/ /,"",$3);print $3}' "$F")" "$(d '$7=="KEEP_NOVEL_CONTENT"')"
chk "DROP_ALL_FILES_MATCH" "$(awk -F'|' '/^\| `DROP_ALL_FILES_MATCH` \|/{gsub(/ /,"",$3);print $3}' "$F")" "$(d '$7=="DROP_ALL_FILES_MATCH"')"
chk "/tmp checkouts" "$(grep -o '[0-9]* of the [0-9]* checkouts live under' "$F" | grep -o '^[0-9]*')" "$(d '$3 ~ /^\/tmp/')"
chk "checkout sets identical" "same" "$(diff <(awk '/^\| checkout \| verdict/{f=1;next} f&&/^\| `/{print}' "$F"|sed 's/^| `//; s/`.*//'|sort) <(grep -v '^#' "$T"|cut -f3|sort) >/dev/null && echo same || echo DIFFERENT)"
echo "audit failures: $bad"; [ "$bad" -eq 0 ]
