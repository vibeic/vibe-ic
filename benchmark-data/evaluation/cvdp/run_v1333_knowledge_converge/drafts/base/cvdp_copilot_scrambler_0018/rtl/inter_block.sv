module inter_block #(
    parameter ROW_COL_WIDTH = 16,
    parameter SUB_BLOCKS    = 4,
    parameter DATA_WIDTH    = ROW_COL_WIDTH*ROW_COL_WIDTH
)(
    input  logic clk,
    input  logic rst_n,
    input  logic i_valid,
    input  logic [DATA_WIDTH-1:0] in_data, // Input: 256 bits
    output logic [DATA_WIDTH-1:0] out_data // Output: 256 bits rearranged
);

localparam CHUNK = 8;
localparam NBW_COUNTER = $clog2(SUB_BLOCKS) + 1;
localparam NBW_COUNTER_SUB_OUT = 2;
localparam OUT_CYCLES = 32;
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

genvar k;
generate
   for(k = 0; k < SUB_BLOCKS; k++) begin
      intra_block uu_intra_block (
         .in_data(in_data_reg[k]),
         .out_data(out_data_intra_block[k])
      );
   end
endgenerate

always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
      for(int i = 0; i < SUB_BLOCKS; i++) begin
         out_data_intra_block_reg[i] <= {DATA_WIDTH{1'b0}};
      end
   end
   else begin
      if(start_intra) begin
         for(int i = 0; i < SUB_BLOCKS; i++) begin
            out_data_intra_block_reg[i] <= out_data_intra_block[i];
         end
      end
   end
end

// Combinational rearrangement network (previously blocking assignments
// inside the sequential block). Moving it here removes the mixing of
// blocking and non-blocking assignments while preserving functionality:
// out_data below still samples the freshly-computed value in the same cycle.
always_comb begin
   for(int i = 0; i < SUB_BLOCKS; i++) begin
      out_data_aux[i] = {DATA_WIDTH{1'b0}};
   end
   for(int i = 0; i < 32; i++) begin
      out_data_aux[0][(i+1)*CHUNK-1-:CHUNK] = out_data_intra_block_reg[i%4][((i+1)*CHUNK)-1-:CHUNK];
      out_data_aux[1][(i+1)*CHUNK-1-:CHUNK] = out_data_intra_block_reg[i%4][(((i+1)%OUT_CYCLES+1)*CHUNK)-1-:CHUNK];
      out_data_aux[2][(i+1)*CHUNK-1-:CHUNK] = out_data_intra_block_reg[i%4][(((i+2)%OUT_CYCLES+1)*CHUNK)-1-:CHUNK];
      out_data_aux[3][(i+1)*CHUNK-1-:CHUNK] = out_data_intra_block_reg[i%4][(((i+3)%OUT_CYCLES+1)*CHUNK)-1-:CHUNK];
   end
end

always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
      counter_sub_out <= {NBW_COUNTER_SUB_OUT{1'b1}};
      out_data        <= {DATA_WIDTH{1'b0}};
   end
   else begin
      if(start_intra) begin
         counter_sub_out <= counter_sub_out + 1;
         out_data        <= out_data_aux[counter_sub_out];
      end
   end
end

endmodule
