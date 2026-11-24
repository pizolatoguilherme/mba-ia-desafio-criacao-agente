"""Configuração central: variáveis de ambiente e caminhos do projeto."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

# Chave do Google AI Studio (não Vertex AI).
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

MODELO_PADRAO = "gemini-3.8-flash"
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or MODELO_PADRAO

APP_NAME = "aurora"

DADOS_DIR = RAIZ / "dados"
VAR_DIR = RAIZ / "var"
AURORA_DB = Path(os.getenv("AURORA_DB") or VAR_DIR / "aurora.db")
SESSOES_DB = Path(os.getenv("SESSOES_DB") or VAR_DIR / "sessoes.db")


def garantir_var() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    AURORA_DB.parent.mkdir(parents=True, exist_ok=True)
    SESSOES_DB.parent.mkdir(parents=True, exist_ok=True)


def sessoes_db_url() -> str:
    return f"sqlite+aiosqlite:///{SESSOES_DB}"
