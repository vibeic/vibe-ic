module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output reg z
);

    localparam S0 = 2'd0;  // no useful prefix
    localparam S1 = 2'd1;  // saw "1"
    localparam S2 = 2'd2;  // saw "10"

    reg [1:0] state, next;

    always @(*) begin
        next = state;
        z    = 1'b0;
        case (state)
            S0: next = x ? S1 : S0;
            S1: next = x ? S1 : S2;
            S2: begin
                if (x) begin
                    z    = 1'b1;   // "101" detected
                    next = S1;     // overlap: trailing 1 starts new prefix
                end else begin
                    next = S0;
                end
            end
            default: next = S0;
        endcase
    end

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else
            state <= next;
    end

endmodule
