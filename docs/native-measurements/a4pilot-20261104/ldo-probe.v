module ldo_probe(input vref, output vout);
  ldo u(.vref(vref), .vout(vout));
endmodule
