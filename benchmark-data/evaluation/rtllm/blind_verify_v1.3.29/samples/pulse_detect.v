module pulse_detect (
    input  wire clk,
    input  wire rst_n,
    input  wire data_in,
    output wire data_out
);

    // state: S0 = previous sample was 0 (idle / no pending rise)
    //        S1 = previous sample was 1 (a rise happened, awaiting the fall)
    localparam S0 = 1'b0;
    localparam S1 = 1'b1;

    reg state;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S0;
        end else begin
            state <= data_in ? S1 : S0;
        end
    end

    // Mealy output: pulse completes the same cycle data_in falls back to 0
    // after having been in S1 (i.e. previous sample was 1, current is 0).
    assign data_out = (state == S1) && (~data_in);

endmodule
