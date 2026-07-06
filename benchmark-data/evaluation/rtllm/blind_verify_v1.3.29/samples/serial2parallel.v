module serial2parallel (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       din_serial,
    input  wire       din_valid,
    output reg  [7:0] dout_parallel,
    output reg        dout_valid
);

    reg [3:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt           <= 4'd0;
            dout_parallel <= 8'd0;
            dout_valid    <= 1'b0;
        end else if (din_valid) begin
            // first-received bit ends up at the MSB: new bit enters at the
            // LSB end while the register shifts left.
            dout_parallel <= {dout_parallel[6:0], din_serial};
            if (cnt == 4'd7) begin
                cnt        <= 4'd0;
                dout_valid <= 1'b1;
            end else begin
                cnt        <= cnt + 4'd1;
                dout_valid <= 1'b0;
            end
        end else begin
            dout_valid <= 1'b0;
        end
    end

endmodule
