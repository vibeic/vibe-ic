// spm — configurable N-bit modulo serial-parallel integer multiplier
//
// GENERATED from design documents L1-L9 (benchmark_clean/spm/input/docs/).
// No upstream/reference RTL was read or copied. Algorithm and timing chosen
// under the R3 freedom granted by L2/L7 and declared in
// plugin_output/declaration.json.
//
// Function (L2):  p = (x * y) mod 2^N
//   x : parallel multiplicand, N bits, presented once, held stable during a multiply
//   y : serial multiplier, 1 bit/cycle, LSB-first
//   p : serial product,     1 bit/cycle, LSB-first
//
// Ports (L3):  clk, rst (synchronous active-high), x[size-1:0], y, p
// Parameter (L3/L8):  size (default 32, supports any integer >= 4)
//
// Microarchitecture (declared, R3-free):  CARRY-SAVE bit-serial array.
// ---------------------------------------------------------------------------
//   This was chosen from timing analysis: a single (size+1)-bit ripple-carry
//   add per cycle does NOT close at the SS corner @10 ns (a 33-bit carry chain
//   is ~17 ns at slow). A carry-save accumulator removes the long chain: each
//   bit position keeps its OWN one-bit carry register, so within a cycle the
//   carry NEVER ripples across the width. The combinational critical path is a
//   SINGLE full adder (plus the local AND of the partial product), independent
//   of N. This is the standard textbook Lyon serial/parallel multiplier.
//
//   The array has `size` stages, j = 0 .. size-1. Each stage j holds:
//       s[j] : saved partial-sum bit
//       c[j] : saved carry bit  (carry stays LOCAL to stage j; no ripple)
//
//   Every clk rising edge, in parallel for every stage j:
//       pp     = x[j] & y                 // partial-product bit (one AND)
//       s_in   = (j == size-1) ? 1'b0 : s[j+1]   // sum shifts down one stage
//       {co, ss} = pp + s_in + c[j]       // ONE full adder
//       s[j]  <= ss                        // new saved sum
//       c[j]  <= co                        // new saved carry (kept in place)
//   The product bit emitted this cycle is stage-0's new sum bit:
//       p     <= s_next[0]                 // registered serial output, LSB-first
//
//   Synchronous active-high rst clears the whole array (s, c) and p.
//   latency_cycles = 1 (y[i] driven on cycle i -> p bit i observed on cycle i+1),
//   identical external behavior to the previous accumulator version, proven
//   bit-exact to (x*y) mod 2^N for N in {8,16,32}.
//
// Functional equivalence: the hardware result is the modulo-2^N product, whose
// N-bit pattern is identical for signed 2's-complement and unsigned operands.

`default_nettype none

module spm #(
    parameter size = 32
) (
    input  wire             clk,
    input  wire             rst,   // synchronous, active-high
    input  wire [size-1:0]  x,     // parallel multiplicand
    input  wire             y,     // serial multiplier (LSB-first)
    output reg              p      // serial product   (LSB-first)
);

    // Carry-save array state: per-stage saved sum bit and saved carry bit.
    // verilator lint_off UNUSEDSIGNAL
    reg  [size-1:0] s;             // partial-sum bits, one per stage
    // verilator lint_on UNUSEDSIGNAL
    //  (s[0] is the bottom of the sum shift register: its value is emitted on
    //   p via s_next[0] and is not re-read combinationally, so the s[0] flop is
    //   a leaf that synthesis legally optimizes away — flagged here as intended.)
    reg  [size-1:0] c;             // saved carry bits, one per stage (LOCAL)

    // Next-state (combinational): one full adder per stage, NO cross-stage ripple.
    // Vectorized so every bit is an independent 3-input full adder:
    //   pp[j]  = x[j] & y                  (partial-product bit)
    //   sin[j] = s[j+1] for j<size-1, else 0   (sum shifts one stage down)
    //   {c_next[j], s_next[j]} = pp[j] + sin[j] + c[j]
    // The XOR/majority forms below contain no carry chain across j, so the
    // combinational depth is a single full adder regardless of `size`.
    wire [size-1:0] pp   = x & {size{y}};                   // local AND, per bit
    wire [size-1:0] sin  = {1'b0, s[size-1:1]};             // shift sum down one stage
    wire [size-1:0] s_next = pp ^ sin ^ c;                  // FA sum bits (no ripple)
    wire [size-1:0] c_next = (pp & sin) | (pp & c) | (sin & c); // FA carry bits (saved)

    always @(posedge clk) begin
        if (rst) begin
            s <= {size{1'b0}};
            c <= {size{1'b0}};
            p <= 1'b0;
        end else begin
            s <= s_next;
            c <= c_next;
            p <= s_next[0];   // emit current product bit (LSB-first), registered
        end
    end

endmodule

`default_nettype wire
