"""Banco do domínio (SQLite): schema, conexão e carga dos dados iniciais.

A exclusividade de reserva (Garantia 5) mora no índice único parcial
``ux_reserva_ativa``: o próprio SQLite recusa, no instante do INSERT, uma
segunda reserva ativa para a mesma área na mesma data.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL
);

-- Todo código de reserva já emitido. A restauração não apaga esta tabela,
-- então um código nunca é reemitido, nem o de reserva cancelada (regra 5).
CREATE TABLE IF NOT EXISTS codigos_reserva (
    codigo TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS reservas (
    codigo         TEXT PRIMARY KEY REFERENCES codigos_reserva(codigo),
    apartamento    TEXT NOT NULL,
    area           TEXT NOT NULL REFERENCES areas(id),
    data           TEXT NOT NULL,
    valor_cobranca REAL,               -- preenchido quando a taxa > 0 (regra 2)
    status         TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada')),
    criada_em      TEXT NOT NULL,
    cancelada_em   TEXT
);

-- GARANTIA 5: no máximo uma reserva ATIVA por área e data, garantida na gravação.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa
    ON reservas (area, data) WHERE status = 'ativa';

CREATE INDEX IF NOT EXISTS ix_reservas_apartamento ON reservas (apartamento);

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL,
    criado_em   TEXT NOT NULL,
    UNIQUE (apartamento, nome, data)
);

-- Dono de cada sessão: o apartamento é fixado aqui na criação (Garantia 2).
CREATE TABLE IF NOT EXISTS sessoes (
    session_id  TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    criada_em   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    config.garantir_var()
    con = sqlite3.connect(config.AURORA_DB, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    return con


@contextmanager
def leitura() -> Iterator[sqlite3.Connection]:
    con = conectar()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transacao() -> Iterator[sqlite3.Connection]:
    """Transação de escrita com trava imediata (BEGIN IMMEDIATE)."""
    con = conectar()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        else:
            con.execute("COMMIT")
    finally:
        con.close()


def _ler_json(nome: str) -> list[dict]:
    return json.loads((config.DADOS_DIR / nome).read_text(encoding="utf-8"))


def _carregar_cadastros(con: sqlite3.Connection) -> None:
    for apto in _ler_json("apartamentos.json"):
        con.execute(
            "INSERT INTO apartamentos (numero, morador) VALUES (?, ?) "
            "ON CONFLICT(numero) DO UPDATE SET morador = excluded.morador",
            (apto["numero"], apto["morador"]),
        )
    for area in _ler_json("areas.json"):
        con.execute(
            "INSERT INTO areas (id, nome, taxa) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, taxa = excluded.taxa",
            (area["id"], area["nome"], float(area["taxa"])),
        )


def _carregar_movimento(con: sqlite3.Connection) -> None:
    """Recria reservas e visitantes a partir de dados/*.json."""
    con.execute("DELETE FROM reservas")
    con.execute("DELETE FROM visitantes")
    taxas = {r["id"]: r["taxa"] for r in con.execute("SELECT id, taxa FROM areas")}
    ts = agora()
    for r in _ler_json("reservas.json"):
        con.execute("INSERT OR IGNORE INTO codigos_reserva (codigo) VALUES (?)", (r["codigo"],))
        taxa = taxas.get(r["area"], 0)
        con.execute(
            "INSERT INTO reservas (codigo, apartamento, area, data, valor_cobranca, status, criada_em) "
            "VALUES (?, ?, ?, ?, ?, 'ativa', ?)",
            (r["codigo"], r["apartamento"], r["area"], r["data"], taxa if taxa > 0 else None, ts),
        )
    for v in _ler_json("visitantes.json"):
        con.execute(
            "INSERT OR IGNORE INTO visitantes (apartamento, nome, data, criado_em) VALUES (?, ?, ?, ?)",
            (v["apartamento"], v["nome"], v["data"], ts),
        )


def _criar_schema() -> None:
    # executescript faz COMMIT implícito, por isso fica fora de transacao().
    con = conectar()
    try:
        con.executescript(SCHEMA)
    finally:
        con.close()


def init_db() -> None:
    """Cria o schema e aplica os dados iniciais só na primeira vez.

    Chamado no startup da API: reiniciar nunca reseta reservas nem visitantes.
    """
    _criar_schema()
    with transacao() as con:
        ja = con.execute("SELECT 1 FROM meta WHERE chave = 'seed_aplicado'").fetchone()
        if ja:
            return
        _carregar_cadastros(con)
        _carregar_movimento(con)
        con.execute("INSERT INTO meta (chave, valor) VALUES ('seed_aplicado', ?)", (agora(),))


def restaurar_dados() -> None:
    """Volta reservas e visitantes ao estado de dados/*.json e esquece as sessões."""
    _criar_schema()
    with transacao() as con:
        _carregar_cadastros(con)
        _carregar_movimento(con)
        con.execute("DELETE FROM sessoes")
        con.execute(
            "INSERT INTO meta (chave, valor) VALUES ('seed_aplicado', ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (agora(),),
        )
