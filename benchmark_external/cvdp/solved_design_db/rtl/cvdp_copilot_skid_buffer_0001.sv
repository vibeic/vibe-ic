// Pipelined skid-buffer system:
//   data_i -> skid_0 -> reg1 -> skid_2 -> reg3 -> data_o
// Skid buffers pass data combinationally while downstream is ready and
// absorb one beat when it stalls; registers add one pipeline cycle each.
module pipelined_skid_buffer(
    input wire clock,
    input wire rst,

    input wire [3:0] i_data,
    input wire i_valid,
    output wire ready_o,
    output wire valid_o,
    output wire [3:0] data_o,
    input wire ready_i

    );

    // skid_0 <-> reg1
    wire [3:0] s0_data;
    wire       s0_valid;
    wire       r1_ready;   // reg1.ready_out -> skid_0.i_ready
    // reg1 <-> skid_2
    wire [3:0] r1_data;
    wire       r1_valid;
    wire       s2_ready;   // skid_2.o_ready -> reg1.ready_in
    // skid_2 <-> reg3
    wire [3:0] s2_data;
    wire       s2_valid;
    wire       r3_ready;   // reg3.ready_out -> skid_2.i_ready

    skid_buffer skid_0 (
        .clk     (clock),
        .reset   (rst),
        .i_data  (i_data),
        .i_valid (i_valid),
        .o_ready (ready_o),
        .o_data  (s0_data),
        .o_valid (s0_valid),
        .i_ready (r1_ready)
    );

    register reg1 (
        .clk       (clock),
        .rst       (rst),
        .data_in   (s0_data),
        .valid_in  (s0_valid),
        .ready_out (r1_ready),
        .valid_out (r1_valid),
        .data_out  (r1_data),
        .ready_in  (s2_ready)
    );

    skid_buffer skid_2 (
        .clk     (clock),
        .reset   (rst),
        .i_data  (r1_data),
        .i_valid (r1_valid),
        .o_ready (s2_ready),
        .o_data  (s2_data),
        .o_valid (s2_valid),
        .i_ready (r3_ready)
    );

    register reg3 (
        .clk       (clock),
        .rst       (rst),
        .data_in   (s2_data),
        .valid_in  (s2_valid),
        .ready_out (r3_ready),
        .valid_out (valid_o),
        .data_out  (data_o),
        .ready_in  (ready_i)
    );

endmodule

module register(
    input clk,
    input rst,

    input [3:0] data_in,
    input valid_in,
    output ready_out,
    output valid_out,
    output [3:0] data_out,
    input  ready_in
    );

    reg [3:0] mem;
    reg       data_present;

    assign data_out  = mem;
    assign valid_out = data_present;
    // Can accept new data when empty, or when downstream takes the current beat.
    assign ready_out = ~data_present | ready_in;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            mem          <= 4'd0;
            data_present <= 1'b0;
        end else begin
            if (ready_out) begin
                data_present <= valid_in;
                if (valid_in)
                    mem <= data_in;
            end
        end
    end

endmodule


module skid_buffer(

input  clk,
input  reset ,

input  [3:0]i_data,
input  i_valid,
output o_ready,

output [3:0]o_data,
output o_valid,
input  i_ready

);

    reg [3:0] data_reg;
    reg       buffer;     // high when the skid register holds a beat

    // Accept new input whenever the skid register is empty.
    assign o_ready = ~buffer;
    // Output the buffered beat if present, otherwise pass the input through.
    assign o_data  = buffer ? data_reg : i_data;
    assign o_valid = buffer ? 1'b1     : i_valid;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            data_reg <= 4'd0;
            buffer   <= 1'b0;
        end else begin
            if (~buffer) begin
                // Downstream stalled while a valid beat is presented: skid it.
                if (i_valid & ~i_ready)
                    buffer <= 1'b1;
                data_reg <= i_data;
            end else begin
                // Holding a beat: release it once downstream is ready.
                if (i_ready)
                    buffer <= 1'b0;
            end
        end
    end

endmodule
