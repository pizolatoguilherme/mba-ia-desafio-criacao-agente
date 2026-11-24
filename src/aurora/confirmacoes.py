"""Confirmações de tools (Garantia 1).

Uma confirmação pendente é um FunctionCall ``adk_request_confirmation``
gravado na sessão que ainda não tem FunctionResponse com o mesmo id. A lista é
derivada dos eventos persistidos, então sobrevive ao reinício e não depende do
que o modelo escreve. O texto do morador nunca vira FunctionResponse: só a rota
de confirmações monta essa resposta, e apenas para um id pendente na sessão.
"""

from __future__ import annotations

from typing import Any

from google.adk.events import Event
from google.adk.sessions import Session
from google.genai import types

NOME_CONFIRMACAO = "adk_request_confirmation"


def _chamadas_de_confirmacao(events: list[Event]) -> list[types.FunctionCall]:
    return [fc for ev in events for fc in ev.get_function_calls() if fc.name == NOME_CONFIRMACAO and fc.id]


def _ids_respondidos(events: list[Event]) -> set[str]:
    return {fr.id for ev in events for fr in ev.get_function_responses() if fr.id}


def pendentes(session: Session) -> list[dict[str, Any]]:
    """Confirmações pendentes da sessão, no formato do contrato da API."""
    respondidos = _ids_respondidos(session.events)
    saida = []
    for fc in _chamadas_de_confirmacao(session.events):
        if fc.id in respondidos:
            continue
        args = fc.args or {}
        original = args.get("originalFunctionCall") or {}
        payload = dict((args.get("toolConfirmation") or {}).get("payload") or {})
        acao = payload.pop("acao", None) or original.get("name", "")
        detalhes = payload or dict(original.get("args") or {})
        saida.append({"id": fc.id, "acao": acao, "detalhes": detalhes})
    return saida


def id_original(session: Session, confirmacao_id: str) -> str | None:
    """Id do FunctionCall da tool que pediu a confirmação."""
    for fc in _chamadas_de_confirmacao(session.events):
        if fc.id == confirmacao_id:
            return ((fc.args or {}).get("originalFunctionCall") or {}).get("id")
    return None


def foi_retomada(session: Session, confirmacao_id: str) -> bool:
    """True se, depois da resposta, a tool original voltou a executar.

    A tool original tem duas FunctionResponses com o mesmo id: a do pedido de
    confirmação e a da execução retomada. Se só houver uma, a resposta caiu
    no agente errado e nada foi executado (armadilha silenciosa do Runner).
    """
    fc_id = id_original(session, confirmacao_id)
    if not fc_id:
        return False
    n = sum(1 for ev in session.events for fr in ev.get_function_responses() if fr.id == fc_id)
    return n >= 2


def resposta(confirmacao_id: str, confirmado: bool) -> types.Content:
    """Mensagem que o cliente ADK envia para responder a uma confirmação."""
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=confirmacao_id,
                    name=NOME_CONFIRMACAO,
                    response={"confirmed": bool(confirmado)},
                )
            )
        ],
    )
