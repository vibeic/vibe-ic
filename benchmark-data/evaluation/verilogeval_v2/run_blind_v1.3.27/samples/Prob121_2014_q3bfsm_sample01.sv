// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input x,
    output reg z
);
    localparam SW = 3;
    localparam [2:0] S_000 = 3'd0;
    localparam [2:0] S_001 = 3'd1;
    localparam [2:0] S_010 = 3'd2;
    localparam [2:0] S_011 = 3'd3;
    localparam [2:0] S_100 = 3'd4;
    reg [2:0] state, nstate;
    // next-state
    always @(*) begin
        case (state)
            S_000: nstate = x ? S_001 : S_000;
            S_001: nstate = x ? S_100 : S_001;
            S_010: nstate = x ? S_001 : S_010;
            S_011: nstate = x ? S_010 : S_001;
            S_100: nstate = x ? S_100 : S_011;
            default: nstate = S_000;
        endcase
    end
    // state register
    always @(posedge clk) begin
        if (reset) state <= S_000;
        else state <= nstate;
    end
    // Moore output
    always @(*) begin
        case (state)
            S_000: z = 1'b0;
            S_001: z = 1'b0;
            S_010: z = 1'b0;
            S_011: z = 1'b1;
            S_100: z = 1'b1;
            default: z = 1'b0;
        endcase
    end
endmodule
