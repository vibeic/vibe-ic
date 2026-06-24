// fsm — Mealy detector for the bit sequence 10011, overlap allowed.
// MATCH asserts (combinationally) in the same cycle the trailing IN=1 completes 10011.
// State = length of the currently matched prefix of 10011 (0..4). KMP-style overlap:
// from the match (S4 & IN=1) the trailing 1 re-seeds prefix "1" (next = S1).
module fsm (
    input  wire IN,
    input  wire CLK,
    input  wire RST,
    output wire MATCH
);
    localparam S0 = 3'd0,  // matched ""
               S1 = 3'd1,  // matched "1"
               S2 = 3'd2,  // matched "10"
               S3 = 3'd3,  // matched "100"
               S4 = 3'd4;  // matched "1001"
    reg [2:0] state;

    // Mealy output: full pattern completes when in S4 and IN=1
    assign MATCH = (state == S4) && (IN == 1'b1);

    always @(posedge CLK or posedge RST) begin
        if (RST)
            state <= S0;
        else begin
            case (state)
                S0: state <= IN ? S1 : S0;
                S1: state <= IN ? S1 : S2;
                S2: state <= IN ? S1 : S3;
                S3: state <= IN ? S4 : S0;
                S4: state <= IN ? S1 : S2;   // IN=1 completes (MATCH) then re-seed "1"
                default: state <= S0;
            endcase
        end
    end
endmodule
