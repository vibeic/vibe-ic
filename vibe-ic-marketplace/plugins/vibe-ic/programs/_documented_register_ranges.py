"""Finite table-declared sequential register ranges; no storage inference."""
import re

def append_documented_ranges(registers, extracted):
    """Carry name/address/access/width bindings; leave existing arrays intact.

    Only a one-to-one contiguous address/name span establishes spacing.
    Other strides, symbolic endpoints or missing widths remain unresolved.
    """
    aliases = {'address': {'address','addr','offset','位址(hex)','地址'},
               'name': {'name','register','名稱','名称'},
               'access': {'r/w','rw','access'},
               'width': {'width','width(bits)','寬度','宽度'}}
    candidates = []
    for source, text in extracted.items():
        columns = None
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip().startswith('|'):
                columns = None
                continue
            cells = [x.strip().replace('`','').replace('**','') for x in line.strip().strip('|').split('|')]
            keys = [x.lower().replace(' ', '') for x in cells]
            header = {key: next((n for n,x in enumerate(keys) if x in names), None) for key,names in aliases.items()}
            if all(x is not None for x in header.values()):
                columns = header
                continue
            if columns is None or len(cells) <= max(columns.values()):
                continue
            address = re.fullmatch(r'(0x[0-9a-fA-F]+)\s*[-~–]\s*(0x[0-9a-fA-F]+)', cells[columns['address']])
            names = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*?)(\d+)\s*(?:~|–|\.\.|-)\s*([A-Za-z_][A-Za-z0-9_]*?)(\d+)', cells[columns['name']])
            width = re.fullmatch(r'(\d+)\s*(?:each)?',cells[columns['width']],re.I)
            access = cells[columns['access']].upper()
            if not address or not names or not width or access not in {'R','W','RO','WO','RW','R/W'}:
                continue
            lo,hi = (int(x,16) for x in address.groups())
            stem,first,other,last=names.groups();first,last=int(first),int(last)
            if stem!=other or not (0 < last-first < 256) or hi-lo != last-first or int(width[1])<=0:
                continue
            for index in range(first,last+1):
                candidates.append({'name':f'{stem}{index}','address':hex(lo+index-first),'address_int':lo+index-first,'access':access,'width_bits':int(width[1]),'description':cells[-1],'evidence':f'input/docs/{source}','evidence_line':number,'extraction_strategy':'documented_contiguous_register_range'})
    # Conflicting declarations never select a winner. Existing typed records,
    # including packed arrays, stay authoritative and are never flattened.
    for row in candidates:
        peers=[x for x in candidates if x['evidence']==row['evidence'] and (x['name']==row['name'] or x['address_int']==row['address_int'])]
        signature=lambda x:(x['name'],x['address_int'],x['access'],x['width_bits'])
        if any(signature(x)!=signature(row) for x in peers):
            continue
        if any(x.get('evidence')==row['evidence'] and (x.get('name')==row['name'] or x.get('address_int')==row['address_int'] or x.get('array')) for x in registers):
            continue
        registers.append(row)
