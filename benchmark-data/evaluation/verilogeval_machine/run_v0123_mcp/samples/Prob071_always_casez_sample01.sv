module TopModule (
  input [7:0] in,
  output reg [2:0] pos
);
  always @(*) begin
    if (in[0])      pos = 3'h0;
    else if (in[1]) pos = 3'h1;
    else if (in[2]) pos = 3'h2;
    else if (in[3]) pos = 3'h3;
    else if (in[4]) pos = 3'h4;
    else if (in[5]) pos = 3'h5;
    else if (in[6]) pos = 3'h6;
    else if (in[7]) pos = 3'h7;
    else            pos = 3'h0;
  end
endmodule
