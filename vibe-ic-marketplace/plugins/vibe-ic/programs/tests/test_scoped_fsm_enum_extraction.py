import _rtl_fsm_extract as extractor


def machine(name, members, target):
    return f'''module {name};
typedef enum logic [1:0] {{{','.join(members)}}} state_e;
state_e control_fsm_cs, control_fsm_ns;
always_comb begin
 case(control_fsm_cs)
 {members[0]}: control_fsm_ns = {target};
 endcase
end
endmodule
'''


def test_generate_scopes_preserve_each_same_named_state_type():
    first=machine('first',['A','B'],'B').splitlines()[1:-1]
    second=machine('second',['C','D'],'D').splitlines()[1:-1]
    text='module top;\nif (P) begin : left\n'+'\n'.join(first)+'\nend else begin : right\n'+'\n'.join(second)+'\nend\nendmodule\n'
    rows=extractor.declared_state_machines({'top.sv':text})
    assert [[s['name'] for s in row['states']] for row in rows]==[['A','B'],['C','D']]
    assert [[(e['from'],e['to']) for e in row['transitions']] for row in rows]==[[('A','B')],[('C','D')]]


def test_module_local_state_types_cannot_import_foreign_edges():
    rows=extractor.declared_state_machines({'a.sv':machine('a',['IDLE','RUN','DONE'],'RUN'),
                                           'b.sv':machine('b',['IDLE','RUN','DONE'],'DONE')})
    assert len(rows)==2
    assert [(r['source_file'],[(e['from'],e['to']) for e in r['transitions']]) for r in rows]==[
        ('a.sv',[('IDLE','RUN')]),('b.sv',[('IDLE','DONE')])]
