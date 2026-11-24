"""Comando de restauração: `uv run aurora-restaurar` (rode com a API parada).

Volta reservas e visitantes ao estado de dados/*.json e apaga as sessões,
para que cada avaliação comece limpa. Os códigos de reserva já emitidos
continuam registrados e nunca são reemitidos.
"""

from __future__ import annotations

from . import config, db


def main() -> None:
    db.restaurar_dados()
    for sufixo in ("", "-wal", "-shm", "-journal"):
        arq = config.SESSOES_DB.with_name(config.SESSOES_DB.name + sufixo)
        arq.unlink(missing_ok=True)
    print(f"Dados restaurados a partir de {config.DADOS_DIR} e sessões apagadas.")


if __name__ == "__main__":
    main()
