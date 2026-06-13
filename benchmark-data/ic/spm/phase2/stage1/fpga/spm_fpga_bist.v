// spm_fpga_bist — DE10-Lite / MAX10 on-chip BIST harness around the GENERATED spm.
//
// Pillar 4 (benchmark-verify) FPGA digital verification harness. It instantiates
// the unmodified GENERATED spm (../rtl/spm.v) plus an on-chip pattern engine that:
//   1. holds a ROM of {x, y, expected_p} test patterns (patterns.hex),
//   2. for each pattern: 1-cycle synchronous reset, then streams y LSB-first one
//      bit/cycle for N cycles while x is held stable, reassembling p (latency=1),
//   3. compares the reassembled product to the expected value,
//   4. accumulates a sticky pass/fail and a done flag.
//
// External I/O is the DE10-Lite contract (CLOCK_50 / KEY / LEDR) so this is a
// REAL board-mappable top entity (same MAX10 device as the reference flow):
//   KEY[0]  = active-LOW restart (held high = run; press = restart BIST)
//   LEDR[0] = bist_done   (1 when all patterns consumed)
//   LEDR[1] = bist_pass   (1 iff every pattern matched golden)
//   LEDR[2] = bist_fail   (sticky: 1 if any mismatch)
//   LEDR[8:3] = pattern index (progress)
//   LEDR[9] = heartbeat   (clock alive)
`default_nettype none

module spm_fpga_bist #(
    parameter integer N    = 32,
    parameter integer NPAT = 64
) (
    input  wire        CLOCK_50,
    input  wire [1:0]  KEY,
    output wire [9:0]  LEDR
);
    localparam integer IDXW = 7;

    // 96-bit ROM word: {x[31:0], y[31:0], exp[31:0]}
    reg [95:0] rom [0:NPAT-1];
    initial $readmemh("patterns.hex", rom);

    wire rst_btn = ~KEY[0];   // active-LOW key -> internal active-HIGH restart

    localparam S_LOAD = 2'd0, S_RUNRST = 2'd1, S_STREAM = 2'd2, S_NEXT = 2'd3;
    reg [1:0]      st;
    reg [IDXW-1:0] pidx;
    reg [6:0]      bitc;          // 0..N+1
    reg [N-1:0]    x_reg, y_reg, exp_reg, got_reg;
    reg            done_r, pass_r, fail_r;

    reg          dut_rst;
    reg          dut_y;
    wire         dut_p;
    spm #(.size(N)) dut (.clk(CLOCK_50), .rst(dut_rst), .x(x_reg), .y(dut_y), .p(dut_p));

    always @(posedge CLOCK_50) begin
        if (rst_btn) begin
            st <= S_LOAD; pidx <= 0; bitc <= 0;
            done_r <= 1'b0; pass_r <= 1'b0; fail_r <= 1'b0;
            dut_rst <= 1'b1; dut_y <= 1'b0; got_reg <= 0;
        end else begin
            case (st)
                S_LOAD: begin
                    if (pidx < NPAT) begin
                        x_reg   <= rom[pidx][95:64];
                        y_reg   <= rom[pidx][63:32];
                        exp_reg <= rom[pidx][31:0];
                        dut_rst <= 1'b1;          // 1-cycle sync reset for this pattern
                        dut_y   <= 1'b0;
                        bitc    <= 0;
                        got_reg <= 0;
                        st      <= S_RUNRST;
                    end else begin
                        done_r <= 1'b1;
                        pass_r <= ~fail_r;
                    end
                end
                S_RUNRST: begin
                    dut_rst <= 1'b0;
                    dut_y   <= y_reg[0];          // drive y[0]
                    bitc    <= 0;
                    st      <= S_STREAM;
                end
                S_STREAM: begin
                    // latency=1: the p sampled this cycle is product bit (bitc-1)
                    if (bitc >= 1 && bitc <= N)
                        got_reg[bitc-1] <= dut_p;
                    // drive next y bit while bits remain
                    if (bitc < N-1)
                        dut_y <= y_reg[bitc+1];
                    else
                        dut_y <= 1'b0;
                    if (bitc < N) begin
                        bitc <= bitc + 1'b1;
                        st   <= S_STREAM;
                    end else begin
                        st <= S_NEXT;            // got_reg now fully captured (bits 0..N-1)
                    end
                end
                S_NEXT: begin
                    if (got_reg !== exp_reg)
                        fail_r <= 1'b1;
                    pidx <= pidx + 1'b1;
                    st   <= S_LOAD;
                end
                default: st <= S_LOAD;
            endcase
        end
    end

    reg [25:0] hb = 0;
    always @(posedge CLOCK_50) hb <= hb + 1'b1;

    assign LEDR[0]   = done_r;
    assign LEDR[1]   = pass_r;
    assign LEDR[2]   = fail_r;
    assign LEDR[8:3] = pidx[5:0];
    assign LEDR[9]   = hb[25];
endmodule

`default_nettype wire
