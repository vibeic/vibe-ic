module TopModule(
    input  clk,
    input  load,
    input  [9:0] data,
    output tc
);
    reg [9:0] count = 10'd0;

    always @(posedge clk) begin
        if (load)
            count <= data;
        else if (count != 10'd0)
            count <= count - 1'b1;
    end

    assign tc = (count == 10'd0);
endmodule
