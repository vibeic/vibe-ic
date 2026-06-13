module TopModule(
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);
    // States: A waits for s. Once s=1, the next three clock cycles (states
    // S1,S2,S3) each sample w. After S3 we return to S1 (back-to-back windows)
    // and z is asserted for one cycle when the just-finished window had
    // exactly two w=1.
    localparam A  = 3'd0,
               S1 = 3'd1,
               S2 = 3'd2,
               S3 = 3'd3;

    reg [2:0] state;
    reg [1:0] ones;     // count of w=1 in current window (sampled in S1,S2,S3)
    reg       z_reg;

    always @(posedge clk) begin
        if (reset) begin
            state <= A;
            ones  <= 2'd0;
            z_reg <= 1'b0;
        end else begin
            case (state)
                A: begin
                    z_reg <= 1'b0;
                    if (s) begin
                        state <= S1;
                        ones  <= 2'd0;
                    end else begin
                        state <= A;
                    end
                end
                S1: begin
                    z_reg <= 1'b0;
                    ones  <= (w ? 2'd1 : 2'd0);
                    state <= S2;
                end
                S2: begin
                    z_reg <= 1'b0;
                    ones  <= ones + (w ? 2'd1 : 2'd0);
                    state <= S3;
                end
                S3: begin
                    // finishing the window; decide z for next cycle
                    z_reg <= ((ones + (w ? 2'd1 : 2'd0)) == 2'd2);
                    ones  <= 2'd0;
                    state <= S1;   // start next back-to-back window
                end
                default: begin
                    state <= A;
                    ones  <= 2'd0;
                    z_reg <= 1'b0;
                end
            endcase
        end
    end

    assign z = z_reg;
endmodule
