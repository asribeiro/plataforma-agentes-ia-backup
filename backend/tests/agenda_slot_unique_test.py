"""Testes do indice unico de agenda por profissional (migration 0008).

Regra: nao pode haver dois agendamentos ativos no mesmo horario da mesma agenda.
Cada agenda pertence a um profissional, entao dois profissionais podem atender
no mesmo horario. Horario cancelado volta a ficar livre.

O teste replica o indice parcial em SQLite (que suporta indices parciais com
WHERE desde 3.8) para provar as tres garantias.
"""
import os
import sqlite3

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

CRIAR_TABELA = """
CREATE TABLE agendamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    agenda_id INTEGER,
    consulta_data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED'
)
"""

CRIAR_INDICE = """
CREATE UNIQUE INDEX uq_agendamento_agenda_slot
ON agendamentos (company_id, agenda_id, consulta_data)
WHERE status NOT LIKE 'CANCELLED%'
  AND agenda_id IS NOT NULL
"""


def _banco():
    con = sqlite3.connect(":memory:")
    con.execute(CRIAR_TABELA)
    con.execute(CRIAR_INDICE)
    return con


def _agendar(con, company_id, agenda_id, quando, status="SCHEDULED"):
    con.execute(
        "INSERT INTO agendamentos (company_id, agenda_id, consulta_data, status) VALUES (?,?,?,?)",
        (company_id, agenda_id, quando, status),
    )


class TestIndiceDeAgenda:
    def test_mesma_agenda_mesmo_horario_e_bloqueado(self):
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00")
        with pytest.raises(sqlite3.IntegrityError):
            _agendar(con, 1, 10, "2026-10-29 15:00")

    def test_agendas_diferentes_no_mesmo_horario_sao_permitidas(self):
        # a agenda e por profissional: dois profissionais, mesmo horario, ok
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00")
        _agendar(con, 1, 20, "2026-10-29 15:00")  # nao deve levantar
        total = con.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0]
        assert total == 2

    def test_empresas_diferentes_no_mesmo_horario_sao_permitidas(self):
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00")
        _agendar(con, 2, 10, "2026-10-29 15:00")
        assert con.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0] == 2

    def test_horarios_diferentes_na_mesma_agenda_sao_permitidos(self):
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00")
        _agendar(con, 1, 10, "2026-10-29 16:00")
        assert con.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0] == 2

    def test_horario_cancelado_libera_o_slot(self):
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00", status="CANCELLED")
        _agendar(con, 1, 10, "2026-10-29 15:00")  # deve funcionar
        assert con.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0] == 2

    def test_cancelamento_parcial_por_prefixo_tambem_libera(self):
        # a regra usa NOT LIKE 'CANCELLED%', entao variacoes tambem liberam
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00", status="CANCELLED_BY_CLIENT")
        _agendar(con, 1, 10, "2026-10-29 15:00")
        assert con.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0] == 2

    def test_agenda_nula_nao_colide(self):
        # registros antigos sem agenda nao devem derrubar a migracao
        con = _banco()
        _agendar(con, 1, None, "2026-10-29 15:00")
        _agendar(con, 1, None, "2026-10-29 15:00")
        assert con.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0] == 2

    def test_dois_ativos_nao_cancelados_colidem(self):
        con = _banco()
        _agendar(con, 1, 10, "2026-10-29 15:00", status="SCHEDULED")
        with pytest.raises(sqlite3.IntegrityError):
            _agendar(con, 1, 10, "2026-10-29 15:00", status="CONFIRMED")
