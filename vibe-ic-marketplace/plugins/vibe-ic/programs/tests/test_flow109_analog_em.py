"""SOFTWARE/neutral native comparator controls; no PDK or ADC qualification.

Geometry/extraction/technology fixtures are TEST_ONLY. Actual OP/current and
ordinary execution provenance come solely from the production D58 entry.
"""
import hashlib
import pytest


















def limits_pdf(path, current_ma, temperature):
    """Actual TEST_ONLY PDF source; same existing parser, no pdftotext mock."""
    lines=['TEST_ONLY comparator, no process qualification','2.15 Maximum Current Densities',
           f'(11 years @{temperature} C)',f'Metal2 IMAXM2 mA {current_ma} A.v w = 0.2 ... 0.3 um',
           '2.16 Layer Thickness']
    stream='BT /F1 10 Tf 40 760 Td '+' 0 -16 Td '.join('('+s+') Tj' for s in lines)+' ET'
    objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
             f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream']
    data=b'%PDF-1.4\n';offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n{obj}\nendobj\n'.encode()
    start=len(data)
    data+=('xref\n0 6\n0000000000 65535 f \n'+''.join(f'{n:010d} 00000 n \n' for n in offsets)+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n').encode()
    path.write_bytes(data)










def test_real_installed_converter_refuses_invalid_pdf_bytes(tmp_path):
    import analog_native_em as em
    import subprocess
    bad=tmp_path/'invalid.pdf';bad.write_bytes(b'TEST_ONLY invalid PDF, not a limit document')
    with pytest.raises(subprocess.CalledProcessError):
        em._limit_document_text(bad,hashlib.sha256(bad.read_bytes()).hexdigest(),tmp_path)


def test_real_conversion_rejects_source_changed_after_tool_read(tmp_path,monkeypatch):
    import analog_native_em as em
    pdf=tmp_path/'source.pdf';limits_pdf(pdf,.6,105)
    digest=hashlib.sha256(pdf.read_bytes()).hexdigest();original=em.subprocess.run
    def convert_then_mutate(*args,**kwargs):
        result=original(*args,**kwargs)
        pdf.write_bytes(pdf.read_bytes()+b'\n% TEST_ONLY late mutation\n')
        return result
    monkeypatch.setattr(em.subprocess,'run',convert_then_mutate)
    with pytest.raises(ValueError,match='limit PDF or extraction executable changed'):
        em._limit_document_text(pdf,digest,tmp_path)
