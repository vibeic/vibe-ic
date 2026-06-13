module TopModule (
    input  clk,
    input  aresetn,   // active-low asynchronous reset, negative-edge triggered
    input  x,
    output z
);
    localparam S0 = 2'd0;  // no useful prefix
    localparam S1 = 2'd1;  // seen "1"
    localparam S2 = 2'd2;  // seen "10"

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

    // Mealy output: 101 completed when in S2 and x==1
    assign z = (state == S2) && (x == 1'b1);
endmodule
