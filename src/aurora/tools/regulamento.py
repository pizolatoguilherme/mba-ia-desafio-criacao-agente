"""Tools do especialista de regulamento: índice de capítulos e leitura de um capítulo."""

from __future__ import annotations

from .. import regulamento


def listar_capitulos() -> dict:
    """Lista o número e o título de cada capítulo do regulamento interno.

    Use primeiro para descobrir qual capítulo trata do assunto perguntado.
    """
    return {"capitulos": regulamento.capitulos()}


def ler_capitulo(numero: int) -> dict:
    """Lê o texto de UM capítulo do regulamento interno.

    Args:
        numero: número do capítulo (1 a 14), obtido em listar_capitulos.
    """
    texto = regulamento.capitulo(int(numero))
    if texto is None:
        return {"erro": "Capítulo inexistente. Use listar_capitulos para ver os números válidos."}
    return {"numero": int(numero), "texto": texto}
