"""Tools de visitantes. O apartamento vem sempre da sessão (aurora.sessao).

Garantia 1: autorizar visitante libera acesso ao prédio, então SEMPRE pede
confirmação ao sistema e só grava com ``confirmed=True`` vindo da rota de
confirmações, não importa o que o morador escreva na conversa.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from .. import repositorio
from ..normalizacao import validar_data
from ..sessao import apartamento_da_sessao, chave_idempotencia


def listar_meus_visitantes(tool_context: ToolContext) -> dict[str, Any]:
    """Lista os visitantes autorizados do apartamento do morador desta conversa."""
    return {"visitantes": repositorio.listar_visitantes(apartamento_da_sessao(tool_context))}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict[str, Any]:
    """Autoriza a entrada de um visitante no prédio numa data.

    O próprio sistema pede a confirmação do morador antes de gravar; chame esta
    tool direto, mesmo que o morador diga que já confirmou.

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    nome = " ".join((nome or "").split())
    dia = validar_data(data)
    if not nome:
        return {"status": "nome_invalido", "mensagem": "Informe o nome do visitante."}
    if dia is None:
        return {"status": "data_invalida", "mensagem": "Use a data no formato AAAA-MM-DD."}

    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        tool_context.request_confirmation(
            hint=f"Autorizar a entrada de {nome} em {dia}.",
            payload={"acao": "autorizar_visitante", "nome": nome, "data": dia},
        )
        return {"status": "aguardando_confirmacao_do_sistema",
                "mensagem": "A autorização só vale depois que o morador aprovar pela confirmação do aplicativo."}
    if not confirmacao.confirmed:
        return {"status": "recusado_pelo_morador", "nome": nome, "data": dia,
                "instrucao": "Nada foi gravado. Não tente de novo sem um novo pedido do morador."}
    return repositorio.autorizar_visitante(apartamento, nome, dia,
                                           chave_idempotencia=chave_idempotencia(tool_context))
