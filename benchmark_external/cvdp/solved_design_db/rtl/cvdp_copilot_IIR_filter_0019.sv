module iir_filter (
    input  logic clk,
    input  logic rst,
    input  logic signed [15:0] x,
    output logic signed [15:0] y
);

    // Feed-forward / feed-back coefficients
    parameter signed [15:0] b0 = 16'h0F00;
    parameter signed [15:0] b1 = 16'h0E00;
    parameter signed [15:0] b2 = 16'h0D00;
    parameter signed [15:0] b3 = 16'h0C00;
    parameter signed [15:0] b4 = 16'h0B00;
    parameter signed [15:0] b5 = 16'h0A00;
    parameter signed [15:0] b6 = 16'h0900;
    parameter signed [15:0] a1 = -16'h0800;
    parameter signed [15:0] a2 = -16'h0700;
    parameter signed [15:0] a3 = -16'h0600;
    parameter signed [15:0] a4 = -16'h0500;
    parameter signed [15:0] a5 = -16'h0400;
    parameter signed [15:0] a6 = -16'h0300;

    // LINT FIX (unused parameter): 'unused_param' removed.

    logic signed [15:0] x_prev1, x_prev2, x_prev3, x_prev4, x_prev5, x_prev6;
    logic signed [15:0] y_prev1, y_prev2, y_prev3, y_prev4, y_prev5, y_prev6;

    // LINT FIX (width mismatch): result is sized to the 16-bit output. The
    // wide multiply-accumulate sum is scaled by >>> 16 and explicitly cast to
    // 16 bits, so no extra bits are left unused.
    logic signed [15:0] temp_y;
    // LINT FIX (undriven signal): 'undriven_signal' removed.

    // LINT FIX (combinational logic in sequential block / latch inference):
    // the purely combinational sum is computed in a dedicated always_comb,
    // keeping the clocked block strictly sequential. temp_y is fully assigned
    // every evaluation so no latch is inferred.
    always_comb begin
        temp_y = 16'((b0 * x + b1 * x_prev1 + b2 * x_prev2 + b3 * x_prev3 +
                      b4 * x_prev4 + b5 * x_prev5 + b6 * x_prev6 -
                      a1 * y_prev1 - a2 * y_prev2 - a3 * y_prev3 -
                      a4 * y_prev4 - a5 * y_prev5 - a6 * y_prev6) >>> 16);
    end

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            x_prev1 <= 16'sd0; x_prev2 <= 16'sd0; x_prev3 <= 16'sd0;
            x_prev4 <= 16'sd0; x_prev5 <= 16'sd0; x_prev6 <= 16'sd0;
            y_prev1 <= 16'sd0; y_prev2 <= 16'sd0; y_prev3 <= 16'sd0;
            y_prev4 <= 16'sd0; y_prev5 <= 16'sd0; y_prev6 <= 16'sd0;
            // LINT FIX (uninitialized register): y now has a defined reset value.
            y       <= 16'sd0;
        end else begin
            // LINT FIX (width mismatch): explicit 16-bit slice of the 32-bit sum.
            // Saturation condition preserved exactly as in the original RTL.
            if (x > 16'h8000)
                y <= 16'h7FFF;
            else
                y <= temp_y;

            x_prev6 <= x_prev5; x_prev5 <= x_prev4; x_prev4 <= x_prev3;
            x_prev3 <= x_prev2; x_prev2 <= x_prev1; x_prev1 <= x;
            y_prev6 <= y_prev5; y_prev5 <= y_prev4; y_prev4 <= y_prev3;
            y_prev3 <= y_prev2; y_prev2 <= y_prev1; y_prev1 <= y;
        end
    end

endmodule
