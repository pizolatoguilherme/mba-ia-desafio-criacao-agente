"""Normalização de entradas vindas do modelo (área e data)."""

from __future__ import annotations

import unicodedata
from datetime import date

from . import repositorio


def _simplificar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "-".join(sem_acento.lower().replace("_", " ").replace("-", " ").split())


def normalizar_area(valor: str) -> str | None:
    """Aceita id ('salao-de-festas') ou nome ('Salão de festas'). Devolve o id ou None."""
    alvo = _simplificar(valor or "")
    if not alvo:
        return None
    areas = repositorio.listar_areas()
    for a in areas:
        if alvo in (a["id"], _simplificar(a["nome"])):
            return a["id"]
    # nome parcial, ex.: "salão" ou "quadra poliesportiva"
    candidatas = [a["id"] for a in areas if alvo in a["id"] or a["id"] in alvo
                  or alvo in _simplificar(a["nome"])]
    return candidatas[0] if len(candidatas) == 1 else None


def validar_data(valor: str) -> str | None:
    """Aceita apenas AAAA-MM-DD válido. Devolve a data normalizada ou None."""
    try:
        return date.fromisoformat((valor or "").strip()).isoformat()
    except ValueError:
        return None
