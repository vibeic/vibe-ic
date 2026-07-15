import hashlib, textwrap

def pad_blocks(msg: bytes):
    ml = len(msg)*8
    data = msg + b'\x80'
    while (len(data) % 64) != 56:
        data += b'\x00'
    data += ml.to_bytes(8,'big')
    blocks=[]
    for i in range(0,len(data),64):
        chunk=data[i:i+64]
        words=[int.from_bytes(chunk[j:j+4],'big') for j in range(0,64,4)]
        blocks.append(words)
    return blocks

def digest_words(msg, mode256=True):
    h = hashlib.sha256(msg).digest() if mode256 else hashlib.sha224(msg).digest()
    # sha224 -> 7 words; pad to 8 for uniform read (last undefined)
    words=[int.from_bytes(h[i:i+4],'big') for i in range(0,len(h),4)]
    while len(words)<8: words.append(0)
    return words

vectors = [
    ("abc_256",  b"abc", True),
    ("twoblk_256", b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", True),
    ("abc_224",  b"abc", False),
    ("empty_256", b"", True),
]

lines=[]
lines.append("`timescale 1ns/1ps")
lines.append("module tb_selfverify;")
lines.append("  reg clk=0; reg reset_n=0; reg cs=0; reg we=0;")
lines.append("  reg [7:0] address=0; reg [31:0] write_data=0;")
lines.append("  wire [31:0] read_data; wire error;")
lines.append("  integer errors=0;")
lines.append("  sha256 dut(.clk(clk),.reset_n(reset_n),.cs(cs),.we(we),")
lines.append("      .address(address),.write_data(write_data),.read_data(read_data),.error(error));")
lines.append("  always #5 clk=~clk;")
lines.append("  task wr; input [7:0] a; input [31:0] d; begin")
lines.append("    @(posedge clk); cs<=1; we<=1; address<=a; write_data<=d;")
lines.append("    @(posedge clk); cs<=0; we<=0; end endtask")
lines.append("  task rd_chk; input [7:0] a; input [31:0] exp; input [127:0] nm; begin")
lines.append("    @(posedge clk); cs<=1; we<=0; address<=a;")
lines.append("    @(posedge clk); cs<=0; @(posedge clk);")
lines.append("    if (read_data!==exp) begin errors=errors+1;")
lines.append("      $display(\"MISMATCH %0s addr=%02x got=%08x exp=%08x\",nm,a,read_data,exp); end")
lines.append("    else $display(\"OK       %0s addr=%02x val=%08x\",nm,a,read_data); end endtask")
lines.append("  task wait_ready; integer k; begin k=0;")
lines.append("    @(posedge clk); cs<=1; we<=0; address<=8'h09;")
lines.append("    forever begin @(posedge clk);")
lines.append("      if (read_data[0]==1'b1 && k>2) begin cs<=0; disable wait_ready; end")
lines.append("      k=k+1; if (k>200) begin $display(\"TIMEOUT waiting ready\"); errors=errors+1; cs<=0; disable wait_ready; end")
lines.append("    end end endtask")
lines.append("  integer i;")
lines.append("  initial begin")
lines.append("    reset_n=0; repeat(4) @(posedge clk); reset_n=1; @(posedge clk);")

def emit_hash(prefix, blocks, mode256, dwords):
    out=[]
    for bidx,blk in enumerate(blocks):
        for wi,wv in enumerate(blk):
            out.append(f"    wr(8'h{0x10+wi:02x}, 32'h{wv:08x});")
        ctrl = (1<<2 if mode256 else 0)
        if bidx==0:
            ctrl |= 1  # INIT
        else:
            ctrl |= 2  # NEXT
            if mode256: ctrl |= 4
        out.append(f"    wr(8'h08, 32'h{ctrl:08x});")
        out.append("    wait_ready;")
    # read digest
    nreg = 8 if mode256 else 7
    for di in range(nreg):
        out.append(f'    rd_chk(8\'h{0x20+di:02x}, 32\'h{dwords[di]:08x}, "{prefix[:12]}");')
    return out

for name,msg,mode256 in vectors:
    blocks=pad_blocks(msg)
    dwords=digest_words(msg,mode256)
    lines.append(f"    // ---- {name} : {len(blocks)} block(s) ----")
    lines += emit_hash(name, blocks, mode256, dwords)

lines.append("    if (errors==0) $display(\"SELFVERIFY_PASS all vectors match\");")
lines.append("    else $display(\"SELFVERIFY_FAIL errors=%0d\",errors);")
lines.append("    $finish; end")
lines.append("  initial begin #500000 $display(\"GLOBAL TIMEOUT\"); $finish; end")
lines.append("endmodule")
open("tb_selfverify.v","w").write("\n".join(lines)+"\n")
print("wrote tb_selfverify.v; vectors:", [(n,len(pad_blocks(m))) for n,m,_ in vectors])
print("SHA256(abc)=", hashlib.sha256(b'abc').hexdigest())
print("SHA256(2blk)=", hashlib.sha256(b'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq').hexdigest())
print("SHA224(abc)=", hashlib.sha224(b'abc').hexdigest())
