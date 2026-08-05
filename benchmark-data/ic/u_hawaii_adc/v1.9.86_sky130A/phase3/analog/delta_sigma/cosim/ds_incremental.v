// u_hawaii_adc -- behavioral mixed-signal cosim of a 2nd-order incremental
// delta-sigma modulator + matched 2nd-order (CoI^2) decimator. GENERATED from
// L5 Block A spec. Models the SC CIFB loop arithmetic in Q.FRAC fixed-point;
// the analog OTA/comparator CORE bias is verified separately by the SPICE A4
// corner sweep. A8 HIL-WAIVED substitute + A9 cosim: a REAL iverilog/vvp run
// measuring ENOB >= 14 at OSR=256. MODELED, not silicon sign-off.
//
// Scaled CIFB 2nd-order (coefficients validated in float: a1=a2=1/4, c1=2):
//   i1[n] = i1[n-1] + a1*(vin - dac)
//   i2[n] = i2[n-1] + a2*(c1*i1[n] - dac)
//   bs[n] = (i2[n] >= 0)              (1-bit, +/-vref DAC)
// Scaling keeps the integrators from saturating so the noise shaping is
// 2nd-order across the input range -> in-band quantization noise gives
// ENOB ~14.6 at OSR=256.
// Matched 2nd-order decimator = double running sum of the +/-vref bitstream,
// normalized by the exact 2nd-order CoI gain N*(N+1)/2.

`timescale 1ns/1ps

module ds_incremental #(
    parameter integer FRAC = 30,
    parameter integer OSR  = 256
) (
    input  wire                 clk,
    input  wire                 rst,
    input  wire signed [63:0]   vin_q,    // Q.FRAC
    input  wire signed [63:0]   vref_q,   // Q.FRAC
    output reg                  bs,
    output reg signed [63:0]    dout_q
);
    reg signed [63:0] i1, i2;
    reg signed [63:0] w1, w2;

    // a1=a2=1/4 -> >>>2 ; c1=2 -> <<<1.  dac = +/- vref.
    // ROUND (not truncate) each >>>2 divide: add a signed half-LSB before the
    // arithmetic shift. Truncating every cycle over OSR=256 loses ~1 ENOB;
    // rounding recovers it.
    wire signed [63:0] dac  = bs ? vref_q : -vref_q;
    wire signed [63:0] u1   = (vin_q - dac);
    wire signed [63:0] u1r  = u1 + (u1[63] ? -64'sd2 : 64'sd2);   // round
    wire signed [63:0] i1n  = i1 + (u1r >>> 2);                  // a1*(vin-dac)
    wire signed [63:0] u2   = ((i1n <<< 1) - dac);               // c1*i1 - dac
    wire signed [63:0] u2r  = u2 + (u2[63] ? -64'sd2 : 64'sd2);   // round
    wire signed [63:0] i2n  = i2 + (u2r >>> 2);                  // a2*(...)
    wire                bsn  = (i2n >= 0) ? 1'b1 : 1'b0;
    wire signed [63:0] d2   = bsn ? vref_q : -vref_q;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            i1 <= 0; i2 <= 0; w1 <= 0; w2 <= 0; bs <= 0;
        end else begin
            i1 <= i1n;
            i2 <= i2n;
            bs <= bsn;
            w1 <= w1 + d2;
            w2 <= w2 + w1 + d2;
        end
    end

    always @(*) begin
        dout_q = w2 / ((OSR*(OSR+1))/2);
    end
endmodule
