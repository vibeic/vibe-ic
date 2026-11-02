---
name: delivery-ownership-review
description: Resolve a pending complete-source delivery ownership task through a fresh agent and an operator-observed Codex action. Use when ordinary entry or coordinator routing reports DELIVERY_OWNERSHIP_UNRESOLVED.
---

# Review complete-source delivery ownership

This review grants source or physical scope only. It does not grant owner approval,
D1 qualification, a route nature, native completion, or acceptance.

1. Run `python3 programs/delivery_intent.py issue --project PROJECT`. Ordinary
   entry and the coordinator also expose this task. For changed inputs or policy,
   issue a new task with `--fresh`; old responses cannot be upgraded by rehashing.
2. Read the issued task and its complete sources. Dispatch one fresh agent with
   the exact task path and task SHA-256 explicitly in its message. Ask it to follow
   the task's response contract and write strict JSON to the stated response path.
   The existing nature reviewer may handle this separately issued task in the
   same fresh action. Give it both exact tasks and separate response paths.
3. Preserve the exact dispatched message as `dispatch.txt`. Record the actual
   returned agent thread ID, path, requested model, and parent thread ID. Do not
   write a semantic answer yourself or substitute an old nature response.
4. Require the agent's final message to be exactly this JSON shape, with every
   explicitly issued task and the SHA-256 of its exact response file bytes:

   ```json
   {"task_responses":[{"task_sha256":"...","response_sha256":"..."}]}
   ```

5. After receiving actual final completion, export that child's completed Codex
   runtime. A worker's earlier self-export can lack completion. Preserve the
   actual `session_meta` identity and `source.subagent.thread_spawn`, `task_started`,
   `turn_context`, final assistant `message` with `phase=final_answer`, and
   `task_complete` records. Private base instructions are unnecessary. Unsupported
   runtimes remain refused. Do not fabricate events or decrypt the child handoff.
6. Save the trusted operator's observed dispatch as `observation.json`:

   ```json
   {
     "schema":"vibeic.codex-delivery-observation.v1",
     "parent_thread_id":"actual parent",
     "agent_thread_id":"actual child",
     "agent_path":"actual returned path",
     "model":"actual requested model",
     "dispatch_prompt_sha256":"SHA-256 of exact dispatch.txt bytes",
     "task_sha256s":["every explicitly dispatched task SHA-256"]
   }
   ```

7. Import the observed action:

   ```bash
   python3 programs/delivery_intent.py collect --project PROJECT \
     --observation observation.json --runtime-export child.jsonl \
     --dispatch-prompt dispatch.txt --response response.json
   ```

8. Repeat the original entry command. It rechecks original membership, bytes,
   policy, decision, and accepted action before selecting a profile or launching.

The controller retains immutable issuance and acceptance outside the project at
`~/.local/state/vibe-ic/delivery-ownership`. Set
`VIBE_IC_DELIVERY_AUTHORITY_ROOT` to another controller directory outside every
worker output root when needed. The operator must keep it outside worker write
scope. Worker-written project reports never serve as that authority.

This is a cooperative audit. Codex encrypts the task body in the child's handoff,
so the operator's honest observed dispatch binds that body. Completion records
corroborate the child identity and returned response bytes. Hashes and model names
do not authenticate a model or prove the semantic answer. Same-user hostile
operators and compromised runtimes are outside this trust model. Independent
semantic controls and implementation review remain required before integration.
