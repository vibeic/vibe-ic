module hamming_code_receiver (
  input[7:0] data_in,
  output [3:0] data_out
);
 
  wire c1,c2,c3,error;
  reg[7:0] correct_data;
 
 
  assign c3 =  data_in[1] ^ data_in[3] ^ data_in[5] ^ data_in[7];
  assign c2 =  data_in[2] ^ data_in[3] ^ data_in[6] ^ data_in[7];
  assign c1 =  data_in[4] ^ data_in[5] ^ data_in[6] ^ data_in[7];
 
  assign error = ({c3,c2,c1}==3'b000) ? 1'b0 : 1'b1;
 
  always@(*)
  begin
    correct_data = 0;
    if(error)
    begin
      correct_data             = data_in;
      correct_data[{c1,c2,c3}] = ~correct_data[{c1,c2,c3}];
    end
    else
    begin
      correct_data             = data_in;
    end
  end
 
 assign data_out = {correct_data[7],correct_data[6],correct_data[5],correct_data[3]};
 
endmodule