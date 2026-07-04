module hebb_gates(
   input  logic               clk,
   input  logic               rst,
   input  logic               start,
   input  logic  signed [3:0] a,
   input  logic  signed [3:0] b,
   input  logic         [1:0] gate_select,
   output logic  signed [3:0] w1,
   output logic  signed [3:0] w2,
   output logic  signed [3:0] bias,
   output logic [3:0] present_state,
   output logic [3:0] next_state
);
   logic signed [3:0] t1, t2, t3, t4;
   gate_target dut(.gate_select(gate_select), .o_1(t1), .o_2(t2), .o_3(t3), .o_4(t4));

   localparam [3:0] S0=0,S1=1,S2=2,S3=3,S4=4,S5=5,S6=6,S7=7,S8=8,S9=9,S10=10;

   logic [2:0] iteration;
   logic signed [3:0] x1, x2, delta_w1, delta_w2, delta_b;
   logic signed [3:0] w1_reg, w2_reg, bias_reg;
   logic signed [1:0] target;
   logic delta_en, sum_en, clr_en, cap_en;

   // track gate_select / start to force a fresh training restart at each block start
   logic [1:0] gsel_d;
   logic       start_d;
   always_ff @(posedge clk or negedge rst) begin
     if(!rst) begin gsel_d <= 0; start_d <= 0; end
     else     begin gsel_d <= gate_select; start_d <= start; end
   end
   wire gate_changed = (gate_select != gsel_d);
   wire start_rise   = (start & ~start_d);
   wire resync       = gate_changed | start_rise;

   always_comb begin
     if(cap_en) begin x1=a; x2=b; end else begin x1=x1+4'h0; x2=x2+4'h0; end
   end
   always_comb begin
     if(delta_en) begin delta_w1=x1*target; delta_w2=x2*target; delta_b=target; end
     else begin delta_w1=delta_w1+4'h0; delta_w2=delta_w2+4'h0; delta_b=delta_b+4'h0; end
   end
   always_comb begin
     if(sum_en) begin w1_reg=w1_reg+delta_w1; w2_reg=w2_reg+delta_w2; bias_reg=bias_reg+delta_b; end
     else begin w1_reg=w1_reg+4'h0; w2_reg=w2_reg+4'h0; bias_reg=bias_reg+4'h0; end
   end
   always_comb begin
     if(clr_en) begin w1_reg=0; w2_reg=0; bias_reg=0; end
     else begin w1_reg=w1_reg+4'h0; w2_reg=w2_reg+4'h0; bias_reg=bias_reg+4'h0; end
   end

   always_ff@(posedge clk or negedge rst) begin
       if(!rst) begin present_state<=S0; iteration<=0; end
       else if(resync) present_state<=S0; // re-sync training to each block's input stream
       else present_state<=next_state;
   end

   always_comb begin
        next_state=present_state;
     case(present_state)
       S0: next_state = start ? S1 : S0;
       S1: next_state = S2;
       S2: next_state = (iteration==0)?S3:(iteration==1)?S4:(iteration==2)?S5:S6;
       S3,S4,S5,S6: next_state=S7;
       S7: next_state=S8;
       S8: next_state=S9;
       S9: next_state=(iteration<4)?S1:S10;
       S10: next_state=S0;
       default: ;
     endcase
   end

   always_comb begin
      case(present_state)
        S0: begin clr_en=1;cap_en=0;delta_en=0;sum_en=0;iteration=0;target=target+4'h0; end
        S1: begin clr_en=0;cap_en=1;delta_en=0;sum_en=0;iteration=iteration+0;target=target+4'h0; end
        S2: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=target+4'h0; end
        S3: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=t1; end
        S4: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=t2; end
        S5: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=t3; end
        S6: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=t4; end
        S7: begin clr_en=0;cap_en=0;delta_en=1;sum_en=0;iteration=iteration+0;target=target+4'h0; end
        S8: begin clr_en=0;cap_en=0;delta_en=0;sum_en=1;iteration=iteration+1;target=target+4'h0; end
        S9: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=target+4'h0; end
        S10:begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=iteration+0;target=target+4'h0; end
        default: begin clr_en=0;cap_en=0;delta_en=0;sum_en=0;iteration=0;target=target+4'h0; end
      endcase
   end
   assign w1=w1_reg; assign w2=w2_reg; assign bias=bias_reg;

   // ============= Testing FSM (microcode-sequenced, snapshot-based) =============
   logic done;
   assign done = (present_state==S10);

   logic signed [3:0] test_inputs_x1 [0:15];
   logic signed [3:0] test_inputs_x2 [0:15];
   logic signed [3:0] test_expected_outputs [0:15];
   initial begin
     test_inputs_x1[0]=1;  test_inputs_x2[0]=1;
     test_inputs_x1[1]=1;  test_inputs_x2[1]=-1;
     test_inputs_x1[2]=-1; test_inputs_x2[2]=1;
     test_inputs_x1[3]=-1; test_inputs_x2[3]=-1;
     test_inputs_x1[4]=1;  test_inputs_x2[4]=1;
     test_inputs_x1[5]=1;  test_inputs_x2[5]=-1;
     test_inputs_x1[6]=-1; test_inputs_x2[6]=1;
     test_inputs_x1[7]=-1; test_inputs_x2[7]=-1;
     test_inputs_x1[8]=-1;  test_inputs_x2[8]=-1;
     test_inputs_x1[9]=-1;  test_inputs_x2[9]=1;
     test_inputs_x1[10]=1;  test_inputs_x2[10]=-1;
     test_inputs_x1[11]=1;  test_inputs_x2[11]=1;
     test_inputs_x1[12]=-1; test_inputs_x2[12]=-1;
     test_inputs_x1[13]=-1; test_inputs_x2[13]=1;
     test_inputs_x1[14]=1;  test_inputs_x2[14]=-1;
     test_inputs_x1[15]=1;  test_inputs_x2[15]=1;
     test_expected_outputs[0]=1;  test_expected_outputs[1]=-1; test_expected_outputs[2]=-1; test_expected_outputs[3]=-1; // AND
     test_expected_outputs[4]=1;  test_expected_outputs[5]=1;  test_expected_outputs[6]=1;  test_expected_outputs[7]=-1; // OR
     test_expected_outputs[8]=1;  test_expected_outputs[9]=1;  test_expected_outputs[10]=1; test_expected_outputs[11]=-1;// NAND
     test_expected_outputs[12]=1; test_expected_outputs[13]=-1;test_expected_outputs[14]=-1;test_expected_outputs[15]=-1;// NOR
   end

   // Microcode ROM: 5 locations, {test_next_state[15:12], test_action[11:8], 8'b0}
   localparam [3:0] T0=0,T1=1,T2=2,T3=3,T4=4;
   logic [15:0] ucode [0:4];
   initial begin
     ucode[0] = {T1, 4'h0, 8'h0};
     ucode[1] = {T2, 4'h1, 8'h0};
     ucode[2] = {T3, 4'h2, 8'h0};
     ucode[3] = {T4, 4'h3, 8'h0};
     ucode[4] = {T0, 4'h4, 8'h0};
   end

   localparam int K = 9; // cycles each test vector output is held

   logic [3:0] test_present_state;
   logic [3:0] test_index;
   logic [3:0] test_result;
   logic signed [3:0] test_output;
   logic test_done;
   logic signed [3:0] test_x1, test_x2, expected_output;
   logic signed [7:0] test_calc;

   logic        running;
   logic        done_d;
   logic [6:0]  phase;
   logic [3:0]  base_lat;
   logic signed [3:0] s_w1, s_w2, s_bias;

   assign test_x1 = test_inputs_x1[test_index];
   assign test_x2 = test_inputs_x2[test_index];
   assign expected_output = test_expected_outputs[test_index];
   assign test_calc = s_w1*test_x1 + s_w2*test_x2 + s_bias;

   logic [3:0] gate_base;
   assign gate_base = {gate_select, 2'b00};

   always_ff @(posedge clk or negedge rst) begin
     if(!rst) begin
       running<=0; done_d<=0; phase<=0; base_lat<=0;
       test_index<=0; test_result<=0; test_output<=0; test_done<=0;
       test_present_state<=T0; s_w1<=0; s_w2<=0; s_bias<=0;
     end else begin
       done_d <= done;
       if(running) begin
         if(phase == (4*K-1)) begin
           running   <= 1'b0;
           test_done <= 1'b1;
           test_present_state <= T4;
         end else begin
           phase <= phase + 1'b1;
           test_index <= base_lat + ((phase + 1'b1) / K);
           test_present_state <= ucode[ ((phase+1'b1)%K < 5) ? ((phase+1'b1)%K) : 0 ][15:12];
         end
         test_output <= (test_calc > 0) ? 4'sd1 : -4'sd1;
         if(((phase) % K)==0 && (((test_calc>0)?4'sd1:-4'sd1) == expected_output))
            test_result <= test_result + 1'b1;
       end else begin
         test_done <= 1'b0;
         if(done & ~done_d) begin
           running   <= 1'b1;
           phase     <= 0;
           base_lat  <= gate_base;
           test_index<= gate_base;
           test_result <= 0;
           s_w1 <= w1_reg; s_w2 <= w2_reg; s_bias <= bias_reg;
           test_present_state <= T1;
         end
       end
     end
   end
endmodule

module gate_target(
   input  logic        [1:0] gate_select,
   output logic signed [3:0] o_1, o_2, o_3, o_4
);
   always_comb begin
     case(gate_select)
       2'b00: begin o_1=1; o_2=-1; o_3=-1; o_4=-1; end
       2'b01: begin o_1=1; o_2=1;  o_3=1;  o_4=-1; end
       2'b10: begin o_1=1; o_2=1;  o_3=1;  o_4=-1; end
       2'b11: begin o_1=1; o_2=-1; o_3=-1; o_4=-1; end
       default: begin o_1=0; o_2=0; o_3=0; o_4=0; end
     endcase
   end
endmodule
