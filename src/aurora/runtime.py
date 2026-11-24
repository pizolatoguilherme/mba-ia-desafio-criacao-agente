"""Runtime do assistente: App, sessão persistida (SQLite) e Runner.

Config validada no spike (scripts/spike_confirmacao.py, config A): especialistas
como sub_agents com as flags de transferência padrão e App sem
resumability_config. Assim o Runner entrega a resposta de uma confirmação ao
agente que a pediu, inclusive depois de reiniciar a API.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from typing import Any

from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, Session
from google.genai import types

from . import config, confirmacoes, db, repositorio
from .agents.coordenador import coordenador
from .sessao import CHAVE_STATE

logger = logging.getLogger("aurora.runtime")

AVISO_PENDENCIA = (
    "Há uma confirmação aguardando a sua resposta. Aprove ou recuse a confirmação pendente "
    "antes de fazer um novo pedido."
)
AVISO_INDISPONIVEL = "Não consegui concluir agora. Tente novamente em instantes."


class SessaoNaoEncontrada(LookupError):
    pass


class ConfirmacaoNaoPendente(LookupError):
    pass


class Assistente:
    def __init__(self) -> None:
        config.garantir_var()
        db.init_db()
        self.session_service = DatabaseSessionService(
            db_url=config.sessoes_db_url(), connect_args={"timeout": 30}
        )
        self.app = App(name=config.APP_NAME, root_agent=coordenador)
        self.runner = Runner(app=self.app, session_service=self.session_service)
        self._travas: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def fechar(self) -> None:
        await self.runner.close()
        await self.session_service.close()

    # ------------------------------------------------------------------ sessões

    async def criar_sessao(self, apartamento: str) -> str:
        session_id = uuid.uuid4().hex
        # Garantia 2: o apartamento é fixado aqui, uma única vez, fora do alcance do modelo.
        await self.session_service.create_session(
            app_name=config.APP_NAME,
            user_id=apartamento,
            session_id=session_id,
            state={CHAVE_STATE: apartamento},
        )
        repositorio.registrar_sessao(session_id, apartamento)
        return session_id

    async def sessao(self, session_id: str) -> tuple[str, Session]:
        apartamento = repositorio.apartamento_da_sessao(session_id)
        if apartamento is None:
            raise SessaoNaoEncontrada(session_id)
        s = await self.session_service.get_session(
            app_name=config.APP_NAME, user_id=apartamento, session_id=session_id
        )
        if s is None:
            raise SessaoNaoEncontrada(session_id)
        return apartamento, s

    async def eventos(self, session_id: str) -> list[dict[str, Any]]:
        _, s = await self.sessao(session_id)
        return [e.model_dump(mode="json", by_alias=True, exclude_none=True) for e in s.events]

    # ------------------------------------------------------------------ conversa

    async def _executar(self, apartamento: str, session_id: str, mensagem: types.Content) -> str:
        partes: list[str] = []
        try:
            async for ev in self.runner.run_async(
                user_id=apartamento, session_id=session_id, new_message=mensagem
            ):
                if ev.author == "user" or not ev.content or not ev.content.parts or ev.partial:
                    continue
                for p in ev.content.parts:
                    if p.text and not p.thought:
                        partes.append(p.text.strip())
        except Exception:  # erro do modelo ou da retomada: resposta normal, sem 500
            logger.exception("falha ao executar o assistente na sessão %s", session_id)
            partes.append(AVISO_INDISPONIVEL)
        return "\n\n".join(p for p in partes if p)

    async def _resultado(self, session_id: str, resposta: str) -> dict[str, Any]:
        _, s = await self.sessao(session_id)
        return {"resposta": resposta, "confirmacoes_pendentes": confirmacoes.pendentes(s)}

    async def enviar_texto(self, session_id: str, texto: str) -> dict[str, Any]:
        apartamento, s = await self.sessao(session_id)
        async with self._travas[session_id]:
            apartamento, s = await self.sessao(session_id)
            if confirmacoes.pendentes(s):
                # Nada executa sem confirmação: o modelo nem roda enquanto houver pendência.
                return await self._resultado(session_id, AVISO_PENDENCIA)
            # O texto do morador entra só como texto; nunca vira resposta de confirmação.
            mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
            resposta = await self._executar(apartamento, session_id, mensagem)
            return await self._resultado(session_id, resposta)

    async def responder_confirmacao(self, session_id: str, confirmacao_id: str, confirmado: bool) -> dict[str, Any]:
        apartamento, s = await self.sessao(session_id)
        async with self._travas[session_id]:
            apartamento, s = await self.sessao(session_id)
            # Garantia 1: só um id pendente NESTA sessão é aceito (o resto vira 409).
            if confirmacao_id not in {p["id"] for p in confirmacoes.pendentes(s)}:
                raise ConfirmacaoNaoPendente(confirmacao_id)
            resposta = await self._executar(
                apartamento, session_id, confirmacoes.resposta(confirmacao_id, confirmado)
            )
            _, depois = await self.sessao(session_id)
            if not confirmacoes.foi_retomada(depois, confirmacao_id):
                logger.error("confirmação %s não foi retomada pela tool (sessão %s)", confirmacao_id, session_id)
            return await self._resultado(session_id, resposta)
