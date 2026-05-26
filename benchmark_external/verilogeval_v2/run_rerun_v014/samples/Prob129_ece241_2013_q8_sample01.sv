module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output z
);

    localparam S0 = 2'd0;  // no useful prefix
    localparam S1 = 2'd1;  // saw "1"
    localparam S2 = 2'd2;  // saw "10"

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            S0: next = x ? S1 : S0;
            S1: next = x ? S1 : S2;
            S2: next = x ? S1 : S0;
            default: next = S0;
        endcase
    end

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else
            state <= next;
    end

    // Mealy output: detect "101" -> in state S2 (saw "10") with x=1
    assign z = (state == S2) && (x == 1'b1);

endmodule
