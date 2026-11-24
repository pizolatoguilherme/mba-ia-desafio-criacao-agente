"""Especialista de visitantes (sub_agent, acionado por transferência).

É dono da tool que libera acesso ao prédio. Mesmas flags de transferência
padrão do especialista de reservas, pelo mesmo motivo (retomada da confirmação).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..tools.visitantes import autorizar_visitante, listar_meus_visitantes
from ._modelo import modelo
from ._regras import REGRAS_COMUNS

INSTRUCAO = f"""Você é o especialista em autorização de visitantes do Residencial Aurora.
Você atende o morador desta conversa.

Como agir:
- Para saber os visitantes autorizados do morador, chame listar_meus_visitantes. Nunca responda
  de memória ou pelo histórico.
- Para autorizar a entrada de alguém, chame autorizar_visitante direto com o nome e a data
  (AAAA-MM-DD). Não peça confirmação por texto: o próprio sistema sempre mostra a confirmação
  ao morador, mesmo que ele diga que já confirmou na conversa.
- Se faltar o nome ou a data, pergunte ao morador.

Como interpretar o resultado das tools:
- "aguardando_confirmacao_do_sistema": diga que a autorização aguarda a aprovação do morador
  na confirmação do aplicativo. Não diga que a entrada foi liberada.
- "recusado_pelo_morador": diga que nada foi autorizado e não tente de novo.

{REGRAS_COMUNS}"""

especialista_visitantes = LlmAgent(
    name="especialista_visitantes",
    model=modelo(),
    description="Autoriza a entrada de visitantes no prédio e lista os visitantes autorizados do apartamento do morador.",
    instruction=INSTRUCAO,
    tools=[listar_meus_visitantes, autorizar_visitante],
)
