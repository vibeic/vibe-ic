// program-SOLVED reset-pulse counter (assert for N cycles after reset,
// then 0 forever; free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    output shift_ena
);
    localparam [2:0] DONE = 3'd4;
    reg [2:0] state, nstate;
    always @(*) begin
        if (state == DONE) nstate = DONE;
        else nstate = state + 3'd1;
    end
    always @(posedge clk) begin
        if (reset) state <= 3'd0;
        else state <= nstate;
    end
    assign shift_ena = (state != DONE);
endmodule
