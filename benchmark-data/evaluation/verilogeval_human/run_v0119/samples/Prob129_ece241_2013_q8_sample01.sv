module TopModule (
  input clk,
  input aresetn,
  input x,
  output reg z
);
    localparam S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
    reg [1:0] state;

    always @(posedge clk or negedge aresetn) begin
        if (!aresetn)
            state <= S0;
        else begin
            case (state)
                S0: state <= x ? S1 : S0;     // wait for 1
                S1: state <= x ? S1 : S2;     // saw 1; on 0 -> saw 10
                S2: state <= x ? S1 : S0;     // saw 10; on 1 -> detect & restart at 1
                default: state <= S0;
            endcase
        end
    end

    // Mealy output: 101 completed when in S2 and x=1
    always @(*) begin
        z = (state == S2) && (x == 1'b1);
    end
endmodule
