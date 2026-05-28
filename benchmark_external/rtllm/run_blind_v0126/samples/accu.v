module accu (
    input              clk,
    input              rst_n,
    input      [7:0]   data_in,
    input              valid_in,
    output reg         valid_out,
    output reg [9:0]   data_out
);

    reg [9:0] sum;
    reg [1:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum       <= 10'd0;
            cnt       <= 2'd0;
            data_out  <= 10'd0;
            valid_out <= 1'b0;
        end else begin
            if (valid_in) begin
                if (cnt == 2'd3) begin
                    // 4th valid datum arrives: output accumulation, reset for next group
                    data_out  <= sum + data_in;
                    valid_out <= 1'b1;
                    sum       <= 10'd0;
                    cnt       <= 2'd0;
                end else begin
                    sum       <= sum + data_in;
                    cnt       <= cnt + 2'd1;
                    valid_out <= 1'b0;
                end
            end else begin
                valid_out <= 1'b0;
            end
        end
    end

endmodule
