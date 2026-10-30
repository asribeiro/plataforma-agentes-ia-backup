"""Trava o conserto do horario: "as 14h" nao pode virar 15h, e regra de +1h some."""
from pathlib import Path

FONTE = Path("backend/agents_sdk/tools/scheduling_tools.py").read_text(encoding="utf-8")


def _linhas_com(prefixo: str):
    return [l.strip() for l in FONTE.splitlines() if l.strip().startswith(prefixo)]


def test_prompt_ensina_horario_exato():
    assert 'type="exact"' in FONTE, "falta o tipo 'exact' para hora pedida"
    assert '"type": "exact", "min_time": "14:00"' in FONTE
    assert "NUNCA acrescente uma hora" in FONTE


def test_regra_de_somar_uma_hora_foi_removida():
    assert "NOTA: \"depois de 14\" = 15:00 ou mais tarde" not in FONTE
    assert "NOTA: \"depois de 15\" = 16:00 ou mais tarde" not in FONTE
    assert 'means min_time="16:00"' not in FONTE
    assert "NUNCA some uma hora ao horário citado" in FONTE


def test_exemplos_de_depois_das_usam_o_mesmo_horario():
    for prefixo, esperado in (('- "depois das 14h"', "14:00"), ('- "depois das 15"', "15:00")):
        achados = _linhas_com(prefixo)
        assert achados, f"exemplo {prefixo} desapareceu"
        assert any(esperado in l for l in achados), f"{prefixo} nao aponta {esperado}: {achados}"


def test_codigo_filtra_por_horario_exato():
    assert "[EXACT_TIME]" in FONTE
    assert 'time_restrictions.get("type") == "exact"' in FONTE
