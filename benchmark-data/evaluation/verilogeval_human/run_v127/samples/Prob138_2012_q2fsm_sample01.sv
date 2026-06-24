// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input w,
    output reg z
);
    localparam SW = 3;
    localparam [2:0] S_A = 3'd0;
    localparam [2:0] S_B = 3'd1;
    localparam [2:0] S_C = 3'd2;
    localparam [2:0] S_D = 3'd3;
    localparam [2:0] S_E = 3'd4;
    localparam [2:0] S_F = 3'd5;
    reg [2:0] state, nstate;
    // next-state
    always @(*) begin
        case (state)
            S_A: nstate = w ? S_B : S_A;
            S_B: nstate = w ? S_C : S_D;
            S_C: nstate = w ? S_E : S_D;
            S_D: nstate = w ? S_F : S_A;
            S_E: nstate = w ? S_E : S_D;
            S_F: nstate = w ? S_C : S_D;
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
            S_A: z = 1'b0;
            S_B: z = 1'b0;
            S_C: z = 1'b0;
            S_D: z = 1'b0;
            S_E: z = 1'b1;
            S_F: z = 1'b1;
            default: z = 1'b0;
        endcase
    end
endmodule
