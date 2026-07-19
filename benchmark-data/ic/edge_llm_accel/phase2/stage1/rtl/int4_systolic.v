// int4_systolic — weight-stationary systolic INT4 MAC array (TPU-MXU style), parametric ROWS x COLS.
// Each PE holds a stationary signed INT4 weight; activations flow west->east (registered), partial
// sums accumulate north->south. Weights are loaded by shifting down the columns during load_w.
// Scales to ~1.4M+ std cells at large ROWS/COLS (class-comparable to the Kimi K3 INT4 MAC array).
`default_nettype none
module pe #(parameter ACCW = 20) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     load_w,
    input  wire signed [3:0]        w_in,
    output reg  signed [3:0]        w_out,
    input  wire signed [3:0]        a_in,
    output reg  signed [3:0]        a_out,
    input  wire signed [ACCW-1:0]   ps_in,
    output reg  signed [ACCW-1:0]   ps_out
);
    reg signed [3:0] w;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            w <= 4'sd0; w_out <= 4'sd0; a_out <= 4'sd0; ps_out <= {ACCW{1'b0}};
        end else begin
            if (load_w) begin
                w     <= w_in;   // load stationary weight
                // Full-rate load chain: pass the INCOMING weight down the
                // column, so DIM load pulses populate all DIM rows and every
                // row is overwritten each run. (Shifting the old `w` instead
                // advances the chain at half rate: only 32 of 64 rows load,
                // and rows 32..63 retain the previous run's tile — the F1
                // cross-run-carryover / half-tile defect caught by L7 V2.)
                w_out <= w_in;
            end
            a_out  <= a_in;                       // systolic pass east
            ps_out <= ps_in + $signed(w) * $signed(a_in);  // MAC, accumulate south
        end
    end
endmodule

module int4_systolic #(
    parameter ROWS = 32,
    parameter COLS = 32,
    parameter ACCW = 20
)(
    input  wire                        clk,
    input  wire                        rst_n,
    input  wire                        load_w,
    input  wire signed [4*COLS-1:0]    w_top,    // weight shift-in at top edge (during load)
    input  wire signed [4*ROWS-1:0]    a_left,   // activations at left edge
    output wire signed [ACCW*COLS-1:0] ps_bot    // results at bottom edge
);
    wire signed [3:0]      a_h  [0:ROWS-1][0:COLS];   // activation wires (COLS+1 per row)
    wire signed [3:0]      w_v  [0:ROWS][0:COLS-1];   // weight-shift wires (ROWS+1 per col)
    wire signed [ACCW-1:0] ps_v [0:ROWS][0:COLS-1];   // partial-sum wires (ROWS+1 per col)

    genvar r, c;
    generate
        for (c = 0; c < COLS; c = c + 1) begin: g_topedge
            assign w_v[0][c]  = w_top[4*c +: 4];      // weights enter top
            assign ps_v[0][c] = {ACCW{1'b0}};         // partial sums start at 0
        end
        for (r = 0; r < ROWS; r = r + 1) begin: g_leftedge
            assign a_h[r][0] = a_left[4*r +: 4];      // activations enter left
        end
        for (r = 0; r < ROWS; r = r + 1) begin: g_row
            for (c = 0; c < COLS; c = c + 1) begin: g_col
                pe #(.ACCW(ACCW)) u_pe (
                    .clk(clk), .rst_n(rst_n), .load_w(load_w),
                    .w_in (w_v[r][c]),  .w_out (w_v[r+1][c]),
                    .a_in (a_h[r][c]),  .a_out (a_h[r][c+1]),
                    .ps_in(ps_v[r][c]), .ps_out(ps_v[r+1][c])
                );
            end
        end
        for (c = 0; c < COLS; c = c + 1) begin: g_botedge
            assign ps_bot[ACCW*c +: ACCW] = ps_v[ROWS][c];
        end
    endgenerate
endmodule
`default_nettype wire
