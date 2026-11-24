"""API HTTP do assistente (contrato do desafio). Suba com `uv run aurora-api`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from . import repositorio
from .runtime import Assistente, ConfirmacaoNaoPendente, SessaoNaoEncontrada

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.assistente = Assistente()
    try:
        yield
    finally:
        await app.state.assistente.fechar()


app = FastAPI(title="Residencial Aurora — assistente", lifespan=lifespan)


class NovaSessao(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)
    apartamento: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


def _assistente(request: Request) -> Assistente:
    return request.app.state.assistente


@app.exception_handler(SessaoNaoEncontrada)
async def _sessao_nao_encontrada(_: Request, exc: SessaoNaoEncontrada) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Sessão não encontrada."})


@app.exception_handler(ConfirmacaoNaoPendente)
async def _confirmacao_nao_pendente(_: Request, exc: ConfirmacaoNaoPendente) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "Não existe confirmação pendente com esse id nesta sessão."},
    )


@app.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao, request: Request) -> dict[str, str]:
    apartamento = corpo.apartamento.strip()
    if not repositorio.apartamento_existe(apartamento):
        raise HTTPException(status_code=422, detail="Apartamento inexistente.")
    return {"session_id": await _assistente(request).criar_sessao(apartamento)}


@app.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: Mensagem, request: Request) -> dict[str, Any]:
    return await _assistente(request).enviar_texto(session_id, corpo.texto)


@app.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao, request: Request) -> dict[str, Any]:
    return await _assistente(request).responder_confirmacao(session_id, corpo.id, corpo.confirmado)


@app.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str, request: Request) -> list[dict[str, Any]]:
    return await _assistente(request).eventos(session_id)


# Rotas de verificação: leem o banco direto, sem passar pelo modelo.


@app.get("/apartamentos/{numero}/reservas")
async def reservas_do_apartamento(numero: str) -> list[dict[str, str]]:
    return repositorio.listar_reservas_ativas(numero)


@app.get("/apartamentos/{numero}/visitantes")
async def visitantes_do_apartamento(numero: str) -> list[dict[str, str]]:
    return repositorio.listar_visitantes(numero)


def main() -> None:
    uvicorn.run("aurora.api:app", host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
