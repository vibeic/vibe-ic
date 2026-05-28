module parallel2serial (
    input  clk,
    input  rst_n,
    input  [3:0] d,
    output reg valid_out,
    output dout
);

    reg [3:0] data;
    reg [1:0] cnt;

    // Serial output is always the MSB of the data register
    assign dout = data[3];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt       <= 2'd0;
            data      <= 4'd0;
            valid_out <= 1'b0;
        end else if (cnt == 2'd3) begin
            data      <= d;        // load new parallel word
            cnt       <= 2'd0;
            valid_out <= 1'b1;
        end else begin
            data      <= {data[2:0], data[3]}; // rotate left
            cnt       <= cnt + 2'd1;
            valid_out <= 1'b0;
        end
    end

endmodule
