// Parallel (multi-stream) run-length encoder. Each stream tracks the run length
// of consecutive identical bits independently, gated by stream_enable.
module parallel_run_length
#(
    parameter DATA_WIDTH  = 8,   // maximum run length per stream
    parameter NUM_STREAMS = 4    // number of parallel streams
)
(
    input  wire                         clk,
    input  wire                         reset_n,        // async active-low reset
    input  wire [NUM_STREAMS-1:0]       data_in,
    input  wire [NUM_STREAMS-1:0]       stream_enable,
    output wire [NUM_STREAMS-1:0]       data_out,
    output wire [(NUM_STREAMS*($clog2(DATA_WIDTH)+1))-1:0] run_value,
    output wire [NUM_STREAMS-1:0]       valid
);

    localparam W = $clog2(DATA_WIDTH) + 1;   // run-length counter width

    reg [W-1:0] run_length_arr [0:NUM_STREAMS-1];
    reg [W-1:0] run_value_arr  [0:NUM_STREAMS-1];
    reg         prev_arr       [0:NUM_STREAMS-1];
    reg         valid_arr      [0:NUM_STREAMS-1];
    reg         data_out_arr   [0:NUM_STREAMS-1];

    genvar i;
    generate
        for (i = 0; i < NUM_STREAMS; i = i + 1) begin : gen_stream

            // run-length counter / latched run value
            always @(posedge clk or negedge reset_n) begin
                if (!reset_n) begin
                    run_length_arr[i] <= {W{1'b0}};
                    run_value_arr[i]  <= {W{1'b0}};
                    prev_arr[i]       <= 1'b0;
                end else if (!stream_enable[i]) begin
                    // disabled stream: reset to defaults, resume fresh on re-enable
                    run_length_arr[i] <= {W{1'b0}};
                    run_value_arr[i]  <= {W{1'b0}};
                    prev_arr[i]       <= 1'b0;
                end else begin
                    if (data_in[i] == prev_arr[i]) begin
                        if (run_length_arr[i] == DATA_WIDTH)
                            run_value_arr[i] <= run_length_arr[i];
                        if (run_length_arr[i] < DATA_WIDTH)
                            run_length_arr[i] <= run_length_arr[i] + 1'b1;
                        else
                            run_length_arr[i] <= {{(W-1){1'b0}}, 1'b1};
                    end else begin
                        run_value_arr[i]  <= run_length_arr[i];
                        run_length_arr[i] <= {{(W-1){1'b0}}, 1'b1};
                    end
                    prev_arr[i] <= data_in[i];
                end
            end

            // valid / data_out generation
            always @(posedge clk or negedge reset_n) begin
                if (!reset_n) begin
                    valid_arr[i]    <= 1'b0;
                    data_out_arr[i] <= 1'b0;
                end else if (!stream_enable[i]) begin
                    valid_arr[i]    <= 1'b0;
                    data_out_arr[i] <= 1'b0;
                end else begin
                    if ((run_length_arr[i] == DATA_WIDTH) || (data_in[i] != prev_arr[i])) begin
                        valid_arr[i]    <= 1'b1;
                        data_out_arr[i] <= prev_arr[i];
                    end else begin
                        valid_arr[i]    <= 1'b0;
                        data_out_arr[i] <= 1'b0;
                    end
                end
            end

            // pack per-stream outputs into the flattened buses
            assign run_value[(i+1)*W-1 : i*W] = run_value_arr[i];
            assign valid[i]                   = valid_arr[i];
            assign data_out[i]                = data_out_arr[i];

        end
    endgenerate

endmodule
