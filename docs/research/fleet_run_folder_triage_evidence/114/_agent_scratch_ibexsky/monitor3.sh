PID=2333926
R=/home/reyerchu/_agent_scratch_ibexsky/run/ibex
for i in $(seq 1 90); do
  if ! kill -0 $PID 2>/dev/null; then echo "PROCESS_EXITED after ~$((i*120))s"; break; fi
  if [ -f $R/reports/orchestrator/vibe_ic_one_shot.json ]; then echo "ORCHESTRATOR_DONE after ~$((i*120))s"; break; fi
  sleep 120
done
echo "=== final log tail ==="; tail -25 /home/reyerchu/_agent_scratch_ibexsky/run_patched3.log
