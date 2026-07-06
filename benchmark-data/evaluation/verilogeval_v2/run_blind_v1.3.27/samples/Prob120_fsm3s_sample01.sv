// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input in,
    output reg out
);
    localparam SW = 2;
    localparam [1:0] S_A = 2'd0;
    localparam [1:0] S_B = 2'd1;
    localparam [1:0] S_C = 2'd2;
    localparam [1:0] S_D = 2'd3;
    reg [1:0] state, nstate;
    // next-state
    always @(*) begin
        case (state)
            S_A: nstate = in ? S_B : S_A;
            S_B: nstate = in ? S_B : S_C;
            S_C: nstate = in ? S_D : S_A;
            S_D: nstate = in ? S_B : S_C;
            default: nstate = S_A;
        endcase
    end
    // state register
    always @(posedge clk) begin
        if (reset) state <= S_A;
        else state <= nstate;
    end
    // Moore output
    always @(*) begin
        case (state)
            S_A: out = 1'b0;
            S_B: out = 1'b0;
            S_C: out = 1'b0;
            S_D: out = 1'b1;
            default: out = 1'b0;
        endcase
    end
endmodule
