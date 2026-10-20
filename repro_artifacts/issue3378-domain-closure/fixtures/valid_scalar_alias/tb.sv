module tb;reg clk=0,rst=1,seed=0;reg[2:0]data=0;reg[1:0]phase=0;wire seen;neutral d(.*);integer i;
initial begin #1;clk=1;#1;clk=0;rst=0;
for(i=0;i<4;i=i+1)begin case(i)0:seed=0;1:seed=1;2:seed=1'bx;3:seed=1'bz;endcase
#1;clk=1;#1;clk=0;if(seen !== (seed===1'b1))$fatal(1,"VALID_SCALAR_CONTROL_FAILED");end
$display("VALID_SCALAR_CONTROL_PASS cases=4");$finish;end endmodule
