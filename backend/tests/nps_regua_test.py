"""Testes da regua de classificacao do NPS (enquete de 1 a 5).

Bug corrigido: o endpoint /responses usava a regua 0-10 (promotor >= 9,
detrator <= 6) numa enquete de 1 a 5. Resultado: promoters sempre 0 e todo
score <= 6 contava como detrator, entao o NPS saia negativo mesmo com todos
os clientes dando nota 5.

A regua correta para escala 1-5 (a mesma que /dashboard/metrics ja usava):
    promotor  = 4 ou 5
    neutro    = 3
    detrator  = 1 ou 2

O teste replica a agregacao SQL em SQLite para provar o comportamento.
"""
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")


REGRUA_CORRETA = """
    SELECT
        COUNT(*) as answered,
        COUNT(CASE WHEN score >= 4 THEN 1 END) as promoters,
        COUNT(CASE WHEN score <= 2 THEN 1 END) as detractors
    FROM nps_responses
    WHERE score IS NOT NULL
"""

REGRUA_ERRADA = """
    SELECT
        COUNT(*) as answered,
        COUNT(CASE WHEN score >= 9 THEN 1 END) as promoters,
        COUNT(CASE WHEN score <= 6 THEN 1 END) as detractors
    FROM nps_responses
    WHERE score IS NOT NULL
"""


def _banco(scores):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE nps_responses (score INTEGER)")
    con.executemany("INSERT INTO nps_responses (score) VALUES (?)", [(s,) for s in scores])
    return con


def _nps(con, query):
    answered, promoters, detractors = con.execute(query).fetchone()
    if not answered:
        return None
    return (promoters / answered * 100) - (detractors / answered * 100)


class TestReguaCorreta:
    def test_todos_nota_cinco_dao_nps_100(self):
        con = _banco([5, 5, 5, 5])
        assert _nps(con, REGRUA_CORRETA) == 100.0

    def test_todos_nota_um_dao_nps_menos_100(self):
        con = _banco([1, 1, 1])
        assert _nps(con, REGRUA_CORRETA) == -100.0

    def test_neutros_nao_contam(self):
        con = _banco([5, 3, 3, 3])
        # 1 promotor de 4 respondidas = 25%, ninguem detrator
        assert _nps(con, REGRUA_CORRETA) == 25.0

    def test_mistura_promotor_neutro_detrator(self):
        con = _banco([5, 4, 3, 2, 1])
        # 2 promotores, 2 detratores, 1 neutro de 5 respondidas = 0
        assert _nps(con, REGRUA_CORRETA) == 0.0

    def test_sem_resposta_devolve_none(self):
        con = _banco([])
        assert _nps(con, REGRUA_CORRETA) is None


class TestReguaAntigaFalhava:
    """Documenta o bug: a regua 0-10 numa enquete 1-5."""

    def test_nota_cinco_virava_detrator(self):
        con = _banco([5, 5, 5])
        # score 5 >= 9? nao (promotores=0). score 5 <= 6? sim (3 detratores)
        assert _nps(con, REGRUA_ERRADA) == -100.0

    def test_nenhum_score_alcanca_promotor(self):
        con = _banco([1, 2, 3, 4, 5])
        answered, promoters, detractors = con.execute(REGRUA_ERRADA).fetchone()
        assert promoters == 0
        assert detractors == 5

    def test_contraste_entre_as_duas_reguas(self):
        con = _banco([5, 5, 5, 4, 4])
        assert _nps(con, REGRUA_CORRETA) == 100.0
        assert _nps(con, REGRUA_ERRADA) == -100.0
