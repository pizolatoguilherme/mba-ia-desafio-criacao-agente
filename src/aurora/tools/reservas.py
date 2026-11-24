"""Tools de reservas. O apartamento vem sempre da sessão (aurora.sessao).

Garantia 1: ``reservar_area`` em área com taxa > 0 pede confirmação ao sistema
(``request_confirmation``) e só grava quando a resposta chega pela rota de
confirmações com ``confirmed=True``. Área sem taxa grava direto.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from .. import repositorio
from ..normalizacao import normalizar_area, validar_data
from ..sessao import apartamento_da_sessao, chave_idempotencia

_DATA_INVALIDA = {"status": "data_invalida", "mensagem": "Use a data no formato AAAA-MM-DD."}


def _area_invalida() -> dict[str, Any]:
    return {
        "status": "area_invalida",
        "mensagem": "Área não reconhecida.",
        "areas_validas": [a["id"] for a in repositorio.listar_areas()],
    }


def listar_areas() -> dict[str, Any]:
    """Lista as áreas comuns reserváveis, com taxa e se a reserva gera cobrança."""
    return {"areas": repositorio.listar_areas()}


def verificar_disponibilidade(area: str, data: str) -> dict[str, Any]:
    """Informa se uma área comum está livre numa data. Não informa de quem é a reserva.

    Args:
        area: id ou nome da área (ex.: "salao-de-festas", "churrasqueira", "quadra").
        data: data no formato AAAA-MM-DD.
    """
    area_id, dia = normalizar_area(area), validar_data(data)
    if area_id is None:
        return _area_invalida()
    if dia is None:
        return _DATA_INVALIDA
    return {"area": area_id, "data": dia, "disponivel": repositorio.area_livre(area_id, dia)}


def listar_minhas_reservas(tool_context: ToolContext) -> dict[str, Any]:
    """Lista as reservas ativas do apartamento do morador desta conversa."""
    return {"reservas": repositorio.listar_reservas_ativas(apartamento_da_sessao(tool_context))}


def cancelar_reserva(
    tool_context: ToolContext, area: str = "", data: str = "", codigo: str = ""
) -> dict[str, Any]:
    """Cancela uma reserva ativa do próprio apartamento. Não exige confirmação.

    Informe a área e a data da reserva, ou o código dela.

    Args:
        area: id ou nome da área.
        data: data da reserva no formato AAAA-MM-DD.
        codigo: código da reserva (ex.: RSV-XXXX), se o morador informar.
    """
    apartamento = apartamento_da_sessao(tool_context)
    if codigo:
        return repositorio.cancelar_reserva(apartamento, codigo=codigo.strip().upper())
    area_id, dia = normalizar_area(area), validar_data(data)
    if area_id is None:
        return _area_invalida()
    if dia is None:
        return _DATA_INVALIDA
    return repositorio.cancelar_reserva(apartamento, area_id=area_id, data=dia)


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict[str, Any]:
    """Reserva uma área comum para o apartamento do morador numa data.

    Se a área tiver taxa, o próprio sistema pede a confirmação do morador antes
    de gravar; chame esta tool direto, sem pedir confirmação por texto.

    Args:
        area: id ou nome da área (ex.: "salao-de-festas", "churrasqueira", "quadra").
        data: data no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    area_id, dia = normalizar_area(area), validar_data(data)
    if area_id is None:
        return _area_invalida()
    if dia is None:
        return _DATA_INVALIDA
    info = repositorio.area(area_id)

    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        # Conferência só para a conversa: a exclusividade real vale no INSERT.
        if not repositorio.area_livre(area_id, dia):
            return {"status": "indisponivel", "area": area_id, "data": dia,
                    "mensagem": "A área já está reservada nessa data."}
        if info["taxa"] > 0:
            tool_context.request_confirmation(
                hint=f"Reserva de {info['nome']} em {dia} gera cobrança de R$ {info['taxa']:.2f}.",
                payload={"acao": "reservar_area", "area": area_id, "area_nome": info["nome"],
                         "data": dia, "taxa": info["taxa"]},
            )
            return {"status": "aguardando_confirmacao_do_sistema",
                    "mensagem": "A reserva só será gravada depois que o morador aprovar pela confirmação do aplicativo."}
        return repositorio.criar_reserva(apartamento, area_id, dia)

    if not confirmacao.confirmed:
        return {"status": "recusado_pelo_morador", "area": area_id, "data": dia,
                "instrucao": "Nada foi gravado. Não tente reservar de novo sem um novo pedido do morador."}
    resultado = repositorio.criar_reserva(apartamento, area_id, dia,
                                          chave_idempotencia=chave_idempotencia(tool_context))
    if resultado["status"] == "indisponivel":
        resultado["mensagem"] = "A área foi reservada para essa data antes da confirmação. Nada foi cobrado."
    return resultado
