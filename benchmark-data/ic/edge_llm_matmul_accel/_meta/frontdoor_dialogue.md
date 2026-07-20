# Front-Door Dialogue — Plain-Language Intake

This is the natural-language conversation between the **IC Expert** (me, speaking
in plain product language — no silicon jargon) and the **User** (a non-expert;
answers taken from `persona_card.md`, the live user's answer key).

The user's opening request (`input/docs/00_user_request.md`) is dialogue turn 1.
Everything below is the elicitation the sufficiency gate needs. Where the user
defers ("you decide / whatever's standard"), that is my cue to **fill** with
expert judgment — those fills are called out in each turn and recorded in
`provenance_ledger.json`.

---

**Turn 1 — User (opening request):**
> I run language models on a little box on my desk. The math-heavy part — all
> those big multiply operations while the model thinks — is slow and burns a lot
> of power. I want a small, cheap, low-power helper chip that just does the
> multiply math really well, using tiny 4-bit numbers, on an old free open
> manufacturing process, about the size/ambition of those 48-hour demo chips.
> Load weights and inputs into its memory, say "go", read the results back.

**Turn 2 — Expert:**
Got it — a small bolt-on helper that takes the heavy multiply work off your
machine so it stays snappy and cool. Before I size it, a few plain questions.
First: how fast does it actually need to feel? Are we trying to beat a data
center, or just make your current "few seconds" feel instant?

**Turn 3 — User (Q1):**
Not crazy fast. Today it's sometimes a few seconds per prompt. If common
operations felt sub-second, great. I'm not competing with a data center —
whatever speed is reasonable for a helper chip, you'd know better.

> **Expert fill:** "reasonable for a helper chip on a free/open process" → I'll
> target a comfortable, low-power **50 MHz** clock. That's an easy, safe speed to
> hit on the open process and keeps power down — the throughput comes from doing
> 256 multiplies at once, not from a high clock.

**Turn 4 — Expert:**
How much scratch memory should live on the chip itself — to hold the weights,
your inputs, and the partial answers?

**Turn 5 — User (Q2):**
Enough for weights, inputs, and intermediate results. I don't know numbers —
maybe a megabyte? A few? Pick what's practical for a small chip.

> **Expert fill + honest correction:** On this old, cheap, open process, on-chip
> memory is physically expensive — "a few megabytes" won't fit on a small, cheap
> die. The practical, standard answer is **tens of kilobytes of fast on-chip
> memory used as a streaming work-buffer** (I'll use **~64 KB total**: a weight
> buffer, an input buffer, and an output buffer). The chip does **not** hold the
> whole model — your machine streams tiles of it through these buffers. That's
> what lets it handle any model size while staying small and cheap.

**Turn 6 — Expert:**
Power ceiling? You said it can't cook your desk.

**Turn 7 — User (Q3):**
Low. A few watts at most. It sits on my desk, it can't be a heater. The whole
point is to be way more efficient than my CPU.

> **Expert fill:** A 4-bit multiply array this size on the open process at 50 MHz
> will draw **well under half a watt** in active use — comfortably inside your
> "a few watts max," and far more efficient per-multiply than a CPU.

**Turn 8 — Expert:**
Should the chip run the whole model, or only the expensive multiply parts?

**Turn 9 — User (Q4):**
Only the heavy multiply parts — the attention math and the fully-connected
layers. The rest can stay on my CPU.

**Turn 10 — Expert:**
There's some "tidying" math around those multiplies — softmax and normalization.
They need division and exponentials, which are a poor fit for a tiny hard-wired
multiply engine. Want those on the chip too, or left on the CPU?

**Turn 11 — User (Q5):**
I don't really know what that involves. If it's cheap, sure; if it's
complicated, I'll do it on the CPU. Your call.

> **Expert fill:** Softmax / layer-normalization are **out of scope** — kept on
> the CPU. The chip does the multiply-accumulate plus one cheap scaling step (see
> Turn 17). This matches "just the heavy multiply parts."

**Turn 12 — Expert:**
When a batch finishes, how do you want the answer back?

**Turn 13 — User (Q6):**
Just put it somewhere I can read it back into my machine's memory, then wait for
the next batch. Chip does the math, drops the answer, waits.

> **Expert fill:** Results land in the on-chip **output buffer**; your machine
> reads them back over the bus after a "done" signal. Chip returns to idle and
> waits for the next "go."

**Turn 14 — Expert:**
What size are the number-grids you multiply? (rows × columns)

**Turn 15 — User (Q7):**
No idea — depends on the model. Maybe 512×512, 1024×1024, sometimes bigger. I
don't want to be locked to one size. Flexible is good.

> **Expert fill:** I'll build a **fixed 16×16 multiply tile** and stream any size
> matrix through it in 16-wide chunks (tiling). So 512×512, 1024×1024, or larger
> all work — the chip is size-agnostic; your machine feeds it tiles.

**Turn 16 — Expert:**
Manufacturing process — you mentioned old, free, open.

**Turn 17 — User (Q8):**
Yes. Old and boring — 28 nm, 45 nm, whatever's standard and cheap. No licensing
headaches. The 48-hour demo used an open process; that direction.

> **Expert fill + honest correction:** The truly free, open, *actually-
> manufacturable* process behind those "48-hour" open-silicon demos is the
> **SkyWater 130 nm open PDK (sky130)** — 28/45 nm aren't available as a free,
> no-licensing, open-shuttle option. So I'll target **sky130** on an Efabless
> chipIgnite / Caravel-class shuttle. That's the boring, standard, open direction
> you asked for, and it's what keeps per-chip cost in the low hundreds.

**Turn 18 — Expert:**
And the number format — you chose 4-bit. Signed or unsigned, and how do we turn
those tiny 4-bit numbers back into real values?

**Turn 19 — User (Q11):**
I picked 4-bit for space and power. You're the expert on the exact format —
signed, unsigned, overflow. Use whatever's standard.

> **Expert fill:** Standard for 4-bit model math is **signed 4-bit integers
> (two's-complement, −8…+7)** for both the weights and the inputs. I multiply and
> add them up into a wide **32-bit running total** (so nothing overflows even for
> big grids), then apply **one scale factor per output row** to convert back to a
> normal-range number, giving an **8-bit result**. That single scaling step is the
> only "dequantize" math on-chip; everything fancier stays on the CPU.

**Turn 20 — Expert:**
How does your machine plug in and talk to the chip?

**Turn 21 — User (Q9):**
Something simple and standard. USB, PCIe, whatever my laptop or desktop can
connect to. Just make it easy to send data and read results.

> **Expert fill + honest correction:** A tiny open-process chip can't host a
> USB/PCIe port directly — those need big analog blocks it doesn't have room for.
> The standard, simple, royalty-free way these open-silicon chips talk to a host
> is a **plain memory-mapped bus (Wishbone)**: your machine writes weights/inputs
> into the chip's memory, writes a "go," and reads results — through a small
> board-level bridge (the carrier board / its management chip) that presents
> itself to your laptop over USB/PCIe. So: simple bus at the chip, familiar
> USB/PCIe at the board.

**Turn 22 — Expert:**
Should the chip remember data between runs, or start fresh each time?

**Turn 23 — User (Q10):**
Either is fine — whatever's simpler or cheaper. I can manage my own workflow.

> **Expert fill:** Simple volatile on-chip memory. Nothing is guaranteed across a
> power-cycle, but **within a session the weight buffer keeps its contents until
> you overwrite them** — so you can load weights once and push many input batches
> through, which is the efficient way to use it.

**Turn 24 — Expert:**
Any debugging or status lights you want?

**Turn 25 — User (Q13):**
Nothing fancy. Maybe a simple "ready" / "done" indicator. I can see problems from
the CPU side.

> **Expert fill:** A **status register** (busy / done / error bits) your machine
> can read, a **done interrupt** line, plus two simple **status pins** ("ready"
> and "done") that can drive LEDs. Nothing more.

**Turn 26 — Expert:**
Fully hard-wired for the multiply, or programmable?

**Turn 27 — User (Q14):**
Hard-wired is fine. It does one thing well. Don't over-engineer it.

> **Expert fill:** **Hard-wired multiply datapath.** The only "programming" is a
> handful of config registers — grid dimensions for the current tile, the scale
> setting, and start/status. No instruction set.

**Turn 28 — Expert:**
Physical size, budget, timeline?

**Turn 29 — User (Q12, Q15):**
Small enough to sit on a little board next to my CPU — about the 48-hour demo
size. Cheap: if it's more than a couple hundred dollars I won't build it. No
rush on timing.

> **Expert fill:** Targeting the **chipIgnite / Caravel user-area footprint
> (~2.9 mm × 3.5 mm user macro, ~10 mm² die)** keeps it demo-sized and puts
> per-chip cost in the low hundreds on a shared shuttle. No schedule constraint
> recorded.

---

**Expert wrap-up (plain language):**
Here's what I'll build you: a small helper chip on the free open 130 nm process,
about the size of those 48-hour demo chips. Inside is a 16-wide-by-16 grid of
tiny 4-bit multipliers that chew through the attention and fully-connected math
of your model. Your machine loads a tile of weights and inputs into the chip's
small on-chip memory over a simple standard bus, flips a "go" switch, and the
chip multiplies, adds everything up, scales it back to normal numbers, and drops
an 8-bit answer into its output memory with a "done" light. Any model size works
because your machine feeds it in tiles. Softmax and the other tidy-up math stay
on your CPU. It runs cool (well under half a watt), at a comfortable 50 MHz, and
should land in the low-hundreds-of-dollars range. Everything else — exact memory
sizes, the multiply-grid size, number format, bus choice, timing — I've filled
in with standard engineering choices, all recorded so you can see what you asked
for versus what I decided.
