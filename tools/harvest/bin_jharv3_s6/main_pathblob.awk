NF{
  split($0,a,"\t"); split(a[1],f," ");
  z="0000000000000000000000000000000000000000";
  if(length(f[3])==40 && f[3]!=z) print a[2]"\t"f[3];
  if(length(f[4])==40 && f[4]!=z) print a[2]"\t"f[4];
}
