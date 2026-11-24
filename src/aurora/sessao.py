"""Apartamento da sessão (Garantia 2).

O apartamento é gravado uma única vez, pela API, ao criar a sessão: no state
da sessão ADK e na tabela ``sessoes``. As tools obtêm o apartamento SÓ por
aqui. Nenhuma tool recebe apartamento como parâmetro, então nada que o
morador escreva ou o modelo escolha muda o apartamento usado.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from . import repositorio

CHAVE_STATE = "apartamento"


class SessaoSemApartamento(PermissionError):
    pass


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    do_state = tool_context.state.get(CHAVE_STATE)
    do_banco = repositorio.apartamento_da_sessao(tool_context.session.id)
    if not do_state or not do_banco or str(do_state) != do_banco:
        raise SessaoSemApartamento("Sessão sem apartamento válido; operação negada.")
    return do_banco


def chave_idempotencia(tool_context: ToolContext) -> str:
    """Identifica a chamada de tool aprovada (sessão + id da chamada)."""
    return f"{tool_context.session.id}:{tool_context.function_call_id}"
