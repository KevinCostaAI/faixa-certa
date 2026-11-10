"""Faixa Certa: compara preços de smartphones em várias lojas, com busca na hora e correção de digitação."""

import difflib
import json
import os
import random
import re
import statistics
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote, quote_plus, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from lxml import html

USER_AGENT = "Mozilla/5.0 (compatible; FaixaCerta/1.0; +https://github.com/KevinCostaAI/faixa-certa)"
ROBO = "FaixaCerta"
TEMPO_LOJA = 10  # segundos de espera por loja
TEMPO_LLM = 20  # segundos para classificar os títulos de uma busca
CACHE_SEGUNDOS = 15 * 60  # a mesma busca só é repetida na loja depois de 15 minutos
MINIMO_OFERTAS = 3  # abaixo disso, a faixa de preço não é exibida
MAXIMO_POR_LOJA = 30
FUSO = ZoneInfo("America/Fortaleza")
LLM_URL = os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
LLM_MODELO = os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")
LLM_MODELO_RESERVA = os.environ.get("LLM_MODEL_FALLBACK", "gemini-3.5-flash-lite")
COMPARELIVRE = os.environ.get("COMPARELIVRE_URL", "https://comparelivre.com.br").rstrip("/")
KABUM = os.environ.get("KABUM_URL", "https://www.kabum.com.br").rstrip("/")


# Regras de extração usadas como linha de base na validação (as mesmas da versão anterior, sem ajustes).
MODELOS = {
    "iPhone 11": "Apple", "iPhone 13": "Apple", "iPhone 14": "Apple", "iPhone 15": "Apple", "iPhone 16": "Apple",
    "Galaxy A17": "Samsung", "Galaxy A17 5G": "Samsung",
    "Moto G06": "Motorola", "Edge 60 Fusion": "Motorola", "Edge 60 Pro": "Motorola", "Edge 70 Fusion": "Motorola", "Edge 70": "Motorola",
    "Redmi 15C": "Xiaomi", "Redmi 15C 5G": "Xiaomi",
}
ARMAZENAMENTOS = [64, 128, 256, 512, 1000]
CONDICOES = ["novo", "usado", "recondicionado"]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto).casefold())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def modelo_por_regras(t):
    iphone = re.search(r"\biphone\s*(11|13|14|15|16)\b(?!\s*(?:pro|plus|max|mini|e)\b)", t)
    if iphone:
        return f"iPhone {iphone[1]}"
    if re.search(r"\b(?:galaxy\s*)?a17\b", t):
        return "Galaxy A17 5G" if re.search(r"\b5g\b", t) else "Galaxy A17"
    if re.search(r"\bmoto\s*g\s*06\b|\bmotorola\s*g\s*06\b", t):
        return "Moto G06"
    if re.search(r"\bredmi\s*15\s*c\b", t):
        return "Redmi 15C 5G" if re.search(r"\b5g\b", t) else "Redmi 15C"
    edge = re.search(r"\bedge\s*(60|70)(?:\s+(fusion|pro))?\b", t)
    if edge:
        if edge[2]:
            nome = f"Edge {edge[1]} {edge[2].capitalize()}"
            return nome if nome in MODELOS else None
        return "Edge 70" if edge[1] == "70" else None
    return None


def armazenamento_por_regras(t):
    valores = set()
    for numero, unidade in re.findall(r"(?<![\d.,])(\d{1,4})\s*(gb|tb)\b", t):
        valor = int(numero) * (1000 if unidade == "tb" else 1)
        if valor in ARMAZENAMENTOS:
            valores.add(valor)
    return valores.pop() if len(valores) == 1 else None


def condicao_por_regras(t):
    if re.search(r"\b(?:recondicionad[oa]|refurbished|remanufaturad[oa])\b", t):
        return "recondicionado"
    if re.search(r"\b(?:usad[oa]|semi\s*-?nov[oa]|vitrine|mostruario|excelente|bom estado)\b", t):
        return "usado"
    return "novo"


def extrair_por_regras(titulo):
    t = normalizar(titulo)
    modelo = modelo_por_regras(t)
    return {"marca": MODELOS.get(modelo), "modelo": modelo, "armazenamento_gb": armazenamento_por_regras(t), "condicao": condicao_por_regras(t)}


# Títulos de teste rotulados à parte (modelo, armazenamento em GB e condição), usados só na validação.
TITULOS_TESTE = [
    ('Apple iPhone 17e 256gb rosa rosa', None, 256, 'novo'),
    ('Apple iPhone 16 (256 GB) - Preto', 'iPhone 16', 256, 'novo'),
    ('Apple iPhone 15 (256 GB) - Azul', 'iPhone 15', 256, 'novo'),
    ('Apple iPhone 16 (256 GB) - Branco', 'iPhone 16', 256, 'novo'),
    ('Apple iPhone 15 256GB Preto', 'iPhone 15', 256, 'novo'),
    ('Apple iPhone 16 (256 GB) - Rosa', 'iPhone 16', 256, 'novo'),
    ('Apple iPhone 16 256GB Branco', 'iPhone 16', 256, 'novo'),
    ('Apple iPhone 16 Pro Max (256 GB) - Titânio branco', None, 256, 'novo'),
    ('Apple iPhone 16 256GB Ultramarino', 'iPhone 16', 256, 'novo'),
    ('Apple iPhone 16 Pro Max (256 GB) - Titânio-preto', None, 256, 'novo'),
    ('Apple iPhone 16 Pro (somente Esim) (256 Gb) - preto titânio', None, 256, 'novo'),
    ('Apple iPhone 16 Pro Max (256 GB) - Titânio-deserto', None, 256, 'novo'),
    ('iPhone 18 Pro Max 256GB Bordô', None, 256, 'novo'),
    ('Apple iPhone 16 Pro Max (somente Esim) (256 Gb) - preto titânio', None, 256, 'novo'),
    ('iPhone 17 Pro Max 256 GB - Azul-profundo - somente eSIM', None, 256, 'novo'),
    ('iPhone 18 Pro de 256 GB — Preto', None, 256, 'novo'),
    ('iPhone 18 Pro de 256 GB — Bordô', None, 256, 'novo'),
    ('iPhone 18 Pro de 256 GB — Prateado', None, 256, 'novo'),
    ('iPhone 18 Pro de 256 GB — Glacial', None, 256, 'novo'),
    ('iPhone 17 Pro Max 256 GB - Prateado - somente eSIM', None, 256, 'novo'),
    ('iPhone 18 Pro Max 256GB Preto', None, 256, 'novo'),
    ('iPhone Duo de 256 GB — Branco-estrela', None, 256, 'novo'),
    ('iPhone Duo de 256 GB — Céu noturno', None, 256, 'novo'),
    ('Smartphone Samsung Galaxy A17 com IA 256GB 8GB RAM Câmera de 50MP Tela de 6.7 NFC IP54 - Cinza', 'Galaxy A17', 256, 'novo'),
    ('Smartphone Samsung Galaxy A17 5G 256GB 8GB RAM - Cinza', 'Galaxy A17 5G', 256, 'novo'),
    ('Smartphone Samsung Galaxy A17 4g Tela 6.7 256gb Câmera Tri Cinza', 'Galaxy A17', 256, 'novo'),
    ('Smartphone Samsung Galaxy A17 5g A17 256gb - Cinza Cinza', 'Galaxy A17 5G', 256, 'novo'),
    ('Smartphone Samsung Galaxy A17 4G 6.7 256GB 8GB Câmera Tripla', 'Galaxy A17', 256, 'novo'),
    ('Smartphone Xiaomi Redmi 15C 4GB + 128GB – Tela 6.9" Dual SIM LTE, Desempenho e Estilo Moderno', 'Redmi 15C', 128, 'novo'),
    ('Celular Xiaomi Redmi 15c 128gb 8gb Ram Dual Sim Azul Azul', 'Redmi 15C', 128, 'novo'),
    ('Smartphone Xiaomi Redmi 15C 4G 128GB 4GB RAM + 4GB Memoria Virtual 50MP 8MP Preto Verde Azul', 'Redmi 15C', 128, 'novo'),
    ('Smartphone Xiaomi Redmi 15C de 128 GB com 6 GB de RAM, Verde Menta', 'Redmi 15C', 128, 'novo'),
    ('Câmera Redmi 15c 6+6 128 Gb Azul Azul', 'Redmi 15C', 128, 'novo'),
    ('Smartphone Motorola Moto G06 - 64GB 4GB RAM + 8GB Ram Boost, Camera 50MP com AI, Bateria de 5200 mAh e Tela 6.9" - Bege', 'Moto G06', 64, 'novo'),
    ('Smartphone Motorola Moto G06 - 64GB 4GB RAM + 8GB Ram Boost, Camera 50MP com AI, Bateria de 5200 mAh e Tela 6.9" - Verde', 'Moto G06', 64, 'novo'),
    ('Smartphone Motorola Moto G06 - 64GB 4GB RAM + 8GB Ram Boost, Camera 50MP com AI, Bateria de 5200 mAh e Tela 6.9" - Azul Marinho', 'Moto G06', 64, 'novo'),
    ('Smartphone Motorola Moto G06 - 64GB 4GB RAM + 8GB Ram Boost, Camera 50MP com AI, Bateria de 5200 mAh e Tela 6.9" - Laranja', 'Moto G06', 64, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G De Capa 5594 TYB', None, None, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G Capa Preto Macia Silicone Case TYB 7597', None, None, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G De Capa 7204 TYB', None, None, 'novo'),
    ('Capinha de Silicone Preta Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G Capa de Celular Macia TY7619', None, None, 'novo'),
    ('Motorola Edge 70 Fusion Capa De Telefone Para Ultra 60 Pro Stylus 5G 4G Traseira À Prova De Choque', None, None, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 Fusion Plus 5G Capa De Silicone Macia Estilo Simples Macaron Case 0388', None, None, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G Capa De Silicone Anti-impacto Macia Case MKL0562', None, None, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G Capa De Silicone Case MKL0325', None, None, 'novo'),
    ('Película Protetora Hidrogel  TPU Motorola Moto Linha Edge 70 60 50 40 30 20 Pro+ Pro Fusion Plus S Neo', None, None, 'novo'),
    ('Capinha Para Motorola Moto Edge 70 60 40 50 Fusion Plus Pro Neo 5G Capa Anti Impacto Transparente Macia Case FS1269', None, None, 'novo'),
    ('Para Motorola edge 70 fusion + 60 g100 pro g86 power g57 60s stylus 50 ultra Fusão', None, None, 'novo'),
    ('Capa Armadura À Prova De Choque Para Motorola G17 G37 G47 G57 G67 G77 G56 G86 Edge 70 60 50 40 Fusion Protetor De Câmera', None, None, 'novo'),
    ('Para Motorola Edge 60 70 Fusion Moto G67 G77 G17 G37 G47 G06 G56 G86 G75 Caso De Telefone Armadura Câmera Proteção Capa', None, None, 'novo'),
]


# Correção de digitação da busca
MARCAS = {
    "apple", "samsung", "motorola", "xiaomi", "realme", "asus", "nokia", "oppo", "honor", "huawei",
    "google", "infinix", "tecno", "multilaser", "positivo", "sony", "oneplus", "lenovo",
}
LINHAS = {
    "iphone", "galaxy", "moto", "redmi", "poco", "edge", "razr", "pixel", "zenfone", "note",
    "fusion", "neo", "narzo", "reno", "magic", "spark", "camon", "pova", "fold", "flip", "xperia", "nord",
}
VARIANTES = {"pro", "max", "plus", "mini", "ultra", "lite", "fe", "prime", "power", "play", "stylus"}
VOCABULARIO = sorted(MARCAS | LINHAS | VARIANTES)
APELIDOS = {
    "aifone": "iphone", "aifon": "iphone", "ifone": "iphone", "ifon": "iphone", "iphon": "iphone",
    "ipone": "iphone", "epone": "iphone", "iphome": "iphone", "eiphone": "iphone",
    "galaxi": "galaxy", "galax": "galaxy", "galaxe": "galaxy", "galacsi": "galaxy",
    "sansung": "samsung", "samsumg": "samsung", "samsun": "samsung", "sansumg": "samsung", "sanzung": "samsung",
    "motorolla": "motorola", "motorla": "motorola", "mottorola": "motorola",
    "xiaome": "xiaomi", "xiaomy": "xiaomi", "xaomi": "xiaomi", "xiomi": "xiaomi", "chaomi": "xiaomi",
    "redimi": "redmi", "redme": "redmi", "pocco": "poco", "realmi": "realme", "nokya": "nokia",
}
NEUTRAS = {
    "de", "da", "do", "das", "dos", "com", "sem", "para", "e", "o", "a", "os", "as", "em", "no", "na",
    "celular", "smartphone", "telefone", "aparelho", "novo", "nova", "usado", "usada", "seminovo", "seminova",
    "recondicionado", "recondicionada", "vitrine", "preto", "preta", "branco", "branca", "azul", "verde",
    "rosa", "roxo", "roxa", "vermelho", "vermelha", "amarelo", "amarela", "cinza", "prata", "prateado",
    "dourado", "dourada", "grafite", "titanio", "meia", "noite", "estelar", "lilas", "creme", "bege",
    "laranja", "ram", "dual", "chip", "tela", "camera", "bateria", "original", "lacrado", "barato",
    "barata", "promocao", "oferta", "esim",
}
EXIBIR = {
    "iphone": "iPhone", "moto": "Moto", "rog": "ROG", "oneplus": "OnePlus", "fe": "FE",
}
ARMAZENAMENTOS_BUSCA = {32, 64, 128, 256, 512, 1000, 2000}


def separar(texto):
    texto = re.sub(r"\b(iphone|galaxy|redmi|moto|edge|note|pixel|poco|razr)(?=\d)", r"\1 ", texto)
    texto = re.sub(r"\bgalaxy(?=[asmzf]\d)", "galaxy ", texto)
    texto = re.sub(r"\b([a-z]{4,})(\d+)\b", r"\1 \2", texto)
    texto = re.sub(r"(?<![\d.,])(16|32|64|128|256|512)\s*(?:gb|g|gigas?|gigabytes?)\b", r"\1gb", texto)
    texto = re.sub(r"(?<![\d.,])([12])\s*(?:tb|teras?|terabytes?)\b", r"\1tb", texto)
    return " ".join(texto.split())


def limpar(texto):
    return separar(re.sub(r"[^\w\s]", " ", normalizar(texto)))


def corrigir_palavra(palavra):
    if palavra in APELIDOS:
        return APELIDOS[palavra]
    if palavra in VOCABULARIO or palavra in NEUTRAS or len(palavra) < 4 or any(c.isdigit() for c in palavra):
        return palavra
    parecidas = difflib.get_close_matches(palavra, VOCABULARIO, n=1, cutoff=0.72)
    return parecidas[0] if parecidas else palavra


def corrigir_busca(texto):
    original = limpar(texto)
    corrigida = " ".join(corrigir_palavra(palavra) for palavra in original.split())
    return corrigida, corrigida != original


def exibir(busca):
    palavras = []
    for palavra in busca.split():
        if palavra in EXIBIR:
            palavras.append(EXIBIR[palavra])
        elif re.fullmatch(r"\d+(?:gb|tb)|[a-z]{1,2}\d+[a-z]?|\d+[a-z]", palavra) or (len(palavra) == 1 and palavra not in NEUTRAS):
            palavras.append(palavra.upper())
        elif palavra in VOCABULARIO:
            palavras.append(palavra.capitalize())
        else:
            palavras.append(palavra)
    return " ".join(palavras)


def armazenamento_em(texto):
    valores = {
        int(numero) * (1000 if unidade == "tb" else 1)
        for numero, unidade in re.findall(r"(?<![\d.,])(\d{1,4})\s*(gb|tb)\b", limpar(texto))
    }
    valores &= ARMAZENAMENTOS_BUSCA
    return valores.pop() if len(valores) == 1 else None


def condicao_em(texto):
    return condicao_por_regras(normalizar(texto))


# Comparação dos títulos coletados com a busca
ACESSORIO = re.compile(
    r"^(?:kit\s+(?:de\s+)?)?(?:\d+\s+)?(?:capa|capinha|case|pelicula|vidro|protetor|carregador|fonte|cabo|fone|"
    r"suporte|adaptador|lente|caneta|bateria|tampa|chip|cartao|pulseira|smartwatch|relogio|tablet|controle|bolsa|"
    r"carteira)\b|\bpara\s+(?:iphone|galaxy|samsung|motorola|moto|xiaomi|redmi|poco)\b|\bcompativel\b"
)


def chave_modelo(modelo):
    palavras = [p for p in limpar(modelo or "").split() if p not in MARCAS]
    return re.sub(r"[^a-z0-9]", "", "".join(palavras))


def chave_marca(marca):
    return re.sub(r"[^a-z0-9]", "", normalizar(marca or ""))


def palavras_do_modelo(busca):
    return [
        p for p in busca.split()
        if p not in NEUTRAS and p not in MARCAS and p != "4g" and not re.fullmatch(r"\d+(?:gb|tb)", p)
    ]


def classificar_por_regras(busca, titulos):
    palavras = palavras_do_modelo(busca)
    alvo = {
        "celular": True,
        "marca": None,
        "modelo": " ".join(palavras) or None,
        "armazenamento_gb": armazenamento_em(busca),
        "condicao": condicao_em(busca),
    }
    if not palavras:
        return alvo, [dict(alvo, modelo=None) for _ in titulos]
    partes = [r"\s*".join(re.escape(pedaco) for pedaco in re.findall(r"[a-z]+|\d+", p)) for p in palavras]
    proibidas = sorted(VARIANTES - set(palavras)) + ([] if "5g" in palavras else ["5g"])
    padrao = re.compile(r"\b" + r"[\s-]*".join(partes) + r"\b(?![\s-]*(?:" + "|".join(proibidas) + r")\b)")
    itens = []
    for titulo in titulos:
        texto = limpar(titulo)
        itens.append({
            "celular": not ACESSORIO.search(texto),
            "marca": None,
            "modelo": alvo["modelo"] if padrao.search(texto) else "outro modelo",
            "armazenamento_gb": armazenamento_em(titulo),
            "condicao": condicao_em(titulo),
        })
    return alvo, itens


INSTRUCOES_LOTE = """Você classifica smartphones a partir de textos de lojas.
O primeiro texto é a busca do usuário e os demais são títulos de anúncios.
Para cada texto, na mesma ordem, devolva celular, marca, modelo, armazenamento_gb e condicao.
- celular: false para acessórios (capa, película, carregador, cabo, fone, suporte), peças, kits sem o aparelho ou produtos que não são smartphones; true nos demais casos e sempre na busca.
- marca: fabricante, como Apple, Samsung, Motorola ou Xiaomi, ou null.
- modelo: nome do modelo sem a marca e sem armazenamento, cor ou memória RAM, por exemplo "iPhone 13", "Galaxy A17 5G", "Moto G06" ou "Redmi 15C". Use exatamente a mesma grafia para o mesmo modelo. Inclua Pro, Max, Plus, Ultra, Lite, FE, 5G ou letras como e e C somente quando fizerem parte do nome. Use null se não houver modelo.
- armazenamento_gb: armazenamento interno em GB (1 TB = 1000), ou null. Não confunda com memória RAM.
- condicao: novo, usado ou recondicionado. Sem indicação, novo.
Responda somente com JSON no formato {"itens": [{"celular": true, "marca": "Apple", "modelo": "iPhone 13", "armazenamento_gb": 128, "condicao": "novo"}]}."""


def chave_llm():
    chave = os.environ.get("LLM_API_KEY")
    if chave:
        return chave
    try:
        return st.secrets.get("LLM_API_KEY")
    except Exception:
        return None


LLM_CHAVE = chave_llm()


def chamar_llm(textos, modelo, formato_json=True):
    corpo = {
        "model": modelo,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": INSTRUCOES_LOTE},
            {"role": "user", "content": json.dumps({"textos": textos}, ensure_ascii=False)},
        ],
    }
    if formato_json:
        corpo["response_format"] = {"type": "json_object"}
    return requests.post(
        f"{LLM_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_CHAVE}"},
        json=corpo,
        timeout=TEMPO_LLM,
    )


def limpar_item(item):
    try:
        armazenamento = int(item.get("armazenamento_gb")) if item.get("armazenamento_gb") is not None else None
    except (TypeError, ValueError):
        armazenamento = None
    modelo, marca = item.get("modelo"), item.get("marca")
    return {
        "celular": bool(item.get("celular")),
        "marca": marca if isinstance(marca, str) and marca.strip() else None,
        "modelo": modelo if isinstance(modelo, str) and modelo.strip() else None,
        "armazenamento_gb": armazenamento,
        "condicao": item.get("condicao") if item.get("condicao") in CONDICOES else "novo",
    }


ERROS_PASSAGEIROS = {429, 500, 502, 503, 504}


def classificar_por_llm(textos):
    """Tenta o modelo principal duas vezes e, se ele estiver sobrecarregado, o modelo reserva."""
    inicio = time.monotonic()
    ultima = None
    for modelo in dict.fromkeys([LLM_MODELO, LLM_MODELO_RESERVA]):
        for _ in range(2):
            if time.monotonic() - inicio > TEMPO_LLM:
                break
            resposta = chamar_llm(textos, modelo)
            if resposta.status_code == 400:
                resposta = chamar_llm(textos, modelo, formato_json=False)
            if resposta.status_code in ERROS_PASSAGEIROS or resposta.status_code == 404:
                ultima = resposta
                if resposta.status_code == 404:
                    break
                time.sleep(1.5)
                continue
            resposta.raise_for_status()
            conteudo = resposta.json()["choices"][0]["message"]["content"]
            itens = json.loads(re.search(r"\{.*\}", conteudo, re.S)[0])["itens"]
            if len(itens) != len(textos):
                raise ValueError("A resposta não tem um item para cada texto.")
            return [limpar_item(item) for item in itens], modelo
    if ultima is None:
        raise requests.Timeout("Tempo esgotado.")
    ultima.raise_for_status()
    raise requests.HTTPError(f"Erro {ultima.status_code}", response=ultima)


def detalhe_do_erro(resposta):
    try:
        dados = resposta.json()
        dados = dados[0] if isinstance(dados, list) else dados
        return str(dados.get("error", {}).get("message", ""))[:80]
    except Exception:
        return ""


@st.cache_resource
def memoria():
    return {"paginas": {}, "robots": {}, "classificacoes": {}, "trava": threading.Lock()}


def classificar(busca, titulos, mem):
    if LLM_CHAVE:
        chave = (busca, tuple(titulos))
        guardado = mem["classificacoes"].get(chave)
        if guardado and time.time() - guardado[0] < CACHE_SEGUNDOS:
            return guardado[1][0], guardado[1][1:], f"LLM ({guardado[2]})"
        try:
            itens, modelo = classificar_por_llm([busca] + list(titulos))
            mem["classificacoes"][chave] = (time.time(), itens, modelo)
            return itens[0], itens[1:], f"LLM ({modelo})"
        except requests.HTTPError as erro:
            detalhe = detalhe_do_erro(erro.response)
            motivo = f"erro HTTP {erro.response.status_code}" + (f", {detalhe}" if detalhe else "")
        except requests.RequestException:
            motivo = "sem resposta"
        except Exception:
            motivo = "resposta inválida"
        origem = f"regras (serviço de IA indisponível: {motivo})"
    else:
        origem = "regras (sem chave de IA configurada)"
    alvo, itens = classificar_por_regras(busca, titulos)
    return alvo, itens, origem


def mesmo_produto(alvo, item):
    return motivo_descarte(alvo, item) is None


def motivo_descarte(alvo, item):
    if not item["celular"]:
        return "acessório ou outro produto"
    if not item["modelo"] or chave_modelo(item["modelo"]) != chave_modelo(alvo["modelo"]):
        return "outro modelo"
    if alvo["marca"] and item["marca"] and chave_marca(alvo["marca"]) != chave_marca(item["marca"]):
        return "outra marca"
    if alvo["armazenamento_gb"] and item["armazenamento_gb"] != alvo["armazenamento_gb"]:
        return "outro armazenamento"
    if item["condicao"] != alvo["condicao"]:
        return f"produto {item['condicao']}"
    return None


# Coleta online (web scraping) nas lojas
def preco_brl(texto):
    achado = re.search(r"R\$\s*([\d.]+,\d{2})", texto or "")
    return float(achado[1].replace(".", "").replace(",", ".")) if achado else None


def numero(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        texto = valor.strip().replace("R$", "").strip()
        if re.fullmatch(r"[\d.]+,\d{2}", texto):
            return float(texto.replace(".", "").replace(",", "."))
        try:
            return float(texto)
        except ValueError:
            return None
    return None


def preco_valido(preco):
    return preco is not None and 50 <= preco <= 50000


def ler_comparelivre(conteudo, url):
    arvore = html.fromstring(conteudo)
    ofertas = []
    for cartao in arvore.xpath('//a[starts-with(@href, "/p/")]'):
        titulo = cartao.xpath("normalize-space(string(.//h4))") or cartao.xpath("normalize-space(string(.//h3))")
        preco = preco_brl(cartao.xpath('normalize-space(string(.//*[contains(@class, "price")]))'))
        if preco is None:
            preco = preco_brl(cartao.text_content())
        lojas = cartao.xpath('normalize-space(string(.//*[contains(@class, "noffers")]))')
        if not titulo or not preco_valido(preco):
            continue
        quantidade = re.search(r"(\d+)\s+lojas?", lojas, re.I)
        loja = lojas.split("·", 1)[1].strip() if "·" in lojas else ""
        total = int(quantidade[1]) if quantidade else 1
        if not loja:
            loja = f"{total} lojas" if total > 1 else "Loja não informada"
        elif total > 1:
            loja = f"{loja} e mais {total - 1}"
        ofertas.append({"titulo": titulo, "preco": preco, "loja": loja, "fonte": "Compare Livre",
                        "link": urljoin(url, cartao.get("href"))})
    return ofertas


def ler_kabum(conteudo, url):
    arvore = html.fromstring(conteudo)
    ofertas = []
    for bloco in arvore.xpath('//script[@id="__NEXT_DATA__"]/text()'):
        try:
            pilha = [json.loads(bloco)]
        except ValueError:
            continue
        while pilha:
            atual = pilha.pop()
            if isinstance(atual, str) and len(atual) > 200 and atual.lstrip().startswith("{"):
                try:
                    pilha.append(json.loads(atual))
                except ValueError:
                    pass
            elif isinstance(atual, list):
                pilha.extend(atual)
            elif isinstance(atual, dict):
                pilha.extend(atual.values())
                if not (isinstance(atual.get("name"), str) and atual.get("code") and "price" in atual):
                    continue
                if atual.get("available") is False:
                    continue
                preco = numero(atual.get("priceWithDiscount"))
                if not preco_valido(preco):
                    preco = numero(atual.get("price"))
                if preco_valido(preco):
                    link = f"{KABUM}/produto/{atual['code']}/{atual.get('friendlyName') or ''}".rstrip("/")
                    ofertas.append({"titulo": atual["name"].strip(), "preco": preco,
                                    "loja": atual.get("sellerName") or "KaBuM!", "fonte": "KaBuM!", "link": link})
    return ofertas


FONTES = {
    "Compare Livre": (lambda busca: f"{COMPARELIVRE}/busca?q={quote_plus(busca)}", ler_comparelivre),
    "KaBuM!": (lambda busca: f"{KABUM}/busca/{quote('-'.join(busca.split()))}", ler_kabum),
}
CABECALHOS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "pt-BR,pt;q=0.9"}


def robots_permite(url, mem):
    partes = urlparse(url)
    dominio = f"{partes.scheme}://{partes.netloc}"
    guardado = mem["robots"].get(dominio)
    if not guardado or time.time() - guardado[0] > 24 * 3600:
        try:
            resposta = requests.get(f"{dominio}/robots.txt", headers=CABECALHOS, timeout=TEMPO_LOJA)
            linhas = resposta.text.splitlines() if resposta.status_code < 400 else []
            bloqueado = resposta.status_code >= 500
        except requests.RequestException:
            linhas, bloqueado = [], False
        leitor = RobotFileParser()
        leitor.parse(linhas)
        guardado = (time.time(), leitor, bloqueado)
        mem["robots"][dominio] = guardado
    _, leitor, bloqueado = guardado
    return not bloqueado and leitor.can_fetch(ROBO, url)


def coletar(nome, busca, mem):
    montar_url, ler = FONTES[nome]
    url = montar_url(busca)
    guardado = mem["paginas"].get(url)
    if guardado and time.time() - guardado["momento"] < CACHE_SEGUNDOS:
        return guardado
    resultado = {"fonte": nome, "url": url, "ofertas": [], "momento": time.time()}
    try:
        if not robots_permite(url, mem):
            resultado["status"] = "o site não permite coleta automática (robots.txt)"
            return resultado
        resposta = requests.get(url, headers=CABECALHOS, timeout=TEMPO_LOJA)
        resposta.raise_for_status()
        ofertas = ler(resposta.content, url)
    except requests.HTTPError as erro:
        resultado["status"] = f"erro HTTP {erro.response.status_code}"
        return resultado
    except requests.RequestException:
        resultado["status"] = "sem resposta"
        return resultado
    except Exception:
        resultado["status"] = "página em formato não reconhecido"
        return resultado
    vistos, unicas = set(), []
    for oferta in ofertas:
        if oferta["link"] not in vistos:
            vistos.add(oferta["link"])
            unicas.append(oferta)
    resultado["ofertas"] = unicas[:MAXIMO_POR_LOJA]
    resultado["status"] = f"{len(resultado['ofertas'])} ofertas" if unicas else "nenhuma oferta encontrada"
    resultado["coletado"] = datetime.now(FUSO).strftime("%H:%M")
    with mem["trava"]:
        mem["paginas"][url] = resultado
    return resultado


def coletar_todas(busca, mem):
    with ThreadPoolExecutor(max_workers=len(FONTES)) as executor:
        return list(executor.map(lambda nome: coletar(nome, busca, mem), FONTES))


# Exibição
def reais(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def descrever(alvo):
    modelo = alvo["modelo"] or ""
    if modelo == modelo.lower():
        modelo = exibir(modelo)
    partes = [" ".join(p for p in [alvo["marca"], modelo] if p) or "modelo buscado"]
    if alvo["armazenamento_gb"]:
        partes.append(f"{alvo['armazenamento_gb']} GB" if alvo["armazenamento_gb"] < 1000 else f"{alvo['armazenamento_gb'] // 1000} TB")
    partes.append(alvo["condicao"])
    return " · ".join(partes)


def mostrar_faixa(linhas):
    if len(linhas) < MINIMO_OFERTAS:
        st.warning(
            f"Poucas ofertas equivalentes: encontrei {len(linhas)}. "
            f"A faixa de preço só é exibida com pelo menos {MINIMO_OFERTAS} ofertas."
        )
        return
    menor, mediana, maior = st.columns(3)
    menor.metric("Menor preço", reais(linhas["preco"].min()))
    mediana.metric("Mediana", reais(statistics.median(linhas["preco"])))
    maior.metric("Maior preço", reais(linhas["preco"].max()))
    st.caption(
        f"Baseada em {len(linhas)} ofertas de {linhas['loja_base'].nunique()} lojas. "
        "É uma referência para comparação, não um preço recomendado."
    )


def tabela_de_ofertas(linhas, com_motivo=False):
    tabela = pd.DataFrame({
        "Produto": linhas["titulo"],
        "Preço": linhas["preco"].map(reais),
        "Loja": linhas["loja"],
        "Link": linhas["link"],
        "Fonte": linhas["fonte"],
    })
    if com_motivo:
        tabela.insert(1, "Motivo", linhas["motivo"])
    st.dataframe(
        tabela,
        hide_index=True,
        column_config={"Produto": st.column_config.TextColumn(width="medium"),
                       "Link": st.column_config.LinkColumn(display_text="Abrir")},
    )


def marcar_fora_do_padrao(linhas):
    """Descarta preços com menos da metade ou mais do dobro da mediana do grupo (kits, defeitos, erros)."""
    grupos = linhas["armazenamento_gb"].fillna(0).astype(int)
    for gb in grupos[linhas["motivo"].isna()].unique():
        grupo = linhas["motivo"].isna() & (grupos == gb)
        if grupo.sum() >= MINIMO_OFERTAS:
            mediana = linhas.loc[grupo, "preco"].median()
            fora = grupo & ((linhas["preco"] < mediana * 0.5) | (linhas["preco"] > mediana * 2))
            linhas.loc[fora, "motivo"] = "preço fora do padrão (menos da metade ou mais do dobro da mediana)"


def mostrar_resultados(busca, coletas, mem):
    situacao = " · ".join(f"{c['fonte']}: {c['status']}" for c in coletas)
    horarios = sorted({c["coletado"] for c in coletas if c.get("coletado")})
    st.caption(f"Lojas consultadas: {situacao}." + (f" Preços coletados às {horarios[-1]}." if horarios else ""))
    ofertas = [oferta for coleta in coletas for oferta in coleta["ofertas"]]
    if not ofertas:
        st.warning("Nenhuma loja devolveu ofertas para esta busca. Tente escrever de outro jeito ou busque de novo em alguns minutos.")
        return
    alvo, itens, origem = classificar(busca, [o["titulo"] for o in ofertas], mem)
    st.caption(f"Ofertas comparadas por **{origem}**.")
    if not alvo["modelo"]:
        st.warning("Não identifiquei o modelo na busca. Escreva a marca e o modelo, por exemplo: iPhone 13 128GB.")
        return
    linhas = pd.DataFrame(ofertas)
    linhas["motivo"] = [motivo_descarte(alvo, item) for item in itens]
    linhas["armazenamento_gb"] = [item["armazenamento_gb"] for item in itens]
    linhas["loja_base"] = linhas["loja"].str.replace(r" e mais \d+$", "", regex=True)
    marcar_fora_do_padrao(linhas)
    iguais = linhas[linhas["motivo"].isna()].sort_values("preco")
    descartadas = linhas[linhas["motivo"].notna()].sort_values("preco")
    st.subheader(f"Faixa de preço: {descrever(alvo)}")
    if alvo["armazenamento_gb"] or iguais.empty:
        mostrar_faixa(iguais)
    else:
        resumo = []
        for gb, grupo in iguais.groupby(iguais["armazenamento_gb"].fillna(0).astype(int)):
            resumo.append({
                "Armazenamento": f"{gb} GB" if gb else "não informado",
                "Ofertas": len(grupo),
                "Menor": reais(grupo["preco"].min()) if len(grupo) >= MINIMO_OFERTAS else "poucas ofertas",
                "Mediana": reais(statistics.median(grupo["preco"])) if len(grupo) >= MINIMO_OFERTAS else "",
                "Maior": reais(grupo["preco"].max()) if len(grupo) >= MINIMO_OFERTAS else "",
            })
        st.write("A busca não informou o armazenamento. Faixa por armazenamento:")
        st.table(pd.DataFrame(resumo), hide_index=True)
    if not iguais.empty:
        st.subheader("Ofertas equivalentes")
        tabela_de_ofertas(iguais)
    with st.expander(f"Ofertas descartadas ({len(descartadas)})"):
        if descartadas.empty:
            st.write("Nenhuma oferta foi descartada.")
        else:
            tabela_de_ofertas(descartadas, com_motivo=True)


# Validação
CORRECOES = [
    ("epone 13", "iphone 13"), ("aifone 15 pro max", "iphone 15 pro max"), ("galaxi a17", "galaxy a17"),
    ("sansung galaxi s24", "samsung galaxy s24"), ("motorolla moto g06", "motorola moto g06"),
    ("xiaome redmi 15c", "xiaomi redmi 15c"), ("iphone13 128 gigas", "iphone 13 128gb"),
    ("galaxy a17 128g", "galaxy a17 128gb"), ("ifone 11", "iphone 11"), ("redimi note 14", "redmi note 14"),
    ("motorola edje 60 fusion", "motorola edge 60 fusion"), ("samsumg a56", "samsung a56"),
    ("iphon 16", "iphone 16"), ("galaxy s25 ultra", "galaxy s25 ultra"), ("moto g06", "moto g06"),
    ("pocco x7 pro", "poco x7 pro"), ("realmi c75", "realme c75"), ("motorla razr 60", "motorola razr 60"),
    ("xaomi poco f7", "xiaomi poco f7"), ("ipone 14 plus", "iphone 14 plus"),
]


def erros_simulados(quantidade=40, semente=7):
    sorteio = random.Random(semente)
    palavras = [p for p in VOCABULARIO if len(p) >= 5]
    letras = "abcdefghijklmnopqrstuvwxyz"
    erros = []
    while len(erros) < quantidade:
        palavra = sorteio.choice(palavras)
        posicao = sorteio.randrange(len(palavra) - 1)
        tipo = sorteio.choice(["troca", "falta", "sobra", "inverte"])
        if tipo == "troca":
            errada = palavra[:posicao] + sorteio.choice(letras) + palavra[posicao + 1:]
        elif tipo == "falta":
            errada = palavra[:posicao] + palavra[posicao + 1:]
        elif tipo == "sobra":
            errada = palavra[:posicao] + sorteio.choice(letras) + palavra[posicao:]
        else:
            errada = palavra[:posicao] + palavra[posicao + 1] + palavra[posicao] + palavra[posicao + 2:]
        if errada != palavra and errada not in VOCABULARIO:
            erros.append((errada, palavra))
    return erros


def rotulo_teste(modelo, armazenamento, condicao):
    return {"modelo": modelo, "armazenamento_gb": armazenamento, "condicao": condicao}


CHAVES_MODELOS = {chave_modelo(m): m for m in MODELOS}


def como_rotulo(item):
    modelo = CHAVES_MODELOS.get(chave_modelo(item["modelo"])) if item["celular"] and item["modelo"] else None
    return rotulo_teste(modelo, item["armazenamento_gb"], item["condicao"])


def mostrar_validacao():
    st.write("**Correção de digitação**")
    acertos_lista = sum(corrigir_busca(errada)[0] == certa for errada, certa in CORRECOES)
    simulados = erros_simulados()
    acertos_simulados = sum(corrigir_palavra(errada) == certa for errada, certa in simulados)
    st.write(
        f"Erros comuns escritos pela equipe: {acertos_lista} de {len(CORRECOES)} buscas corrigidas. "
        f"Erros simulados (uma letra trocada, faltando, sobrando ou invertida): "
        f"{acertos_simulados} de {len(simulados)} palavras corrigidas."
    )
    st.write("**Extração de atributos nos 50 títulos de teste**")
    total = len(TITULOS_TESTE)
    acertos_regras = 0
    for titulo, modelo, armazenamento, condicao in TITULOS_TESTE:
        extraido = extrair_por_regras(titulo)
        acertos_regras += rotulo_teste(extraido["modelo"], extraido["armazenamento_gb"], extraido["condicao"]) == rotulo_teste(modelo, armazenamento, condicao)
    st.write(f"Regras: {acertos_regras} de {total} títulos corretos ({acertos_regras / total:.0%}).")
    if LLM_CHAVE and st.button("Medir o LLM nos 50 títulos (uma chamada)"):
        inicio = time.perf_counter()
        try:
            itens, modelo = classificar_por_llm([t[0] for t in TITULOS_TESTE])
            acertos = sum(como_rotulo(i) == rotulo_teste(*t[1:]) for i, t in zip(itens, TITULOS_TESTE))
            st.session_state.medicao_llm = (
                f"LLM ({modelo}): {acertos} de {total} títulos corretos ({acertos / total:.0%}), "
                f"em {time.perf_counter() - inicio:.1f} s. Diferença para as regras: "
                f"{(acertos - acertos_regras) / total * 100:.0f} pontos percentuais."
            )
        except Exception as erro:
            st.session_state.medicao_llm = f"Não foi possível medir o LLM agora ({type(erro).__name__})."
    if "medicao_llm" in st.session_state:
        st.write(st.session_state.medicao_llm)


# Interface
def usar_exemplo(texto):
    st.session_state.update(campo_busca=texto, digitado=texto, sem_correcao=False)


def buscar_como_digitado():
    st.session_state.sem_correcao = True


st.set_page_config(page_title="Faixa Certa")
st.title("Faixa Certa")
st.write("Compara o preço de um smartphone em várias lojas, com preços buscados na hora.")
st.caption(f"Extrator principal: {'LLM' if LLM_CHAVE else 'regras (sem chave de IA configurada)'}. Fontes: {', '.join(FONTES)}.")

with st.form("busca"):
    st.text_input("Qual celular você procura?", placeholder="Ex.: iphone 13 128gb", key="campo_busca")
    if st.form_submit_button("Buscar", type="primary"):
        st.session_state.update(digitado=st.session_state.campo_busca, sem_correcao=False)

st.write("Exemplos:")
colunas = st.columns(3)
for coluna, exemplo in zip(colunas, ["epone 13 128gb", "galaxi a17 128gb", "motorolla moto g06"]):
    coluna.button(exemplo, on_click=usar_exemplo, args=(exemplo,), width="stretch")

digitado = (st.session_state.get("digitado") or "").strip()
if digitado:
    if st.session_state.get("sem_correcao"):
        busca, mudou = limpar(digitado), False
    else:
        busca, mudou = corrigir_busca(digitado)
    if mudou:
        st.info(f"Você quis dizer **{exibir(busca)}**? Mostrando resultados para a busca corrigida.")
        st.button(f"Buscar “{digitado}” como digitei", on_click=buscar_como_digitado)
    mem = memoria()
    with st.spinner(f"Buscando “{exibir(busca)}” nas lojas..."):
        coletas = coletar_todas(busca, mem)
        mostrar_resultados(busca, coletas, mem)

with st.expander("Validação"):
    mostrar_validacao()
