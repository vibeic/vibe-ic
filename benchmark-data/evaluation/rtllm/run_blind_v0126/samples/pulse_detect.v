module pulse_detect (
    input  clk,
    input  rst_n,
    input  data_in,
    output reg data_out
);

    // Detect a 0 -> 1 -> 0 sequence over 3 cycles; assert data_out on the
    // final cycle (when input returns to 0 after having been 1).
    localparam S0 = 2'd0;  // waiting / saw 0
    localparam S1 = 2'd1;  // saw 1 (after a 0)

    reg [1:0] state;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S0;
            data_out <= 1'b0;
        end else begin
            case (state)
                S0: begin
                    if (data_in) begin
                        state    <= S1;
                        data_out <= 1'b0;
                    end else begin
                        state    <= S0;
                        data_out <= 1'b0;
                    end
                end
                S1: begin
                    if (data_in) begin
                        state    <= S1;   // still high, stay
                        data_out <= 1'b0;
                    end else begin
                        state    <= S0;   // 1 -> 0 : end of pulse
                        data_out <= 1'b1;
                    end
                end
                default: begin
                    state    <= S0;
                    data_out <= 1'b0;
                end
            endcase
        end
    end

endmodule
