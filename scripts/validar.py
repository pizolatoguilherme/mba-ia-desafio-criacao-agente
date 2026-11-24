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


# --------------------------------------------------------------------------- #
# WP2 — camada de dados (banco temporário isolado, ver TMP_VAR)
# --------------------------------------------------------------------------- #

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402

TMP_VAR = Path(tempfile.mkdtemp(prefix="aurora-validar-"))
os.environ["AURORA_DB"] = str(TMP_VAR / "aurora.db")
os.environ["SESSOES_DB"] = str(TMP_VAR / "sessoes.db")


def _dados(nome: str) -> list[dict]:
    return json.loads((RAIZ / "dados" / nome).read_text(encoding="utf-8"))


@checagem("wp2", "aurora-restaurar num var/ vazio cria o banco com os dados iniciais")
def wp2_restaurar_vazio() -> None:
    (TMP_VAR / "sessoes.db").write_text("lixo")  # restauração deve apagar sessões
    sh("uv", "run", "aurora-restaurar")
    afirmar(not (TMP_VAR / "sessoes.db").exists(), "sessoes.db não foi apagado")
    from aurora import repositorio as rp

    for r in _dados("reservas.json"):
        ativas = rp.listar_reservas_ativas(r["apartamento"])
        afirmar({"codigo": r["codigo"], "area": r["area"], "data": r["data"]} in ativas,
                f"reserva inicial ausente: {r}")
    for v in _dados("visitantes.json"):
        afirmar({"nome": v["nome"], "data": v["data"]} in rp.listar_visitantes(v["apartamento"]),
                f"visitante inicial ausente: {v}")
    afirmar(rp.listar_reservas_ativas("101") == [{"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}],
            "101 deveria ter só RSV-1377")
    afirmar(len(rp.listar_areas()) == 3, "áreas não carregadas")


@checagem("wp2", "cancelar só a própria reserva, sem revelar reservas alheias")
def wp2_cancelar() -> None:
    from aurora import repositorio as rp

    r = rp.cancelar_reserva("101", area_id="salao-de-festas", data="2030-03-16")
    afirmar(r["status"] == "nao_encontrada", f"101 cancelou reserva alheia: {r}")
    afirmar("RSV-4821" not in json.dumps(r) and "302" not in json.dumps(r), f"vazou dado alheio: {r}")
    afirmar(any(x["codigo"] == "RSV-4821" for x in rp.listar_reservas_ativas("302")), "RSV-4821 sumiu")
    r = rp.cancelar_reserva("101", codigo="RSV-4821")
    afirmar(r["status"] == "nao_encontrada", f"101 cancelou RSV-4821 por código: {r}")
    r = rp.cancelar_reserva("101", area_id="quadra", data="2030-03-09")
    afirmar(r["status"] == "cancelada", f"não cancelou a própria: {r}")
    afirmar(rp.listar_reservas_ativas("101") == [], "RSV-1377 ainda ativa")


@checagem("wp2", "área ocupada só informa livre/ocupada; cancelada libera a data")
def wp2_disponibilidade() -> None:
    from aurora import repositorio as rp

    afirmar(rp.area_livre("salao-de-festas", "2030-03-16") is False, "data do 302 deveria estar ocupada")
    afirmar(rp.area_livre("quadra", "2030-03-09") is True, "data cancelada deveria estar livre")
    r = rp.criar_reserva("101", "quadra", "2030-03-09")
    afirmar(r["status"] == "reservado" and r["valor_cobranca"] is None, f"recriar após cancelar falhou: {r}")
    r2 = rp.criar_reserva("201", "salao-de-festas", "2030-03-16")
    afirmar(r2 == {"status": "indisponivel", "area": "salao-de-festas", "data": "2030-03-16"},
            f"reserva duplicada ou resposta com dado alheio: {r2}")
    r3 = rp.criar_reserva("101", "churrasqueira", "2030-06-01")
    afirmar(r3["valor_cobranca"] == 80.0, f"cobrança não registrada: {r3}")


@checagem("wp2", "20 gravações simultâneas na mesma área/data = exatamente 1 reserva, sem exceção")
def wp2_concorrencia() -> None:
    from aurora import db, repositorio as rp

    resultados: list = []
    erros: list = []
    barreira = threading.Barrier(20)

    def tentar(i: int) -> None:
        try:
            barreira.wait()
            resultados.append(rp.criar_reserva(str(100 + i), "salao-de-festas", "2030-05-11"))
        except Exception as e:  # noqa: BLE001
            erros.append(repr(e))

    ts = [threading.Thread(target=tentar, args=(i,)) for i in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    afirmar(not erros, f"exceções vazaram: {erros[:3]}")
    ok = [r for r in resultados if r["status"] == "reservado"]
    afirmar(len(ok) == 1, f"{len(ok)} reservas criadas")
    with db.leitura() as con:
        n = con.execute("SELECT COUNT(*) FROM reservas WHERE area='salao-de-festas' AND data='2030-05-11' "
                        "AND status='ativa'").fetchone()[0]
    afirmar(n == 1, f"{n} reservas ativas no banco")


@checagem("wp2", "códigos nunca repetem, nem após restaurar; reinício (init_db) não reseta nada")
def wp2_codigos_e_reinicio() -> None:
    from aurora import db, repositorio as rp

    with db.leitura() as con:
        emitidos = {r[0] for r in con.execute("SELECT codigo FROM codigos_reserva")}
    rp.autorizar_visitante("101", "Teste Reinicio", "2030-07-01")
    db.init_db()  # simula novo startup da API
    afirmar({"nome": "Teste Reinicio", "data": "2030-07-01"} in rp.listar_visitantes("101"),
            "init_db apagou dados gravados")
    sh("uv", "run", "aurora-restaurar")
    with db.leitura() as con:
        depois = {r[0] for r in con.execute("SELECT codigo FROM codigos_reserva")}
    afirmar(emitidos <= depois, "restauração apagou códigos emitidos")
    novos = {rp.criar_reserva("101", "churrasqueira", f"2031-01-{d:02d}")["codigo"] for d in range(1, 21)}
    afirmar(len(novos) == 20 and not (novos & emitidos), "código repetido")
    afirmar(rp.listar_reservas_ativas("101")[0]["codigo"] == "RSV-1377", "restauração não voltou RSV-1377")
    sh("uv", "run", "aurora-restaurar")


@checagem("wp2", "normalização de área e data")
def wp2_normalizacao() -> None:
    from aurora.normalizacao import normalizar_area, validar_data

    casos = {"Salão de festas": "salao-de-festas", "salao-de-festas": "salao-de-festas",
             "quadra": "quadra", "Quadra poliesportiva": "quadra", "churrasqueira": "churrasqueira",
             "piscina": None, "": None}
    for entrada, esperado in casos.items():
        afirmar(normalizar_area(entrada) == esperado, f"normalizar_area({entrada!r}) != {esperado}")
    afirmar(validar_data("2030-04-20") == "2030-04-20", "data válida rejeitada")
    afirmar(validar_data("20/04/2030") is None and validar_data("2030-02-30") is None, "data inválida aceita")


# --------------------------------------------------------------------------- #
# WP3 — regulamento
# --------------------------------------------------------------------------- #


def ancoras_de_outros_capitulos(exceto: int) -> list[str]:
    """Título e frases longas de cada capítulo diferente de `exceto` (detector da Garantia 4)."""
    from aurora import regulamento as rg

    ancoras = []
    for c in rg.capitulos():
        if c["numero"] == exceto:
            continue
        ancoras.append(c["titulo"])  # ex.: "Capítulo VIII: Animais de estimação"
        texto = rg.capitulo(c["numero"])
        frases = [f.strip(" *") for f in re.split(r"(?<=[.;:])\s+", texto) if len(f) > 80]
        ancoras += [f[:60] for f in frases[:: max(1, len(frases) // 4)]][:4]
    return ancoras


@checagem("wp3", "regulamento dividido em 14 capítulos, cobrindo o arquivo inteiro")
def wp3_parser() -> None:
    from aurora import regulamento as rg

    caps = rg.capitulos()
    afirmar([c["numero"] for c in caps] == list(range(1, 15)), f"numeração: {caps}")
    afirmar(caps[3]["titulo"] == "Capítulo IV: Piscina", f"cap IV: {caps[3]}")
    texto = (RAIZ / "dados" / "regulamento.md").read_text(encoding="utf-8")
    soma = sum(len(rg.capitulo(c["numero"])) for c in caps)
    afirmar(soma > len(texto) * 0.95, "capítulos não cobrem o arquivo")
    afirmar(rg.capitulo(99) is None, "capítulo inexistente devolveu texto")


@checagem("wp3", "ler_capitulo(4) traz o horário de domingo e nada de outros capítulos")
def wp3_capitulo_piscina() -> None:
    from aurora.tools.regulamento import ler_capitulo, listar_capitulos

    t = ler_capitulo(4)["texto"]
    afirmar("Aos domingos e feriados, a piscina funciona das 9h às 20h" in t, "horário ausente")
    vazou = [a for a in ancoras_de_outros_capitulos(4) if a in t]
    afirmar(not vazou, f"capítulo 4 contém trechos de outros: {vazou[:3]}")
    afirmar("erro" in ler_capitulo(0), "capítulo 0 aceito")
    afirmar(all("texto" not in c for c in listar_capitulos()["capitulos"]), "índice traz texto")


@checagem("wp3", "especialista de regulamento sozinho responde 20h (piscina, domingo)", requer="llm")
def wp3_especialista_llm() -> None:
    import asyncio

    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from aurora.agents.regulamento import especialista_regulamento

    async def rodar() -> str:
        runner = InMemoryRunner(agent=especialista_regulamento, app_name="validar")
        s = await runner.session_service.create_session(app_name="validar", user_id="u")
        texto = ""
        async for ev in runner.run_async(
            user_id="u", session_id=s.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Até que horas a piscina funciona aos domingos?")]),
        ):
            if ev.content and ev.content.parts:
                texto += "".join(p.text or "" for p in ev.content.parts if not p.thought)
        return texto

    resp = asyncio.run(rodar())
    afirmar(re.search(r"\b20\s?h", resp) is not None, f"resposta sem 20h: {resp!r}")


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
