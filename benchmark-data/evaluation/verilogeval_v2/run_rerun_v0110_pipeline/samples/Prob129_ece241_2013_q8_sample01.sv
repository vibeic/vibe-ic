module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output z
);
    localparam S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
    reg [1:0] state;

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else begin
            case (state)
                S0: state <= x ? S1 : S0;       // saw 1 -> S1
                S1: state <= x ? S1 : S2;       // saw 10 -> S2
                S2: state <= x ? S1 : S0;       // saw 101 -> on 1, that 1 starts next
                default: state <= S0;
            endcase
        end
    end

    // Mealy: assert z when in S2 and x=1 (completes 101)
    assign z = (state == S2) && x;
endmodule
