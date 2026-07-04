module lcm_3_ip #(
   parameter WIDTH = 4                    // Input bit-width
   )(
   input                         clk,
   input                         rst,
   input  [WIDTH-1:0]            A,
   input  [WIDTH-1:0]            B,
   input  [WIDTH-1:0]            C,
   input                         go,
   output logic  [3 * WIDTH-1:0] OUT,   // Updated output width
   output logic                  done
);

   logic [2*WIDTH-1:0]      gcd_result;     // GCD result
   logic [3*WIDTH-1:0]      product;        // Intermediate product
   logic                    gcd_done;
   logic                    product_ready;
   logic [2*WIDTH-1:0]      A_int;
   logic [2*WIDTH-1:0]      B_int;
   logic [2*WIDTH-1:0]      C_int;

   always_comb begin
      A_int = A*B;
      B_int = B*C;
      C_int = C*A;
   end

   // Calculate GCD of A, B, and C
   gcd_3_ip #(
      .WIDTH(2*WIDTH)
   ) gcd_inst (
      .clk   (clk),
      .rst   (rst),
      .A     (A_int),
      .B     (B_int),
      .C     (C_int),
      .go    (go),
      .OUT   (gcd_result),
      .done  (gcd_done)
   );

   // Sequential logic for LCM computation
   always_ff @(posedge clk) begin
      if (rst) begin
         OUT <= 0;
         done <= 0;
         product_ready <= 0;
      end else begin
         if (gcd_done) begin
            // Compute |A * B * C|
            product <= A * B * C;
            product_ready <= 1;
         end

         if (product_ready) begin
            // Compute LCM = |A * B * C| / GCD
            // Zero-extend gcd_result to the divisor width (value-preserving) so the
            // DIV operands share the 3*WIDTH width and no implicit expansion is needed.
            OUT <= product / {{WIDTH{1'b0}}, gcd_result};
            done <= 1;
            product_ready <= 0;
         end else begin
            done <= 0;
         end
      end
   end
endmodule

module gcd_3_ip #(
   parameter WIDTH = 4
   )(
   input                     clk,
   input                     rst,
   input  [WIDTH-1:0]        A,
   input  [WIDTH-1:0]        B,
   input  [WIDTH-1:0]        C,
   input                     go,
   output logic  [WIDTH-1:0] OUT,
   output logic              done
);

logic [WIDTH-1:0] gcd_ab;
logic [WIDTH-1:0] gcd_bc;
logic             go_abc;
logic             done_ab;
logic             done_bc;
logic             done_ab_latched;
logic             done_bc_latched;

// GCD is calculated for AB and BC in parallel. The GCD for two numbers is lower than the numbers themselves in most cases.
// And calculating GCD for smaller numbers is comparatively faster using the implemented algorithm.
// Hence in order to reduce GCD computation latency the calculation is broken up in this fashion.

gcd_top
#( .WIDTH(WIDTH)
) gcd_A_B_inst (
   .clk           (clk),
   .rst           (rst),
   .A             (A),
   .B             (B),
   .go            (go),
   .OUT           (gcd_ab),
   .done          (done_ab)
);

gcd_top
#( .WIDTH(WIDTH)
) gcd_B_C_inst (
   .clk           (clk),
   .rst           (rst),
   .A             (B),
   .B             (C),
   .go            (go),
   .OUT           (gcd_bc),
   .done          (done_bc)
);

gcd_top
#( .WIDTH(WIDTH)
) gcd_ABC_inst (
   .clk           (clk),
   .rst           (rst),
   .A             (gcd_ab),
   .B             (gcd_bc),
   .go            (go_abc),
   .OUT           (OUT),
   .done          (done)
);

always_ff @ (posedge clk) begin
   if (rst) begin
      done_ab_latched    <= 0;
      done_bc_latched    <= 0;
   end else begin
      if(done_ab) begin
         done_ab_latched <= done_ab;
      end else if (go_abc) begin
         done_ab_latched <= 0;
      end

      if(done_bc) begin
         done_bc_latched <= done_bc;
      end else if (go_abc) begin
         done_bc_latched <= 0;
      end
   end
end

assign go_abc = done_ab_latched & done_bc_latched;

endmodule

module gcd_top #(
   parameter WIDTH = 4              // Parameter to define the bit-width of the input and output data
   )(
   input                     clk,   // Clock signal
   input                     rst,   // Active High Synchronous reset signal
   input  [WIDTH-1:0]        A,     // Input operand A
   input  [WIDTH-1:0]        B,     // Input operand B
   input                     go,    // Start signal to begin GCD computation
   output logic  [WIDTH-1:0] OUT,   // Output for the GCD result
   output logic              done   // Signal to indicate completion of computation
);

   // Internal signals to communicate between control path and data path
   logic equal;                     // Signal indicating A == B
   logic greater_than;              // Signal indicating A > B
   logic [1:0] controlpath_state;   // Current state of the control FSM

   // Instantiate the control path module
   gcd_controlpath gcd_controlpath_inst (
      .clk               (clk),               // Connect clock signal
      .rst               (rst),               // Connect reset signal
      .go                (go),                // Connect go signal
      .equal             (equal),             // Connect equal signal from datapath
      .greater_than      (greater_than),      // Connect greater_than signal from datapath
      .controlpath_state (controlpath_state), // Output current state to datapath
      .done              (done)               // Output done signal
   );

   // Instantiate the data path module
   gcd_datapath
   #( .WIDTH(WIDTH)
   ) gcd_datapath_inst (
      .clk               (clk),               // Connect clock signal
      .rst               (rst),               // Connect reset signal
      .A                 (A),                 // Connect input A
      .B                 (B),                 // Connect input B
      .controlpath_state (controlpath_state), // Connect current state from control path
      .equal             (equal),             // Output equal signal to control path
      .greater_than      (greater_than),      // Output greater_than signal to control path
      .OUT               (OUT)                // Output GCD result
   );
endmodule


// Datapath module for GCD computation
module gcd_datapath  #(
   parameter WIDTH = 4                           // Bit-width of operands
   )(
   input                     clk,                // Clock signal
   input                     rst,                // Active High Synchronous reset
   input  [WIDTH-1:0]        A,                  // Input operand A
   input  [WIDTH-1:0]        B,                  // Input operand B
   input  [1:0]              controlpath_state,  // Current state from control path
   output logic              equal,              // Signal indicating A_ff == B_ff
   output logic              greater_than,       // Signal indicating A_ff > B_ff
   output logic  [WIDTH-1:0] OUT                 // Output GCD result
);

   // Registers to hold intermediate values of A and B
   logic [WIDTH-1:0] A_ff;
   logic [WIDTH-1:0] B_ff;

   // State encoding for control signals
   localparam S0 = 2'd0;    // State 0: Initialization state
   localparam S1 = 2'd1;    // State 1: Computation complete
   localparam S2 = 2'd2;    // State 2: A_ff > B_ff, subtract B_ff from A_ff
   localparam S3 = 2'd3;    // State 3: B_ff > A_ff, subtract A_ff from B_ff

   // Sequential logic to update registers based on controlpath_state
   always_ff @ (posedge clk) begin
      if (rst) begin
         // On reset, initialize registers to zero
         A_ff <= 'b0;
         B_ff <= 'b0;
         OUT  <= 'b0;
      end else begin
         case (controlpath_state)
            S0: begin
                // In state S0, load input values into registers
                A_ff <= A;
                B_ff <= B;
             end
            S1: begin
                // In state S1, computation is done, output the result
                OUT  <= A_ff;
             end
            S2: begin
                // In state S2, A_ff > B_ff, subtract B_ff from A_ff
                if (greater_than)
                   A_ff <= A_ff - B_ff;
             end
            S3: begin
                // In state S3, B_ff > A_ff, subtract A_ff from B_ff
                if (!equal & !greater_than)
                   B_ff <= B_ff - A_ff;
             end
            default: begin
                A_ff <= 'b0;
                B_ff <= 'b0;
                OUT <= 'b0;
            end
         endcase
      end
   end

   // Generating control response signals for the control path FSM
   always_comb begin
      case(controlpath_state)
         S0: begin
            // In state S0, compare initial input values A and B
            equal        = (A == B)? 1'b1 : 1'b0;
            greater_than = (A >  B)? 1'b1 : 1'b0;
          end
          default: begin
            // In other states, compare the current values in registers A_ff and B_ff
            equal        = (A_ff == B_ff)? 1'b1 : 1'b0;
            greater_than = (A_ff >  B_ff)? 1'b1 : 1'b0;
          end
      endcase
   end
endmodule

// Control path module for GCD computation FSM
module gcd_controlpath (
   input                    clk,               // Clock signal
   input                    rst,               // Active High Synchronous reset
   input                    go,                // Start GCD calculation signal
   input                    equal,             // From Datapath: A_ff equals B_ff
   input                    greater_than,      // From Datapath: A_ff is greater than B_ff
   output logic [1:0]       controlpath_state, // Current state to Datapath
   output logic             done               // Indicates completion of GCD calculation
);

   // Internal state registers
   logic [1:0] curr_state;  // Current state of FSM
   logic [1:0] next_state;  // Next state of FSM

   // State encoding
   localparam S0 = 2'd0;    // State 0: Initialization or waiting for 'go' signal
   localparam S1 = 2'd1;    // State 1: Computation complete
   localparam S2 = 2'd2;    // State 2: A_ff > B_ff
   localparam S3 = 2'd3;    // State 3: B_ff > A_ff

   // State latching logic: Update current state on clock edge
   always_ff @ (posedge clk) begin
      if (rst) begin
         curr_state   <= S0;   // On reset, set state to S0
      end else begin
         curr_state   <= next_state;   // Transition to next state
      end
   end

   // State transition logic: Determine next state based on current state and inputs
   always_comb begin
      case(curr_state)
         S0: begin
             // State S0: Waiting for 'go' signal
             if(!go)
                next_state = S0;         // Remain in S0 until 'go' is asserted
             else if (equal)
                next_state = S1;         // If A == B, computation is complete
             else if (greater_than)
                next_state = S2;         // If A > B, go to state S2
             else
                next_state = S3;         // If B > A, go to state S3
         end
         S1: begin
             // State S1: Computation complete, output the result
             next_state = S0;           // Return to S0 after completion
         end
         S2: begin
             // State S2: A_ff > B_ff, subtract B_ff from A_ff
             if(equal)
                next_state = S1;         // If A_ff == B_ff after subtraction, go to S1
             else if (greater_than)
                next_state = S2;         // If A_ff > B_ff, stay in S2
             else
                next_state = S3;         // If B_ff > A_ff, go to S3
         end
         S3: begin
             // State S3: B_ff > A_ff, subtract A_ff from B_ff
             if (equal)
                next_state = S1;         // If A_ff == B_ff after subtraction, go to S1
             else if (greater_than)
                next_state = S2;         // If A_ff > B_ff, go to S2
             else
                next_state = S3;         // If B_ff > A_ff, stay in S3
         end
         default: begin
             next_state = S0;
         end
      endcase
   end

   // Output logic: Generate 'done' signal when computation is complete
   always_ff @ (posedge clk) begin
     if(rst) begin
        done <= 1'b0;             // On reset, 'done' is low
     end else begin
        done <= (curr_state == S1); // 'done' is asserted when in state S1
     end
   end

   // Assign current state to output for datapath
   assign controlpath_state = curr_state;

endmodule
