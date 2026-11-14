"""Revisão técnica das evidências publicadas. Não produz conferência humana nem dados de participantes.

python revisar_evidencias.py --coletar --saida revisao_paginas.json
"""
import argparse
import hashlib
import json
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import app


def normalizar_preco_exibido(texto):
    """A captura do navegador pode traduzir os separadores. Preserva o texto e lê os dois últimos dígitos como centavos."""
    unico = re.fullmatch(r'\s*R\$\s*([0-9][0-9.,]*)\s*', texto)
    if not unico:
        return None
    numero = unico[1]
    m = re.fullmatch(r"([0-9.,]+)[.,]([0-9]{2})", numero)
    return int(re.sub(r"\D", "", m[1])) + int(m[2]) / 100 if m else None


def percorrer_json(dado):
    if isinstance(dado, dict):
        yield dado
        for valor in dado.values():
            yield from percorrer_json(valor)
    elif isinstance(dado, list):
        for valor in dado:
            yield from percorrer_json(valor)


def valores_estruturados(dados):
    valores = set()
    for produto in dados.get("produtos_jsonld", []):
        for oferta in produto.get("ofertas", []):
            for campo in ("price", "lowPrice", "highPrice"):
                try:
                    valores.add(round(float(oferta[campo]), 2))
                except (KeyError, ValueError, TypeError):
                    pass
    return valores


def conferir_preco(registrado, dados):
    esperado = normalizar_preco_exibido(registrado["preco"])
    dinheiro = re.compile(r'R\$\s*\d[\d.,]*[.,]\d{2}(?!\d)')
    confirmados, evidencias = set(), []
    for produto in dados.get("estado_produto", []):
        for opcao in produto.get("pagamentos", []):
            nome = app.normalizar(opcao.get("Name") or "")
            if (opcao.get("NumberOfInstallments") == 1 and opcao.get("InterestRate") == 0 and "a vista" in nome
                    and not re.search(r'cupom|assin|clube|mensal',nome)):
                valor = opcao.get("TotalValuePlusInterestRate")
                if isinstance(valor, (int,float)):
                    confirmados.add(round(valor,2))
                    if valor == esperado:
                        evidencias.append(opcao.get("Name"))
    for texto in dados.get("trechos_pagamento", []):
        if re.search(r'cupom|assinante|exclusiv|prime|aplicativo',texto,re.I):
            continue
        quantias = list(dinheiro.finditer(texto))
        for marca in re.finditer(r'\bno\s+pix|[aà]\s+vista',texto,re.I):
            anteriores = [m for m in quantias if m.end()<=marca.start() and marca.start()-m.end()<=55]
            seguintes = [m for m in quantias if m.start()>=marca.end() and m.start()-marca.end()<=20]
            m = anteriores[-1] if anteriores else seguintes[0] if seguintes else None
            if m:
                valor = normalizar_preco_exibido(m[0])
                if valor is not None:
                    confirmados.add(valor)
                    if valor == esperado:
                        evidencias.append(texto[:240])
    genericos = valores_estruturados(dados)
    if esperado is None:
        return {"status": "inconclusivo: formato do preço capturado", "valor_registrado": None}
    if registrado["pagamento"] not in {"Pix", "à vista"}:
        return {"status": "valor compatível nos dados da página; pagamento continua não confirmado" if esperado in genericos else
                "valor diferente ou não localizado na página", "valor_registrado": esperado,
                "valores_pagina": sorted(genericos)}
    if esperado in confirmados:
        return {"status": "valor à vista/Pix compatível na página", "valor_registrado": esperado,
                "valores_pagina": sorted(confirmados), "evidencia": list(dict.fromkeys(evidencias))[:2]}
    formas = dados.get("pagamentos_estruturados", [])
    if any(p.get("forma")=="boleto" and p.get("preco")==esperado for p in formas):
        return {"status": "valor encontrado no boleto; marcação Pix não confirmada", "valor_registrado": esperado,
                "valores_pagina": [esperado], "evidencia": ["Dados da página: formas_pagamento.boleto.por"]}
    return {"status": "valor diferente ou não confirmado à vista/Pix", "valor_registrado": esperado,
            "valores_pagina": sorted(confirmados), "valores_genericos": sorted(genericos)}


def ler_pagina(conteudo, url):
    if isinstance(conteudo, bytes) and re.search(br'charset\s*=\s*["\x27]?iso-8859-1', conteudo[:15000], re.I):
        conteudo = conteudo.decode("iso-8859-1")
    arvore = app.arvore_utf8(conteudo)
    h1 = [" ".join(no.text_content().split()) for no in arvore.xpath('//h1')]
    produtos = []
    for texto in arvore.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            dados = json.loads(texto)
        except ValueError:
            continue
        for no in percorrer_json(dados):
            if no.get("@type") != "Product":
                continue
            ofertas = no.get("offers") or []
            ofertas = [ofertas] if isinstance(ofertas, dict) else ofertas
            produtos.append({"nome": no.get("name"), "url": no.get("url"),
                             "ofertas": [{k: o.get(k) for k in ("price", "lowPrice", "highPrice", "priceCurrency",
                                "availability", "itemCondition", "url", "name", "seller") if k in o}
                                         for o in ofertas if isinstance(o, dict)]})
    next_texto = arvore.xpath('//script[@id="__NEXT_DATA__"]/text()')
    next_chaves = {}
    pagamentos_estruturados, rede_descricao = [], []
    if next_texto:
        try:
            raiz = json.loads(next_texto[0]).get("props", {}).get("pageProps", {})
            next_chaves = {k: list(v)[:35] if isinstance(v, dict) else type(v).__name__
                           for k, v in raiz.items() if k not in ("dehydratedState", "initialState")}
            for anuncio in raiz.get("productVariation", {}).get("anuncios", []):
                if not anuncio.get("situacao") or (anuncio.get("estoque") or 0) <= 0:
                    continue
                for forma, condicao in (anuncio.get("formas_pagamento") or {}).items():
                    if not isinstance(condicao, dict):
                        continue
                    pagamento = {"forma": forma, "preco": condicao.get("por")}
                    if pagamento not in pagamentos_estruturados:
                        pagamentos_estruturados.append(pagamento)
            produto = raiz.get("product") or {}
            if isinstance(produto, dict) and produto.get("about"):
                texto = " ".join(app.arvore_utf8(produto["about"]).text_content().split())
                for m in re.finditer(r'rede|conectividade|tecnologia de rede', texto, re.I):
                    trecho = texto[max(0,m.start()-20):m.end()+140]
                    if re.search(r'\b[45]\s*G\b',trecho,re.I):
                        rede_descricao.append(trecho)
                    if len(rede_descricao)>=4:
                        break
        except ValueError:
            pass
    estados = [no.text_content() for no in arvore.xpath('//template[@data-varname="__STATE__"]')]
    if not estados:
        for texto in arvore.xpath('//script/text()'):
            m = re.search(r'\b__STATE__\s*=\s*(\{)', texto)
            if m:
                try:
                    estado, _ = json.JSONDecoder().raw_decode(texto[m.start(1):])
                    estados.append(json.dumps(estado))
                except ValueError:
                    pass
    estado_produto = []
    for texto in estados[:1]:
        try:
            estado = json.loads(texto)
        except ValueError:
            continue
        for chave, produto in estado.items():
            if not isinstance(produto, dict) or produto.get("__typename") != "Product" or not produto.get("productName"):
                continue
            registro = {"nome": produto["productName"], "pagamentos": [], "ficha": []}
            for campo, valor in estado.items():
                if not isinstance(valor, dict) or not campo.lstrip("$").startswith(chave + "."):
                    continue
                if valor.get("__typename") == "Installment" and valor.get("PaymentSystemName") in ("Pix", "Boleto Bancário", "Boleto"):
                    parcela = {k: valor.get(k) for k in ("PaymentSystemName", "Name", "NumberOfInstallments",
                                                       "TotalValuePlusInterestRate", "InterestRate")}
                    if parcela not in registro["pagamentos"]:
                        registro["pagamentos"].append(parcela)
                if re.search(r'rede|conectiv|armazenamento', str(valor.get("name", "")), re.I):
                    registro["ficha"].append({"nome": valor["name"], "valor": valor.get("values")})
            estado_produto.append(registro)
    metas = [{"campo": n.get("property") or n.get("itemprop"), "valor": n.get("content")}
             for n in arvore.xpath('//meta[@content]')
             if "price" in (n.get("property", "") + n.get("itemprop", "")).lower()]
    campos_rede = []
    for linha in arvore.xpath('//tr'):
        celulas = linha.xpath('./th|./td')
        if len(celulas) == 2 and any(p in app.normalizar(celulas[0].text_content()) for p in ("rede", "conectiv", "armazenamento")):
            campos_rede.append([" ".join(c.text_content().split())[:220] for c in celulas])
    for no in arvore.xpath('//script|//style|//noscript'):
        no.drop_tree()
    trechos = []
    for no in arvore.xpath('//p|//span|//div|//strong'):
        texto = " ".join(no.text_content().split())
        if len(texto) <= 260 and re.search(r"pix|[aà] vista", texto, re.I) and re.search(r"R\$", texto):
            if texto and not any(texto in t for t in trechos):
                trechos.append(texto)
        if len(trechos) >= 8:
            break
    variantes = arvore.xpath('//button[@aria-pressed="true" and contains(@class,"rc-qv-row")]')
    variante = " ".join(variantes[0].text_content().split()) if len(variantes)==1 else ""
    return {"titulo_pagina": arvore.xpath('normalize-space(string(//title))'), "h1": h1,
            "canonical": arvore.xpath('//link[@rel="canonical"]/@href'), "produtos_jsonld": produtos,
            "metas_preco": metas, "campos_ficha": campos_rede[:15], "trechos_pagamento": trechos,
            "chaves_pagina": next_chaves, "estado_produto": estado_produto,
            "pagamentos_estruturados": pagamentos_estruturados, "rede_descricao": rede_descricao,
            "variante_selecionada": variante}


def coletar_paginas(registro, cache, amostra=False):
    unicas = {}
    for busca in registro["buscas"]:
        for oferta in busca["ofertas"]:
            unicas.setdefault(oferta["link"], oferta)
    if amostra:
        por_dominio = {}
        for url, oferta in unicas.items():
            por_dominio.setdefault(urlparse(url).netloc, (url, oferta))
        unicas = dict(por_dominio.values())
    cache.mkdir(parents=True, exist_ok=True)
    mem = {"paginas": {}, "classificacoes": {}, "robots": {}, "trava": threading.Lock()}
    travas = {urlparse(url).netloc: threading.Semaphore(2) for url in unicas}

    def coletar(url):
        codigo = hashlib.sha256(url.encode()).hexdigest()
        meta = cache / (codigo + ".json")
        if meta.exists():
            resultado = json.loads(meta.read_text())
            html = cache / (codigo + ".html")
            if html.exists():
                resultado["dados"] = ler_pagina(html.read_bytes(), url)
                meta.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))
            return resultado
        with travas[urlparse(url).netloc]:
            quando = datetime.now(app.FUSO).isoformat(timespec="seconds")
            inicio = time.monotonic()
            bruto = None

            def ler(conteudo, destino):
                nonlocal bruto
                bruto = conteudo
                return ler_pagina(conteudo, destino)

            pagina, erro = app.baixar(url, ler, mem, prazo=inicio + 22)
            resultado = {"url": url, "quando": quando, "segundos": round(time.monotonic() - inicio, 3),
                         "status": erro or "página pública lida", "dados": pagina if isinstance(pagina, dict) else {}}
            if bruto is not None:
                resultado["sha256_html"] = hashlib.sha256(bruto).hexdigest()
                (cache / (codigo + ".html")).write_bytes(bruto)
            meta.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))
            return resultado

    resultados = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futuras = {executor.submit(coletar, url): url for url in unicas}
        for futura in as_completed(futuras):
            resultado = futura.result()
            resultados.append(resultado)
            if len(resultados) % 20 == 0 or amostra:
                print(json.dumps({"concluidas": len(resultados), "total": len(unicas),
                                  "dominio": urlparse(resultado["url"]).netloc, "status": resultado["status"]}, ensure_ascii=False), flush=True)
    return sorted(resultados, key=lambda r: r["url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coletar", action="store_true")
    parser.add_argument("--amostra", action="store_true")
    parser.add_argument("--saida", default="revisao_paginas.json")
    parser.add_argument("--cache", default="../investigacao/paginas_revisao")
    args = parser.parse_args()
    if not args.coletar:
        parser.error("informe --coletar para consultar as páginas públicas")
    registro = json.loads(Path("validacao_fontes_adicionais.json").read_text())
    inicio = datetime.now(app.FUSO).isoformat(timespec="seconds")
    paginas = coletar_paginas(registro, Path(args.cache), args.amostra)
    saida = {"origem": "Revisão técnica por IA e leitura automática de páginas públicas", "inicio": inicio,
             "fim": datetime.now(app.FUSO).isoformat(timespec="seconds"),
             "fonte_registros": "validacao_fontes_adicionais.json", "conferencia_humana": False,
             "limite": "Esta visita posterior não comprova retrospectivamente o preço no horário da bateria.",
             "resumo_acesso": dict(Counter(p["status"] for p in paginas)), "paginas": paginas}
    Path(args.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(saida["resumo_acesso"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
