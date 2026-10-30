"""F1-02 (convite), F1-03 (freebusy) e F1-06 (credencial por agenda).

Tudo com cliente Google FALSO: nenhuma chamada real, nenhuma credencial, nenhum
evento criado na conta de ninguem. O que se prova aqui e o que o codigo MONTA e o
que ele faz com a resposta — que e exatamente onde estavam os tres defeitos:
evento sem convidado, ocupacao invisivel e credencial unica por empresa.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import (
    Agenda,
    Agendamento,
    Base,
    CalendarIntegration,
    Company,
    Professional,
)
from backend.routes.integrations.google_calendar_service import (
    create_google_event,
    get_busy_intervals,
    update_google_event,
)
from backend.services.google_convite import (
    descrever_convite,
    montar_attendees,
    normalizar_email,
    politica_de_aviso,
)
from backend.services.google_credencial import (
    FONTE_AGENDA,
    FONTE_EMPRESA,
    calendar_id_da_agenda,
    credencial_google_da_agenda,
)


# ------------------------------------------------------- cliente Google falso
class _Requisicao:
    def __init__(self, resultado):
        self._resultado = resultado

    def execute(self):
        if isinstance(self._resultado, Exception):
            raise self._resultado
        return self._resultado


class _Events:
    def __init__(self, registro):
        self.registro = registro

    def insert(self, **kwargs):
        self.registro.append(("insert", kwargs))
        return _Requisicao({"id": "evt-novo-1"})

    def patch(self, **kwargs):
        self.registro.append(("patch", kwargs))
        return _Requisicao({"id": kwargs.get("eventId")})


class _Freebusy:
    def __init__(self, registro, resposta):
        self.registro = registro
        self.resposta = resposta

    def query(self, **kwargs):
        self.registro.append(("freebusy", kwargs))
        return _Requisicao(self.resposta)


class ServicoGoogleFalso:
    def __init__(self, resposta_freebusy=None):
        self.registro = []
        self.resposta_freebusy = resposta_freebusy

    def events(self):
        return _Events(self.registro)

    def freebusy(self):
        return _Freebusy(self.registro, self.resposta_freebusy)


# ------------------------------------------------------------------ F1-02 puro
def test_email_invalido_vira_none_em_vez_de_convidado_quebrado():
    assert normalizar_email("  Ana@Clinica.COM ") == "ana@clinica.com"
    assert normalizar_email("ana.sem.arroba") is None
    assert normalizar_email("") is None
    assert normalizar_email(None) is None


def test_attendees_deduplica_e_mantem_ordem():
    lista = montar_attendees("ana@x.com", "ANA@x.com", None, "bruno@y.com", "invalido")
    assert lista == ["ana@x.com", "bruno@y.com"]


def test_paciente_sem_email_nao_impede_convite_do_profissional():
    """Decisao de 28/10: sem e-mail do paciente, o profissional ainda e convidado."""
    assert montar_attendees(None, "dra.ana@clinica.com") == ["dra.ana@clinica.com"]


def test_aviso_e_all_com_convidado_e_none_sem():
    assert politica_de_aviso(["ana@x.com"]) == "all"
    assert politica_de_aviso([]) == "none"
    assert politica_de_aviso(None) == "none"


def test_descricao_do_convite_diz_a_verdade_nos_dois_casos():
    assert "ana@x.com" in descrever_convite(["ana@x.com"])
    sem_email = descrever_convite([], "dra.ana@clinica.com")
    assert "WhatsApp" in sem_email and "não recebeu convite" in sem_email


# ----------------------------------------------------- F1-02 no payload Google
def test_create_envia_attendees_e_sendUpdates_all():
    fake = ServicoGoogleFalso()
    evento = create_google_event(
        calendar_id="cal-1",
        summary="Consulta",
        description="desc",
        start_naive_iso="2026-11-02T09:00:00",
        end_naive_iso="2026-11-02T09:30:00",
        timezone="America/Sao_Paulo",
        service=fake,
        return_event=True,
        attendees=["Paciente@Exemplo.com", "dra.ana@clinica.com"],
    )
    assert evento["id"] == "evt-novo-1"
    acao, kwargs = fake.registro[0]
    assert acao == "insert"
    emails = [a["email"] for a in kwargs["body"]["attendees"]]
    assert emails == ["paciente@exemplo.com", "dra.ana@clinica.com"]
    assert kwargs["sendUpdates"] == "all", "sem sendUpdates o Google nao avisa ninguem"


def test_create_sem_attendees_nao_manda_lista_e_nao_avisa():
    fake = ServicoGoogleFalso()
    create_google_event(
        calendar_id="cal-1", summary="s", description="d",
        start_naive_iso="2026-11-02T09:00:00", end_naive_iso="2026-11-02T09:30:00",
        timezone="America/Sao_Paulo", service=fake,
    )
    _, kwargs = fake.registro[0]
    assert "attendees" not in kwargs["body"]
    assert kwargs["sendUpdates"] == "none"


def test_update_tambem_avisa_quem_ja_estava_convidado():
    fake = ServicoGoogleFalso()
    update_google_event(
        calendar_id="cal-1", event_id="evt-9", summary="s", description="d",
        start_naive_iso="2026-11-02T10:00:00", end_naive_iso="2026-11-02T10:30:00",
        timezone="America/Sao_Paulo", service=fake, attendees=["ana@x.com"],
    )
    acao, kwargs = fake.registro[0]
    assert acao == "patch"
    assert kwargs["sendUpdates"] == "all"
    assert kwargs["body"]["attendees"] == [{"email": "ana@x.com"}]


def test_send_updates_explicito_manda_no_payload():
    fake = ServicoGoogleFalso()
    create_google_event(
        calendar_id="cal-1", summary="s", description="d",
        start_naive_iso="2026-11-02T09:00:00", end_naive_iso="2026-11-02T09:30:00",
        timezone="America/Sao_Paulo", service=fake,
        attendees=["ana@x.com"], send_updates="externalOnly",
    )
    _, kwargs = fake.registro[0]
    assert kwargs["sendUpdates"] == "externalOnly"


# ------------------------------------------------------------------- F1-03
def test_freebusy_devolve_intervalos_ocupados_da_agenda():
    resposta = {
        "calendars": {
            "cal-1": {
                "busy": [
                    {"start": "2026-11-02T12:00:00Z", "end": "2026-11-02T13:00:00Z"},
                    {"start": "2026-11-02T18:00:00Z", "end": "2026-11-02T18:30:00Z"},
                ]
            }
        }
    }
    fake = ServicoGoogleFalso(resposta_freebusy=resposta)
    intervalos = get_busy_intervals(
        "cal-1", "2026-11-02T00:00:00-03:00", "2026-11-02T23:59:59-03:00",
        service=fake, time_zone="America/Sao_Paulo",
    )
    assert intervalos == [
        {"start": "2026-11-02T12:00:00Z", "end": "2026-11-02T13:00:00Z"},
        {"start": "2026-11-02T18:00:00Z", "end": "2026-11-02T18:30:00Z"},
    ]
    acao, kwargs = fake.registro[0]
    assert acao == "freebusy"
    assert kwargs["body"]["items"] == [{"id": "cal-1"}]
    assert kwargs["body"]["timeZone"] == "America/Sao_Paulo"


def test_freebusy_sem_evento_devolve_lista_vazia_nao_none():
    """[] = verifiquei e esta livre. None = nao consegui verificar."""
    fake = ServicoGoogleFalso(resposta_freebusy={"calendars": {"cal-1": {"busy": []}}})
    assert get_busy_intervals("cal-1", "a", "b", service=fake) == []


def test_freebusy_com_falha_devolve_none_e_nao_lista_vazia():
    class ServicoQueExplode(ServicoGoogleFalso):
        def freebusy(self):
            return _Freebusy(self.registro, RuntimeError("rede caiu"))

    assert get_busy_intervals("cal-1", "a", "b", service=ServicoQueExplode()) is None


def test_freebusy_sem_servico_devolve_none():
    assert get_busy_intervals("cal-1", "a", "b", service=None) is None


# ------------------------------------------------------------------- F1-06
@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        eng,
        tables=[
            Company.__table__,
            Professional.__table__,
            Agenda.__table__,
            CalendarIntegration.__table__,
        ],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    empresa = Company(name="Clinica A", cnpj="00000000000800")
    db.add(empresa)
    db.commit()

    agenda = Agenda(company_id=empresa.id, name="Dra. Ana", slot_duration=30)
    db.add(agenda)
    db.commit()

    integracao = CalendarIntegration(
        company_id=empresa.id,
        provider="google",
        google_calendar_id="cal-empresa",
        google_oauth_token={"refresh_token": "r-empresa"},
    )
    db.add(integracao)
    db.commit()
    return {"empresa": empresa, "agenda": agenda, "integracao": integracao}


def test_credencial_da_agenda_ganha_da_empresa(db, cenario):
    cenario["agenda"].google_oauth_token = {"refresh_token": "r-agenda"}
    db.commit()

    dono, fonte = credencial_google_da_agenda(db, cenario["empresa"].id, cenario["agenda"])
    assert fonte == FONTE_AGENDA
    assert dono.google_oauth_token["refresh_token"] == "r-agenda"


def test_sem_credencial_na_agenda_cai_para_a_empresa(db, cenario):
    dono, fonte = credencial_google_da_agenda(db, cenario["empresa"].id, cenario["agenda"])
    assert fonte == FONTE_EMPRESA
    assert dono.google_calendar_id == "cal-empresa"


def test_sem_credencial_nenhuma_devolve_none_e_nao_explode(db):
    empresa = Company(name="Sem Google", cnpj="00000000000801")
    db.add(empresa)
    db.commit()
    dono, fonte = credencial_google_da_agenda(db, empresa.id, None)
    assert dono is None and fonte is None


def test_calendar_id_prefere_o_da_agenda(db, cenario):
    cenario["agenda"].google_calendar_id = "cal-da-dra-ana"
    db.commit()
    assert calendar_id_da_agenda(db, cenario["empresa"].id, cenario["agenda"]) == "cal-da-dra-ana"


def test_calendar_id_cai_para_o_da_empresa(db, cenario):
    cenario["agenda"].google_calendar_id = None
    db.commit()
    assert calendar_id_da_agenda(db, cenario["empresa"].id, cenario["agenda"]) == "cal-empresa"
