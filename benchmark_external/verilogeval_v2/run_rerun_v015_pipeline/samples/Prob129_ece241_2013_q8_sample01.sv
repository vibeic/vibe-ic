module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output reg z
);

    localparam S0 = 2'd0;  // no useful history
    localparam S1 = 2'd1;  // last bits end in "1"
    localparam S2 = 2'd2;  // last bits end in "10"

    reg [1:0] state, next;

    // Mealy next-state logic
    always @(*) begin
        case (state)
            S0: next = x ? S1 : S0;
            S1: next = x ? S1 : S2;
            S2: next = x ? S1 : S0;  // overlapping: trailing 1 starts new seq
            default: next = S0;
        endcase
    end

    // Mealy output: z=1 when in S2 ("10" seen) and x==1 -> "101" detected
    always @(*) begin
        z = (state == S2) && (x == 1'b1);
    end

    // Negative-edge-triggered asynchronous reset (active low)
    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else
            state <= next;
    end

endmodule
