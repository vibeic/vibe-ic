PID=2246271
R=/home/reyerchu/_agent_scratch_ibexsky/run/ibex
for i in $(seq 1 60); do
  if ! kill -0 $PID 2>/dev/null; then echo "PROCESS_EXITED after $((i*120))s"; break; fi
  if [ -f $R/reports/orchestrator/vibe_ic_one_shot.json ]; then echo "ORCHESTRATOR_DONE after $((i*120))s"; break; fi
  # progress markers
  P2=$( [ -f $R/reports/orchestrator/phase2_one_shot.json ] && echo yes || echo no )
  P3=$( ls -d $R/phase3 2>/dev/null && echo yes || echo no )
  sleep 120
done
echo "=== final log tail ==="; tail -20 /home/reyerchu/_agent_scratch_ibexsky/run_patched2.log
