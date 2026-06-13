module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output z
);
    localparam S0 = 2'd0;  // no useful prefix
    localparam S1 = 2'd1;  // last bit was 1
    localparam S2 = 2'd2;  // saw "10"

    reg [1:0] state;

    // Asynchronous active-low reset (negative-edge of aresetn)
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

    // Mealy output: detect "101" (in S2 with x=1)
    assign z = (state == S2) && (x == 1'b1);
endmodule
