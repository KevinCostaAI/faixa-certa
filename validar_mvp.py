"""Coleta técnica reproduzível. Não produz rótulos humanos nem respostas de participantes.

Execute: python validar_mvp.py --coletar
O arquivo gerado aparece na página ?avaliar=1 quando publicado junto com o app.
"""

import argparse
import hashlib
import json
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import app


BUSCAS = [
    "galaxy a07 128gb", "galaxi a17 128gb", "galaxy a16 128gb", "galaxy a36 5g 128gb",
    "galaxy a14 128gb usado", "motorolla g06 128gb", "moto g17 256gb", "moto g35 256gb",
    "moto g47 128gb", "moto e15 64gb", "xiaome redmi 15c 256gb", "redmi 15 256gb",
    "poco c85 128gb", "redmi note 15 256gb", "oppo a6x 128gb", "iphone 16e 128gb",
    "epone 16 128gb", "iphone 17 pro max 256gb", "iphone 13 128gb usado",
    "iphone 14 128gb recondicionado",
]


def comparar(busca, coletas):
    """Reproduz a abertura da tela, sem alterar memória, rede ou condição escolhidas pela busca."""
    ofertas = [dict(oferta) for coleta in coletas for oferta in coleta["ofertas"]]
    if not ofertas:
        return pd.DataFrame(), {}
    ofertas.sort(key=lambda oferta: not app.menciona_o_modelo(oferta["titulo"], busca))
    citam = sum(app.menciona_o_modelo(oferta["titulo"], busca) for oferta in ofertas)
    titulos = [oferta["titulo"] for oferta in ofertas[:citam]]
    alvo, itens = app.classificar_por_regras(busca, titulos)
    itens += [{"celular": True, "marca": None, "modelo": None, "armazenamento_gb": None, "condicao": "novo"}
              for _ in ofertas[citam:]]
    modo = app.versao_da_tela(busca, alvo, [ofertas[k]["titulo"] for k in app.do_mesmo_modelo(alvo, itens)])
    if modo == "unica":
        alvo["versao_unica"] = True
    elif modo == "opcao":
        alvo["rede"] = "4g"
    return app.separar_ofertas(busca, ofertas, alvo, itens)


def medir_busca(entrada, mem):
    inicio = time.perf_counter()
    quando = datetime.now(app.FUSO).isoformat(timespec="seconds")
    busca, corrigida = app.corrigir_busca(entrada)
    coletas = app.coletar_todas(busca, mem, forcar_coleta=True)
    linhas, alvo = comparar(busca, coletas)
    tempo = time.perf_counter() - inicio
    registros = []
    if not linhas.empty:
        for linha in linhas.to_dict("records"):
            registro = {chave: linha[chave] for chave in ["titulo", "preco", "fonte", "loja", "pagamento", "link", "pagina"]}
            registro["motivo"] = None if pd.isna(linha["motivo"]) else linha["motivo"]
            registro["na_faixa"] = registro["motivo"] is None and registro["pagamento"] in app.PAGAMENTOS_DA_FAIXA
            for chave in ("rede_confirmada", "evidencia_rede", "pagina_rede", "rede_conferida_em"):
                valor = linha.get(chave)
                if isinstance(valor, str) and valor:
                    registro[chave] = valor
            registros.append(registro)
    aceitas = [oferta for oferta in registros if oferta["na_faixa"]]
    lojas = sorted({app.nome_da_loja(oferta["link"]) for oferta in aceitas})
    precos = [oferta["preco"] for oferta in aceitas]
    return {
        "entrada": entrada, "busca": busca, "corrigida": corrigida, "quando": quando,
        "segundos_servidor": round(tempo, 3), "coleta_nova": all(not c.get("cache") for c in coletas),
        "versao": alvo.get("rede") or (next(iter(app.versoes_conhecidas(alvo)))
                  if alvo and app.versoes_conhecidas(alvo) and len(app.versoes_conhecidas(alvo)) == 1 else None),
        "lojas": lojas, "ofertas_confirmadas": len(aceitas), "gerou_faixa": len(aceitas) >= app.MINIMO_OFERTAS,
        "menor": min(precos) if len(aceitas) >= app.MINIMO_OFERTAS else None,
        "mediana": statistics.median(precos) if len(aceitas) >= app.MINIMO_OFERTAS else None,
        "maior": max(precos) if len(aceitas) >= app.MINIMO_OFERTAS else None,
        "fontes": [{chave: coleta[chave] for chave in ("fonte", "status", "cache", "aviso") if chave in coleta}
                   for coleta in coletas],
        "ofertas": registros,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coletar", action="store_true", help="executa as 20 buscas reais, uma vez cada, sem cache de preços")
    parser.add_argument("--saida", default="validacao_tecnica.json")
    args = parser.parse_args()
    if not args.coletar:
        parser.error("informe --coletar para autorizar os pedidos às lojas")
    codigo = Path(app.__file__).read_bytes()
    destino = Path(args.saida)
    historico = []
    if destino.exists():
        anterior = json.loads(destino.read_text(encoding="utf-8"))
        historico = anterior.get("historico", [])
        diretorio = destino.parent / "validacoes"
        diretorio.mkdir(exist_ok=True)
        arquivo = diretorio / ("coleta-" + datetime.now(app.FUSO).strftime("%Y%m%d-%H%M%S") + ".json")
        arquivo.write_text(json.dumps(anterior, ensure_ascii=False, indent=2), encoding="utf-8")
        historico.append({chave: anterior[chave] for chave in ("inicio", "fim", "codigo_sha256", "resumo")})
        historico[-1]["arquivo"] = arquivo.relative_to(destino.parent).as_posix()
    tabela = pd.read_csv(Path(app.__file__).with_name(app.ARQUIVO_AVALIACAO), dtype=str, keep_default_na=False)
    acertos = sum(app.conferir_extracao(linha, app.extracao_das_regras(linha["titulo"]))["titulo"]
                  for linha in tabela.to_dict("records"))
    relatorio = {
        "inicio": datetime.now(app.FUSO).isoformat(timespec="seconds"),
        "codigo_sha256": hashlib.sha256(codigo).hexdigest(), "prompt_sha256": app.versao_do_prompt(),
        "origem": "Execução automatizada no ambiente de desenvolvimento do Codex",
        "limites": [
            "Tempo medido no servidor de testes; não é o tempo do clique ao resultado no navegador publicado.",
            "A cobertura é preliminar, baseada na classificação do app. A conferência humana das ofertas está pendente.",
            "Os 50 rótulos registrados foram feitos por IA e ainda precisam de revisão humana.",
            "Esta é uma reconferência dos modelos já conhecidos, não uma nova amostra independente.",
            "Nenhum participante foi simulado. Testes com pessoas, utilidade e redução do tempo seguem pendentes.",
        ],
        "extracao_regras": {"acertos": int(acertos), "total": len(tabela), "referencia": "rótulos publicados, feitos por IA"},
        "buscas": [],
        "historico": historico,
    }
    mem = {"paginas": {}, "robots": {}, "classificacoes": {}, "trava": threading.Lock()}
    for n, entrada in enumerate(BUSCAS, 1):
        resultado = medir_busca(entrada, mem)
        resultado["n"] = n
        relatorio["buscas"].append(resultado)
        relatorio["fim"] = datetime.now(app.FUSO).isoformat(timespec="seconds")
        relatorio["resumo"] = {
            "buscas": len(relatorio["buscas"]),
            "duas_lojas": sum(len(b["lojas"]) >= 2 for b in relatorio["buscas"]),
            "ate_15s_servidor": sum(b["segundos_servidor"] <= 15 for b in relatorio["buscas"]),
            "geraram_faixa": sum(b["gerou_faixa"] for b in relatorio["buscas"]),
            "ofertas_para_conferencia": sum(b["ofertas_confirmadas"] for b in relatorio["buscas"]),
        }
        destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"{n:02d}/20 {entrada}: {resultado['segundos_servidor']:.2f}s; "
              f"{len(resultado['lojas'])} lojas; {resultado['ofertas_confirmadas']} ofertas; "
              f"faixa={'sim' if resultado['gerou_faixa'] else 'não'}", flush=True)
    print(json.dumps(relatorio["resumo"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
