module pulse_detect(
    input  clk,
    input  rst_n,
    input  data_in,
    output reg data_out
);

// state[1] = value seen 2 cycles ago, state[0] = value seen 1 cycle ago
reg [1:0] state;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state <= 2'b00;
    end else begin
        state <= {state[0], data_in};
    end
end

// Mealy output: the 0-1-0 pulse completes THIS cycle (state holds the
// previous two samples, data_in is the current sample) -- must be
// combinational, not registered, or the assertion lags by one cycle.
always @(*) begin
    if (!rst_n)
        data_out = 1'b0;
    else
        data_out = (state == 2'b01) && (data_in == 1'b0);
end

endmodule
