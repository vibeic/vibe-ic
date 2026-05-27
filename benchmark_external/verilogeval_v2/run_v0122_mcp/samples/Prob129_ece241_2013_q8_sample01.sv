module TopModule (
    input  clk,
    input  aresetn,   // active-low asynchronous reset (negative-edge triggered)
    input  x,
    output z
);

    localparam S0 = 2'd0,  // no useful prefix
               S1 = 2'd1,  // last bit seen contributes "1"
               S2 = 2'd2;  // seen "10"

    reg [1:0] state, nxt;

    always @(*) begin
        case (state)
            S0: nxt = x ? S1 : S0;
            S1: nxt = x ? S1 : S2;
            S2: nxt = x ? S1 : S0;   // on x=1 -> 101 detected, trailing 1 starts new
            default: nxt = S0;
        endcase
    end

    // Asynchronous active-low reset
    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else
            state <= nxt;
    end

    // Mealy output: detect 101 (in S2 and x=1)
    assign z = (state == S2) && x;

endmodule
