// tb_v2_map.v — V2 mapping EXTRACTION testbench (instrumented; NOT the check TB).
//
// Purpose: empirically extract the effective preloaded-word -> (W tile, A window) schedule
// of edge_llm_accel (DIM=64, NBANK=20). Hierarchical monitors are used on
// dut.load_w / dut.w_beat / dut.a_beat / dut.ps_cap ONLY (allowed for extraction only).
//
// Method: index-coded data. Weight word i (i=0..511) carries payload = 512+i is NOT used;
// instead payload low 16 bits = i itself, so every 32-bit lane observed inside w_beat/a_beat
// directly announces WHICH preloaded word it is. This directly reads out:
//   - which words compose each 256-bit weight beat (framing / 2-word skew),
//   - the load-pulse schedule,
//   - the a_beat sliding-window schedule and the exact ps_cap capture cycle.
`timescale 1ns/1ps
module tb_v2_map;
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

    integer cyc = 0;
    integer start_cyc = -1;
    always @(posedge clk) cyc = cyc + 1;

    // ---------------- monitors (EXTRACTION ONLY: load_w / w_beat / a_beat / ps_cap) --------
    integer pulse_n = 0;
    integer m;
    integer frame_bad = 0;
    reg [31:0] lane;
    // load_w pulse monitor: at the loading posedge the PEs sample the PRE-EDGE w_beat.
    // Reading dut.w_beat in the active region here returns exactly that pre-edge value.
    always @(posedge clk) begin
        if (dut.load_w === 1'b1) begin
            // expected framing hypothesis: beat p lane m (bits 32m+:32) = word 8p+5-m
            for (m = 0; m < 8; m = m + 1) begin
                lane = dut.w_beat[32*m +: 32];
                if (8*pulse_n + 5 - m >= 0) begin
                    if (lane !== (8*pulse_n + 5 - m))
                        begin frame_bad = frame_bad + 1;
                          $display("WFRAME-BAD pulse=%0d lane=%0d got=%h exp=%0d", pulse_n, m, lane, 8*pulse_n+5-m);
                        end
                end else begin
                    $display("WFRAME pulse=%0d lane=%0d PRE-STREAM GARBAGE = %h", pulse_n, m, lane);
                end
            end
            if (pulse_n < 2 || pulse_n > 61)
                $display("WPULSE p=%0d cyc_rel=%0d w_beat lanes7..0 = %h %h %h %h %h %h %h %h",
                    pulse_n, cyc - start_cyc,
                    dut.w_beat[255:224], dut.w_beat[223:192], dut.w_beat[191:160], dut.w_beat[159:128],
                    dut.w_beat[127:96],  dut.w_beat[95:64],   dut.w_beat[63:32],   dut.w_beat[31:0]);
            pulse_n = pulse_n + 1;
        end
    end

    // a_beat monitor: sliding window, shifts EVERY cycle during S_RUN.
    // Hypothesis: after its shift at relative cycle u (u counted so that first S_LDW action is u=0),
    // lane m of a_beat = word (u-2-m).
    reg [255:0] a_prev = 0;
    integer a_first_u = -1, a_last_u = -1, a_bad = 0;
    integer u_now;
    always @(negedge clk) begin   // sample settled post-edge value
        if (a_prev !== dut.a_beat) begin
            u_now = (cyc - 1) - start_cyc;   // relative posedge index of the shift (u=0 first S_LDW action)
            if (a_first_u < 0) a_first_u = u_now;
            a_last_u = u_now;
            for (m = 0; m < 8; m = m + 1) begin
                lane = dut.a_beat[32*m +: 32];
                if ((u_now - 2 - m) >= 510) begin // words below 510 were never shifted into a_beat
                    if (lane !== (u_now - 2 - m)) a_bad = a_bad + 1;
                end
            end
            a_prev = dut.a_beat;
        end
    end

    // ps_cap capture-cycle monitor
    reg [20*64-1:0] cap_prev = 0;
    integer cap_u = -1;
    always @(negedge clk) begin
        if (cap_prev !== dut.ps_cap) begin
            cap_u = (cyc - 1) - start_cyc;
            $display("PSCAP captured at relative posedge u=%0d (ps_bot value established at u=%0d)", cap_u, cap_u-1);
            cap_prev = dut.ps_cap;
        end
    end

    // ---------------- host preload ----------------
    integer i;
    task hwrite(input [4:0] b, input [BAW-1:0] a, input [BDW-1:0] d);
        begin
            @(negedge clk);
            host_en = 1; host_we = 1; host_bank = b; host_addr = a; host_wdata = d;
        end
    endtask

    integer done_cyc;
    initial begin
        rst_n = 0; host_en = 0; host_we = 0; host_bank = 0; host_addr = 0; host_wdata = 0;
        start = 0; dequant_scale = 16'd1; dequant_shift = 5'd0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        @(negedge clk);
        // index-coded preload: word i payload = i (low 32 bits)
        for (i = 0; i < 1032; i = i + 1)
            hwrite(((i % 32) % NBANK), i[BAW-1:0], {7'b0, i[31:0]});
        @(negedge clk); host_en = 0; host_we = 0;
        @(negedge clk);
        // start pulse
        @(negedge clk); start = 1;
        @(posedge clk); start_cyc = cyc;  // posedge that samples start (S_IDLE->S_LDW); first S_LDW action = start_cyc+1
        start_cyc = start_cyc + 1;        // u=0 == first S_LDW action posedge
        @(negedge clk); start = 0;
        // wait for done
        done_cyc = -1;
        begin : wait_done
            integer w;
            for (w = 0; w < 4500; w = w + 1) begin
                @(posedge clk);
                if (done === 1'b1) begin done_cyc = cyc - start_cyc; disable wait_done; end
            end
        end
        $display("DONE at relative posedge u=%0d (done_cyc<=4096: %s)", done_cyc,
                 (done_cyc > 0 && done_cyc <= 4096) ? "OK" : "VIOLATION/TIMEOUT");
        $display("SUMMARY load pulses observed = %0d (expect 64)", pulse_n);
        $display("SUMMARY w_beat framing 'beat p lane m = word 8p+5-m' violations = %0d", frame_bad);
        $display("SUMMARY a_beat first shift u=%0d last shift u=%0d (expect 512..1031), lane-check violations = %0d",
                 a_first_u, a_last_u, a_bad);
        $display("SUMMARY ps_cap capture u=%0d (expect 1032 -> window B[u], u=967+r-c)", cap_u);
        if (pulse_n == 64 && frame_bad == 0 && a_first_u == 512 && a_last_u == 1031 && a_bad == 0 && cap_u == 1032)
            $display("MAP-EXTRACT: ALL SCHEDULE HYPOTHESES CONFIRMED");
        else
            $display("MAP-EXTRACT: HYPOTHESIS MISMATCH — REVISE MAPPING");
        $finish;
    end
endmodule
