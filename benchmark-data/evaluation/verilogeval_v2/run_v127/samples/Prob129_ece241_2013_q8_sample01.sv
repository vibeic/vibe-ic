// program-SOLVED Mealy FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input aresetn,
    input x,
    output reg z
);
    localparam SW = 2;
    localparam [1:0] S_P0 = 2'd0;
    localparam [1:0] S_P1 = 2'd1;
    localparam [1:0] S_P2 = 2'd2;
    reg [1:0] state, nstate;
    // next-state (depends on state and input)
    always @(*) begin
        case (state)
            S_P0: nstate = x ? S_P1 : S_P0;
            S_P1: nstate = x ? S_P1 : S_P2;
            S_P2: nstate = x ? S_P1 : S_P0;
            default: nstate = 2'd0;
        endcase
    end
    // state register
    always @(posedge clk or negedge aresetn) begin
        if (!aresetn) state <= 2'd0;
        else state <= nstate;
    end
    // Mealy output (depends on state AND input)
    always @(*) begin
        case (state)
            S_P0: z = x ? 1'b0 : 1'b0;
            S_P1: z = x ? 1'b0 : 1'b0;
            S_P2: z = x ? 1'b1 : 1'b0;
            default: z = 1'b0;
        endcase
    end
endmodule
