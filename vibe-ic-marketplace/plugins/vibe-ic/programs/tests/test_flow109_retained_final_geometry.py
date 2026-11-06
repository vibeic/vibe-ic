"""Existing Default native checkpoints retain their original authority/readset."""
import librelane_fill_dfm as F












def test_retained_image_verification_does_not_write_provenance(tmp_path, monkeypatch):
    calls = []
    def resolve(project, *, record=True):
        calls.append(record)
        return 'pinned'
    monkeypatch.setattr(F, 'resolve_image', resolve)
    assert F._record_provider_binding(tmp_path, {'image': 'pinned'}) == 'pinned'
    assert calls == [False]
