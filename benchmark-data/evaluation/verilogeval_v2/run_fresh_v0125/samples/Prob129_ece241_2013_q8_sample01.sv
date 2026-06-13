module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output reg z
);

    // 3 states: S0 (start/seen nothing), S1 (seen 1), S2 (seen 10)
    localparam S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
    reg [1:0] state;

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else begin
            case (state)
                S0: state <= x ? S1 : S0;
                S1: state <= x ? S1 : S2;
                S2: state <= x ? S1 : S0;
                default: state <= S0;
            endcase
        end
    end

    // Mealy output: assert z when in S2 and x=1 (completes 101), overlapping
    always @(*) begin
        z = (state == S2) && x;
    end

endmodule
