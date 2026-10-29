"""A reescrita legada nao pode engolir caminho vivo (defeito do 404 do F1-12).

Historico curto: as rotas novas /api/clinic/users e /api/clinic/access-log
subiram, apareciam em app.routes, casavam no roteador — e respondiam 404. O
middleware de compatibilidade trocava /api/clinic por /api/company antes do
roteador. Estes testes travam o comportamento certo: legado reescreve, vivo nao.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.utils.legado_clinic import (
    reescrever_caminho_legado,
    reescrever_query_legada,
)


# ------------------------------------------------------- funcao pura

def test_caminho_vivo_nao_e_reescrito():
    """O caso do defeito: /api/clinic/users existe, entao nao e legado."""
    novo = reescrever_caminho_legado("/api/clinic/users", lambda p: True)
    assert novo == "/api/clinic/users"


def test_caminho_inexistente_e_tratado_como_legado():
    novo = reescrever_caminho_legado("/api/clinic/qualquer-coisa", lambda p: False)
    assert novo == "/api/company/qualquer-coisa"


def test_sem_funcao_de_checagem_o_comportamento_antigo_continua():
    """Compatibilidade preservada para quem chamar sem o predicado."""
    assert reescrever_caminho_legado("/api/clinic/x") == "/api/company/x"


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("/client-clinics", "/client-companies"),
        ("/clinics-admin", "/companies-admin"),
        ("/complete-clinic", "/complete-company"),
        ("/clinics/7", "/companies/7"),
        ("/clinic/7/agenda", "/company/7/agenda"),
        ("/api/clinic", "/api/company"),
        ("/api/clinic/", "/api/company/"),
    ],
)
def test_substituicoes_legadas_conhecidas(entrada, esperado):
    assert reescrever_caminho_legado(entrada, lambda p: False) == esperado


def test_caminho_sem_clinic_nao_e_tocado():
    for caminho in ("/api/services", "/api/company/flag", "/procedimentos"):
        assert reescrever_caminho_legado(caminho, lambda p: False) == caminho


def test_query_legada_vira_company_id():
    assert reescrever_query_legada(b"clinic_id=3&x=1") == b"company_id=3&x=1"
    assert reescrever_query_legada(b"company_id=3") == b"company_id=3"
    assert reescrever_query_legada(b"") == b""


# ------------------------------------------------ integracao com a app inteira

@pytest.fixture()
def app_com_rota_viva():
    app = FastAPI()

    @app.get("/api/clinic/ping")
    def ping():
        return {"ok": True}

    @app.get("/api/company/ping")
    def ping_company():
        return {"onde": "company"}

    from starlette.routing import Match

    @app.middleware("http")
    async def legado(request, call_next):
        caminho = request.scope.get("path", "")

        def registrado(p: str) -> bool:
            alvo = dict(request.scope)
            alvo["path"] = p
            for rota in request.app.router.routes:
                casou, _ = rota.matches(alvo)
                if casou == Match.FULL:
                    return True
            return False

        novo = reescrever_caminho_legado(caminho, registrado)
        if novo != caminho:
            request.scope["path"] = novo
        return await call_next(request)

    return app


def test_rota_nova_responde_quando_o_middleware_esta_ligado(app_com_rota_viva):
    resposta = TestClient(app_com_rota_viva).get("/api/clinic/ping")
    assert resposta.status_code == 200
    assert resposta.json() == {"ok": True}


def test_url_legada_continua_caindo_na_rota_nova(app_com_rota_viva):
    """/api/company/ping existe: chamar por ele nao deve virar outra coisa."""
    resposta = TestClient(app_com_rota_viva).get("/api/company/ping")
    assert resposta.status_code == 200
    assert resposta.json() == {"onde": "company"}
