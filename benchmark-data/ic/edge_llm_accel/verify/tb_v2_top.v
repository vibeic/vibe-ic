// tb_v2_top.v — V2 full-scale END-TO-END validation of edge_llm_accel (DIM=64, NBANK=20).
// RE-VERIFICATION ROUND 2 — against the FIXED int4_systolic load chain (w_out <= w_in).
//
// BLACK-BOX: no hierarchical references. Golden is a pure-software model computed in this TB
// from the TB's own copies of the preloaded words, using the FROZEN mapping re-extracted by
// tb_v2_map.v (see mapping.json):
//
//   Row orientation (post-fix, full-rate chain): array row r <- weight beat (63-r), ALL 64
//   rows populated and fully overwritten each run. Beat framing (2-cycle read pipe, unchanged):
//   beat p lane m (bits[32m+:32]) = word (8p+5-m)  =>
//     Wnib(r,c) = signed nib (c%8) of low-32b of weight word [ 509 - 8*r - (c/8) ]
//       valid for r<63, and for r=63 c<48 (words 0..5). For r=63:
//         cols 48..55 (beat-0 lane 6) = nib (c%8) of word 0   (start-branch pre-read bank0@0)
//         cols 56..63 (beat-0 lane 7) = nib (c%8) of RESIDUE word:
//              = word 0                       if the run starts from a post-reset idle
//              = {res63_prev, res63_prev}     if it follows a completed run without reset
//                (S_STORE leaves acc_bank=11/acc_addr=0x7BF; idle keeps re-reading res[63])
//     Weight words 510, 511 never enter any beat (dropped).
//     Anib(r,c) = signed nib (r%8) of low-32b of activation word [ 965 + r - (r/8) - c ]
//     acc[c] = sum_r Wnib*Anib (20-bit signed modular);
//     res[c] = SAT16( (acc[c] * zero_ext(scale)) >>> shift )
//   Result word k: bank (k%32)%20, addr 0x780+k, payload {7'b0, res[k], res[k]}.
`timescale 1ns/1ps
module tb_v2_top;
    localparam DIM  = 64;
    localparam NBANK= 20;
    localparam BAW  = 11;
    localparam BDW  = 39;

    reg clk = 0;
    reg rst_n;
    reg host_en, host_we;
    reg [4:0] host_bank;
    reg [BAW-1:0] host_addr;
    reg [BDW-1:0] host_wdata;
    wire [BDW-1:0] host_rdata;
    reg start;
    reg [15:0] dequant_scale;
    reg [4:0]  dequant_shift;
    wire busy, done;

    edge_llm_accel #(.DIM(DIM), .NBANK(NBANK)) dut (
        .clk(clk), .rst_n(rst_n),
        .host_en(host_en), .host_we(host_we), .host_bank(host_bank),
        .host_addr(host_addr), .host_wdata(host_wdata), .host_rdata(host_rdata),
        .start(start), .dequant_scale(dequant_scale), .dequant_shift(dequant_shift),
        .busy(busy), .done(done)
    );

    always #5 clk = ~clk;

    // ------------------------------------------------------------------ TB state
    reg [31:0] wmem  [0:511];      // weight word payloads (low 32b)
    reg [31:0] amem  [0:1031];     // activation word payloads (512..1031 used)
    reg [15:0] res_dut  [0:63];
    reg [15:0] res_gold [0:63];
    integer seed = 32'hBEEF0042;
    integer total_fail = 0;
    integer done_lat_ref = -1;     // reference start->done latency (fixed-schedule design)

    function signed [3:0] nib(input [31:0] w, input integer n);
        nib = w[4*n +: 4];
    endfunction

    // ------------------------------------------------------------------ golden model
    // resid = beat-0 lane-7 residue word (word 0 after reset; {res63_prev,res63_prev} back-to-back)
    task compute_golden(input [15:0] sc_i, input [4:0] sh_i, input [31:0] resid);
        integer r, c;
        reg signed [19:0] acc;
        reg signed [3:0]  wn, an;
        reg signed [63:0] sc, sh;
        begin
            for (c = 0; c < 64; c = c + 1) begin
                acc = 20'sd0;
                for (r = 0; r < 64; r = r + 1) begin
                    if (r < 63 || c < 48)  wn = nib(wmem[509 - 8*r - (c/8)], c % 8);
                    else if (c < 56)       wn = nib(wmem[0], c % 8);  // beat-0 lane 6 pre-read
                    else                   wn = nib(resid,   c % 8);  // beat-0 lane 7 residue
                    an = nib(amem[965 + r - (r/8) - c], r % 8);
                    acc = acc + wn * an;                     // 20-bit modular, same as HW
                end
                sc = $signed(acc) * $signed({1'b0, sc_i});
                sh = sc >>> sh_i;
                if      (sh > 64'sd32767)  res_gold[c] = 16'h7FFF;
                else if (sh < -64'sd32768) res_gold[c] = 16'h8000;
                else                       res_gold[c] = sh[15:0];
            end
        end
    endtask

    // ------------------------------------------------------------------ host access
    task hwrite(input [4:0] b, input [BAW-1:0] a, input [BDW-1:0] d);
        begin
            @(negedge clk);
            host_en = 1; host_we = 1; host_bank = b; host_addr = a; host_wdata = d;
        end
    endtask

    task host_idle;
        begin @(negedge clk); host_en = 0; host_we = 0; end
    endtask

    task preload_all(input integer junk_hi);   // write all 1032 operand words per L4 layout
        integer i; reg [6:0] j;
        begin
            for (i = 0; i < 512; i = i + 1) begin
                j = junk_hi ? $random(seed) : 7'b0;
                hwrite((i % 32) % NBANK, i[BAW-1:0], {j, wmem[i]});
            end
            for (i = 512; i < 1032; i = i + 1) begin
                j = junk_hi ? $random(seed) : 7'b0;
                hwrite((i % 32) % NBANK, i[BAW-1:0], {j, amem[i]});
            end
            host_idle;
            @(negedge clk);   // >=2 idle cycles before start (lets the idle pre-read settle)
        end
    endtask

    task pulse_reset;
        begin
            @(negedge clk); rst_n = 0;
            @(negedge clk); @(negedge clk); rst_n = 1;
            @(negedge clk);
        end
    endtask

    // run engine + protocol checks (busy rise <=1 cycle, done <=4096, done 1-cycle pulse,
    // busy low during/after done, fixed latency)
    integer proto_bad;
    task run_engine(input [15:0] sc_i, input [4:0] sh_i);
        integer n, lat;
        begin
            proto_bad = 0;
            if (busy !== 1'b0) begin proto_bad = proto_bad + 1; $display("PROTO busy!=0 before start"); end
            @(negedge clk); start = 1; dequant_scale = sc_i; dequant_shift = sh_i;
            @(posedge clk);            // start sampled here
            @(negedge clk); start = 0;
            @(posedge clk);            // 1 cycle after sampling: busy must be up (L4 4.3.2)
            if (busy !== 1'b1) begin proto_bad = proto_bad + 1; $display("PROTO busy not up 1 cycle after start"); end
            lat = 1;
            begin : wd
                for (n = 0; n < 4400; n = n + 1) begin
                    @(posedge clk); lat = lat + 1;
                    if (done === 1'b1) disable wd;
                end
            end
            if (done !== 1'b1) begin
                proto_bad = proto_bad + 1;
                $display("PROTO FATAL: done did not arrive within 4400 cycles");
            end else begin
                if (lat > 4096) begin proto_bad = proto_bad + 1; $display("PROTO done latency %0d > 4096", lat); end
                if (busy !== 1'b0) begin proto_bad = proto_bad + 1; $display("PROTO busy still 1 in done cycle"); end
                if (done_lat_ref < 0) done_lat_ref = lat;
                else if (lat !== done_lat_ref) begin
                    proto_bad = proto_bad + 1;
                    $display("PROTO latency %0d != reference %0d (fixed schedule violated)", lat, done_lat_ref);
                end
                @(posedge clk);
                if (done !== 1'b0) begin proto_bad = proto_bad + 1; $display("PROTO done wider than 1 cycle"); end
                $display("  run: done latency = %0d cycles (<=4096 OK)", lat);
            end
        end
    endtask

    // pipelined 2-cycle readback of result words k=0..63 (also checks word layout)
    integer layout_bad;
    task readback_results;
        integer k; reg [BDW-1:0] cap;
        begin
            layout_bad = 0;
            for (k = 0; k <= 65; k = k + 1) begin
                @(negedge clk);
                if (k >= 2) begin
                    cap = host_rdata;
                    res_dut[k-2] = cap[15:0];
                    if (cap[38:32] !== 7'b0)      begin layout_bad = layout_bad + 1; end
                    if (cap[31:16] !== cap[15:0]) begin layout_bad = layout_bad + 1; end
                end
                if (k < 64) begin
                    host_en = 1; host_we = 0;
                    host_bank = (k % 32) % NBANK; host_addr = 11'h780 + k[6:0];
                end else begin
                    host_en = 0;
                end
            end
            @(negedge clk);
        end
    endtask

    // compare + report
    task check_results(input [255:0] name);
        integer c, bad;
        begin
            bad = 0;
            for (c = 0; c < 64; c = c + 1)
                if (res_dut[c] !== res_gold[c]) begin
                    bad = bad + 1;
                    if (bad <= 8)
                        $display("  MISMATCH %0s col=%0d dut=%h gold=%h", name, c, res_dut[c], res_gold[c]);
                end
            if (bad == 0 && layout_bad == 0 && proto_bad == 0)
                $display("TEST %0s : PASS (64/64 bit-true, layout ok, protocol ok)", name);
            else begin
                $display("TEST %0s : FAIL (col mismatches=%0d layout_bad=%0d proto_bad=%0d)", name, bad, layout_bad, proto_bad);
                total_fail = total_fail + 1;
            end
        end
    endtask

    // standard from-reset run: residue == word 0 (see mapping.json)
    task full_run(input [15:0] sc_i, input [4:0] sh_i, input integer do_rst, input [255:0] name);
        begin
            if (do_rst) pulse_reset;
            preload_all(1);
            run_engine(sc_i, sh_i);
            compute_golden(sc_i, sh_i, wmem[0]);
            readback_results;
            check_results(name);
        end
    endtask

    task clear_ops;   // wmem/amem := 0
        integer i;
        begin
            for (i = 0; i < 512; i = i + 1) wmem[i] = 32'h0;
            for (i = 0; i < 1032; i = i + 1) amem[i] = 32'h0;
        end
    endtask

    task rand_ops;
        integer i;
        begin
            for (i = 0; i < 512; i = i + 1) wmem[i] = $random(seed);
            for (i = 512; i < 1032; i = i + 1) amem[i] = $random(seed);
        end
    endtask

    // ------------------------------------------------------------------ main
    integer i, k, t, bad, badout;
    reg [15:0] rsc; reg [4:0] rsh;
    reg [15:0] prev_res63;
    reg [BDW-1:0] hexp [0:79];
    reg [BDW-1:0] cap;
    integer n;

    initial begin
        rst_n = 0; host_en = 0; host_we = 0; host_bank = 0; host_addr = 0; host_wdata = 0;
        start = 0; dequant_scale = 0; dequant_shift = 0;
        repeat (4) @(negedge clk);
        rst_n = 1; @(negedge clk);

        // ================= T0 — L7 V2.3: host write/read all 20 banks, pipelined b2b reads
        $display("== T0 host scratchpad: all 20 banks, back-to-back pipelined 2-cycle reads ==");
        for (i = 0; i < 80; i = i + 1) begin
            hexp[i] = {$random(seed), $random(seed)} & {BDW{1'b1}};
            hwrite(i % 20, 11'h600 + (i / 20) * 32 + (i % 20), hexp[i]);   // addrs 0x600.. (clear of operands/results)
        end
        host_idle;
        bad = 0;
        for (i = 0; i <= 81; i = i + 1) begin
            @(negedge clk);
            if (i >= 2) begin
                cap = host_rdata;
                if (cap !== hexp[i-2]) begin bad = bad + 1; if (bad<=5) $display("  T0 rd[%0d] got=%h exp=%h", i-2, cap, hexp[i-2]); end
            end
            if (i < 80) begin host_en = 1; host_we = 0; host_bank = i % 20; host_addr = 11'h600 + (i/20)*32 + (i%20); end
            else host_en = 0;
        end
        if (bad == 0) $display("TEST T0_hostram : PASS (80/80 words, 20 banks, 2-cycle pipelined)");
        else begin $display("TEST T0_hostram : FAIL (%0d bad)", bad); total_fail = total_fail + 1; end

        // ================= T1 — basis probe: A one-hot, W all-ones (window structure, 64 active rows)
        clear_ops;
        for (i = 0; i < 512; i = i + 1) wmem[i] = 32'h11111111;
        amem[965] = 32'h00000001;   // word 965, nibble 0 = +1
        full_run(16'd1, 5'd0, 1, "T1_probe_A_onehot_w965n0");
        // hand prediction (post-fix, ALL 64 rows active): r=0,8,..,56 -> c = r-(r/8):
        // res[0]=res[7]=res[14]=res[21]=res[28]=res[35]=res[42]=res[49]=1, rest 0
        bad = 0;
        for (k = 0; k < 64; k = k + 1)
            if (res_dut[k] !== ((k==0||k==7||k==14||k==21||k==28||k==35||k==42||k==49) ? 16'd1 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T1_hand_prediction : PASS (window diag r-(r/8), ALL 64 rows active)");
        else begin $display("TEST T1_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T2 — basis probe: W one-hot word509 nib0 -> (row0,col0)
        clear_ops;
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h11111111;
        wmem[509] = 32'h00000001;
        full_run(16'd1, 5'd0, 1, "T2_probe_W_w509n0");
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== ((k==0) ? 16'd1 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T2_hand_prediction : PASS (word509 nib0 -> row0,col0)");
        else begin $display("TEST T2_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T3 — basis probe: W one-hot word508 nib3 -> (row0,col11)
        clear_ops;
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h11111111;
        wmem[508] = 32'h00001000;   // nibble 3 = +1
        full_run(16'd1, 5'd0, 1, "T3_probe_W_w508n3");
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== ((k==11) ? 16'd1 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T3_hand_prediction : PASS (word508 nib3 -> row0,col11)");
        else begin $display("TEST T3_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T3b — basis probe row>=32 (fix confirmation): word253 nib0 -> (row32,col0)
        clear_ops;
        wmem[253] = 32'h00000001;   // 509-8*32 = 253 -> row 32, col 0
        amem[993] = 32'h00000001;   // 965+32-4-0 = 993, nibble 32%8=0
        full_run(16'd1, 5'd0, 1, "T3b_probe_row32");
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== ((k==0) ? 16'd1 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T3b_hand_prediction : PASS (row32 LIVE: word253 x word993 -> res[0]=1)");
        else begin $display("TEST T3b_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T4 — former even-beat drop: word 500 (beat 62) now LIVE -> row1 cols8..15
        clear_ops;
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h11111111;
        wmem[500] = 32'h77777777;   // beat 62 lane 1 -> row 63-62=1, cols 8..15
        full_run(16'd1, 5'd0, 1, "T4_even_beat_now_live_word500");
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== ((k>=8 && k<=15) ? 16'd7 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T4_hand_prediction : PASS (even beats now live: word500 -> row1 cols8-15)");
        else begin $display("TEST T4_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T5 — beat-0/row63 structure: words 0..5 -> cols0..47; lanes 6,7 = word0
        clear_ops;
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h11111111;
        for (i = 0; i < 6; i = i + 1) wmem[i] = 32'h77777777;
        wmem[510] = 32'h77777777; wmem[511] = 32'h77777777;   // still dropped
        full_run(16'd1, 5'd0, 1, "T5_row63_beat0_words0to5");
        // row63 cols0..47 <- words 5..0 (=7); cols48..55 <- word0 (=7); cols56..63 <- residue=word0 (=7)
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== 16'd7) bad = bad + 1;
        if (bad == 0) $display("TEST T5_hand_prediction : PASS (row63 = beat0: words0-5 + word0-aliased lanes; 510/511 still dropped)");
        else begin $display("TEST T5_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T5b — residue aliasing probe: word0 nib0 appears at cols 40,48,56 of row63
        clear_ops;
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h11111111;
        wmem[0] = 32'h00000005;     // nibble 0 = 5
        full_run(16'd1, 5'd0, 1, "T5b_residue_alias_word0");
        bad = 0;
        for (k = 0; k < 64; k = k + 1)
            if (res_dut[k] !== ((k==40||k==48||k==56) ? 16'd5 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T5b_hand_prediction : PASS (word0 aliased to row63 cols 40,48,56 — lanes 5,6,7)");
        else begin $display("TEST T5b_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T6 — joint row probe: W w13n5=+2 (row62,col5) x A w1015n6=+3 -> res[5]=6
        clear_ops;
        wmem[13] = 32'h00200000;    // beat1 lane0 nib5 -> row 62, col 5
        amem[1015] = 32'h03000000;  // word 965+62-7-5=1015, nibble 62%8=6, value 3
        full_run(16'd1, 5'd0, 1, "T6_joint_row62_col5");
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== ((k==5) ? 16'd6 : 16'd0)) bad = bad + 1;
        if (bad == 0) $display("TEST T6_hand_prediction : PASS (row62 W/A pairing exact)");
        else begin $display("TEST T6_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end
        // T6b: shift A word by 1 -> must vanish
        amem[1015] = 32'h0; amem[1014] = 32'h03000000;
        full_run(16'd1, 5'd0, 1, "T6b_joint_offbyone");
        bad = 0;
        for (k = 0; k < 64; k = k + 1) if (res_dut[k] !== 16'd0) bad = bad + 1;
        if (bad == 0) $display("TEST T6b_hand_prediction : PASS (window off-by-one vanishes)");
        else begin $display("TEST T6b_hand_prediction : FAIL (%0d)", bad); total_fail = total_fail + 1; end

        // ================= T7..T12 — directed dequant saturation / boundary (L7 V1.3)
        // acc = +1 or -1 at col 0 only: W[509]n0=+1, A[965]n0=+1/-1
        clear_ops; wmem[509] = 32'h00000001; amem[965] = 32'h00000001;
        full_run(16'd32767, 5'd0, 1, "T7_deq_plus_boundary_32767");   // acc=1 -> +32767 exact
        clear_ops; wmem[509] = 32'h00000001; amem[965] = 32'h00000001;
        full_run(16'd32768, 5'd0, 1, "T8_deq_plus_sat_32768");        // -> saturate +32767
        clear_ops; wmem[509] = 32'h00000001; amem[965] = 32'h0000000F; // a=-1
        full_run(16'd32768, 5'd0, 1, "T9_deq_minus_boundary_-32768"); // acc=-1 -> -32768 exact
        clear_ops; wmem[509] = 32'h00000001; amem[965] = 32'h0000000F;
        full_run(16'd32769, 5'd0, 1, "T10_deq_minus_sat_-32769");     // -> saturate -32768
        clear_ops; wmem[509] = 32'h00000001; amem[965] = 32'h0000000F;
        full_run(16'd1, 5'd4, 1, "T11_deq_arith_floor_-1>>>4");       // -1>>>4 = -1 (floor)
        // big both-sign saturation with FULL 64-row array active
        for (i = 0; i < 512; i = i + 1) wmem[i] = 32'h77777777;
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h77777777;
        full_run(16'd65535, 5'd0, 1, "T12a_deq_full_possat");
        for (i = 512; i < 1032; i = i + 1) amem[i] = 32'h88888888;
        full_run(16'd65535, 5'd0, 1, "T12b_deq_full_negsat");

        // ================= T13 — start ignored while busy (L4 4.3.5)
        rand_ops; rsc = 16'd7; rsh = 5'd2;
        pulse_reset; preload_all(1);
        $display("== T13 start-during-busy ==");
        @(negedge clk); start = 1; dequant_scale = rsc; dequant_shift = rsh;
        @(negedge clk); start = 0;
        repeat (300) @(posedge clk);
        if (busy !== 1'b1) begin $display("TEST T13 : FAIL busy dropped early"); total_fail = total_fail + 1; end
        @(negedge clk); start = 1; dequant_scale = 16'hFFFF; dequant_shift = 5'd0;  // must be IGNORED
        @(negedge clk); @(negedge clk); start = 0;
        begin : t13wd
            for (n = 0; n < 4400; n = n + 1) begin
                @(posedge clk);
                if (done === 1'b1) disable t13wd;
            end
        end
        if (done !== 1'b1) begin $display("TEST T13 : FAIL no done"); total_fail = total_fail + 1; end
        else begin
            // no second run may launch: busy must stay 0, no second done
            bad = 0;
            for (n = 0; n < 1300; n = n + 1) begin
                @(posedge clk);
                if (n > 0 && (done === 1'b1 || busy === 1'b1)) bad = bad + 1;
            end
            compute_golden(rsc, rsh, wmem[0]);   // FIRST start's scale/shift must have been used
            layout_bad = 0; proto_bad = 0;
            readback_results;
            check_results("T13_start_ignored_while_busy");
            if (bad != 0) begin $display("TEST T13b : FAIL restart after ignored start (%0d)", bad); total_fail = total_fail + 1; end
            else $display("TEST T13b_no_restart : PASS");
        end

        // ================= T14 — reset mid-run, then clean re-run (L7 V1.4)
        rand_ops;
        pulse_reset; preload_all(0);
        @(negedge clk); start = 1; dequant_scale = 16'd3; dequant_shift = 5'd1;
        @(negedge clk); start = 0;
        repeat (400) @(posedge clk);
        pulse_reset;
        if (busy !== 1'b0) begin $display("TEST T14 : FAIL busy after reset"); total_fail = total_fail + 1; end
        // SRAM keeps operands; array + acc regs cleared by reset -> from-reset golden, no re-preload
        run_engine(16'd3, 5'd1);
        compute_golden(16'd3, 5'd1, wmem[0]);
        readback_results;
        check_results("T14_reset_midrun_rerun");

        // ================= T15..T34 — 20 fully random end-to-end runs (reset between runs)
        for (t = 0; t < 20; t = t + 1) begin
            rand_ops;
            case (t)
                0: begin rsc = 16'd0;     rsh = 5'd0;  end
                1: begin rsc = 16'd65535; rsh = 5'd31; end
                default: begin rsc = $random(seed); rsh = $random(seed); end
            endcase
            $display("== T%0d random run: scale=%0d shift=%0d ==", 15 + t, rsc, rsh);
            full_run(rsc, rsh, 1, {"T_rand_", 8'h30 + 8'(t / 10), 8'h30 + 8'(t % 10)});
        end

        // ================= T35 — BACK-TO-BACK suite: 6 runs, runs 1..5 WITHOUT reset (F1 regression)
        $display("== T35 back-to-back suite: 6 random runs, no reset between runs 1..5 ==");
        pulse_reset;
        prev_res63 = 16'h0;
        for (t = 0; t < 6; t = t + 1) begin
            rand_ops;
            rsc = $random(seed); rsh = $random(seed);
            preload_all(1);
            run_engine(rsc, rsh);
            readback_results;
            // (i) characterization: PURE history-blind golden (residue := word 0)
            compute_golden(rsc, rsh, wmem[0]);
            bad = 0; badout = 0;
            for (k = 0; k < 64; k = k + 1)
                if (res_dut[k] !== res_gold[k]) begin
                    bad = bad + 1;
                    if (k < 56) badout = badout + 1;   // outside the residue columns 56..63
                end
            $display("  B2B run %0d: history-blind mismatches = %0d/64 (outside cols56-63: %0d)", t, bad, badout);
            if (badout != 0) begin
                $display("TEST T35_b2b_confinement_run%0d : FAIL (leak outside cols 56..63)", t);
                total_fail = total_fail + 1;
            end
            // (ii) verdict: residue-aware golden must be bit-true
            compute_golden(rsc, rsh, (t == 0) ? wmem[0] : {prev_res63, prev_res63});
            check_results({"T35_b2b_run", 8'h30 + 8'(t)});
            prev_res63 = res_gold[63];
        end

        // ================= summary
        $display("");
        if (total_fail == 0) $display("V2 RESULT: ALL TESTS PASS");
        else                 $display("V2 RESULT: %0d TEST(S) FAILED", total_fail);
        $finish;
    end
endmodule
