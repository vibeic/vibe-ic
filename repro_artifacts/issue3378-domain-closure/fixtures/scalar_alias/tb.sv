module tb; reg clk=0,rst=1;reg[2:0]data=3'd2;reg[1:0]phase=0;wire[2:0]value;neutral dut(.*);integer i;
initial begin #1;clk=1;#1;clk=0;rst=0;for(i=0;i<3;i=i+1)begin phase=i;#1;clk=1;#1;clk=0;end
$display("SERIAL_RECONSTRUCTION binary=%d observed=%d",data,value);if(value!==data)$fatal(1,"SERIAL_GRAY_BINARY_MISMATCH");$finish;end endmodule
