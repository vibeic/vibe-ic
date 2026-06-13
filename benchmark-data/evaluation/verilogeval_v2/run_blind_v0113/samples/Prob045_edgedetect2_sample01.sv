module TopModule (
    input        clk,
    input  [7:0] in,
    output [7:0] anyedge
);
    reg [7:0] in_d = 8'b0;
    reg [7:0] anyedge_r = 8'b0;

    always @(posedge clk) begin
        in_d      <= in;
        anyedge_r <= in ^ in_d;   // any transition between previous two samples
    end

    assign anyedge = anyedge_r;
endmodule
