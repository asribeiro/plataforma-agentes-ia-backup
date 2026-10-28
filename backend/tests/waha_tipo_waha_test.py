"""Testes da resolucao do tipo de mensagem do WAHA.

Bug de producao (28/10 15:09, mensagem de voz de 5500000000000): o WAHA envia
`type` na raiz como string VAZIA e o tipo real em `_data.type` ("ptt"). O codigo
fazia `payload.get("type", media_type)`, que ignora o fallback quando a chave
existe, e depois forcava "chat" — fazendo nota de voz virar mensagem de texto
vazia e ser descartada.

Estes testes travam o comportamento correto.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.worker.process_message_waha import resolver_tipo_waha  # noqa: E402


class TestPayloadRealDeVoz:
    """O caso exato que falhou em producao."""

    PAYLOAD_VOZ = {
        "id": "false_140501365833969@lid_AC4A6A5B6BABD2E281EECD1386326B5C",
        "type": "",  # chave existe, valor vazio: a armadilha
        "_data": {"type": "ptt", "_data": {"mediaType": ""}},
        "media": {"mimetype": "audio/ogg; codecs=opus", "url": "http://waha:3000/api/files/x.ogg"},
        "hasMedia": True,
        "body": "",
    }

    def test_nota_de_voz_resolve_para_ptt(self):
        # "ptt" e o que o mapa traduz para "audio"
        assert resolver_tipo_waha(self.PAYLOAD_VOZ) == "ptt"

    def test_nao_vira_chat(self):
        # era exatamente isso que acontecia antes da correcao
        assert resolver_tipo_waha(self.PAYLOAD_VOZ) != "chat"

    def test_nao_vira_string_vazia(self):
        assert resolver_tipo_waha(self.PAYLOAD_VOZ) != ""


class TestOrdenacaoDeConfianca:
    def test_type_da_raiz_tem_prioridade(self):
        p = {"type": "image", "_data": {"type": "ptt"}}
        assert resolver_tipo_waha(p) == "image"

    def test_usa_data_type_quando_type_esta_vazio(self):
        p = {"type": "", "_data": {"type": "video"}}
        assert resolver_tipo_waha(p) == "video"

    def test_usa_media_type_quando_nada_mais_existe(self):
        assert resolver_tipo_waha({}, "document") == "document"

    def test_texto_normal(self):
        assert resolver_tipo_waha({"type": "chat", "_data": {"type": "chat"}}) == "chat"

    def test_payload_vazio_retorna_vazio(self):
        assert resolver_tipo_waha({}) == ""

    def test_espacos_sao_ignorados(self):
        assert resolver_tipo_waha({"type": "   "}, "image") == "image"

    def test_case_e_normalizado(self):
        assert resolver_tipo_waha({"type": "PTT"}) == "ptt"

    def test_data_nao_e_dicionario_nao_quebra(self):
        assert resolver_tipo_waha({"type": "", "_data": "string"}) == ""

    def test_none_nao_quebra(self):
        assert resolver_tipo_waha({"type": None, "_data": None}, "") == ""
