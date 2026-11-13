from io import BytesIO

import pytest

from research_y import install_local_assistant as setup


def test_incomplete_first_use_download_never_activates_package(tmp_path,monkeypatch):
    class ShortResponse(BytesIO):
        def geturl(self):
            return "https://example.test/release"
    monkeypatch.setattr(setup,"urlopen",lambda *a,**k:ShortResponse(b"incomplete"))
    def forbidden(*args,**kwargs):
        raise AssertionError("Incomplete package must not activate")
    monkeypatch.setattr(setup,"install_local_package",forbidden)
    with pytest.raises(ValueError,match="Incomplete model download"):
        setup.download_local_package(tmp_path)
    assert list(tmp_path.iterdir())==[]
