"""Testes da guarda que decide se uma mensagem sem texto pode ser persistida.

Contexto do bug: notas de voz do WhatsApp chegam como `ptt` com corpo vazio, e o
mapa de tipos traduz para `audio`. A guarda antiga exigia `content` nao vazio para
todo tipo diferente de `contact`, entao audio era descartado como
"Tipo desconhecido ou contudo vazio" antes de qualquer transcricao.

Estes testes cobrem a regra extraida `tipo_aceita_conteudo_vazio` e a composicao
da guarda, sem subir banco, Celery ou WAHA.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.worker.process_message_waha import (  # noqa: E402
    TIPOS_COM_CONTEUDO_OPCIONAL,
    tipo_aceita_conteudo_vazio,
)


def _descarta(msg_type: str, content) -> bool:
    """Reproduz a guarda de process_message_waha (mesma expressao do codigo)."""
    return msg_type == "unknown" or (
        not content and not tipo_aceita_conteudo_vazio(msg_type)
    )


class TestTipoAceitaConteudoVazio:
    def test_audio_e_aceito_sem_texto(self):
        # nota de voz (ptt) chega como internal_type=audio, content vazio se a
        # materializacao falhar: ainda assim deve ser aceita
        assert tipo_aceita_conteudo_vazio("audio") is True

    def test_tipos_de_midia_sao_aceitos(self):
        for tipo in ("image", "video", "file", "sticker", "location"):
            assert tipo_aceita_conteudo_vazio(tipo) is True, tipo

    def test_contato_continua_aceito(self):
        assert tipo_aceita_conteudo_vazio("contact") is True

    def test_texto_nao_esta_na_lista(self):
        # texto sem conteudo continua sendo lixo e deve ser descartado
        assert tipo_aceita_conteudo_vazio("text") is False

    def test_desconhecido_nao_esta_na_lista(self):
        assert tipo_aceita_conteudo_vazio("unknown") is False

    def test_document_nao_e_o_nome_interno(self):
        # o mapa traduz "document" -> "file"; "document" cru nao deve entrar
        assert tipo_aceita_conteudo_vazio("document") is False

    def test_lista_nao_tem_duplicatas(self):
        assert len(TIPOS_COM_CONTEUDO_OPCIONAL) == len(set(TIPOS_COM_CONTEUDO_OPCIONAL))


class TestGuarda:
    """Regressao do bug: audio nao pode ser descartado por content vazio."""

    def test_audio_com_content_vazio_nao_e_descartado(self):
        assert _descarta("audio", "") is False

    def test_audio_com_url_nao_e_descartado(self):
        assert _descarta("audio", "http://waha:3000/api/files/x.ogg") is False

    def test_imagem_sem_url_nao_e_descartada(self):
        assert _descarta("image", "") is False

    def test_documento_sem_url_nao_e_descartado(self):
        assert _descarta("file", "") is False

    def test_texto_vazio_continua_descartado(self):
        assert _descarta("text", "") is True

    def test_tipo_desconhecido_continua_descartado(self):
        assert _descarta("unknown", "qualquer coisa") is True

    def test_texto_com_conteudo_passa(self):
        assert _descarta("text", "bom dia, quero agendar") is False

    def test_contato_sem_texto_passa(self):
        assert _descarta("contact", "") is False
