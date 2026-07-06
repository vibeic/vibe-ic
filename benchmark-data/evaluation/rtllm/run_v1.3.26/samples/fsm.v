module fsm(
    input  wire IN,
    input  wire CLK,
    input  wire RST,
    output wire MATCH
);

localparam S0 = 3'd0, // no bits matched
           S1 = 3'd1, // "1"
           S2 = 3'd2, // "10"
           S3 = 3'd3, // "100"
           S4 = 3'd4; // "1001" - waiting for final '1'

reg [2:0] state, next_state;

always @(posedge CLK or posedge RST) begin
    if (RST)
        state <= S0;
    else
        state <= next_state;
end

always @(*) begin
    case (state)
        S0: next_state = IN ? S1 : S0;
        S1: next_state = IN ? S1 : S2;
        S2: next_state = IN ? S1 : S3;
        S3: next_state = IN ? S4 : S0;
        S4: next_state = IN ? S1 : S0; // trailing bit re-seeds overlap
        default: next_state = S0;
    endcase
end

// Mealy output: combinational function of current state and current input
assign MATCH = (state == S4) && IN;

endmodule
