# Persona Card: Local LLM Accelerator User
## Interview Answer Key

### Q1: How fast does the chip need to run?
**A:** Not crazy fast. I mean, the models I run at home on my CPU are acceptable speed already—sometimes a few seconds to process a prompt. If your chip can speed that up to something really snappy, like sub-second for common operations, that'd be great. But I'm not trying to compete with a data center. Whatever speed is "reasonable" for this kind of helper chip—you'd know better than me.

### Q2: How much on-chip memory do you need?
**A:** I need enough to hold the weights (the numbers the model was trained with) and the input data, and room for the intermediate results. I don't know exact numbers—maybe a megabyte? A few megabytes? Pick whatever is practical for a small chip. What do chips like this usually have?

### Q3: How much power can the chip use?
**A:** Low. The whole point is I don't want my little machine overheating or draining batteries. It should be way more efficient than running the math on the CPU. Maybe a few watts at most? It's sitting on my desk, so it can't be a heater.

### Q4: Should the chip handle the entire model, or just parts of it?
**A:** Just the heavy multiply parts. The models have a bunch of different layers, but the big number-crunching that slows everything down is in specific places—the attention math and the fully-connected layers. Those are the parts I want to offload. The rest of the model can stay on my CPU.

### Q5: Does it need to do any of the normalization math too (like softmax)?
**A:** I don't know what all that involves. If it's part of the same expensive math, sure, if it's efficient. If it's complicated, I'll do it on the CPU. You pick what makes sense for the chip to do.

### Q6: What should happen when the multiply is done? How should results come back?
**A:** Read them back into my machine's memory so the CPU can keep going with the rest of the model. Simple as that—chip does the math, puts the answer somewhere I can read it, then waits for the next batch.

### Q7: What size matrices are we talking about? (dimensions of the numbers you're multiplying)
**A:** I have no idea. Depends on the model. Small models might be 512 by 512 or 1024 by 1024, bigger ones could be much larger. I don't want to lock myself into supporting only one size. Whatever's flexible is good.

### Q8: What's your manufacturing process preference?
**A:** Open and free, like I said. Something old and boring—28 nanometers, 45 nanometers, whatever's standard and cost-effective. Not exotic. I want to be able to build it or have someone build it without licensing problems. The 48-hour demo I read about used an open process, so that direction.

### Q9: Should it support any standard protocols to talk to the CPU? (like PCIe, or just a simple memory bus?)
**A:** Something simple and standard. I don't care if it's fancy. Whatever my laptop or desktop can plug into or connect to—USB, PCIe, whatever. Just make it easy for my machine to send data to the chip and read results back.

### Q10: Does it need to hold data between runs, or is memory cleared each time?
**A:** I can live with either. If keeping things in memory is simpler or cheaper, that's fine—I can manage my own workflow. If it's easier to clear it fresh each time, that's fine too. Your call.

### Q11: Any specific 4-bit number format, or should I just use what's standard?
**A:** I said 4-bit because I know it saves space and power. You're the expert on what the best format is—signed, unsigned, how to handle overflow. Whatever's standard for this kind of work, use that.

### Q12: How big can the physical chip be, and what's your budget?
**A:** Small enough to sit on a little board next to my CPU. The 48-hour demo chip seemed like a reasonable size to me—not tiny, not huge. And cheap—I want this to be affordable, not thousands of dollars. If it costs more than a couple hundred dollars, I probably won't build it. Practical and cheap.

### Q13: Do you need any debugging or monitoring features?
**A:** Not really. If something goes wrong, I can see it from the CPU side. Maybe a simple status indicator—like "chip is ready", "chip is done"—but nothing fancy. Keep it simple.

### Q14: Should the chip be programmable, or just hard-wired for matrix multiply?
**A:** Hard-wired is fine. I just need it to do one thing well. Don't over-engineer it.

### Q15: Timeline: how soon do you need this?
**A:** Whenever. I'm not in a rush. I know chip design takes time. I'm interested in exploring whether it's possible to make something practical for my use case.

---

## Summary of Opinions vs Deferrals

**Real opinions (user has a stake in these):**
1. **4-bit numbers** — explicitly chosen for memory and power savings
2. **Local/edge helper use case** — not a data-center accelerator, sits next to CPU
3. **Low power budget** — "a few watts max", won't be a heater
4. **Small, cheap, practical** — ~48-hour-demo ambition, couple hundred dollars budget
5. **Open manufacturing process** — boring, free, no licensing complexity
6. **Offload only the multiply parts** — leave the rest to CPU

**Deferred to engineer (user genuinely doesn't know or care):**
- Exact memory sizes
- Specific clock speed
- Matrix dimensions
- Whether to include normalization
- Exact 4-bit format (signed/unsigned/overflow handling)
- Which standard bus/protocol
- Whether data persists between runs
- Debugging feature complexity
- Hard-wired vs programmable trade-off
