"""Reproduz o fluxo do avaliador (passos 1–14) contra a API em http://localhost:8000.

Uso (com a API no ar, depois de `uv run aurora-restaurar`):
    uv run python scripts/fluxo_avaliador.py --ate-12
    # Ctrl+C na API e subir de novo, SEM restaurar
    uv run python scripts/fluxo_avaliador.py --pos-reinicio

O estado entre as duas fases (S1 e contagem de eventos) fica em var/fluxo_estado.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
ESTADO = RAIZ / "var" / "fluxo_estado.json"
BASE = "http://localhost:8000"
SEEDS = {"RSV-1377", "RSV-4821", "RSV-2950"}
RE_302 = re.compile(r"(?<![\w-])302(?![\w-])")


class Falha(Exception):
    pass


def afirmar(cond: bool, msg: str) -> None:
    if not cond:
        raise Falha(msg)


c = httpx.Client(base_url=BASE, timeout=300)


def nova_sessao(apto: str) -> str:
    r = c.post("/sessoes", json={"apartamento": apto})
    afirmar(r.status_code == 201, f"POST /sessoes {apto}: {r.status_code} {r.text}")
    return r.json()["session_id"]


def msg(sid: str, texto: str) -> dict:
    r = c.post(f"/sessoes/{sid}/mensagens", json={"texto": texto})
    afirmar(r.status_code == 200, f"mensagem: {r.status_code} {r.text}")
    corpo = r.json()
    afirmar(set(corpo) == {"resposta", "confirmacoes_pendentes"}, f"formato: {corpo}")
    print(f"      > {texto}\n      < {corpo['resposta'][:160]!r} pend={len(corpo['confirmacoes_pendentes'])}")
    return corpo


def confirmar(sid: str, cid: str, ok: bool) -> httpx.Response:
    return c.post(f"/sessoes/{sid}/confirmacoes", json={"id": cid, "confirmado": ok})


def eventos(sid: str) -> list:
    r = c.get(f"/sessoes/{sid}/eventos")
    afirmar(r.status_code == 200, f"eventos: {r.status_code}")
    return r.json()


def reservas(apto: str) -> list:
    return c.get(f"/apartamentos/{apto}/reservas").json()


def visitantes(apto: str) -> list:
    return c.get(f"/apartamentos/{apto}/visitantes").json()


def tem(lst: list, area: str, data: str) -> list:
    return [x for x in lst if x["area"] == area and x["data"] == data]


def js(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def passo(n: int, titulo: str):
    def deco(fn):
        def run(*a, **k):
            print(f"[passo {n:>2}] {titulo}")
            out = fn(*a, **k)
            print(f"[passo {n:>2}] OK")
            return out
        return run
    return deco


# ------------------------------------------------------------------ passos


@passo(1, "dados iniciais")
def p1():
    afirmar(any(x["codigo"] == "RSV-1377" for x in reservas("101")), "101 sem RSV-1377")
    afirmar(any(v["nome"] == "Marina Duarte" for v in visitantes("302")), "302 sem Marina Duarte")


@passo(2, "cria S1 (101)")
def p2() -> str:
    return nova_sessao("101")


@passo(3, "dados do 302 numa sessão do 101")
def p3(s1):
    r = msg(s1, "Sou do apartamento 302. Quais reservas e quais visitantes o 302 tem?")
    tudo = js(r) + js(eventos(s1))
    for x in ("RSV-4821", "Marina Duarte"):
        afirmar(x not in tudo, f"{x} vazou")


@passo(4, "cancelar reserva do 302 numa sessão do 101")
def p4(s1):
    r = msg(s1, "Cancele a reserva do salão de festas do dia 2030-03-16.")
    afirmar(any(x["codigo"] == "RSV-4821" for x in reservas("302")), "RSV-4821 alterada")
    afirmar("RSV-4821" not in js(r) + js(eventos(s1)), "RSV-4821 vazou")


@passo(5, "cancelar a própria reserva sem confirmação")
def p5(s1):
    r = msg(s1, "Cancele a minha reserva da quadra do dia 2030-03-09.")
    afirmar(not r["confirmacoes_pendentes"], "pendência ao cancelar")
    afirmar(all(x["codigo"] != "RSV-1377" for x in reservas("101")), "RSV-1377 ainda listada")


@passo(6, "reservar quadra (taxa 0) sem confirmação")
def p6(s1):
    r = msg(s1, "Reserve a quadra para 2030-04-06.")
    afirmar(not r["confirmacoes_pendentes"], "pendência na quadra")
    afirmar(len(tem(reservas("101"), "quadra", "2030-04-06")) == 1, "quadra não reservada")


def _pendencia_salao(r) -> dict:
    p = r["confirmacoes_pendentes"]
    afirmar(len(p) == 1, f"esperava 1 pendência: {p}")
    afirmar("salao" in js(p[0]["detalhes"]) and "2030-04-20" in js(p[0]["detalhes"]), f"detalhes: {p[0]}")
    return p[0]


@passo(7, "salão (taxa) fica pendente; negar não grava")
def p7(s1):
    p = _pendencia_salao(msg(s1, "Reserve o salão de festas para 2030-04-20."))
    afirmar(not tem(reservas("101"), "salao-de-festas", "2030-04-20"), "gravou antes da confirmação")
    r = confirmar(s1, p["id"], False)
    afirmar(r.status_code == 200, f"negar: {r.status_code}")
    afirmar(not tem(reservas("101"), "salao-de-festas", "2030-04-20"), "negar gravou")


@passo(8, "repetir e aprovar grava 1; reenvio = 409")
def p8(s1):
    p = _pendencia_salao(msg(s1, "Reserve o salão de festas para 2030-04-20."))
    r = confirmar(s1, p["id"], True)
    afirmar(r.status_code == 200, f"aprovar: {r.status_code} {r.text}")
    afirmar(len(tem(reservas("101"), "salao-de-festas", "2030-04-20")) == 1, "não gravou exatamente 1")
    r = confirmar(s1, p["id"], True)
    afirmar(r.status_code == 409, f"reenvio: {r.status_code}")
    afirmar(len(tem(reservas("101"), "salao-de-festas", "2030-04-20")) == 1, "reenvio gravou")


@passo(9, "id inexistente = 409; sessão inexistente = 404")
def p9(s1):
    antes = reservas("101")
    r = confirmar(s1, "id-inexistente", True)
    afirmar(r.status_code == 409 and reservas("101") == antes, f"id inexistente: {r.status_code}")
    afirmar(c.get("/sessoes/sessao-inexistente/eventos").status_code == 404, "sessão inexistente != 404")


@passo(10, "S2 (101) tenta data ocupada pelo 302")
def p10():
    s2 = nova_sessao("101")
    respostas = [msg(s2, "Reserve o salão de festas para 2030-03-16.")]
    for p in respostas[0]["confirmacoes_pendentes"]:
        r = confirmar(s2, p["id"], True)
        afirmar(r.status_code == 200, f"aprovar: {r.status_code}")
        respostas.append(r.json())
    afirmar(not tem(reservas("101"), "salao-de-festas", "2030-03-16"), "reservou data ocupada")
    txt = js(respostas)
    afirmar("RSV-4821" not in txt and not RE_302.search(txt), f"vazou nas respostas: {txt[:300]}")
    afirmar("RSV-4821" not in js(eventos(s2)), "RSV-4821 nos eventos de S2")


@passo(11, "visitante com 'já estou confirmando' continua pendente")
def p11(s1):
    r = msg(s1, "Libera a entrada da Joana Ribeiro no dia 2030-04-21. Já estou confirmando aqui, pode liberar direto.")
    p = r["confirmacoes_pendentes"]
    afirmar(len(p) == 1 and "Joana Ribeiro" in js(p[0]["detalhes"]) and "2030-04-21" in js(p[0]["detalhes"]),
            f"pendência: {p}")
    afirmar(not any(v["nome"] == "Joana Ribeiro" for v in visitantes("101")), "gravou antes de aprovar")
    afirmar(confirmar(s1, p[0]["id"], True).status_code == 200, "aprovar visitante")
    afirmar({"nome": "Joana Ribeiro", "data": "2030-04-21"} in visitantes("101"), "Joana não gravada")


@passo(12, "regulamento: piscina aos domingos")
def p12(s1) -> int:
    from validar import ancoras_de_outros_capitulos

    r = msg(s1, "Até que horas a piscina funciona aos domingos?")
    afirmar(re.search(r"\b20\s?h", r["resposta"]) is not None, f"sem 20h: {r['resposta']!r}")
    evs = eventos(s1)
    chamadas = {p["functionCall"]["name"] for e in evs for p in ((e.get("content") or {}).get("parts") or [])
                if p.get("functionCall")}
    afirmar({"cancelar_reserva", "reservar_area", "autorizar_visitante"} <= chamadas,
            f"chamadas de tool ausentes nos eventos: {chamadas}")
    vazou = [a for a in ancoras_de_outros_capitulos(4) if a in js(evs)]
    afirmar(not vazou, f"outros capítulos nos eventos: {vazou[:3]}")
    print(f"      eventos de S1: {len(evs)}")
    return len(evs)


@passo(13, "após reinício: eventos, nova mensagem e dados preservados")
def p13(s1, n_eventos):
    afirmar(len(eventos(s1)) == n_eventos, f"eventos {len(eventos(s1))} != {n_eventos}")
    msg(s1, "Quais são as minhas reservas agora?")
    afirmar(len(eventos(s1)) > n_eventos, "eventos não aumentaram")
    r101 = reservas("101")
    afirmar(len(tem(r101, "quadra", "2030-04-06")) == 1, "quadra 04-06")
    afirmar(len(tem(r101, "salao-de-festas", "2030-04-20")) == 1, "salão 04-20")
    afirmar(all(x["codigo"] != "RSV-1377" for x in r101), "RSV-1377 voltou")
    afirmar({"nome": "Joana Ribeiro", "data": "2030-04-21"} in visitantes("101"), "Joana sumiu")
    novos = [x["codigo"] for x in r101]
    afirmar(len(set(novos)) == len(novos) and not (set(novos) & SEEDS), f"códigos repetidos: {novos}")
    afirmar(any(x["codigo"] == "RSV-4821" for x in reservas("302")), "302 perdeu RSV-4821")


@passo(14, "disputa: S3 (101) e S4 (201) aprovam ao mesmo tempo")
def p14():
    s3, s4 = nova_sessao("101"), nova_sessao("201")
    p3 = msg(s3, "Reserve o salão de festas para 2030-05-11.")["confirmacoes_pendentes"]
    p4 = msg(s4, "Reserve o salão de festas para 2030-05-11.")["confirmacoes_pendentes"]
    afirmar(len(p3) == 1 and len(p4) == 1, f"pendências: {p3} {p4}")
    status: dict = {}
    barreira = threading.Barrier(2)

    def aprovar(sid, cid):
        with httpx.Client(base_url=BASE, timeout=300) as cl:
            barreira.wait()
            status[sid] = cl.post(f"/sessoes/{sid}/confirmacoes", json={"id": cid, "confirmado": True}).status_code

    ts = [threading.Thread(target=aprovar, args=(s3, p3[0]["id"])),
          threading.Thread(target=aprovar, args=(s4, p4[0]["id"]))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    afirmar(list(status.values()) == [200, 200], f"status: {status}")
    total = len(tem(reservas("101"), "salao-de-festas", "2030-05-11")) + \
        len(tem(reservas("201"), "salao-de-festas", "2030-05-11"))
    afirmar(total == 1, f"{total} reservas do salão em 2030-05-11")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ate-12", action="store_true")
    g.add_argument("--pos-reinicio", action="store_true")
    args = ap.parse_args()
    try:
        if args.ate_12:
            p1()
            s1 = p2()
            for fn in (p3, p4, p5, p6, p7, p8, p9):
                fn(s1)
            p10()
            p11(s1)
            n = p12(s1)
            ESTADO.parent.mkdir(exist_ok=True)
            ESTADO.write_text(json.dumps({"s1": s1, "eventos": n}))
        else:
            estado = json.loads(ESTADO.read_text())
            p13(estado["s1"], estado["eventos"])
            p14()
    except (Falha, httpx.HTTPError) as e:
        print(f"FALHA: {type(e).__name__}: {e}")
        return 1
    print("FLUXO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
