// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin spec-to-rtl (AI-authored from input/docs/L*.md + NIST FIPS-180-4)
//
// SHA-256 / SHA-224 iterative hash core (FIPS-180-4 §6.2).
//
// Iterative single-cycle round implementation. Latency = 2 init + 64 rounds = 66 cycles.
// Reset polarity = active-LOW, synchronous (per L3 / L7).
//
// I/O
//   init     : start NEW hash — H[] loaded from NIST initial vector (SHA-256 or SHA-224 by mode)
//   next     : start CONTINUING hash — H[] kept from previous block (multi-block)
//   mode     : 1 = SHA-256 (initial H, full 256-bit digest)
//              0 = SHA-224 (different initial H, take first 224 bits)
//   block    : 512-bit input message block (already padded by SW)
//
//   ready    : 1 = idle, can accept next init/next
//   valid    : 1 = digest is valid result of last hash
//   digest   : 256-bit output digest. SHA-224 truncates upstream by ignoring digest[31:0].

`default_nettype none
module sha256_core (
    input  wire         clk,
    input  wire         reset_n,    // sync active-LOW

    input  wire         init,
    input  wire         next,
    input  wire         mode,       // 1=SHA-256, 0=SHA-224
    input  wire [511:0] block,

    output reg          ready,
    output reg          valid,
    output wire [255:0] digest
);
    // -------------------------------------------------------------------
    // NIST FIPS-180-4 §5.3.3 initial hash values
    // -------------------------------------------------------------------
    // SHA-256 (first 32 bits of fractional parts of square roots of first 8 primes)
    localparam [31:0] H256_0 = 32'h6a09e667;
    localparam [31:0] H256_1 = 32'hbb67ae85;
    localparam [31:0] H256_2 = 32'h3c6ef372;
    localparam [31:0] H256_3 = 32'ha54ff53a;
    localparam [31:0] H256_4 = 32'h510e527f;
    localparam [31:0] H256_5 = 32'h9b05688c;
    localparam [31:0] H256_6 = 32'h1f83d9ab;
    localparam [31:0] H256_7 = 32'h5be0cd19;

    // SHA-224 (second 32 bits of fractional parts of square roots of 9th..16th primes)
    localparam [31:0] H224_0 = 32'hc1059ed8;
    localparam [31:0] H224_1 = 32'h367cd507;
    localparam [31:0] H224_2 = 32'h3070dd17;
    localparam [31:0] H224_3 = 32'hf70e5939;
    localparam [31:0] H224_4 = 32'hffc00b31;
    localparam [31:0] H224_5 = 32'h68581511;
    localparam [31:0] H224_6 = 32'h64f98fa7;
    localparam [31:0] H224_7 = 32'hbefa4fa4;

    // -------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------
    localparam S_IDLE   = 2'd0;
    localparam S_ROUND  = 2'd1;
    localparam S_DONE   = 2'd2;

    reg [1:0]  state;
    reg [6:0]  t;             // round counter 0..63, +overflow margin

    // Persistent hash state H[0..7]
    reg [31:0] H0, H1, H2, H3, H4, H5, H6, H7;

    // Working variables a..h
    reg [31:0] a, b, c, d_v, e, f, g, h_v;

    // -------------------------------------------------------------------
    // K-constants + W-memory sub-blocks
    // -------------------------------------------------------------------
    wire [31:0] K_t;
    wire [31:0] W_t;

    sha256_k_constants u_k (
        .addr (t[5:0]),
        .K    (K_t)
    );

    // W-mem control
    wire w_init = (state == S_IDLE) && (init || next);
    wire w_next = (state == S_ROUND);

    sha256_w_mem u_w (
        .clk     (clk),
        .reset_n (reset_n),
        .init    (w_init),
        .next    (w_next),
        .block   (block),
        .w_out   (W_t)
    );

    // -------------------------------------------------------------------
    // Round function helpers (FIPS-180-4 §4.1.2)
    // -------------------------------------------------------------------
    function [31:0] rotr;
        input [31:0] x;
        input [4:0]  n;
        begin
            rotr = (x >> n) | (x << (32 - n));
        end
    endfunction

    function [31:0] big_sigma0;
        input [31:0] x;
        begin
            big_sigma0 = rotr(x, 5'd2) ^ rotr(x, 5'd13) ^ rotr(x, 5'd22);
        end
    endfunction

    function [31:0] big_sigma1;
        input [31:0] x;
        begin
            big_sigma1 = rotr(x, 5'd6) ^ rotr(x, 5'd11) ^ rotr(x, 5'd25);
        end
    endfunction

    function [31:0] ch_fn;
        input [31:0] x, y, z;
        begin
            ch_fn = (x & y) ^ (~x & z);
        end
    endfunction

    function [31:0] maj_fn;
        input [31:0] x, y, z;
        begin
            maj_fn = (x & y) ^ (x & z) ^ (y & z);
        end
    endfunction

    wire [31:0] T1 = h_v + big_sigma1(e) + ch_fn(e, f, g) + K_t + W_t;
    wire [31:0] T2 = big_sigma0(a) + maj_fn(a, b, c);

    // -------------------------------------------------------------------
    // FSM
    // -------------------------------------------------------------------
    always @(posedge clk) begin
        if (!reset_n) begin
            state <= S_IDLE;
            t     <= 7'd0;
            ready <= 1'b1;
            valid <= 1'b0;
            // H[] takes don't-care here — will be set by init at start of hash
            H0<=0; H1<=0; H2<=0; H3<=0; H4<=0; H5<=0; H6<=0; H7<=0;
            a<=0; b<=0; c<=0; d_v<=0; e<=0; f<=0; g<=0; h_v<=0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (init) begin
                        // Load NIST initial H (per mode)
                        if (mode) begin
                            H0 <= H256_0; H1 <= H256_1; H2 <= H256_2; H3 <= H256_3;
                            H4 <= H256_4; H5 <= H256_5; H6 <= H256_6; H7 <= H256_7;
                            a  <= H256_0; b  <= H256_1; c  <= H256_2; d_v<= H256_3;
                            e  <= H256_4; f  <= H256_5; g  <= H256_6; h_v<= H256_7;
                        end else begin
                            H0 <= H224_0; H1 <= H224_1; H2 <= H224_2; H3 <= H224_3;
                            H4 <= H224_4; H5 <= H224_5; H6 <= H224_6; H7 <= H224_7;
                            a  <= H224_0; b  <= H224_1; c  <= H224_2; d_v<= H224_3;
                            e  <= H224_4; f  <= H224_5; g  <= H224_6; h_v<= H224_7;
                        end
                        state <= S_ROUND;
                        t     <= 7'd0;
                        ready <= 1'b0;
                        valid <= 1'b0;
                    end else if (next) begin
                        // Continue from prior H[]
                        a  <= H0; b  <= H1; c  <= H2; d_v<= H3;
                        e  <= H4; f  <= H5; g  <= H6; h_v<= H7;
                        state <= S_ROUND;
                        t     <= 7'd0;
                        ready <= 1'b0;
                        valid <= 1'b0;
                    end
                end

                S_ROUND: begin
                    // Update working variables (FIPS-180-4 §6.2.2 step 3)
                    h_v <= g;
                    g   <= f;
                    f   <= e;
                    e   <= d_v + T1;
                    d_v <= c;
                    c   <= b;
                    b   <= a;
                    a   <= T1 + T2;

                    if (t == 7'd63) begin
                        state <= S_DONE;
                    end else begin
                        t <= t + 7'd1;
                    end
                end

                S_DONE: begin
                    // Final H update (FIPS-180-4 §6.2.2 step 4)
                    H0 <= H0 + a;
                    H1 <= H1 + b;
                    H2 <= H2 + c;
                    H3 <= H3 + d_v;
                    H4 <= H4 + e;
                    H5 <= H5 + f;
                    H6 <= H6 + g;
                    H7 <= H7 + h_v;
                    ready <= 1'b1;
                    valid <= 1'b1;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase

            // A new init/next while busy is ignored (per L4 — caller must wait for READY)
        end
    end

    assign digest = { H0, H1, H2, H3, H4, H5, H6, H7 };

endmodule
`default_nettype wire
