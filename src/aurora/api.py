"""API HTTP do assistente (contrato do desafio). Suba com `uv run aurora-api`."""

from __future__ import annotations

import logging
import signal
import socket
import time
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


PORTA = 8000


def _socket_loopback(familia: socket.AddressFamily, endereco: str) -> socket.socket:
    s = socket.socket(familia, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if familia == socket.AF_INET6:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.bind((endereco, PORTA))
    s.set_inheritable(True)
    return s


class _Servidor(uvicorn.Server):
    """uvicorn.Server que ignora um Ctrl+C duplicado logo após o primeiro.

    O Ctrl+C entrega SIGINT ao grupo de processos (uv + python), e o sinal pode
    chegar duas vezes em poucos milissegundos. No uvicorn, um segundo SIGINT
    durante o encerramento força a saída e pula o shutdown do lifespan. Aqui, um
    SIGINT repetido dentro de JANELA segundos é ignorado; um segundo Ctrl+C
    intencional, depois disso, continua forçando a saída.
    """

    JANELA = 1.0
    _primeiro_sigint: float | None = None

    def handle_exit(self, sig: int, frame) -> None:
        if sig == signal.SIGINT:
            agora = time.monotonic()
            if self._primeiro_sigint is not None and agora - self._primeiro_sigint < self.JANELA:
                return
            if self._primeiro_sigint is None:
                self._primeiro_sigint = agora
        super().handle_exit(sig, frame)


def main() -> None:
    """Sobe a API em http://localhost:8000, escutando em 127.0.0.1 e em ::1.

    `localhost` pode resolver para IPv4 ou IPv6 conforme a máquina; com os dois
    sockets de loopback a API responde em ambos, sem se expor fora da máquina.
    """
    sockets = [_socket_loopback(socket.AF_INET, "127.0.0.1")]
    try:
        sockets.append(_socket_loopback(socket.AF_INET6, "::1"))
    except OSError as e:  # máquina sem IPv6: segue só com IPv4
        logging.getLogger("aurora.api").warning("IPv6 de loopback indisponível (%s); só 127.0.0.1", e)
    servidor = _Servidor(uvicorn.Config("aurora.api:app", port=PORTA, workers=1))
    try:
        servidor.run(sockets=sockets)
    except KeyboardInterrupt:  # Ctrl+C: encerramento normal (como em uvicorn.run)
        pass
    finally:
        for s in sockets:
            s.close()


if __name__ == "__main__":
    main()
