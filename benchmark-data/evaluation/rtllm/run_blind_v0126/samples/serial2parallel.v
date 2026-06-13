module serial2parallel (
    input            clk,
    input            rst_n,
    input            din_serial,
    input            din_valid,
    output reg [7:0] dout_parallel,
    output reg       dout_valid
);

    // 4-bit counter tracking how many serial bits have been received.
    reg [3:0] cnt;

    // Count valid serial bits (0..7). Wraps after the 8th bit.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cnt <= 4'd0;
        else if (din_valid) begin
            if (cnt == 4'd7)
                cnt <= 4'd0;
            else
                cnt <= cnt + 4'd1;
        end
    end

    // Shift serial data in MSB-first: first bit ends up in dout_parallel[7].
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            dout_parallel <= 8'd0;
        else if (din_valid)
            dout_parallel <= {dout_parallel[6:0], din_serial};
    end

    // dout_valid asserts on the cycle the 8th bit is shifted in (cnt == 7),
    // i.e. exactly when dout_parallel holds the complete 8-bit word.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            dout_valid <= 1'b0;
        else if (din_valid && cnt == 4'd7)
            dout_valid <= 1'b1;
        else
            dout_valid <= 1'b0;
    end

endmodule
