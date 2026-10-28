"""Testes da regra: o agente responde texto e audio; os demais tipos recebem aviso.

Interacao com a guarda de persistencia (waha_media_guard_test.py):
- audio: aceito pela guarda E com resposta automatica -> transcrito e respondido
- image/video/file/sticker/location: aceitos pela guarda (tem midia), mas SEM
  resposta automatica -> o cliente recebe o aviso. A guarda existe para a mensagem
  ser persistida no historico; o aviso evita silencio.
- text: aceito se tiver conteudo e tem resposta automatica
- unknown: barrado pela guarda, nao chega na conversa
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.worker.process_message_waha import (  # noqa: E402
    MSG_TIPO_NAO_SUPORTADO,
    TIPOS_COM_RESPOSTA,
    tipo_aceita_conteudo_vazio,
    tipo_tem_resposta_automatica,
)


class TestTipoTemRespostaAutomatica:
    def test_texto_tem_resposta(self):
        assert tipo_tem_resposta_automatica("text") is True

    def test_audio_tem_resposta(self):
        # nota de voz (ptt) chega como audio depois do mapa de tipos
        assert tipo_tem_resposta_automatica("audio") is True

    def test_demais_tipos_nao_tem_resposta(self):
        for tipo in ("image", "video", "file", "sticker", "location", "contact", "unknown"):
            assert tipo_tem_resposta_automatica(tipo) is False, tipo

    def test_lista_de_resposta_e_exatamente_texto_e_audio(self):
        assert set(TIPOS_COM_RESPOSTA) == {"text", "audio"}

    def test_tipo_novo_desconhecido_nao_responde(self):
        # qualquer tipo que o WAHA invente no futuro cai no aviso, nao no silencio
        assert tipo_tem_resposta_automatica("algum_tipo_novo") is False


class TestAviso:
    def test_aviso_nao_e_vazio(self):
        assert MSG_TIPO_NAO_SUPORTADO.strip()

    def test_aviso_cita_texto_e_audio(self):
        minusculo = MSG_TIPO_NAO_SUPORTADO.lower()
        assert "texto" in minusculo
        assert "audio" in minusculo or "áudio" in minusculo

    def test_aviso_e_curto_para_caber_numa_bolha(self):
        # mensagem de sistema deve ser curta; 350 chars e folgado para WhatsApp
        assert len(MSG_TIPO_NAO_SUPORTADO) <= 350


class TestInteracaoComAGuarda:
    """Os dois mecanismos nao podem se contradizer."""

    def test_audio_passa_na_guarda_e_tem_resposta(self):
        assert tipo_aceita_conteudo_vazio("audio") is True
        assert tipo_tem_resposta_automatica("audio") is True

    def test_midia_passa_na_guarda_mas_recebe_aviso(self):
        for tipo in ("image", "video", "file", "sticker", "location"):
            assert tipo_aceita_conteudo_vazio(tipo) is True, tipo
            assert tipo_tem_resposta_automatica(tipo) is False, tipo

    def test_unknown_barrado_antes_do_aviso(self):
        assert tipo_aceita_conteudo_vazio("unknown") is False
        assert tipo_tem_resposta_automatica("unknown") is False
