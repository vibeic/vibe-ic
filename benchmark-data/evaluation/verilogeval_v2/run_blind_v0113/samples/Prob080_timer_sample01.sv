module TopModule (
    input        clk,
    input        load,
    input  [9:0] data,
    output       tc
);
    reg [9:0] cnt;
    always @(posedge clk) begin
        if (load)
            cnt <= data;
        else if (cnt != 10'd0)
            cnt <= cnt - 10'd1;
    end
    assign tc = (cnt == 10'd0);
endmodule
