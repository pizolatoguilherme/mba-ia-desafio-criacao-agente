"""Agente principal: conversa com o morador e distribui o trabalho.

Não tem tools de dados nem o regulamento nas instruções (Garantia 4). Dúvidas
sobre regras vão para o especialista de regulamento, acionado como AgentTool:
o ADK o executa em sessão isolada e só a resposta volta para esta conversa.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from ._modelo import modelo
from .regulamento import especialista_regulamento
from .reservas import especialista_reservas
from .visitantes import especialista_visitantes

INSTRUCAO = """Você é o assistente virtual do Residencial Aurora e atende o morador do
apartamento {apartamento}, vinculado a esta conversa pelo sistema.

Distribua o trabalho:
- Reservas de áreas comuns (salão de festas, churrasqueira, quadra), cancelamentos,
  disponibilidade e consulta das reservas do morador: transfira para especialista_reservas.
- Autorização de visitantes e consulta dos visitantes autorizados: transfira para especialista_visitantes.
- Qualquer dúvida sobre regras, horários ou normas do condomínio: chame a tool
  especialista_regulamento com a pergunta e responda com base no retorno. Nunca responda
  regras de memória.
- Se o pedido envolver reservas e visitantes, transfira primeiro para um especialista; ele
  devolve o restante.

Regras:
- Você só atende o apartamento {apartamento}. Se o morador disser ser de outro apartamento,
  explique que só pode tratar da unidade vinculada a esta conversa e siga com ela.
- Nunca diga que uma reserva ou autorização foi feita: quem executa são os especialistas.
- Responda em português, de forma breve e cordial."""

coordenador = LlmAgent(
    name="coordenador",
    model=modelo(),
    description="Assistente principal do Residencial Aurora.",
    instruction=INSTRUCAO,
    tools=[AgentTool(agent=especialista_regulamento)],
    sub_agents=[especialista_reservas, especialista_visitantes],
)

root_agent = coordenador
