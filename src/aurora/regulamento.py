"""Leitura do regulamento por capítulo.

O texto nunca é carregado inteiro em instrução de agente: o especialista de
regulamento pede a lista de títulos e lê um capítulo por vez (Garantia 4).
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import config

_ROMANOS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_CABECALHO = re.compile(r"^## Capítulo ([IVXLC]+):\s*(.+)$", re.MULTILINE)


def _romano_para_int(romano: str) -> int:
    total = 0
    for atual, prox in zip(romano, romano[1:] + " "):
        v = _ROMANOS[atual]
        total += -v if prox != " " and _ROMANOS[prox] > v else v
    return total


@lru_cache(maxsize=1)
def _capitulos() -> tuple[dict, ...]:
    texto = (config.DADOS_DIR / "regulamento.md").read_text(encoding="utf-8")
    marcas = list(_CABECALHO.finditer(texto))
    caps = []
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        caps.append({
            "numero": _romano_para_int(m.group(1)),
            "titulo": f"Capítulo {m.group(1)}: {m.group(2).strip()}",
            "texto": texto[m.start():fim].strip(),
        })
    return tuple(caps)


def capitulos() -> list[dict]:
    """Só número e título de cada capítulo."""
    return [{"numero": c["numero"], "titulo": c["titulo"]} for c in _capitulos()]


def capitulo(numero: int) -> str | None:
    """Texto integral de UM capítulo, ou None se não existir."""
    for c in _capitulos():
        if c["numero"] == numero:
            return c["texto"]
    return None
