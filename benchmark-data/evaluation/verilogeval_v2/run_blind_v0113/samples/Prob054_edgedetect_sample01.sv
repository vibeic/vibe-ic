module TopModule (
    input        clk,
    input  [7:0] in,
    output [7:0] pedge
);
    reg [7:0] in_d    = 8'b0;
    reg [7:0] pedge_r = 8'b0;

    always @(posedge clk) begin
        in_d    <= in;
        pedge_r <= ~in_d & in;   // rising edge between previous two samples
    end

    assign pedge = pedge_r;
endmodule
