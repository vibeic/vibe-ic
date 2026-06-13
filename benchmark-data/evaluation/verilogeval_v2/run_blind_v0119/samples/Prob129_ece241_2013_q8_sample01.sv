module TopModule(
    input  clk,
    input  aresetn,
    input  x,
    output z
);
    // Mealy 101 detector, 3 states, overlapping.
    localparam S0 = 2'd0; // no progress
    localparam S1 = 2'd1; // saw "1"
    localparam S2 = 2'd2; // saw "10"
    reg [1:0] state, next;

    always @(*) begin
        case (state)
            S0: next = x ? S1 : S0;
            S1: next = x ? S1 : S2;
            S2: next = x ? S1 : S0; // overlapping: a '1' here both completes 101 and starts a new '1'
            default: next = S0;
        endcase
    end

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)               // asynchronous active-low reset
            state <= S0;
        else
            state <= next;
    end

    // Mealy output: 101 completes when in S2 and x=1
    assign z = (state == S2) && (x == 1'b1);
endmodule
