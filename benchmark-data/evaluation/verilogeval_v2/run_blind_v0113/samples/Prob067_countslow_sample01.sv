module TopModule (
    input        clk,
    input        reset,
    input        slowena,
    output [3:0] q
);
    reg [3:0] cnt;
    always @(posedge clk) begin
        if (reset)
            cnt <= 4'd0;
        else if (slowena) begin
            if (cnt == 4'd9)
                cnt <= 4'd0;
            else
                cnt <= cnt + 4'd1;
        end
    end
    assign q = cnt;
endmodule
