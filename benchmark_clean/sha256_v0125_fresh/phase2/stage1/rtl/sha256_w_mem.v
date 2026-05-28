// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin spec-to-rtl (AI-authored from input/docs/L*.md + NIST FIPS-180-4)
//
// SHA-256 Message Schedule W memory (FIPS-180-4 §6.2.2 step 1).
//
// Implements a 16-deep × 32-bit shift register that on each "next" tick:
//   - For t < 16:  W[t] = block_words[t]            (just shifts in block)
//   - For t ≥ 16:  W[t] = sigma1(W[t-2]) + W[t-7] + sigma0(W[t-15]) + W[t-16]
//
// The current W[t] is always w_out (= the value entering position 0 conceptually).
// A 16-deep ring buffer holds W[t-15..t]; we expose w_out = next-W to be consumed
// in the same cycle by the compressor (round t).
//
// Functions:
//   sigma0(x) = ROTR(x,7)  XOR ROTR(x,18) XOR SHR(x,3)
//   sigma1(x) = ROTR(x,17) XOR ROTR(x,19) XOR SHR(x,10)

`default_nettype none
module sha256_w_mem (
    input  wire         clk,
    input  wire         reset_n,    // sync active-LOW
    input  wire         init,       // load block into W[0..15]
    input  wire         next,       // advance schedule by 1 round
    input  wire [511:0] block,      // 512-bit block, big-endian word order
                                    // block[511:480] = W[0], ... block[31:0] = W[15]
    output wire [31:0]  w_out       // current W[t]
);
    // Ring buffer holds last 16 W values: w_mem[0] = W[t], w_mem[15] = W[t-15]
    reg [31:0] w_mem [0:15];
    integer i;

    function [31:0] rotr;
        input [31:0] x;
        input [4:0]  n;
        begin
            rotr = (x >> n) | (x << (32 - n));
        end
    endfunction

    function [31:0] sigma0;
        input [31:0] x;
        begin
            sigma0 = rotr(x, 5'd7)  ^ rotr(x, 5'd18) ^ (x >> 3);
        end
    endfunction

    function [31:0] sigma1;
        input [31:0] x;
        begin
            sigma1 = rotr(x, 5'd17) ^ rotr(x, 5'd19) ^ (x >> 10);
        end
    endfunction

    // -------------------------------------------------------------------
    // Window convention: w_mem[0] = W[t] (the word consumed by round t),
    // w_mem[k] = W[t+k].  The word that lands at slot 15 on this shift
    // becomes W[t+16] when it reaches slot 0 (16 shifts later):
    //   W[t+16] = sigma1(W[t+14]) + W[t+9] + sigma0(W[t+1]) + W[t]
    //           = sigma1(w_mem[14]) + w_mem[9] + sigma0(w_mem[1]) + w_mem[0]
    // (FIPS-180-4 §6.2.2 step 1, W_t = sigma1(W_{t-2}) + W_{t-7}
    //  + sigma0(W_{t-15}) + W_{t-16}; here expressed forward.)
    // -------------------------------------------------------------------
    wire [31:0] new_w;
    assign new_w = sigma1(w_mem[14])   // W[t+14]
                 + w_mem[9]            // W[t+9]
                 + sigma0(w_mem[1])    // W[t+1]
                 + w_mem[0];           // W[t]

    assign w_out = w_mem[0];

    always @(posedge clk) begin
        if (!reset_n) begin
            for (i = 0; i < 16; i = i + 1) w_mem[i] <= 32'h0;
        end
        else if (init) begin
            // Load block_words[0..15] into w_mem[0..15]
            // block[511:480] is W[0] (first word), big-endian
            w_mem[ 0] <= block[511:480];
            w_mem[ 1] <= block[479:448];
            w_mem[ 2] <= block[447:416];
            w_mem[ 3] <= block[415:384];
            w_mem[ 4] <= block[383:352];
            w_mem[ 5] <= block[351:320];
            w_mem[ 6] <= block[319:288];
            w_mem[ 7] <= block[287:256];
            w_mem[ 8] <= block[255:224];
            w_mem[ 9] <= block[223:192];
            w_mem[10] <= block[191:160];
            w_mem[11] <= block[159:128];
            w_mem[12] <= block[127: 96];
            w_mem[13] <= block[ 95: 64];
            w_mem[14] <= block[ 63: 32];
            w_mem[15] <= block[ 31:  0];
        end
        else if (next) begin
            // Shift: w_mem[i] <= w_mem[i+1], inject new_w at slot 15
            for (i = 0; i < 15; i = i + 1) w_mem[i] <= w_mem[i+1];
            w_mem[15] <= new_w;
        end
    end
endmodule
`default_nettype wire
