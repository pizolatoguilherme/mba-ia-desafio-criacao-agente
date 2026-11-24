"""WP1 — spike: confirmação de tool com sessão persistida em SQLite.

Valida, com a mesma topologia do assistente (raiz + sub_agents por
transferência), se a resposta de confirmação chega ao agente que a pediu:

  1. pedido gera adk_request_confirmation com autor = especialista
  2. aprovar executa a tool exatamente uma vez
  3. negar não executa
  4. aprovar depois de recriar Runner e SessionService (reinício) executa
  5. reenviar a mesma resposta não executa de novo
  6. duas sessões aprovando em paralelo, sem "database is locked"
  7. depois do especialista, um pedido de outro assunto é transferido

Uso: uv run python scripts/spike_confirmacao.py --config A   (ou B = resumable)
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.adk.tools import ToolContext
from google.genai import types

from aurora import confirmacoes
from aurora.agents._modelo import modelo

TMP = Path(tempfile.mkdtemp(prefix="aurora-spike-"))
EFEITOS = TMP / "efeitos.db"
SESSOES_URL = f"sqlite+aiosqlite:///{TMP / 'sessoes.db'}"
APP = "spike"


def _efeitos() -> sqlite3.Connection:
    con = sqlite3.connect(EFEITOS, timeout=15, isolation_level=None)
    con.execute("CREATE TABLE IF NOT EXISTS efeitos (codigo TEXT)")
    return con


def contar(codigo: str) -> int:
    with _efeitos() as con:
        return con.execute("SELECT COUNT(*) FROM efeitos WHERE codigo = ?", (codigo,)).fetchone()[0]


def acao_sensivel(codigo: str, tool_context: ToolContext) -> dict:
    """Executa a ação sensível identificada por 'codigo'. Exige confirmação do sistema."""
    conf = tool_context.tool_confirmation
    if conf is None:
        tool_context.request_confirmation(hint="Confirma?", payload={"acao": "acao_sensivel", "codigo": codigo})
        return {"status": "aguardando_confirmacao_do_sistema"}
    if not conf.confirmed:
        return {"status": "recusado"}
    with _efeitos() as con:
        con.execute("INSERT INTO efeitos (codigo) VALUES (?)", (codigo,))
    return {"status": "executado", "codigo": codigo}


def consultar_clima() -> dict:
    """Informa o clima de hoje."""
    return {"clima": "ensolarado"}


def montar_app(config: str) -> App:
    esp_a = LlmAgent(
        name="especialista_acoes", model=modelo(),
        description="Executa a ação sensível pedida pelo usuário.",
        instruction=("Quando o usuário pedir a ação sensível, chame acao_sensivel com o código informado, "
                     "sem pedir confirmação por texto. Para qualquer outro assunto, transfira ao coordenador."),
        tools=[acao_sensivel],
    )
    esp_b = LlmAgent(
        name="especialista_clima", model=modelo(),
        description="Responde perguntas sobre o clima.",
        instruction="Use consultar_clima para responder sobre o clima. Outros assuntos: transfira ao coordenador.",
        tools=[consultar_clima],
    )
    raiz = LlmAgent(
        name="coordenador", model=modelo(),
        instruction=("Você só roteia. Ação sensível: transfira para especialista_acoes. "
                     "Clima: transfira para especialista_clima."),
        sub_agents=[esp_a, esp_b],
    )
    kw = {"resumability_config": ResumabilityConfig(is_resumable=True)} if config == "B" else {}
    return App(name=APP, root_agent=raiz, **kw)


class Ambiente:
    def __init__(self, config: str):
        self.config = config
        self.recriar()

    def recriar(self) -> None:
        self.service = DatabaseSessionService(db_url=SESSOES_URL, connect_args={"timeout": 30})
        self.runner = Runner(app=montar_app(self.config), session_service=self.service)

    async def nova_sessao(self) -> str:
        s = await self.service.create_session(app_name=APP, user_id="u")
        return s.id

    async def enviar(self, sid: str, content: types.Content) -> None:
        async for _ in self.runner.run_async(user_id="u", session_id=sid, new_message=content):
            pass

    async def texto(self, sid: str, texto: str) -> None:
        await self.enviar(sid, types.Content(role="user", parts=[types.Part(text=texto)]))

    async def sessao(self, sid: str):
        return await self.service.get_session(app_name=APP, user_id="u", session_id=sid)

    async def pedir(self, sid: str, codigo: str) -> dict:
        await self.texto(sid, f"Execute a ação sensível com o código {codigo}.")
        pend = confirmacoes.pendentes(await self.sessao(sid))
        assert len(pend) == 1, f"esperava 1 pendência, veio {pend}"
        return pend[0]


def ok(n: int, msg: str) -> None:
    print(f"  [{n}] OK  {msg}")


async def rodar(config: str) -> None:
    amb = Ambiente(config)

    # 1
    sid = await amb.nova_sessao()
    p = await amb.pedir(sid, "C1")
    s = await amb.sessao(sid)
    autor = next(ev.author for ev in s.events for fc in ev.get_function_calls() if fc.id == p["id"])
    assert autor == "especialista_acoes", f"autor do pedido = {autor}"
    assert p["detalhes"] == {"codigo": "C1"} and contar("C1") == 0
    ok(1, f"pendência criada pelo especialista: {p}")

    # 2
    await amb.enviar(sid, confirmacoes.resposta(p["id"], True))
    s = await amb.sessao(sid)
    assert contar("C1") == 1, f"aprovar executou {contar('C1')}x (armadilha silenciosa?)"
    assert confirmacoes.foi_retomada(s, p["id"]) and not confirmacoes.pendentes(s)
    ok(2, "aprovar executou exatamente uma vez")

    # 5
    try:
        await amb.enviar(sid, confirmacoes.resposta(p["id"], True))
    except Exception as e:  # noqa: BLE001
        print(f"      (reenvio direto ao ADK levantou {type(e).__name__}; a API devolve 409 antes)")
    assert contar("C1") == 1, "reenvio executou de novo"
    ok(5, "reenviar a mesma resposta não executa de novo")

    # 3
    sid3 = await amb.nova_sessao()
    p3 = await amb.pedir(sid3, "C3")
    await amb.enviar(sid3, confirmacoes.resposta(p3["id"], False))
    assert contar("C3") == 0 and not confirmacoes.pendentes(await amb.sessao(sid3))
    ok(3, "negar não executou")

    # 4
    sid4 = await amb.nova_sessao()
    p4 = await amb.pedir(sid4, "C4")
    amb.recriar()
    await amb.enviar(sid4, confirmacoes.resposta(p4["id"], True))
    assert contar("C4") == 1, "aprovação após reinício não executou"
    ok(4, "aprovar após recriar Runner/SessionService executou")

    # 6
    sa, sb = await amb.nova_sessao(), await amb.nova_sessao()
    pa, pb = await amb.pedir(sa, "C6A"), await amb.pedir(sb, "C6B")
    await asyncio.gather(amb.enviar(sa, confirmacoes.resposta(pa["id"], True)),
                         amb.enviar(sb, confirmacoes.resposta(pb["id"], True)))
    assert contar("C6A") == 1 and contar("C6B") == 1
    ok(6, "duas aprovações simultâneas sem erro de lock")

    # 7
    await amb.texto(sid, "Mudando de assunto: como está o clima hoje?")
    s = await amb.sessao(sid)
    chamou = any(fc.name == "consultar_clima" for ev in s.events for fc in ev.get_function_calls())
    assert chamou, "não transferiu para o especialista de clima"
    ok(7, "transferência após o especialista funcionou")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=["A", "B"], default="A")
    args = ap.parse_args()
    print(f"Spike config {args.config} (dados temporários em {TMP})")
    try:
        asyncio.run(rodar(args.config))
    except AssertionError as e:
        print(f"  FALHA: {e}")
        return 1
    print(f"Config {args.config}: todos os itens OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
