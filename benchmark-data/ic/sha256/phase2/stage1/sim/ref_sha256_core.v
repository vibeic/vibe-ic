// ref_sha256_core.v -- NIST FIPS-180-4 SHA-256 hash core (Section 6.2)
// Author: Vibe-IC strict-blind pilot. Derived solely from public NIST FIPS-180-4 spec.
//
// Iterative implementation:
//   - On INIT/NEXT: latch H[] (initial or carried), pre-load W[0..15] from block in
//     one cycle, then run 64 rounds (t=0..63), then accumulate H[] += abcdefgh.
//   - Total latency: 1 (latch) + 64 (rounds) + 1 (accumulate) = 66 cycles per block,
//     matching L1/L7 declarations.
//
// W schedule: a 16-deep ring buffer initialised with M[0..15] then advanced once
// per round.  Index convention (after pre-load):
//   w[0] = W[t]      (the round's current word)
//   w[1] = W[t+1] (i.e. W[t-15] equivalent after we shift)
//   ...
//   w[15] = W[t+15] (i.e. W[t-1] after a shift)
// After consuming W[t], we compute  w_new = s1(W[t+14]) + W[t+9] + s0(W[t+1]) + W[t]
// and shift the buffer left.

`timescale 1ns/1ps
`default_nettype none

module ref_sha256_core (
    input  wire         clk,
    input  wire         reset_n,        // sync active-LOW
    input  wire         init,           // pulse
    input  wire         next,           // pulse
    input  wire         mode,           // 1 = SHA-256, 0 = SHA-224
    input  wire [511:0] block,          // 512-bit message block
    output reg          ready,
    output reg          digest_valid,
    output wire [255:0] digest
);
    // ---------------- helpers ----------------
    function [31:0] rotr;
        input [31:0] x;
        input integer n;
        begin
            rotr = (x >> n) | (x << (32 - n));
        end
    endfunction

    function [31:0] bigS0;
        input [31:0] x;
        begin
            bigS0 = rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22);
        end
    endfunction

    function [31:0] bigS1;
        input [31:0] x;
        begin
            bigS1 = rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25);
        end
    endfunction

    function [31:0] smallS0;
        input [31:0] x;
        begin
            smallS0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3);
        end
    endfunction

    function [31:0] smallS1;
        input [31:0] x;
        begin
            smallS1 = rotr(x, 17) ^ rotr(x, 19) ^ (x >> 10);
        end
    endfunction

    function [31:0] ch;
        input [31:0] x, y, z;
        begin
            ch = (x & y) ^ ((~x) & z);
        end
    endfunction

    function [31:0] maj;
        input [31:0] x, y, z;
        begin
            maj = (x & y) ^ (x & z) ^ (y & z);
        end
    endfunction

    // ---------------- state machine ----------------
    localparam [1:0]
        S_IDLE  = 2'd0,
        S_RUN   = 2'd1,   // 64 rounds
        S_DONE  = 2'd2;

    reg [1:0] state;
    reg [6:0] t;          // 0..63 round counter
    reg       mode_r;
    reg [255:0] H;        // {H0,H1,H2,H3,H4,H5,H6,H7} with H0 in MSB

    // working variables a..h
    reg [31:0] a, b, c, d, e, f, g, h;

    // W ring buffer
    reg [31:0] w [0:15];
    integer i;

    // K[t] ROM
    wire [31:0] k_t;
    ref_sha256_k u_k (.idx(t[5:0]), .k_out(k_t));

    // Round combinational compute
    wire [31:0] t1, t2;
    assign t1 = h + bigS1(e) + ch(e,f,g) + k_t + w[0];
    assign t2 = bigS0(a) + maj(a,b,c);
    wire [31:0] w_new;
    assign w_new = smallS1(w[14]) + w[9] + smallS0(w[1]) + w[0];

    // ---------- NIST initial H constants ----------
    localparam [255:0] H_INIT_SHA256 = {
        32'h6a09e667, 32'hbb67ae85, 32'h3c6ef372, 32'ha54ff53a,
        32'h510e527f, 32'h9b05688c, 32'h1f83d9ab, 32'h5be0cd19
    };
    localparam [255:0] H_INIT_SHA224 = {
        32'hc1059ed8, 32'h367cd507, 32'h3070dd17, 32'hf70e5939,
        32'hffc00b31, 32'h68581511, 32'h64f98fa7, 32'hbefa4fa4
    };

    always @(posedge clk) begin
        if (!reset_n) begin
            state        <= S_IDLE;
            t            <= 7'd0;
            ready        <= 1'b1;
            digest_valid <= 1'b0;
            mode_r       <= 1'b1;
            H            <= H_INIT_SHA256;
            a <= 32'h0; b <= 32'h0; c <= 32'h0; d <= 32'h0;
            e <= 32'h0; f <= 32'h0; g <= 32'h0; h <= 32'h0;
            for (i = 0; i < 16; i = i + 1) w[i] <= 32'h0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (init || next) begin
                        ready        <= 1'b0;
                        digest_valid <= 1'b0;
                        mode_r       <= mode;
                        t            <= 7'd0;

                        // Pre-load W[0..15] from block (block[511:480]=M[0], block[31:0]=M[15])
                        w[ 0] <= block[511:480];
                        w[ 1] <= block[479:448];
                        w[ 2] <= block[447:416];
                        w[ 3] <= block[415:384];
                        w[ 4] <= block[383:352];
                        w[ 5] <= block[351:320];
                        w[ 6] <= block[319:288];
                        w[ 7] <= block[287:256];
                        w[ 8] <= block[255:224];
                        w[ 9] <= block[223:192];
                        w[10] <= block[191:160];
                        w[11] <= block[159:128];
                        w[12] <= block[127: 96];
                        w[13] <= block[ 95: 64];
                        w[14] <= block[ 63: 32];
                        w[15] <= block[ 31:  0];

                        if (init) begin
                            if (mode) begin
                                H <= H_INIT_SHA256;
                                {a,b,c,d,e,f,g,h} <= H_INIT_SHA256;
                            end else begin
                                H <= H_INIT_SHA224;
                                {a,b,c,d,e,f,g,h} <= H_INIT_SHA224;
                            end
                        end else begin
                            // NEXT: carry previous H[]
                            {a,b,c,d,e,f,g,h} <= H;
                        end
                        state <= S_RUN;
                    end
                end
                S_RUN: begin
                    // Round update
                    a <= t1 + t2;
                    b <= a;
                    c <= b;
                    d <= c;
                    e <= d + t1;
                    f <= e;
                    g <= f;
                    h <= g;
                    // Shift W ring buffer; new W goes into w[15]
                    for (i = 0; i < 15; i = i + 1) w[i] <= w[i+1];
                    w[15] <= w_new;
                    if (t == 7'd63) begin
                        state <= S_DONE;
                    end else begin
                        t <= t + 7'd1;
                    end
                end
                S_DONE: begin
                    H[255:224] <= H[255:224] + a;
                    H[223:192] <= H[223:192] + b;
                    H[191:160] <= H[191:160] + c;
                    H[159:128] <= H[159:128] + d;
                    H[127: 96] <= H[127: 96] + e;
                    H[ 95: 64] <= H[ 95: 64] + f;
                    H[ 63: 32] <= H[ 63: 32] + g;
                    H[ 31:  0] <= H[ 31:  0] + h;
                    ready        <= 1'b1;
                    digest_valid <= 1'b1;
                    state        <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end

    assign digest = H;
endmodule

`default_nettype wire
