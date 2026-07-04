module perceptron_gates (
   input  logic clk,// Posedge clock
   input  logic rst_n,// Negedge reset
   input  logic signed [3:0] x1, // First Input of the Perceptron
   input  logic signed [3:0] x2, // Second Input of the Perceptron
   input  logic learning_rate, // Learning rate (alpha)
   input  logic signed [3:0] threshold, // Threshold value
   input  logic [1:0] gate_select, // Gate selection for target values
   output logic signed [3:0] percep_w1, // Trained Weight 1
   output logic signed [3:0] percep_w2, // Trained Weight 2
   output logic signed [3:0] percep_bias, // Trained Bias
   output logic [3:0] present_addr, // Current address in microcode ROM
   output logic stop, // Condition to indicate no learning has occurred(i.e. no weight change between iterations)
   output logic [2:0] input_index,// Vector to track the selection of target for a given input combination for a gate
   output logic signed [3:0] y_in, // Calculated Response
   output logic signed [3:0] y, // Calculated Response obtained by comparing y_in against a threshold value
   output logic signed [3:0] prev_percep_wt_1,//Value of Weight 1 during a previous iteration
   output logic signed [3:0] prev_percep_wt_2,//Value of Weight 2 during a previous iteration
   output logic signed [3:0] prev_percep_bias // Value of Bias during a previous iteration
);

   logic [7:0] microcode_rom [0:5];
   logic [3:0]  next_addr;
   logic [3:0]  train_action;
   logic [3:0]  microcode_addr;
   logic [15:0] microinstruction;
   logic signed [3:0] t1, t2, t3, t4;

   gate_target dut (
       .gate_select(gate_select),
       .o_1(t1),
       .o_2(t2),
       .o_3(t3),
       .o_4(t4)
   );

   logic signed [3:0] percep_wt_1_reg;
   logic signed [3:0] percep_wt_2_reg;
   logic signed [3:0] percep_bias_reg;

   logic signed [3:0] target;
   logic signed [3:0] prev_wt1_update;
   logic signed [3:0] prev_wt2_update;
   logic signed [3:0] prev_bias_update;

   logic signed [3:0] wt1_update;
   logic signed [3:0] wt2_update;
   logic signed [3:0] bias_update;
   logic [7:0] epoch_counter;

   logic [1:0]        gate_prev;     // previous gate_select (detects a new training run)
   logic signed [3:0] applied_x1;    // input latched for the pass currently in flight
   logic signed [3:0] applied_x2;
   logic              waiting;       // idle, holding weights until the next input arrives
   logic              armed;         // a (re)start is pending its first input vector
   logic [3:0]        arm_count;     // settle counter for the first vector after a restart
   logic signed [3:0] yin_c;         // combinational response

   localparam [3:0] ARM_SETTLE = 4'd6;  // clocks to wait before accepting a held first vector

   assign  prev_percep_wt_1 = prev_wt1_update;
   assign  prev_percep_wt_2 = prev_wt2_update;
   assign  prev_percep_bias = prev_bias_update;

   initial begin
      microcode_rom[0] = 8'b0001_0000;
      microcode_rom[1] = 8'b0010_0001;
      microcode_rom[2] = 8'b0011_0010;
      microcode_rom[3] = 8'b0100_0011;
      microcode_rom[4] = 8'b0101_0100;
      microcode_rom[5] = 8'b0000_0101;
   end

   always @(*) begin
      microinstruction = microcode_rom[microcode_addr];
      next_addr        = microinstruction[7:4];
      train_action     = microinstruction[3:0];
   end

   assign present_addr = microcode_addr;

   // The training set is presented one input vector at a time on (x1,x2).  The
   // engine performs exactly ONE learning pass (microcode 1->5) per applied input
   // vector and then idles, holding the trained weights, until the next vector is
   // applied (a change on x1/x2).  This keeps `input_index` paired one-to-one with
   // the input vector even when a vector is held for many clocks, and it survives a
   // new gate_select (which re-initialises and relearns from scratch).
   wire input_changed = (x1 != applied_x1) || (x2 != applied_x2);
   wire input_valid   = (x1 != 4'sd0) || (x2 != 4'sd0);

   always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
         microcode_addr   <= 4'd0;
         waiting          <= 1'b1;
         armed            <= 1'b1;
         arm_count        <= 4'd0;
         gate_prev        <= gate_select;
         applied_x1       <= 4'sd0;
         applied_x2       <= 4'sd0;
         percep_wt_1_reg  <= 4'sd0;
         percep_wt_2_reg  <= 4'sd0;
         percep_bias_reg  <= 4'sd0;
         input_index      <= 3'd0;
         stop             <= 1'b0;
         y_in             <= 4'sd0;
         y                <= 4'sd0;
         target           <= 4'sd0;
         prev_wt1_update  <= 4'sd0;
         prev_wt2_update  <= 4'sd0;
         prev_bias_update <= 4'sd0;
         wt1_update       <= 4'sd0;
         wt2_update       <= 4'sd0;
         bias_update      <= 4'sd0;
         epoch_counter    <= 8'd0;
      end else begin
         gate_prev <= gate_select;
         if (gate_select != gate_prev) begin
            // micro-action 0 : a new gate -> initialise weights/bias and relearn.
            percep_wt_1_reg  <= 4'sd0;
            percep_wt_2_reg  <= 4'sd0;
            percep_bias_reg  <= 4'sd0;
            input_index      <= 3'd0;
            stop             <= 1'b0;
            y_in             <= 4'sd0;
            y                <= 4'sd0;
            target           <= 4'sd0;
            prev_wt1_update  <= 4'sd0;
            prev_wt2_update  <= 4'sd0;
            prev_bias_update <= 4'sd0;
            wt1_update       <= 4'sd0;
            wt2_update       <= 4'sd0;
            bias_update      <= 4'sd0;
            epoch_counter    <= 8'd0;
            microcode_addr   <= 4'd0;
            waiting          <= 1'b1;
            armed            <= 1'b1;        // wait for this gate's first input vector
            arm_count        <= 4'd0;
         end else if (waiting) begin
            // Hold the weights; launch a pass on the next applied input vector.  A
            // change on (x1,x2) is always a new vector.  Right after a (re)start the
            // first vector may be applied with no edge (it can equal the previous
            // gate's last vector), so once armed we also accept a vector that has
            // stayed put for ARM_SETTLE clocks -- long enough to skip the brief stale
            // vector a gate switch leaves on the bus before its real first vector.
            if (input_changed) begin
               applied_x1     <= x1;
               applied_x2     <= x2;
               armed          <= 1'b0;
               arm_count      <= 4'd0;
               waiting        <= 1'b0;
               microcode_addr <= 4'd1;
            end else if (armed && input_valid) begin
               if (arm_count >= ARM_SETTLE) begin
                  applied_x1     <= x1;
                  applied_x2     <= x2;
                  armed          <= 1'b0;
                  arm_count      <= 4'd0;
                  waiting        <= 1'b0;
                  microcode_addr <= 4'd1;
               end else begin
                  arm_count <= arm_count + 4'd1;
               end
            end
         end else begin
            case (microcode_addr)
               4'd1: begin                       // y_in = bias + x1*w1 + x2*w2 ; threshold
                  yin_c = percep_bias_reg
                        + (applied_x1 * percep_wt_1_reg)
                        + (applied_x2 * percep_wt_2_reg);
                  y_in  <= yin_c;
                  if (yin_c > threshold)
                     y <= 4'sd1;
                  else if ((yin_c >= -threshold) && (yin_c <= threshold))
                     y <= 4'sd0;
                  else
                     y <= -4'sd1;
                  microcode_addr <= 4'd2;
               end

               4'd2: begin                       // select the per-iteration target
                  case (input_index)
                     3'd0:    target <= t1;
                     3'd1:    target <= t2;
                     3'd2:    target <= t3;
                     3'd3:    target <= t4;
                     default: target <= 4'sd0;
                  endcase
                  microcode_addr <= 4'd3;
               end

               4'd3: begin                       // on error, compute and apply the deltas
                  if (y != target) begin
                     wt1_update      <= learning_rate ? (applied_x1 * target) : 4'sd0;
                     wt2_update      <= learning_rate ? (applied_x2 * target) : 4'sd0;
                     bias_update     <= learning_rate ? target               : 4'sd0;
                     percep_wt_1_reg <= percep_wt_1_reg + (learning_rate ? (applied_x1 * target) : 4'sd0);
                     percep_wt_2_reg <= percep_wt_2_reg + (learning_rate ? (applied_x2 * target) : 4'sd0);
                     percep_bias_reg <= percep_bias_reg + (learning_rate ? target               : 4'sd0);
                  end else begin
                     wt1_update  <= 4'sd0;
                     wt2_update  <= 4'sd0;
                     bias_update <= 4'sd0;
                  end
                  microcode_addr <= 4'd4;
               end

               4'd4: begin                       // convergence flag (deltas repeat -> stop)
                  if ((wt1_update  == prev_wt1_update) &&
                      (wt2_update  == prev_wt2_update) &&
                      (bias_update == prev_bias_update)) begin
                     stop <= 1'b1;
                  end else begin
                     stop          <= 1'b0;
                     epoch_counter <= epoch_counter + 8'd1;
                  end
                  microcode_addr <= 4'd5;
               end

               4'd5: begin                       // roll deltas to previous, advance index, idle
                  prev_wt1_update  <= wt1_update;
                  prev_wt2_update  <= wt2_update;
                  prev_bias_update <= bias_update;
                  input_index      <= input_index + 3'd1;
                  microcode_addr   <= 4'd0;
                  waiting          <= 1'b1;
               end

               default: begin
                  microcode_addr <= 4'd0;
                  waiting        <= 1'b1;
               end
            endcase
         end
      end
   end

   assign percep_w1 = percep_wt_1_reg;
   assign percep_w2 = percep_wt_2_reg;
   assign percep_bias = percep_bias_reg;

endmodule

module gate_target(
   input  logic        [1:0] gate_select,
   output logic signed [3:0] o_1,
   output logic signed [3:0] o_2,
   output logic signed [3:0] o_3,
   output logic signed [3:0] o_4
);
   always_comb begin
     case(gate_select)
          2'b00 : begin
                    o_1 =  4'b0001;
                    o_2 = -4'b0001;
                    o_3 = -4'b0001;
                    o_4 = -4'b0001;
                  end
          2'b01 : begin
                    o_1 =  4'b0001;
                    o_2 =  4'b0001;
                    o_3 =  4'b0001;
                    o_4 = -4'b0001;
                  end
          2'b10 : begin
                    o_1 =  4'b0001;
                    o_2 =  4'b0001;
                    o_3 =  4'b0001;
                    o_4 = -4'b0001;
                  end
          2'b11 : begin
                    o_1 =  4'b0001;
                    o_2 = -4'b0001;
                    o_3 = -4'b0001;
                    o_4 = -4'b0001;
                  end
        default : begin
                    o_1 =  4'b0000;
                    o_2 =  4'b0000;
                    o_3 =  4'b0000;
                    o_4 =  4'b0000;
                  end
        endcase
   end

endmodule
