module TopModule (
    input  [2:0] sel,
    input  [3:0] data0,
    input  [3:0] data1,
    input  [3:0] data2,
    input  [3:0] data3,
    input  [3:0] data4,
    input  [3:0] data5,
    output [3:0] out
);
    reg [3:0] out_r;
    always @(*) begin
        case (sel)
            3'd0:    out_r = data0;
            3'd1:    out_r = data1;
            3'd2:    out_r = data2;
            3'd3:    out_r = data3;
            3'd4:    out_r = data4;
            3'd5:    out_r = data5;
            default: out_r = 4'b0000;
        endcase
    end
    assign out = out_r;
endmodule
