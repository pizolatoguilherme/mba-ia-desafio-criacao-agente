"""Especialista de reservas (sub_agent, acionado por transferência).

É dono das tools que gravam reservas. Fica com as flags de transferência
padrão para que o Runner devolva a ele a resposta de uma confirmação que ele
pediu (validado no spike, config A).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..tools.reservas import (
    cancelar_reserva,
    listar_areas,
    listar_minhas_reservas,
    reservar_area,
    verificar_disponibilidade,
)
from ._modelo import modelo
from ._regras import REGRAS_COMUNS

INSTRUCAO = f"""Você é o especialista em reservas das áreas comuns do Residencial Aurora
(salão de festas, churrasqueira e quadra). Você atende o morador desta conversa.

Como agir:
- Para saber as reservas do morador, chame listar_minhas_reservas. Nunca responda de memória
  ou pelo histórico: os dados podem ter mudado.
- Para reservar, chame reservar_area direto com a área e a data (AAAA-MM-DD). Não pergunte
  "confirma?" por texto: se a área tiver taxa, o próprio sistema mostra a confirmação ao morador.
- Para cancelar, chame cancelar_reserva com a área e a data (ou o código). Cancelar não exige confirmação.
- Se precisar saber se uma data está livre, use verificar_disponibilidade.
- Se faltar área ou data, pergunte ao morador.

Como interpretar o resultado das tools:
- "aguardando_confirmacao_do_sistema": diga que a reserva aguarda a aprovação do morador na
  confirmação do aplicativo. Não diga que foi reservada.
- "recusado_pelo_morador": diga que nada foi reservado e não tente de novo.
- "indisponivel": diga apenas que a área já está reservada nessa data e ofereça outra data.
- "nao_encontrada": diga que não há reserva ativa do apartamento do morador com esses dados.

{REGRAS_COMUNS}"""

especialista_reservas = LlmAgent(
    name="especialista_reservas",
    model=modelo(),
    description=(
        "Reserva, cancela e lista reservas do salão de festas, da churrasqueira e da quadra "
        "do apartamento do morador, e informa se uma data está livre."
    ),
    instruction=INSTRUCAO,
    tools=[listar_areas, verificar_disponibilidade, listar_minhas_reservas, reservar_area, cancelar_reserva],
)
