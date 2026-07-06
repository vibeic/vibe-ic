// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input in,
    output reg out
);
    localparam SW = 1;
    localparam [0:0] S_B = 1'd0;
    localparam [0:0] S_A = 1'd1;
    reg [0:0] state, nstate;
    // next-state
    always @(*) begin
        case (state)
            S_B: nstate = in ? S_B : S_A;
            S_A: nstate = in ? S_A : S_B;
            default: nstate = S_B;
        endcase
    end
    // state register
    always @(posedge clk) begin
        if (reset) state <= S_B;
        else state <= nstate;
    end
    // Moore output
    always @(*) begin
        case (state)
            S_B: out = 1'b1;
            S_A: out = 1'b0;
            default: out = 1'b0;
        endcase
    end
endmodule
