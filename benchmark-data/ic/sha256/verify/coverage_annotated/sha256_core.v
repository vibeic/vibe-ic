//      // verilator_coverage annotation
        //============================================================================
        // sha256_core.v  --  Iterative SHA-256/SHA-224 compression engine
        //                    (carry-save-adder round datapath)
        //
        // SOURCE: GENERATED from NIST FIPS-180-4 (public standard), sections 5.3.2,
        //   5.3.3, 6.2 (SHA-256) and 5.3.2/6.3 init constants (SHA-224). No upstream
        //   RTL was read; this is the author's own iterative micro-architecture and
        //   the author's own carry-save adder (3:2 compressor) tree.
        //
        // MICRO-ARCHITECTURE (R3 author's choice, "iterative_single_cycle"):
        //   - One compression round per clock. 64 rounds + setup/finalize => 66
        //     cycles per 512-bit block (matches the L1/L2/L7 reference latency).
        //   - Message schedule W[0..63] is realised with a 16-deep 32-bit SHIFT
        //     REGISTER window w[0..15] (w[0] = current W[t]). Each round the window
        //     shifts up by one and the newly computed schedule word enters at w[15],
        //     per FIPS-180-4 sec 6.2.2:
        //       W[t]   = sigma1(W[t-2]) + W[t-7] + sigma0(W[t-15]) + W[t-16]
        //     Reading from FIXED positions (w[0],w[1],w[9],w[14]) makes the schedule
        //     pure wiring (NO 16:1 crossbar muxes), which routes far more cleanly than
        //     an index-rotated circular buffer.
        //   - SHA-224 vs SHA-256 differ ONLY in the 8 initial hash values H0..H7;
        //     the round function is identical (FIPS-180-4 sec 5.3.2 / 5.3.3). The
        //     224-bit truncation (drop H7) is handled by the register-file read side.
        //
        // CRITICAL-PATH RE-ARCHITECTURE (carry-save adder tree):
        //   The FIPS round per sec 6.2.2 is:
        //       T1 = h + Sigma1(e) + Ch(e,f,g) + K[t] + W[t]
        //       T2 = Sigma0(a) + Maj(a,b,c)
        //       a' = T1 + T2 ;  e' = d + T1
        //   A naive RTL adds these operands as a sequential ripple-carry chain
        //   (h + Sigma1 -> + Ch -> + K -> + W -> +T2 / +d), i.e. ~6 dependent 32-bit
        //   carry-propagate adds in series. That ripple depth is what fails the cold
        //   ss_n40C_1v60 setup corner.
        //
        //   This version instead reduces the multi-operand sums in REDUNDANT
        //   carry-save form using 3:2 compressors (CSA), so the only true
        //   carry-propagation is ONE final 32-bit add per result, and the two results
        //   (a', e') are produced by two PARALLEL CSA trees feeding two PARALLEL CPAs:
        //
        //       e' = d + h + Sigma1(e) + Ch + K + W        (6 operands)
        //       a' = h + Sigma1(e) + Ch + K + W + Sigma0(a) + Maj  (7 operands)
        //
        //   A 3:2 compressor maps (x,y,z) -> (s,c) with
        //       s = x ^ y ^ z          (carry-save sum, weight 2^0)
        //       c = (x&y)|(x&z)|(y&z)  (carry-out, weight 2^1 => shifted left 1)
        //   and x+y+z == s + (c<<1) exactly (mod 2^32). Chaining compressors in a
        //   Wallace-style tree reduces N operands to 2 vectors in ceil(log1.5 N)
        //   levels; one CPA then collapses the 2 vectors. Critical path becomes
        //   (CSA tree, ~3-4 XOR/MAJ levels) + (one 32-bit CPA) instead of ~6 CPAs.
        //
        //   This is a BIT-EXACT re-expression of the same modular sum: identical
        //   digests (verified NIST KAT + secworks co-sim). Latency is UNCHANGED
        //   (still one round/clock, 66 cycles/block) so declaration.json is unchanged.
        //
        // Control:
        //   init  : start a fresh hash (H[] = NIST initial constants for the mode)
        //   next  : continue from current H[] (multi-block message)
        //   ready : high when idle (core can accept init/next)
        //   digest_valid : high when digest holds a completed result
        //============================================================================
        `default_nettype none
        
        module sha256_core (
 008815     input  wire         clk,
%000003     input  wire         reset_n,        // synchronous, active-LOW
        
 000082     input  wire         init,           // pulse: start new hash
%000004     input  wire         next,           // pulse: continue from prior H[]
 000022     input  wire         mode,           // 1=SHA-256, 0=SHA-224
        
            input  wire [511:0] block,          // 512-bit padded message block
        
 000087     output wire         ready,          // 1 = idle / accepting commands
 000024     output wire [255:0] digest,         // 256-bit digest (224 = top 224 bits)
 000085     output wire         digest_valid    // 1 = digest is a completed result
        );
        
            //------------------------------------------------------------------
            // NIST FIPS-180-4 initial hash values
            //------------------------------------------------------------------
            // SHA-256 (sec 5.3.3): frac parts of sqrt of first 8 primes.
            localparam [31:0] H256_0 = 32'h6a09e667, H256_1 = 32'hbb67ae85,
                              H256_2 = 32'h3c6ef372, H256_3 = 32'ha54ff53a,
                              H256_4 = 32'h510e527f, H256_5 = 32'h9b05688c,
                              H256_6 = 32'h1f83d9ab, H256_7 = 32'h5be0cd19;
            // SHA-224 (sec 5.3.2): second 32 bits of frac of sqrt of 9th..16th primes.
            localparam [31:0] H224_0 = 32'hc1059ed8, H224_1 = 32'h367cd507,
                              H224_2 = 32'h3070dd17, H224_3 = 32'hf70e5939,
                              H224_4 = 32'hffc00b31, H224_5 = 32'h68581511,
                              H224_6 = 32'h64f98fa7, H224_7 = 32'hbefa4fa4;
        
            //------------------------------------------------------------------
            // FSM
            //------------------------------------------------------------------
            localparam [1:0] S_IDLE   = 2'd0,
                             S_ROUNDS = 2'd1,
                             S_DONE   = 2'd2;
 000086     reg [1:0] state;
        
 000085     reg [6:0] round;        // 0..63 round counter (7 bits for headroom)
        
            // Working variables a..h (FIPS-180-4 sec 6.2.2)
 001295     reg [31:0] a, b, c, d, e, f, g, h;
        
            // Persistent intermediate hash H0..H7 (carried across blocks for `next`)
 000024     reg [31:0] H0, H1, H2, H3, H4, H5, H6, H7;
        
            // 16-deep 32-bit shift-register message window. w[0] = current W[t].
 001116     reg [31:0] w0,w1,w2,w3,w4,w5,w6,w7,w8,w9,w10,w11,w12,w13,w14,w15;
        
 000085     reg digest_valid_r;
        
            //------------------------------------------------------------------
            // K constant ROM
            //------------------------------------------------------------------
 000516     wire [31:0] k_val;
            sha256_k k_rom (.addr(round[5:0]), .K(k_val));
        
            //------------------------------------------------------------------
            // Combinational SHA-256 round functions (FIPS-180-4 sec 4.1.2)
            //------------------------------------------------------------------
 044090     function [31:0] ror;  // rotate right
                input [31:0] x; input [4:0] n;
 044090         ror = (x >> n) | (x << (6'd32 - {1'b0,n}));
            endfunction
 008818     function [31:0] shr;  // logical shift right
                input [31:0] x; input [4:0] n;
 008818         shr = (x >> n);
            endfunction
%000001     function [31:0] big_sigma0; input [31:0] x;
%000001         big_sigma0 = ror(x,2) ^ ror(x,13) ^ ror(x,22);
            endfunction
%000001     function [31:0] big_sigma1; input [31:0] x;
%000001         big_sigma1 = ror(x,6) ^ ror(x,11) ^ ror(x,25);
            endfunction
%000001     function [31:0] small_sigma0; input [31:0] x;
%000001         small_sigma0 = ror(x,7) ^ ror(x,18) ^ shr(x,3);
            endfunction
%000001     function [31:0] small_sigma1; input [31:0] x;
%000001         small_sigma1 = ror(x,17) ^ ror(x,19) ^ shr(x,10);
            endfunction
%000001     function [31:0] ch;  input [31:0] x,y,z;
%000001         ch = (x & y) ^ (~x & z);
            endfunction
%000001     function [31:0] maj; input [31:0] x,y,z;
%000001         maj = (x & y) ^ (x & z) ^ (y & z);
            endfunction
        
            //------------------------------------------------------------------
            // 3:2 carry-save compressor (one CSA cell, 32-bit wide).
            //   Maps (x,y,z) -> {csa_c, csa_s} with x+y+z == csa_s + (csa_c<<1)
            //   (mod 2^32). csa_s is the bitwise XOR sum; csa_c is the bitwise
            //   majority (carry), which has weight 2 and is shifted left by one when
            //   re-injected. The MSB of the carry is dropped (mod 2^32), which is
            //   exactly the arithmetic we want for 32-bit modular addition.
            //------------------------------------------------------------------
 000011     function [31:0] csa_s; input [31:0] x,y,z; begin
 000011         csa_s = x ^ y ^ z;
            end endfunction
 000011     function [31:0] csa_c; input [31:0] x,y,z; begin
                // carry vector, already shifted left by 1 (weight 2^1)
 000011         csa_c = ((x & y) | (x & z) | (y & z)) << 1;
            end endfunction
        
            //------------------------------------------------------------------
            // Carry-select 32-bit final adder (the single carry-propagate add that
            // collapses the CSA tree's redundant (sum,carry) pair). A plain `p + q`
            // synthesises to a 32-bit RIPPLE-carry chain (~22 maj3 cells deep), which
            // is the residual critical-path limiter at the cold ss_n40C_1v60 corner.
            //
            // This carry-select form splits the add into a 16-bit LOW half plus a
            // 16-bit HIGH half computed TWICE (assuming carry-in 0 and carry-in 1)
            // and then SELECTED by the low half's carry-out. The two 16-bit halves
            // run in PARALLEL, so the worst ripple depth is ~16 bits instead of 32 —
            // roughly halving the carry-propagate logic depth. Bit-exact 32-bit
            // modular sum (verified NIST KAT + secworks co-sim).
            //------------------------------------------------------------------
%000003     function [31:0] cpa_add; input [31:0] p, q; begin : cpa
                reg [16:0] lo;          // 16-bit sum + carry-out
                reg [16:0] hi0, hi1;    // high half with carry-in 0 / 1
                reg [15:0] hi_sel;
%000003         lo  = {1'b0, p[15:0]}  + {1'b0, q[15:0]};
%000003         hi0 = {1'b0, p[31:16]} + {1'b0, q[31:16]} + 17'd0;
%000003         hi1 = {1'b0, p[31:16]} + {1'b0, q[31:16]} + 17'd1;
%000003         hi_sel = lo[16] ? hi1[15:0] : hi0[15:0];
%000003         cpa_add = {hi_sel, lo[15:0]};
            end endfunction
        
            // Current round's message word W[round] = head of shift window.
 001118     wire [31:0] w_t = w0;
        
            //------------------------------------------------------------------
            // Round operands (all weight-2^0 vectors to be summed mod 2^32).
            //   FIPS-180-4 sec 6.2.2:
            //     T1 = h + Sigma1(e) + Ch(e,f,g) + K[t] + W[t]
            //     T2 = Sigma0(a) + Maj(a,b,c)
            //     e' = d + T1
            //     a' = T1 + T2
            //   Re-grouped for two parallel CSA trees:
            //     e' = d + h + Sigma1(e) + Ch + K + W          (6 operands)
            //     a' = h + Sigma1(e) + Ch + K + W + Sigma0(a) + Maj   (7 operands)
            //------------------------------------------------------------------
 001342     wire [31:0] s1e   = big_sigma1(e);
 001002     wire [31:0] che   = ch(e,f,g);
 001336     wire [31:0] s0a   = big_sigma0(a);
 000640     wire [31:0] maja  = maj(a,b,c);
        
            //------------------------------------------------------------------
            // CSA tree for e' = d + h + s1e + che + k_val + w_t  (6 operands)
            //   Level 1 (two parallel 3:2): groupA={d,h,s1e}  groupB={che,k_val,w_t}
            //     -> (sA,cA), (sB,cB)  : 6 operands -> 4 vectors
            //   Level 2: compress {sA,cA,sB} -> (s2,c2)        : 4 -> 3 vectors
            //   Level 3: compress {s2,c2,cB} -> (s3,c3)        : 3 -> 2 vectors
            //   CPA   : e' = s3 + c3
            //------------------------------------------------------------------
 001335     wire [31:0] e_sA = csa_s(d, h, s1e);
 001302     wire [31:0] e_cA = csa_c(d, h, s1e);
 001316     wire [31:0] e_sB = csa_s(che, k_val, w_t);
 001137     wire [31:0] e_cB = csa_c(che, k_val, w_t);
 001323     wire [31:0] e_s2 = csa_s(e_sA, e_cA, e_sB);
 001080     wire [31:0] e_c2 = csa_c(e_sA, e_cA, e_sB);
 001345     wire [31:0] e_s3 = csa_s(e_s2, e_c2, e_cB);
 001276     wire [31:0] e_c3 = csa_c(e_s2, e_c2, e_cB);
 001338     wire [31:0] e_next = cpa_add(e_s3, e_c3);  // single carry-select CPA
        
            //------------------------------------------------------------------
            // CSA tree for a' = h + s1e + che + k_val + w_t + s0a + maja (7 operands)
            //   Level 1 (two parallel 3:2):
            //     groupA={h,s1e,che}   -> (aA, cA)
            //     groupB={k_val,w_t,s0a} -> (aB, cB)
            //     leftover: maja
            //   Level 2: compress {aA,cA,aB} -> (a2,c2)        : remaining maja,cB
            //   Level 3: compress {a2,c2,cB} -> (a3,c3)
            //   Level 4: compress {a3,c3,maja} -> (a4,c4)
            //   CPA   : a' = a4 + c4
            //------------------------------------------------------------------
 001362     wire [31:0] a_aA = csa_s(h, s1e, che);
 001088     wire [31:0] a_cA = csa_c(h, s1e, che);
 001316     wire [31:0] a_aB = csa_s(k_val, w_t, s0a);
 001231     wire [31:0] a_cB = csa_c(k_val, w_t, s0a);
 001347     wire [31:0] a_a2 = csa_s(a_aA, a_cA, a_aB);
 001058     wire [31:0] a_c2 = csa_c(a_aA, a_cA, a_aB);
 001331     wire [31:0] a_a3 = csa_s(a_a2, a_c2, a_cB);
 001290     wire [31:0] a_c3 = csa_c(a_a2, a_c2, a_cB);
 001331     wire [31:0] a_a4 = csa_s(a_a3, a_c3, maja);
 000992     wire [31:0] a_c4 = csa_c(a_a3, a_c3, maja);
 001339     wire [31:0] a_next = cpa_add(a_a4, a_c4);  // single carry-select CPA
        
            //------------------------------------------------------------------
            // Next message-schedule word entering at w15 (CSA tree, 4 operands):
            //   W[t+16] = sigma1(W[t+14]) + W[t+9] + sigma0(W[t+1]) + W[t]
            //   In the shift window (w0=W[t]): w14=W[t+14], w9=W[t+9], w1=W[t+1].
            //------------------------------------------------------------------
 001305     wire [31:0] ws1   = small_sigma1(w14);
 001120     wire [31:0] ws0   = small_sigma0(w1);
 001295     wire [31:0] w_sA  = csa_s(ws1, w9, ws0);
 001202     wire [31:0] w_cA  = csa_c(ws1, w9, ws0);
 001290     wire [31:0] w_s2  = csa_s(w_sA, w_cA, w0);
 000788     wire [31:0] w_c2  = csa_c(w_sA, w_cA, w0);
 001301     wire [31:0] w_new = cpa_add(w_s2, w_c2);   // single carry-select CPA
        
            //------------------------------------------------------------------
            // Sequential
            //------------------------------------------------------------------
 004408     always @(posedge clk) begin
%000007         if (!reset_n) begin
%000007             state          <= S_IDLE;
%000007             round          <= 7'd0;
%000007             digest_valid_r <= 1'b0;
%000007             {a,b,c,d,e,f,g,h} <= 256'b0;
%000007             {H0,H1,H2,H3,H4,H5,H6,H7} <= 256'b0;
%000007             {w0,w1,w2,w3,w4,w5,w6,w7,w8,w9,w10,w11,w12,w13,w14,w15} <= 512'b0;
 004401         end else begin
 004401             case (state)
                    //--------------------------------------------------------
 001606             S_IDLE: begin
 000043                 if (init || next) begin
                            // load message window from block (big-endian word order:
                            // BLOCK0 is the most-significant 32 bits => W[0] = w0).
 000043                     w0  <= block[511:480]; w1  <= block[479:448];
 000043                     w2  <= block[447:416]; w3  <= block[415:384];
 000043                     w4  <= block[383:352]; w5  <= block[351:320];
 000043                     w6  <= block[319:288]; w7  <= block[287:256];
 000043                     w8  <= block[255:224]; w9  <= block[223:192];
 000043                     w10 <= block[191:160]; w11 <= block[159:128];
 000043                     w12 <= block[127:96];  w13 <= block[95:64];
 000043                     w14 <= block[63:32];   w15 <= block[31:0];
        
%000002                     if (init) begin
                                // fresh hash: H[] = NIST init for selected mode
 000017                         if (mode) begin
 000024                             a <= H256_0; b <= H256_1; c <= H256_2; d <= H256_3;
 000024                             e <= H256_4; f <= H256_5; g <= H256_6; h <= H256_7;
 000024                             H0<= H256_0; H1<= H256_1; H2<= H256_2; H3<= H256_3;
 000024                             H4<= H256_4; H5<= H256_5; H6<= H256_6; H7<= H256_7;
 000017                         end else begin
 000017                             a <= H224_0; b <= H224_1; c <= H224_2; d <= H224_3;
 000017                             e <= H224_4; f <= H224_5; g <= H224_6; h <= H224_7;
 000017                             H0<= H224_0; H1<= H224_1; H2<= H224_2; H3<= H224_3;
 000017                             H4<= H224_4; H5<= H224_5; H6<= H224_6; H7<= H224_7;
                                end
%000002                     end else begin
                                // continue: seed a..h from persistent H[]
%000002                         a <= H0; b <= H1; c <= H2; d <= H3;
%000002                         e <= H4; f <= H5; g <= H6; h <= H7;
                            end
 000043                     round          <= 7'd0;
 000043                     digest_valid_r <= 1'b0;
 000043                     state          <= S_ROUNDS;
                        end
                    end
                    //--------------------------------------------------------
 002752             S_ROUNDS: begin
                        // apply round function (FIPS-180-4 sec 6.2.2) using the
                        // carry-save datapath above (a_next, e_next bit-exact).
 002752                 h <= g;
 002752                 g <= f;
 002752                 f <= e;
 002752                 e <= e_next;       // = d + T1
 002752                 d <= c;
 002752                 c <= b;
 002752                 b <= a;
 002752                 a <= a_next;       // = T1 + T2
        
                        // advance message schedule by shifting the window up one slot;
                        // freshly computed word enters at w15 (pure wiring, no mux).
 002752                 w0  <= w1;  w1  <= w2;  w2  <= w3;  w3  <= w4;
 002752                 w4  <= w5;  w5  <= w6;  w6  <= w7;  w7  <= w8;
 002752                 w8  <= w9;  w9  <= w10; w10 <= w11; w11 <= w12;
 002752                 w12 <= w13; w13 <= w14; w14 <= w15; w15 <= w_new;
        
 000043                 if (round == 7'd63) begin
 000043                     state <= S_DONE;
                        end
 002752                 round <= round + 7'd1;
                    end
                    //--------------------------------------------------------
 000043             S_DONE: begin
                        // add compressed chunk to current hash (FIPS-180-4 sec 6.2.2)
 000043                 H0 <= H0 + a; H1 <= H1 + b; H2 <= H2 + c; H3 <= H3 + d;
 000043                 H4 <= H4 + e; H5 <= H5 + f; H6 <= H6 + g; H7 <= H7 + h;
 000043                 digest_valid_r <= 1'b1;
 000043                 state <= S_IDLE;
                    end
%000000             default: state <= S_IDLE;
                    endcase
                end
            end
        
            assign ready        = (state == S_IDLE);
            assign digest_valid = digest_valid_r;
            assign digest       = {H0,H1,H2,H3,H4,H5,H6,H7};
        
        endmodule
        
        `default_nettype wire
        
