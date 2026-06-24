// accu — serial 8-bit input accumulator.
// Accumulates four valid (valid_in=1) data_in values; when the 4th valid
// datum arrives, data_out presents the sum of those four and valid_out
// pulses high for exactly one cycle. Active-low synchronous reset.
module accu (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  data_in,
    input  wire        valid_in,
    output reg         valid_out,
    output reg  [9:0]  data_out
);

    reg [9:0] acc;      // running sum of the in-flight group (max 4*255 = 1020 < 1024)
    reg [1:0] cnt;      // count of valid data accepted in the current group (0..3)

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc       <= 10'd0;
            cnt       <= 2'd0;
            data_out  <= 10'd0;
            valid_out <= 1'b0;
        end else if (valid_in) begin
            if (cnt == 2'd3) begin
                // 4th valid datum of the group: emit the accumulated sum.
                data_out  <= acc + data_in;
                valid_out <= 1'b1;
                acc       <= 10'd0;   // start a fresh group
                cnt       <= 2'd0;
            end else begin
                acc       <= acc + data_in;
                cnt       <= cnt + 2'd1;
                valid_out <= 1'b0;
            end
        end else begin
            valid_out <= 1'b0;        // valid_out lasts only one cycle
        end
    end

endmodule
