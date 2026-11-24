"""Portões de validação cumulativos por etapa (WP).

Uso:
    uv run python scripts/validar.py --ate wp3
    uv run python scripts/validar.py --ate wp5 --api   # inclui checagens contra a API no ar
    uv run python scripts/validar.py --ate wp4 --llm   # inclui checagens que chamam o modelo

Roda, em ordem, as checagens de WP0 até o WP pedido e termina com código != 0
na primeira falha. Cada WP acrescenta as suas checagens aqui, de modo que a
regressão das etapas anteriores é automática.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src" / "aurora"

Checagem = Callable[[], None]
CHECAGENS: dict[str, list[tuple[str, Checagem, str]]] = {}
# terceiro item: "" (sempre), "llm" (precisa de --llm) ou "api" (precisa de --api)


def checagem(wp: str, nome: str, requer: str = ""):
    def deco(fn: Checagem) -> Checagem:
        CHECAGENS.setdefault(wp, []).append((nome, fn, requer))
        return fn

    return deco


class Falha(Exception):
    pass


def afirmar(cond: bool, msg: str) -> None:
    if not cond:
        raise Falha(msg)


def sh(*cmd: str, ok: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)
    if ok and r.returncode != 0:
        raise Falha(f"{' '.join(cmd)} falhou: {r.stderr.strip() or r.stdout.strip()}")
    return r


# --------------------------------------------------------------------------- #
# Invariantes globais (rodam em todo portão)
# --------------------------------------------------------------------------- #


@checagem("inv", "dados/ idêntico ao repositório base (upstream/main)")
def inv_dados() -> None:
    r = sh("git", "diff", "--exit-code", "upstream/main", "--", "dados/", ok=False)
    afirmar(r.returncode == 0, f"dados/ difere do upstream:\n{r.stdout[:500]}")
    r = sh("git", "status", "--porcelain", "--", "dados/")
    afirmar(r.stdout.strip() == "", f"dados/ com mudanças locais: {r.stdout}")


@checagem("inv", ".env não versionado e sem chaves no repositório")
def inv_segredos() -> None:
    rastreados = sh("git", "ls-files").stdout.split()
    afirmar(".env" not in rastreados, ".env está versionado")
    r = sh("git", "check-ignore", ".env", ok=False)
    afirmar(r.returncode == 0, ".env não está no .gitignore")
    r = sh("git", "grep", "-nE", r"AIza[0-9A-Za-z_-]{20,}", ok=False)
    afirmar(r.stdout.strip() == "", f"possível chave versionada:\n{r.stdout}")
    exemplo = (RAIZ / ".env.example").read_text().splitlines()
    for linha in exemplo:
        if linha.strip() and not linha.startswith("#"):
            nome, _, valor = linha.partition("=")
            afirmar(valor.strip() == "", f".env.example com valor em {nome}")


@checagem("inv", "google-adk fixado na versão exata 2.9.1")
def inv_adk() -> None:
    proj = tomllib.loads((RAIZ / "pyproject.toml").read_text())
    deps = proj["project"]["dependencies"]
    afirmar("google-adk==2.9.1" in deps, f"google-adk não fixado: {deps}")
    lock = (RAIZ / "uv.lock").read_text()
    afirmar(re.search(r'name = "google-adk"\nversion = "2\.9\.1"', lock) is not None,
            "uv.lock sem google-adk 2.9.1")


@checagem("inv", "nenhuma tool recebe parâmetro 'apartamento'")
def inv_tools_sem_apartamento() -> None:
    pasta = SRC / "tools"
    if not pasta.exists():
        return
    for arq in pasta.glob("*.py"):
        arvore = ast.parse(arq.read_text())
        for no in ast.walk(arvore):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and not no.name.startswith("_"):
                nomes = [a.arg for a in no.args.args + no.args.kwonlyargs]
                afirmar(not any("apart" in n or n in {"apto", "unidade"} for n in nomes),
                        f"{arq.name}:{no.name} recebe apartamento: {nomes}")


@checagem("inv", "coordenador sem o regulamento nas instruções")
def inv_coordenador_sem_regulamento() -> None:
    arq = SRC / "agents" / "coordenador.py"
    if not arq.exists():
        return
    texto = arq.read_text()
    afirmar("regulamento.md" not in texto, "coordenador referencia regulamento.md")
    afirmar("read_text" not in texto and "open(" not in texto, "coordenador lê arquivo")
    afirmar("Capítulo" not in texto and "Art. " not in texto, "coordenador contém trecho do regulamento")


# --------------------------------------------------------------------------- #
# WP0 — projeto
# --------------------------------------------------------------------------- #


@checagem("wp0", "uv sync sem erro")
def wp0_sync() -> None:
    sh("uv", "sync")


@checagem("wp0", "importa google.adk, fastapi e aurora.config; versão do ADK = 2.9.1")
def wp0_imports() -> None:
    r = sh("uv", "run", "python", "-c",
           "import google.adk, fastapi, aurora.config as c; print(google.adk.__version__); print(c.RAIZ)")
    versao, raiz = r.stdout.split()
    afirmar(versao == "2.9.1", f"ADK instalado = {versao}")
    afirmar(Path(raiz) == RAIZ, f"RAIZ calculada errada: {raiz}")


@checagem("wp0", "Python 3.12+ e arquivos do projeto versionáveis")
def wp0_arquivos() -> None:
    afirmar((RAIZ / ".python-version").read_text().strip() >= "3.12", ".python-version < 3.12")
    for f in ["pyproject.toml", "uv.lock", ".env.example", ".gitignore"]:
        afirmar((RAIZ / f).exists(), f"{f} ausente")
        r = sh("git", "check-ignore", f, ok=False)
        afirmar(r.returncode != 0, f"{f} está ignorado pelo git")
    afirmar(sh("git", "check-ignore", "var/x", ok=False).returncode == 0, "var/ não ignorado")


ORDEM = ["wp0", "wp1", "wp2", "wp3", "wp4", "wp5", "wp6", "wp7", "wp8"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ate", default="wp8", choices=ORDEM)
    ap.add_argument("--llm", action="store_true", help="inclui checagens que chamam o modelo")
    ap.add_argument("--api", action="store_true", help="inclui checagens contra a API no ar")
    args = ap.parse_args()

    etapas = ["inv"] + ORDEM[: ORDEM.index(args.ate) + 1]
    total = puladas = 0
    for wp in etapas:
        for nome, fn, requer in CHECAGENS.get(wp, []):
            if (requer == "llm" and not args.llm) or (requer == "api" and not args.api):
                print(f"[{wp}] PULADA ({requer}) {nome}")
                puladas += 1
                continue
            try:
                fn()
            except Falha as e:
                print(f"[{wp}] FALHA {nome}\n      {e}")
                return 1
            print(f"[{wp}] OK    {nome}")
            total += 1
    print(f"\n{total} checagens OK, {puladas} puladas, etapas: {', '.join(etapas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
