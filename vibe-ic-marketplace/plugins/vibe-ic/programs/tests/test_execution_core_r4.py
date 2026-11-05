"""Source-bound controls for R4 admission, execution and CLI refusal contracts."""

from programs.tests import test_execution_modes as H














def test_external_duck_context_cannot_call_binding(tmp_path):
    class Foreign:
        binding_called = False
        def binding(self):
            self.binding_called = True
            return H.context(tmp_path).binding()
    ctx = Foreign()
    result = H.controller(H.adapter('a')).run(ctx, tmp_path / 'run')
    assert result['reason'] == 'CONTEXT_IMPLEMENTATION_UNTRUSTED'
    assert not ctx.binding_called
