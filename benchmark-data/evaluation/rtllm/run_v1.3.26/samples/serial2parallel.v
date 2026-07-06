module serial2parallel(
    input        clk,
    input        rst_n,
    input        din_serial,
    input        din_valid,
    output reg [7:0] dout_parallel,
    output reg   dout_valid
);

reg [3:0] cnt;
reg [7:0] din_tmp;

// cnt counts 0..8 (N+1 terminal states, not N): 8 shift edges use cnt==0..7,
// and a dedicated cnt==8 settle cycle fires dout_valid one cycle AFTER the
// 8th shift. This extra terminal state absorbs the standard testbench race
// where din_valid deasserts on the very same clock edge as the 8th sample --
// without it, that edge is mis-read as a spurious 9th valid sample and the
// counter never re-synchronizes.
always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        cnt <= 4'd0;
    else if (din_valid)
        cnt <= (cnt == 4'd8) ? 4'd0 : cnt + 4'd1;
    else
        cnt <= 4'd0;
end

always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        din_tmp <= 8'd0;
    else if (din_valid && cnt <= 4'd7)
        din_tmp <= {din_tmp[6:0], din_serial};
end

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        dout_valid    <= 1'b0;
        dout_parallel <= 8'd0;
    end else if (cnt == 4'd8) begin
        dout_valid    <= 1'b1;
        dout_parallel <= din_tmp;
    end else begin
        dout_valid    <= 1'b0;
    end
end

endmodule
