"""O schema que chega ao modelo nao pode exigir professional_id.

Bug medido: `horarios_disponiveis_tool` declarava `professional_id: int` (obrigatorio). O
modelo chamou a tool sem esse campo — ele nao tem o id na conversa — e o SDK recusou:

    Invalid JSON input for tool horarios_disponiveis_tool: professional_id Field required

Como a chamada inteira falhava, o agente respondia ao paciente que nao conseguia consultar a
agenda. Este teste trava o contrato: `professional_id` nao pode aparecer em `required`.
"""
from backend.agents_sdk.tools.scheduling_tools import create_scheduling_tools


def _tools():
    return create_scheduling_tools(slots_service=None, company_id=1)


def test_tool_de_horarios_nao_exige_professional_id():
    alvo = next(t for t in _tools() if getattr(t, "name", "") == "horarios_disponiveis_tool")
    obrigatorios = alvo.params_json_schema.get("required", [])
    assert "professional_id" not in obrigatorios, (
        "professional_id nao pode ser obrigatorio: o modelo nao tem esse id na conversa "
        "e a chamada inteira e recusada pelo SDK"
    )
    props = alvo.params_json_schema.get("properties", {})
    assert "professional_id" in props, "o campo continua existindo, apenas opcional"


def test_nenhuma_tool_clinica_exige_parametro():
    """Neste SDK, `x: int = 0` continua obrigatorio; so `Optional[int] = None` libera.

    Se a tool exigir parametro, o modelo chama sem ele e o SDK recusa a chamada inteira —
    foi o que derrubou a consulta de agenda do paciente.
    """
    for tool in _tools():
        nome = getattr(tool, "name", "")
        if nome not in (
            "horarios_disponiveis_tool",
            "buscar_procedimentos_tool",
            "profissionais_que_atendem_tool",
        ):
            continue
        obrigatorios = tool.params_json_schema.get("required", [])
        assert obrigatorios == [], f"{nome} ainda exige {obrigatorios}"


def test_instrucao_pede_tres_opcoes():
    """O produto pede 3 alternativas quando o horario solicitado nao esta livre."""
    from pathlib import Path

    fonte = Path("backend/agents_sdk/tools/scheduling_tools.py").read_text(encoding="utf-8")
    assert "no máximo 3 (três) opções" in fonte
    assert "apenas 2 (duas)" not in fonte
