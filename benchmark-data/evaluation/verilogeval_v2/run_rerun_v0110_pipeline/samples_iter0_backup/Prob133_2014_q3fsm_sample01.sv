module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output reg z
);
    // state A waits for s. Then repeated 3-cycle windows of w.
    localparam A = 1'b0, B = 1'b1;
    reg state;
    reg [1:0] cnt;    // position within window: 0,1,2
    reg [1:0] ones;   // number of w=1 seen so far in window

    always @(posedge clk) begin
        if (reset) begin
            state <= A;
            cnt   <= 2'd0;
            ones  <= 2'd0;
            z     <= 1'b0;
        end else begin
            z <= 1'b0;
            case (state)
                A: begin
                    if (s) begin
                        // move to B next cycle; w sampling begins in B
                        state <= B;
                        cnt   <= 2'd0;
                        ones  <= 2'd0;
                    end
                end
                B: begin
                    // sample w this cycle (1st when cnt==0, etc.)
                    if (cnt == 2'd2) begin
                        // third w sample this cycle; decide, z asserted next cycle
                        if ((ones + (w ? 2'd1 : 2'd0)) == 2'd2)
                            z <= 1'b1;
                        // restart window
                        cnt  <= 2'd0;
                        ones <= 2'd0;
                    end else begin
                        cnt  <= cnt + 2'd1;
                        ones <= ones + (w ? 2'd1 : 2'd0);
                    end
                end
            endcase
        end
    end
endmodule
