#!/bin/bash
# fan the trial list out at concurrency 8, one container per trial
set -u
ROOT=/home/reyerchu/_jxlayer
LIST="${1:-$ROOT/trials.txt}"
cat "$LIST" | xargs -P 8 -n 6 bash "$ROOT/run_trial.sh"
echo ALLDONE > "$ROOT/records/$(basename "$LIST" .txt).done"
