`timescale 1ns/1ps
module dependency_probe;
  reg enable = 0, done_a = 0, done_b = 0;
  wire [3:0] actual, control;
  function automatic [3:0] phase_select(input bit enabled);
    phase_select = !enabled ? 15 : !done_a ? 2 : !done_b ? 3 : 15;
  endfunction
  function automatic [3:0] explicit_inputs(input bit enabled,
                                          input bit a,input bit b);
    explicit_inputs = !enabled ? 15 : !a ? 2 : !b ? 3 : 15;
  endfunction
  assign actual = phase_select(enable);
  assign control = explicit_inputs(enable,done_a,done_b);
  initial begin
    #2; enable=1;
    #2; $display("PENDING actual=%0d control=%0d",actual,control);
    if(actual!=2 || control!=2)$fatal(1,"initial selection");
    done_a=1;
    #2; $display("FIRST_COMPLETE actual=%0d control=%0d",actual,control);
    if(control!=3)$fatal(1,"explicit dependency control failed");
    if(actual!=3)$fatal(1,"hidden dependency did not re-evaluate");
    done_b=1;
    #2; $display("ALL_COMPLETE actual=%0d control=%0d",actual,control);
    if(actual!=15 || control!=15)$fatal(1,"completed selection");
    $finish;
  end
endmodule
