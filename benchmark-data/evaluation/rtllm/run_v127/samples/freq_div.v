// freq_div: 100MHz -> 50MHz (/2), 10MHz (/10), 1MHz (/100)
// Spec-stated implementation: async active-high RST.
module freq_div (
    input  wire CLK_in,
    input  wire RST,
    output reg  CLK_50,
    output reg  CLK_10,
    output reg  CLK_1
);

    // /2 : toggle every input clock edge -> 50 MHz
    always @(posedge CLK_in or posedge RST) begin
        if (RST)
            CLK_50 <= 1'b0;
        else
            CLK_50 <= ~CLK_50;
    end

    // /10 : toggle when cnt_10 reaches 4 -> 10 MHz
    reg [3:0] cnt_10;
    always @(posedge CLK_in or posedge RST) begin
        if (RST) begin
            CLK_10 <= 1'b0;
            cnt_10 <= 4'd0;
        end else if (cnt_10 == 4'd4) begin
            CLK_10 <= ~CLK_10;
            cnt_10 <= 4'd0;
        end else begin
            cnt_10 <= cnt_10 + 4'd1;
        end
    end

    // /100 : toggle when cnt_100 reaches 49 -> 1 MHz
    reg [5:0] cnt_100;
    always @(posedge CLK_in or posedge RST) begin
        if (RST) begin
            CLK_1   <= 1'b0;
            cnt_100 <= 6'd0;
        end else if (cnt_100 == 6'd49) begin
            CLK_1   <= ~CLK_1;
            cnt_100 <= 6'd0;
        end else begin
            cnt_100 <= cnt_100 + 6'd1;
        end
    end

endmodule
