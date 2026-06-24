// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input areset,
    input j,
    input k,
    output reg out
);
    localparam SW = 1;
    localparam [0:0] S_OFF = 1'd0;
    localparam [0:0] S_ON = 1'd1;
    reg [0:0] state, nstate;
    // next-state
    always @(*) begin
        case (state)
            S_OFF: nstate = j ? S_ON : S_OFF;
            S_ON: nstate = k ? S_OFF : S_ON;
            default: nstate = S_OFF;
        endcase
    end
    // state register
    always @(posedge clk or posedge areset) begin
        if (areset) state <= S_OFF;
        else state <= nstate;
    end
    // Moore output
    always @(*) begin
        case (state)
            S_OFF: out = 1'b0;
            S_ON: out = 1'b1;
            default: out = 1'b0;
        endcase
    end
endmodule
