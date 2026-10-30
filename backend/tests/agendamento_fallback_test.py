"""Prova que o fallback da consulta de horarios nao estoura mais.

Regressao real (medida em producao): quando o horario pedido nao existia, a tool chamava
`servico_slots.get_available_slots_filtered` num `DatabaseSchedulingService`, que nao tem
esse metodo → AttributeError → "Erro ao consultar horarios disponiveis" → o agente dizia ao
paciente que nao conseguia consultar a agenda.
"""
from unittest.mock import MagicMock

import pytest

from backend.agents_sdk.services.database_scheduling_service import DatabaseSchedulingService
from backend.agents_sdk.tools.scheduling_tools import _slots_filtrados


class ServicoComFiltrado:
    def __init__(self):
        self.chamadas = []

    def get_available_slots_filtered(self, **kwargs):
        self.chamadas.append(kwargs)
        return [{"slot": "04/11/2026 14:00"}]


class ServicoSoComDatabase:
    """Imita o DatabaseSchedulingService ANTES do conserto: sem o metodo 'filtered'."""

    def __init__(self):
        self.chamadas = []

    def get_available_slots_from_database(self, **kwargs):
        self.chamadas.append(kwargs)
        return ["04/11/2026 14:00"]


def test_helper_usa_filtered_quando_existe():
    servico = ServicoComFiltrado()
    saida = _slots_filtrados(servico, company_id=1, limit=10, agenda_id=3)
    assert saida == [{"slot": "04/11/2026 14:00"}]
    assert servico.chamadas[0]["company_id"] == 1
    assert servico.chamadas[0]["agenda_id"] == 3


def test_helper_cai_para_database_quando_nao_tem_filtered():
    """Este e o caso que estourava AttributeError em producao."""
    servico = ServicoSoComDatabase()
    saida = _slots_filtrados(servico, company_id=1, limit=10, agenda_id=3)
    assert saida == ["04/11/2026 14:00"]
    assert servico.chamadas[0]["limit"] == 10


def test_helper_nunca_propaga_attributeerror():
    servico = ServicoSoComDatabase()
    try:
        _slots_filtrados(servico, company_id=1)
    except AttributeError:
        pytest.fail("fallback ainda estoura AttributeError — e o defeito do print do cliente")


def test_servico_de_producao_tem_o_metodo_do_fallback():
    assert hasattr(DatabaseSchedulingService, "get_available_slots_filtered"), (
        "o manager injeta DatabaseSchedulingService na tool; sem este metodo o fallback quebra"
    )


def test_metodo_novo_delega_para_o_slots_service_interno():
    interno = MagicMock()
    interno.get_available_slots_filtered.return_value = [{"slot": "05/11/2026 09:00"}]
    servico = DatabaseSchedulingService.__new__(DatabaseSchedulingService)
    servico.company_id = 7
    servico.slots_service = interno

    saida = servico.get_available_slots_filtered(limit=5, agenda_id=2)

    assert saida == [{"slot": "05/11/2026 09:00"}]
    interno.get_available_slots_filtered.assert_called_once()
    kwargs = interno.get_available_slots_filtered.call_args.kwargs
    assert kwargs["company_id"] == 7, "company_id deve vir do servico quando nao for passado"
    assert kwargs["limit"] == 5
    assert kwargs["agenda_id"] == 2


def test_escopos_do_google_incluem_calendar_events():
    from backend.routes.integrations.google_calendar_service import GOOGLE_OAUTH_SCOPES

    assert "https://www.googleapis.com/auth/calendar.events" in GOOGLE_OAUTH_SCOPES, (
        "sem calendar.events o freebusy no calendario real do profissional volta 403"
    )
    assert "https://www.googleapis.com/auth/calendar.app.created" not in GOOGLE_OAUTH_SCOPES, (
        "calendar.app.created so dá acesso a calendários criados pelo app"
    )
