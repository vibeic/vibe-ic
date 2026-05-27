module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output reg z
);

    // S0: nothing / saw 0.  S1: saw 1.  S2: saw 10.  Mealy, overlapping.
    localparam S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
    reg [1:0] state, nstate;

    always @(*) begin
        case (state)
            S0: nstate = x ? S1 : S0;
            S1: nstate = x ? S1 : S2;
            S2: nstate = x ? S1 : S0;
            default: nstate = S0;
        endcase
    end

    // Mealy output: 101 completes when in S2 and x=1.
    always @(*)
        z = (state == S2) && x;

    // Active-low asynchronous reset (triggered on the negative edge of aresetn).
    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else
            state <= nstate;
    end

endmodule
