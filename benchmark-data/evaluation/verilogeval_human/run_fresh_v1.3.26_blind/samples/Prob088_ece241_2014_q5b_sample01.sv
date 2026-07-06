// program-SOLVED Mealy FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input areset,
    input x,
    output reg z
);
    localparam SW = 1;
    localparam [0:0] S_A = 1'd0;
    localparam [0:0] S_B = 1'd1;
    reg [0:0] state, nstate;
    // next-state (depends on state and input)
    always @(*) begin
        case (state)
            S_A: nstate = x ? S_B : S_A;
            S_B: nstate = x ? S_B : S_B;
            default: nstate = 1'd0;
        endcase
    end
    // state register
    always @(posedge clk or posedge areset) begin
        if (areset) state <= 1'd0;
        else state <= nstate;
    end
    // Mealy output (depends on state AND input)
    always @(*) begin
        case (state)
            S_A: z = x ? 1'b1 : 1'b0;
            S_B: z = x ? 1'b0 : 1'b1;
            default: z = 1'b0;
        endcase
    end
endmodule
