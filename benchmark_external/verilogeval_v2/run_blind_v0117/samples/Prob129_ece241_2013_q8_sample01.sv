module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output z
);
    // S0: no useful prefix. S1: last bit was 1. S2: prefix "10".
    localparam S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
    reg [1:0] state, nstate;

    always @(*) begin
        case (state)
            S0: nstate = x ? S1 : S0;
            S1: nstate = x ? S1 : S2;   // saw "1", then 0 -> "10"
            S2: nstate = x ? S1 : S0;   // "10" then 1 -> "101"; the trailing 1 = new S1 (overlap)
            default: nstate = S0;
        endcase
    end

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else
            state <= nstate;
    end

    // Mealy output: in S2 ("10") and x==1 -> "101" detected.
    assign z = (state == S2) && x;
endmodule
