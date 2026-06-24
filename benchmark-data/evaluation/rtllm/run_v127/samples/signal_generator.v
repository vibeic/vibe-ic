// signal_generator — 5-bit triangle-wave generator cycling 0..31..0.
// state 0 = ramp up, state 1 = ramp down. The peak (31) and trough (0) are
// held for one cycle while the direction state flips (hold-the-peak), so the
// wave does not over/under-shoot the 0..31 range.
module signal_generator (
    input  wire        clk,
    input  wire        rst_n,   // active-low reset
    output reg  [4:0]  wave
);

    reg state; // 0 = counting up, 1 = counting down

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 1'b0;
            wave  <= 5'd0;
        end else begin
            case (state)
                1'b0: begin
                    // ramp up; at the peak, flip direction WITHOUT incrementing
                    if (wave == 5'd31)
                        state <= 1'b1;
                    else
                        wave <= wave + 5'd1;
                end
                1'b1: begin
                    // ramp down; at the trough, flip direction WITHOUT decrementing
                    if (wave == 5'd0)
                        state <= 1'b0;
                    else
                        wave <= wave - 5'd1;
                end
            endcase
        end
    end

endmodule
