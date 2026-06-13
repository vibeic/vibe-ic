module fsm (
    input  IN,
    input  CLK,
    input  RST,
    output MATCH
);

    // Mealy FSM detecting the sequence 1 0 0 1 1 (overlapping / continuous)
    // States encode how much of the target prefix has been matched so far.
    localparam S0 = 3'd0; // no useful prefix
    localparam S1 = 3'd1; // "1"
    localparam S2 = 3'd2; // "10"
    localparam S3 = 3'd3; // "100"
    localparam S4 = 3'd4; // "1001"

    reg [2:0] state, next_state;

    always @(posedge CLK or posedge RST) begin
        if (RST)
            state <= S0;
        else
            state <= next_state;
    end

    // Next-state logic
    always @(*) begin
        case (state)
            S0: next_state = IN ? S1 : S0;          // 1 -> have "1"
            S1: next_state = IN ? S1 : S2;          // 0 -> have "10"; 1 stays "1"
            S2: next_state = IN ? S1 : S3;          // 0 -> have "100"; 1 -> restart "1"
            S3: next_state = IN ? S4 : S0;          // 1 -> have "1001"; 0 -> "100..0" restart
            S4: next_state = IN ? S1 : S2;          // 1 -> match, overlap leaves "1"; 0 -> "10"
            default: next_state = S0;
        endcase
    end

    // Mealy output: asserted in S4 when IN==1 (completes "10011")
    assign MATCH = (state == S4) && (IN == 1'b1);

endmodule
