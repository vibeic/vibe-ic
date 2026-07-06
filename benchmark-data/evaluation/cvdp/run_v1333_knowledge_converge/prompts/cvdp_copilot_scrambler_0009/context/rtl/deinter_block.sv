module deinter_block #(
    parameter ROW_COL_WIDTH = 16,
    parameter SUB_BLOCKS    = 4,
    parameter DATA_WIDTH    = ROW_COL_WIDTH*ROW_COL_WIDTH,
    parameter OUT_DATA_WIDTH= 16,
    parameter WAIT_CYCLES   = 4
)(
    input  logic clk,
    input  logic rst_n,
    input  logic i_valid,
    input  logic [DATA_WIDTH-1:0] in_data, // Input: 256 bits
    output logic [OUT_DATA_WIDTH-1:0] out_data // Output: 256 bits rearranged
);

localparam CHUNK = 8;
localparam NBW_COUNTER = $clog2(SUB_BLOCKS) + 1;
localparam NBW_COUNTER_SUB_OUT = 2;

localparam OUT_CYCLES = 32;

localparam N_CYCLES = SUB_BLOCKS*DATA_WIDTH/OUT_DATA_WIDTH;
localparam NBW_COUNTER_OUTPUT = $clog2(N_CYCLES);
logic [NBW_COUNTER_OUTPUT-1:0] counter_output;

logic [NBW_COUNTER-1:0] counter_sub_blocks;
logic [NBW_COUNTER_SUB_OUT-1:0] counter_sub_out;

logic [DATA_WIDTH-1:0] in_data_reg [SUB_BLOCKS-1:0];
logic [DATA_WIDTH-1:0] out_data_intra_block [SUB_BLOCKS-1:0];
logic [DATA_WIDTH-1:0] out_data_intra_block_reg [SUB_BLOCKS-1:0];
logic [DATA_WIDTH-1:0] out_data_aux [SUB_BLOCKS-1:0];
logic start_intra;

always_ff @(posedge clk or negedge rst_n ) begin
   if(!rst_n) begin
      counter_sub_blocks <= {NBW_COUNTER{1'b0}};
      start_intra <= 0;
      for(int i = 0; i < SUB_BLOCKS; i++) begin
         in_data_reg[i] <= {DATA_WIDTH{1'b0}};
      end
   end
   else begin
      if(i_valid) begin
         in_data_reg[counter_sub_blocks] <= in_data;

         if(counter_sub_blocks == SUB_BLOCKS) begin
            counter_sub_blocks <= {NBW_COUNTER{1'b0}};
         end
         else begin
            start_intra <= 0;
            counter_sub_blocks <= counter_sub_blocks + 1;
         end
      end
      else if(counter_sub_blocks == SUB_BLOCKS) begin
         start_intra        <= 1;
         counter_sub_blocks <= {NBW_COUNTER{1'b0}};
      end
   end
end

always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
      for(int i = 0; i < SUB_BLOCKS; i++)
         out_data_intra_block_reg[i] <= {DATA_WIDTH{1'b0}};
   end
   else begin
      if(start_intra)
         for(int i = 0; i < SUB_BLOCKS; i++) 
            out_data_intra_block_reg[i] <= in_data_reg[i];
   end
end

logic [WAIT_CYCLES-1:0] start_intra_ff;
logic enable_output;

always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
      enable_output  <= 0;
      start_intra_ff <= 0;
   end
   else begin
      enable_output <= start_intra_ff[WAIT_CYCLES-1];
      start_intra_ff<= {start_intra_ff[WAIT_CYCLES-1:1],start_intra};
   end
end

always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
      for(int i = 0; i < SUB_BLOCKS; i++)
         out_data_aux[i] <= {DATA_WIDTH{1'b0}};
   end
   else begin
      if(start_intra) begin
         for(int i = 0; i < 32; i++) begin
            out_data_aux[0][(i+1)*CHUNK-1-:CHUNK] <= out_data_intra_block_reg[i%4][((i+1)*CHUNK)-1-:CHUNK];
            out_data_aux[1][(i+1)*CHUNK-1-:CHUNK] <= out_data_intra_block_reg[i%4][(((i+1)%OUT_CYCLES+1)*CHUNK)-1-:CHUNK];
            out_data_aux[2][(i+1)*CHUNK-1-:CHUNK] <= out_data_intra_block_reg[i%4][(((i+2)%OUT_CYCLES+1)*CHUNK)-1-:CHUNK];
            out_data_aux[3][(i+1)*CHUNK-1-:CHUNK] <= out_data_intra_block_reg[i%4][(((i+3)%OUT_CYCLES+1)*CHUNK)-1-:CHUNK];
         end
      end
   end
end

always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
      out_data        <= {DATA_WIDTH{1'b0}};      
      counter_sub_out <= {NBW_COUNTER_SUB_OUT{1'b0}};
      counter_output  <= {NBW_COUNTER_OUTPUT{1'b0}};     
   end
   else begin
      counter_sub_out <= counter_sub_out + 1;
      counter_output  <= counter_output  + 1;
      out_data        <= out_data_aux[counter_sub_out][((counter_output%(DATA_WIDTH/OUT_DATA_WIDTH) + 1))*OUT_DATA_WIDTH-1-:OUT_DATA_WIDTH];
   end
end

endmodule