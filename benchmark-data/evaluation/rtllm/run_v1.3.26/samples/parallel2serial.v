module parallel2serial(
    input        clk,
    input        rst_n,
    input  [3:0] d,
    output reg   valid_out,
    output       dout
);

reg [3:0] data;
reg [1:0] cnt;

assign dout = data[3];

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        data      <= 4'd0;
        cnt       <= 2'd0;
        valid_out <= 1'b0;
    end else if (cnt == 2'd3) begin
        data      <= d;
        cnt       <= 2'd0;
        valid_out <= 1'b1;
    end else begin
        cnt       <= cnt + 2'd1;
        valid_out <= 1'b0;
        data      <= {data[2:0], data[3]};
    end
end

endmodule
