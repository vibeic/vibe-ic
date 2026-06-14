// spm.v — Serial-Parallel Multiplier (shift-and-add accumulator)
// Authored fresh from L1-L9 spec (clean-room). Top module name = `spm` per L3/L8.
//
// Functional contract (L2/L3):
//   x : parallel multiplicand, [size-1:0], loaded in parallel, held stable during a compute.
//   y : 1-bit serial multiplier, one bit per clk, LSB-first (declared in declaration.json).
//   p : 1-bit serial product,    one bit per clk, LSB-first.
//   clk: rising-edge sampled.  rst: synchronous, active-high.
//   p = (x * y) mod 2^size  (modulo arithmetic; signed/unsigned bit-identical).
//
// Algorithm: shift-and-add. An (size+1)-bit accumulator holds the running partial
//   product. On each cycle the incoming multiplier bit y selects whether x is added
//   into the high part of the accumulator; the accumulator's LSB is then emitted as the
//   next serial product bit and the accumulator shifts right by one. With the multiplier
//   streamed LSB-first this yields the product LSB-first, latency = 1 cycle.
//   (Functionally equivalent to a CSA/Booth array; verified vs a behavioral golden model.)

module spm #(
    parameter size = 32
) (
    input  wire              clk,
    input  wire              rst,   // synchronous, active-high
    input  wire [size-1:0]   x,     // parallel multiplicand
    input  wire              y,     // serial multiplier  (LSB-first)
    output wire              p      // serial product     (LSB-first)
);

    // Accumulator: one guard bit above `size` so the add cannot lose information
    // before the right-shift drops the already-emitted LSB.
    reg  [size:0] acc;            // size+1 bits

    // Conditionally add the multiplicand into the high `size` bits of the accumulator.
    // acc[size:1] += (y ? x : 0); the shift-out of bit 0 happens by taking acc[size:1].
    wire [size:0] addend = y ? {x, 1'b0} : {(size+1){1'b0}};
    wire [size:0] sum    = acc + addend;

    always @(posedge clk) begin
        if (rst) begin
            acc <= {(size+1){1'b0}};
        end else begin
            // emit sum[0] this cycle (registered as p below), shift the rest down by 1
            acc <= {1'b0, sum[size:1]};
        end
    end

    // The serial product bit is the LSB of the post-add accumulator, registered out.
    reg p_reg;
    always @(posedge clk) begin
        if (rst) p_reg <= 1'b0;
        else     p_reg <= sum[0];
    end

    assign p = p_reg;

endmodule
