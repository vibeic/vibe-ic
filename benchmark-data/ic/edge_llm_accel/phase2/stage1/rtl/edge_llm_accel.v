// edge_llm_accel — Gemmini-inspired edge-LLM matmul accelerator (INT4), Nangate45, ~4 mm2.
// Architecture (ref: UC Berkeley Gemmini / OpenGeMM): a large weight-stationary systolic INT4
// MAC array (the parallel matmul core for LLM linear/attention projections) + a banked on-chip
// SRAM scratchpad (weights / activations / accumulator tiles) + a streaming controller + a
// 64-wide fused-dequant writeback path. Class- and scale-comparable to the Kimi K3 demo chip
// (INT4 MAC array + on-chip SRAM + fused dequant, 100 MHz, Nangate45).
//
//   * matmul core   : 64x64 weight-stationary systolic array  (module int4_systolic)
//   * scratchpad    : NBANK x fakeram45_2048x39 single-port SRAM macros (~195 KB @ NBANK=20)
//   * controller    : loads a 64x64 weight tile, streams activation beats, captures partial sums
//   * dequant       : per-column signed (acc * scale) >>> shift, saturate to 16b, written to SRAM
`default_nettype none
module edge_llm_accel #(
    parameter DIM   = 64,      // systolic array dimension
    parameter ACCW  = 20,
    parameter NBANK = 20,      // fakeram45_2048x39 banks (~9.75 KB each -> ~195 KB)
    parameter BAW   = 11,      // 2048 words
    parameter BDW   = 39       // 39-bit words
)(
    input  wire                   clk,
    input  wire                   rst_n,
    // host / DMA scratchpad access
    input  wire                   host_en,
    input  wire                   host_we,
    input  wire [4:0]             host_bank,
    input  wire [BAW-1:0]         host_addr,
    input  wire [BDW-1:0]         host_wdata,
    output reg  [BDW-1:0]         host_rdata,
    // compute control
    input  wire                   start,
    input  wire [15:0]            dequant_scale,
    input  wire [4:0]             dequant_shift,
    output reg                    busy,
    output reg                    done
);
    localparam EDGE = 4*DIM;            // 256b : 64 INT4 per array edge beat
    localparam RESW = 16;

    // ---------------- banked SRAM scratchpad ----------------
    reg  [4:0]        acc_bank;         // controller-selected bank
    reg  [BAW-1:0]    acc_addr;
    reg               acc_we;
    reg  [BDW-1:0]    acc_wd;
    wire              use_host = host_en;
    wire [4:0]        sel_bank = use_host ? host_bank : acc_bank;
    wire [BAW-1:0]    sel_addr = use_host ? host_addr : acc_addr;
    wire              sel_we   = use_host ? host_we   : acc_we;
    wire [BDW-1:0]    sel_wd   = use_host ? host_wdata: acc_wd;
    wire [BDW-1:0]    bank_rd  [0:NBANK-1];

    genvar b;
    generate
        for (b = 0; b < NBANK; b = b + 1) begin: g_bank
            wire ce = (sel_bank == b[4:0]);
            fakeram45_2048x39 u_bank (
                .clk      (clk),
                .ce_in    (ce),
                .we_in    (ce & sel_we),
                .addr_in  (sel_addr),
                .wd_in    (sel_wd),
                .w_mask_in({BDW{1'b1}}),
                .rd_out   (bank_rd[b])
            );
        end
    endgenerate
    // read mux (registered select for the 1-cycle SRAM latency)
    reg [4:0] sel_bank_q;
    always @(posedge clk) sel_bank_q <= sel_bank;
    wire [BDW-1:0] rd_mux = bank_rd[sel_bank_q];
    always @(posedge clk) host_rdata <= rd_mux;

    // ---------------- edge assembly registers ----------------
    reg  [EDGE-1:0]  w_beat;            // 256b weight beat -> array top
    reg  [EDGE-1:0]  a_beat;            // 256b activation beat -> array left
    reg              load_w;
    wire [ACCW*DIM-1:0] ps_bot;         // 64 x 20b partial sums from array bottom

    int4_systolic #(.ROWS(DIM), .COLS(DIM), .ACCW(ACCW)) u_core (
        .clk(clk), .rst_n(rst_n), .load_w(load_w),
        .w_top (w_beat), .a_left(a_beat), .ps_bot(ps_bot)
    );

    // ---------------- 64-way fused dequant of the captured psum ----------------
    reg  [ACCW*DIM-1:0] ps_cap;
    reg  [15:0]         scale_l;
    reg  [4:0]          shift_l;
    reg  [RESW*DIM-1:0] deq_res;
    integer k;
    always @* begin
        for (k = 0; k < DIM; k = k + 1) begin: dq
            reg signed [ACCW+16-1:0] sc;
            reg signed [ACCW+16-1:0] sh;
            sc = $signed(ps_cap[ACCW*k +: ACCW]) * $signed({1'b0, scale_l});
            sh = sc >>> shift_l;
            if (sh >  $signed({1'b0,{(RESW-1){1'b1}}}))       deq_res[RESW*k +: RESW] = {1'b0,{(RESW-1){1'b1}}};
            else if (sh < $signed({1'b1,{(RESW-1){1'b0}}}))   deq_res[RESW*k +: RESW] = {1'b1,{(RESW-1){1'b0}}};
            else                                              deq_res[RESW*k +: RESW] = sh[RESW-1:0];
        end
    end

    // ---------------- streaming controller (tile load -> run -> store) ----------------
    localparam S_IDLE=3'd0, S_LDW=3'd1, S_RUN=3'd2, S_CAP=3'd3, S_STORE=3'd4, S_DONE=3'd5;
    reg [2:0]      st;
    reg [BAW-1:0]  cptr;               // scratchpad stream pointer
    reg [6:0]      beat;               // beat counter within a phase (0..DIM)
    reg [2:0]      chunk;              // 8x32b assembly chunk (0..7)
    reg [7:0]      run_beats;          // activation beats to stream

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st<=S_IDLE; busy<=1'b0; done<=1'b0; load_w<=1'b0;
            acc_bank<=0; acc_addr<=0; acc_we<=1'b0; acc_wd<=0;
            w_beat<=0; a_beat<=0; ps_cap<=0; cptr<=0; beat<=0; chunk<=0;
            scale_l<=0; shift_l<=0; run_beats<=8'd64;
        end else begin
            done<=1'b0; load_w<=1'b0; acc_we<=1'b0;
            case (st)
                S_IDLE: begin
                    busy<=1'b0;
                    if (start) begin
                        busy<=1'b1; scale_l<=dequant_scale; shift_l<=dequant_shift;
                        cptr<=0; beat<=0; chunk<=0; acc_bank<=0; acc_addr<=0; st<=S_LDW;
                    end
                end
                // load a DIM-row weight tile: assemble each 256b row from 8 bank reads, shift in
                S_LDW: begin
                    acc_bank <= cptr[4:0] % NBANK[4:0];   // round-robin banks (keeps them live)
                    acc_addr <= cptr;
                    w_beat   <= {w_beat[EDGE-33:0], rd_mux[31:0]};  // shift 32b into the 256b beat
                    cptr <= cptr + 1'b1;
                    chunk <= chunk + 1'b1;
                    if (chunk == 3'd7) begin
                        load_w <= 1'b1;                    // full 256b beat ready -> shift weights
                        beat <= beat + 1'b1;
                        if (beat == DIM-1) begin beat<=0; st<=S_RUN; end
                    end
                end
                // stream activation beats through the array
                S_RUN: begin
                    acc_bank <= (cptr[4:0] % NBANK[4:0]);
                    acc_addr <= cptr;
                    a_beat   <= {a_beat[EDGE-33:0], rd_mux[31:0]};
                    cptr <= cptr + 1'b1;
                    chunk <= chunk + 1'b1;
                    if (chunk == 3'd7) begin
                        beat <= beat + 1'b1;
                        if (beat == run_beats[6:0]) begin beat<=0; st<=S_CAP; end
                    end
                end
                S_CAP: begin ps_cap <= ps_bot; st<=S_STORE; beat<=0; end
                // write the 64x16b dequantized result back to scratchpad (2 cols/39b word)
                S_STORE: begin
                    acc_bank <= (beat[4:0] % NBANK[4:0]);
                    acc_addr <= {4'hF, beat};
                    acc_we   <= 1'b1;
                    acc_wd   <= {7'b0, deq_res[RESW*beat +: RESW], deq_res[RESW*beat +: RESW]};
                    beat <= beat + 1'b1;
                    if (beat == DIM-1) st<=S_DONE;
                end
                S_DONE: begin done<=1'b1; busy<=1'b0; st<=S_IDLE; end
                default: st<=S_IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
