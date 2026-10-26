module neutral_unit(clk, rst, data, result);
 input clk;
 input rst;
 input data;
 output result;
 wire d0, d1, stage;
 sky130_fd_sc_hd__mux2_1 rm0 (.A0(data), .A1(1'b0), .S(rst), .X(d0));
 sky130_fd_sc_hd__mux2_1 rm1 (.A0(stage), .A1(1'b0), .S(rst), .X(d1));
 sky130_fd_sc_hd__dfxtp_1 r0 (.CLK(clk), .D(d0), .Q(stage));
 sky130_fd_sc_hd__dfxtp_1 r1 (.CLK(clk), .D(d1), .Q(result));
endmodule
