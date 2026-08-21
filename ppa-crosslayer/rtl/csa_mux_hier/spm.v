//============================================================================
// CROSS-LAYER SEARCH CANDIDATE — the lever moved, and the sentence in the
// design's OWN input documents that leaves it to the implementation.
// levers   : arithmetic_architecture  carry-save, mux-form majority  AND
//            module_hierarchy         flat -> split-by-function
// authority: phase1/input_doc/L2_architecture.txt:11
//            r3_multiple_correct: "PASS — 演算法/結構由 Plugin 自選,只要功能等價、時序滿足"
// equivalence: cycle_exact (state encoding and latency both unchanged)
//============================================================================
//============================================================================
// spm — serial-parallel modulo-2^size integer multiplier
//----------------------------------------------------------------------------
// Authored from the L1-L9 design documents only (clean-room, §4.05).
//
// FUNCTION (L2):   p = (x * y) mod 2^size
//   x : parallel multiplicand, `size` bits, presented once and held stable
//   y : serial multiplier,     1 bit per clock
//   p : serial product,        1 bit per clock
//
// DECLARED CHOICES (L2/L3/L7 leave these to the implementer — see
// plugin_output/declaration.json):
//   bit_order        = LSB_first   (y[0] first, p[0] first)
//   reset_polarity   = active_high, SYNCHRONOUS (L3)
//   latency_cycles   = 2           (y bit j is captured by the posedge ending
//                                   cycle j; product bit j is driven on p two
//                                   cycles later)
//   integer_encoding = signed_2c   (bit-identical to unsigned mod 2^size)
//   multiplier_algorithm = carry_save_serial_parallel_array
//
// ARCHITECTURE
//   A `size`-cell carry-save accumulator. Each clock the row x*y_j is added to
//   the running accumulator held in redundant (sum, carry) form; the result is
//   shifted right by one, and the bit shifted out is the next product bit.
//
//   Weight bookkeeping for cell i:
//     m[i]      = x[i] & y_j          weight 2^i   (partial-product row)
//     {co,so}[i]= m[i] + s[i] + c[i]  so weight 2^i, co weight 2^(i+1)
//   After the >>1 shift, so[i] carries weight 2^(i-1) so it is stored into
//   s[i-1]; co[i] carries weight 2^i so it is stored into c[i]. so[0] leaves
//   the array as the product bit.
//
//   The critical path is exactly one AND + one full adder, independent of
//   `size`, which is what lets the array close timing at the L9 10 ns target.
//
// SERIAL-OPERAND BROADCAST (physical-design driven, functionally neutral)
//   `y` is the one signal that must reach ALL `size` partial-product cells, so
//   it is the design's only high-fanout net. It is captured into a bank of
//   FANOUT_GROUP-way REPLICATED registers (`y_rep`), each copy driving at most
//   FANOUT_GROUP cells. This bounds the broadcast net's load independently of
//   `size` and keeps the input-port path at a single load, so slew/capacitance
//   design rules hold at the slow process corner without relying on the
//   downstream resizer to repair a 32-load port net. Replication is functional
//   identity — every copy holds the same bit — so the only observable effect is
//   the one extra cycle already declared in `latency_cycles`.
//
// CONTINUOUS OPERATION (L7 "連續多筆乘法")
//   The accumulator holds the upper half of the product after `size` y bits.
//   Between independent operations either pulse `rst` for one cycle, or clock
//   in `size` further y=0 bits — which streams out the upper `size` product
//   bits and leaves the accumulator at zero.
//============================================================================
`default_nettype none

module spm_cs_array #(
    parameter size = 32
) (
    input  wire [size-1:0] m,
    input  wire [size-1:0] s,
    input  wire [size-1:0] c,
    output wire [size-1:0] so,
    output wire [size-1:0] co
);
    wire [size-1:0] ms = m ^ s;                        // shared XOR level
    assign so = ms ^ c;                                // sum out
    assign co = (ms & c) | (~ms & m);                  // carry out, bitwise mux
endmodule

module spm #(
    parameter size = 32
) (
    input  wire            clk,  // system clock, rising edge
    input  wire            rst,  // SYNCHRONOUS reset, active high
    input  wire [size-1:0] x,    // parallel multiplicand
    input  wire            y,    // serial multiplier, LSB first
    output wire            p     // serial product,    LSB first
);

    // Maximum number of partial-product cells one copy of the serial operand
    // is allowed to drive.
    localparam integer FANOUT_GROUP = 8;
    localparam integer NREP = (size + FANOUT_GROUP - 1) / FANOUT_GROUP;

    // Replicated capture of the serial multiplier bit. Every copy is identical;
    // `keep` stops the synthesiser from collapsing the bank back into one
    // flop and re-creating the size-load broadcast net.
    (* keep = "true" *) reg [NREP-1:0] y_rep;

    // Redundant carry-save accumulator.
    reg [size-1:0] s;      // saved sum bits,   s[i] has weight 2^i
    reg [size-1:0] c;      // saved carry bits, c[i] has weight 2^i
    reg            p_reg;  // registered serial product bit

    // Partial-product row for the captured serial multiplier bit.
    wire [size-1:0] m;
    genvar gi;
    generate
        for (gi = 0; gi < size; gi = gi + 1) begin : g_pp
            assign m[gi] = x[gi] & y_rep[gi / FANOUT_GROUP];
        end
    endgenerate

    // `size` full adders, majority expressed as ONE two-input multiplexer:
    //   maj(m,s,c) == (m ^ s) ? c : m
    // (when m and s agree the carry is that agreed value; when they differ the
    // carry is whatever c is).  Boolean-identical to the baseline's
    // three-AND/two-OR form; the mapper sees a mux instead of an AOI tree.
    // The carry-save cell array, in its own module.
    wire [size-1:0] so, co;
    spm_cs_array #(.size(size)) u_array (.m(m), .s(s), .c(c), .so(so), .co(co));

    always @(posedge clk) begin
        if (rst) begin
            y_rep <= {NREP{1'b0}};
            s     <= {size{1'b0}};
            c     <= {size{1'b0}};
            p_reg <= 1'b0;
        end else begin
            y_rep <= {NREP{y}};
            // Shift the carry-save accumulator right by one position:
            //   s[i] <= so[i+1] (top cell fed with 0 — bits above 2^(size-1)
            //                    can never reach position 0 within the
            //                    modulo-2^size result window)
            //   c[i] <= co[i]   (carry-out weight 2^(i+1) becomes 2^i after
            //                    the shift)
            s     <= {1'b0, so[size-1:1]};
            c     <= co;
            p_reg <= so[0];
        end
    end

    assign p = p_reg;

endmodule

`default_nettype wire
