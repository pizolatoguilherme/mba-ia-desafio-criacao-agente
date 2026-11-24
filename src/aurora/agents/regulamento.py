"""Especialista de regulamento, acionado pelo coordenador como AgentTool.

Por que AgentTool: o ADK executa este agente numa sessão em memória própria,
separada da sessão do morador. Os capítulos lidos ficam nessa sessão isolada
e só a resposta curta volta para a conversa (Garantia 4).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..tools.regulamento import ler_capitulo, listar_capitulos
from ._modelo import modelo

INSTRUCAO = """Você é o especialista no regulamento interno do Residencial Aurora.
Responda à dúvida recebida usando SOMENTE o texto do regulamento, obtido pelas tools.

Procedimento obrigatório:
1. Chame listar_capitulos para ver os títulos.
2. Escolha o capítulo que trata do assunto perguntado e chame ler_capitulo com o número dele.
   Leia outro capítulo apenas se o primeiro claramente não tratar do assunto.
3. Responda em no máximo três frases, em português, citando o artigo (ex.: "Art. N").

Regras:
- Responda apenas o que foi perguntado. Não transcreva o capítulo e não mencione,
  resuma ou cite capítulos ou artigos sobre outros assuntos.
- Se o regulamento não tratar do assunto, diga isso em uma frase.
"""

especialista_regulamento = LlmAgent(
    name="especialista_regulamento",
    model=modelo(),
    description=(
        "Consulta o regulamento interno do condomínio e responde dúvidas sobre regras "
        "(horários, uso de áreas, silêncio, animais, mudanças, obras etc.). "
        "Envie a pergunta do morador em 'request'."
    ),
    instruction=INSTRUCAO,
    tools=[listar_capitulos, ler_capitulo],
)
