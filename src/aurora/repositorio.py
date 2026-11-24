"""Operações do domínio. Única camada que executa SQL.

Toda função que lê ou altera dados de um apartamento recebe o apartamento do
chamador, que sempre o obtém da sessão (``aurora.sessao``), nunca do modelo.
Nenhuma função devolve dados de outro apartamento: checar disponibilidade
responde apenas se a data está livre.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from . import db

MAX_TENTATIVAS_CODIGO = 20


# --------------------------------------------------------------------------- #
# Cadastros
# --------------------------------------------------------------------------- #


def listar_areas() -> list[dict[str, Any]]:
    with db.leitura() as con:
        linhas = con.execute("SELECT id, nome, taxa FROM areas ORDER BY nome").fetchall()
    return [
        {"id": r["id"], "nome": r["nome"], "taxa": r["taxa"], "gera_cobranca": r["taxa"] > 0}
        for r in linhas
    ]


def area(area_id: str) -> dict[str, Any] | None:
    with db.leitura() as con:
        r = con.execute("SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)).fetchone()
    return dict(r) if r else None


def apartamento_existe(numero: str) -> bool:
    with db.leitura() as con:
        return con.execute("SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)).fetchone() is not None


# --------------------------------------------------------------------------- #
# Sessões (dono de cada sessão)
# --------------------------------------------------------------------------- #


def registrar_sessao(session_id: str, apartamento: str) -> None:
    with db.transacao() as con:
        con.execute(
            "INSERT INTO sessoes (session_id, apartamento, criada_em) VALUES (?, ?, ?)",
            (session_id, apartamento, db.agora()),
        )


def apartamento_da_sessao(session_id: str) -> str | None:
    with db.leitura() as con:
        r = con.execute("SELECT apartamento FROM sessoes WHERE session_id = ?", (session_id,)).fetchone()
    return r["apartamento"] if r else None


# --------------------------------------------------------------------------- #
# Reservas
# --------------------------------------------------------------------------- #


def listar_reservas_ativas(apartamento: str) -> list[dict[str, str]]:
    with db.leitura() as con:
        linhas = con.execute(
            "SELECT codigo, area, data FROM reservas "
            "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (apartamento,),
        ).fetchall()
    return [{"codigo": r["codigo"], "area": r["area"], "data": r["data"]} for r in linhas]


def area_livre(area_id: str, data: str) -> bool:
    """Só diz se a data está livre. Nunca devolve dono nem código."""
    with db.leitura() as con:
        r = con.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area_id, data),
        ).fetchone()
    return r is None


def _ja_executada(con: sqlite3.Connection, chave: str | None) -> dict[str, Any] | None:
    if not chave:
        return None
    r = con.execute("SELECT resultado FROM acoes_executadas WHERE chave = ?", (chave,)).fetchone()
    return json.loads(r["resultado"]) if r else None


def _registrar_execucao(con: sqlite3.Connection, chave: str | None, resultado: dict[str, Any]) -> None:
    if chave:
        con.execute(
            "INSERT INTO acoes_executadas (chave, resultado, executada_em) VALUES (?, ?, ?)",
            (chave, json.dumps(resultado, ensure_ascii=False), db.agora()),
        )


def _novo_codigo() -> str:
    return f"RSV-{uuid.uuid4().hex[:6].upper()}"


def criar_reserva(
    apartamento: str, area_id: str, data: str, *, chave_idempotencia: str | None = None
) -> dict[str, Any]:
    """Grava a reserva. A exclusividade vale no INSERT (índice ux_reserva_ativa).

    Não depende de conferência prévia: se outra reserva ativa para a mesma área
    e data entrar antes, o SQLite recusa este INSERT e a função devolve
    ``indisponivel`` como resposta normal. Com ``chave_idempotencia`` (id da
    chamada de tool aprovada), uma reexecução devolve o resultado já gravado.
    """
    info = area(area_id)
    if info is None:
        return {"status": "area_invalida"}
    valor = info["taxa"] if info["taxa"] > 0 else None
    for _ in range(MAX_TENTATIVAS_CODIGO):
        codigo = _novo_codigo()
        try:
            with db.transacao() as con:
                if (anterior := _ja_executada(con, chave_idempotencia)) is not None:
                    return anterior
                # PK de codigos_reserva: código nunca repete, nem de reserva cancelada.
                con.execute("INSERT INTO codigos_reserva (codigo) VALUES (?)", (codigo,))
                con.execute(
                    "INSERT INTO reservas (codigo, apartamento, area, data, valor_cobranca, status, criada_em) "
                    "VALUES (?, ?, ?, ?, ?, 'ativa', ?)",
                    (codigo, apartamento, area_id, data, valor, db.agora()),
                )
                resultado = {
                    "status": "reservado",
                    "codigo": codigo,
                    "area": area_id,
                    "data": data,
                    "valor_cobranca": valor,
                }
                _registrar_execucao(con, chave_idempotencia, resultado)
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "codigos_reserva.codigo" in msg:
                continue  # colisão de código: gera outro
            if "reservas.area" in msg or "reservas.data" in msg:
                return {"status": "indisponivel", "area": area_id, "data": data}
            raise
        return resultado
    raise RuntimeError("não foi possível gerar um código de reserva único")


def cancelar_reserva(
    apartamento: str, *, codigo: str = "", area_id: str = "", data: str = ""
) -> dict[str, Any]:
    """Cancela reserva ativa DO PRÓPRIO apartamento. Nunca revela reservas alheias."""
    if codigo:
        filtro, params = "codigo = ?", (codigo,)
    elif area_id and data:
        filtro, params = "area = ? AND data = ?", (area_id, data)
    else:
        return {"status": "dados_insuficientes", "mensagem": "Informe a área e a data, ou o código."}
    with db.transacao() as con:
        alvo = con.execute(
            f"SELECT codigo, area, data FROM reservas "
            f"WHERE apartamento = ? AND status = 'ativa' AND {filtro}",
            (apartamento, *params),
        ).fetchone()
        if alvo is None:
            return {
                "status": "nao_encontrada",
                "mensagem": "Não há reserva ativa do seu apartamento com esses dados.",
            }
        con.execute(
            "UPDATE reservas SET status = 'cancelada', cancelada_em = ? WHERE codigo = ?",
            (db.agora(), alvo["codigo"]),
        )
    return {"status": "cancelada", "codigo": alvo["codigo"], "area": alvo["area"], "data": alvo["data"]}


# --------------------------------------------------------------------------- #
# Visitantes
# --------------------------------------------------------------------------- #


def listar_visitantes(apartamento: str) -> list[dict[str, str]]:
    with db.leitura() as con:
        linhas = con.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, nome",
            (apartamento,),
        ).fetchall()
    return [{"nome": r["nome"], "data": r["data"]} for r in linhas]


def autorizar_visitante(
    apartamento: str, nome: str, data: str, *, chave_idempotencia: str | None = None
) -> dict[str, Any]:
    with db.transacao() as con:
        if (anterior := _ja_executada(con, chave_idempotencia)) is not None:
            return anterior
        con.execute(
            "INSERT OR IGNORE INTO visitantes (apartamento, nome, data, criado_em) VALUES (?, ?, ?, ?)",
            (apartamento, nome, data, db.agora()),
        )
        resultado = {"status": "autorizado", "nome": nome, "data": data}
        _registrar_execucao(con, chave_idempotencia, resultado)
    return resultado
