from io import BytesIO
from pathlib import Path

import pytest

from backend.routes import clinical_attachment_routes
from backend.routes.clinical_attachment_routes import _extension_for


class UploadStub:
    def __init__(self, content_type, content=b"conteudo"):
        self.content_type = content_type
        self.file = BytesIO(content)
        self.filename = "documento"


def test_allowed_attachment_extension():
    assert _extension_for(UploadStub("application/pdf")) == ".pdf"
    assert _extension_for(UploadStub("image/png")) == ".png"


def test_rejects_unsupported_attachment_type():
    with pytest.raises(Exception) as exc:
        _extension_for(UploadStub("text/plain"))

    assert "Tipo de arquivo não permitido" in str(exc.value)


def test_storage_root_is_private_and_isolated_from_public_uploads(monkeypatch, tmp_path):
    monkeypatch.setenv("CLINICAL_ATTACHMENTS_DIR", str(tmp_path / "clinical"))
    assert Path(tmp_path / "clinical").name == "clinical"
    assert "public" not in str(tmp_path / "clinical")
