"""Faixa Certa: compara preços de smartphones em várias lojas, com busca na hora e correção de digitação."""

import difflib
import hashlib
import json
import os
import re
import statistics
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import parse_qs, parse_qsl, quote, quote_plus, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from lxml import html

USER_AGENT = "Mozilla/5.0 (compatible; FaixaCerta/1.0; +https://github.com/KevinCostaAI/faixa-certa)"
ROBO = "FaixaCerta"
TEMPO_LOJA = 10  # segundos de espera por loja
TEMPO_LLM = 12  # segundos, no total, para o LLM classificar os títulos de uma busca; depois disso, o app segue por regras
LOTE_LLM = 15  # títulos por chamada ao LLM; com mais títulos, as chamadas são feitas em paralelo
CACHE_SEGUNDOS = 15 * 60  # o resultado de uma busca bem-sucedida é reutilizado por 15 minutos e depois apagado
MINIMO_OFERTAS = 3  # abaixo disso, a faixa de preço não é exibida
MAXIMO_POR_LOJA = 30
FUSO = ZoneInfo("America/Fortaleza")
COMPARELIVRE = os.environ.get("COMPARELIVRE_URL", "https://comparelivre.com.br").rstrip("/")
KABUM = os.environ.get("KABUM_URL", "https://www.kabum.com.br").rstrip("/")
GAZIN = os.environ.get("GAZIN_URL", "https://www.gazin.com.br").rstrip("/")
NOVOMUNDO = os.environ.get("NOVOMUNDO_URL", "https://www.novomundo.com.br").rstrip("/")


def configuracao(nome, padrao=None):
    """Valor de uma variável de ambiente ou dos Secrets do Streamlit (ex.: LLM_API_KEY, LLM_MODEL)."""
    valor = os.environ.get(nome)
    if valor:
        return valor
    try:
        return st.secrets.get(nome) or padrao
    except Exception:
        return padrao


# O provedor de IA vem da chave: as do Groq começam com "gsk_"; as demais usam o Gemini.
# LLM_BASE_URL, LLM_MODEL e LLM_MODEL_FALLBACK nos Secrets trocam o provedor ou o modelo sem mudar o código.
LLM_CHAVE = configuracao("LLM_API_KEY")
GROQ = str(LLM_CHAVE or "").startswith("gsk_")
LLM_URL = configuracao("LLM_BASE_URL", "https://api.groq.com/openai/v1" if GROQ
                       else "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
LLM_MODELO = configuracao("LLM_MODEL", "openai/gpt-oss-120b" if GROQ else "gemini-3.1-flash-lite")
LLM_MODELO_RESERVA = configuracao("LLM_MODEL_FALLBACK", "openai/gpt-oss-20b" if GROQ else "gemini-3.5-flash-lite")


CONDICOES = ["novo", "usado", "recondicionado"]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto).casefold())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def condicao_por_regras(t):
    if re.search(r"\b(?:recondicionad[oa]|refurbished|remanufaturad[oa])\b", t):
        return "recondicionado"
    if re.search(r"\b(?:usad[oa]|semi\s*-?nov[oa]|vitrine|mostruario|excelente|bom estado)\b", t):
        return "usado"
    return "novo"


# Correção de digitação da busca
MARCAS = {
    "apple", "samsung", "motorola", "xiaomi", "realme", "asus", "nokia", "oppo", "honor", "huawei",
    "google", "infinix", "tecno", "itel", "multilaser", "positivo", "sony", "oneplus", "lenovo", "lg",
    "zte", "nubia", "tcl", "semp", "alcatel", "philco", "nothing", "vivo", "jovi", "iqoo", "meizu", "blu",
    "hmd", "fairphone", "blackview", "ulefone", "doogee", "oukitel", "cubot", "umidigi",
}
LINHAS = {
    "iphone", "galaxy", "moto", "redmi", "poco", "edge", "razr", "pixel", "zenfone", "note",
    "fusion", "neo", "narzo", "reno", "magic", "spark", "camon", "pova", "fold", "flip", "xperia", "nord",
    "phone", "blade", "axon", "twist", "phantom", "xcover",
}
VARIANTES = {"pro", "max", "plus", "mini", "ultra", "lite", "fe", "prime", "power", "play", "stylus", "se"}
VOCABULARIO = sorted(MARCAS | LINHAS | VARIANTES)
APELIDOS = {
    "aifone": "iphone", "aifon": "iphone", "ifone": "iphone", "ifon": "iphone", "iphon": "iphone",
    "ipone": "iphone", "epone": "iphone", "iphome": "iphone", "eiphone": "iphone",
    "galaxi": "galaxy", "galax": "galaxy", "galaxe": "galaxy", "galacsi": "galaxy",
    "sansung": "samsung", "samsumg": "samsung", "samsun": "samsung", "sansumg": "samsung", "sanzung": "samsung",
    "motorolla": "motorola", "motorla": "motorola", "mottorola": "motorola",
    "xiaome": "xiaomi", "xiaomy": "xiaomi", "xaomi": "xiaomi", "xiomi": "xiaomi", "chaomi": "xiaomi",
    "shaomi": "xiaomi", "xaiomi": "xiaomi", "redimi": "redmi", "redme": "redmi", "pocco": "poco",
    "realmi": "realme", "realmy": "realme", "nokya": "nokia", "hauwei": "huawei", "huawai": "huawei",
    "opo": "oppo", "filco": "philco", "infinity": "infinix", "infinics": "infinix",
}
NEUTRAS = {
    "de", "da", "do", "das", "dos", "com", "sem", "para", "e", "o", "a", "os", "as", "em", "no", "na",
    "celular", "smartphone", "telefone", "aparelho", "novo", "nova", "usado", "usada", "seminovo", "seminova",
    "recondicionado", "recondicionada", "vitrine", "preto", "preta", "branco", "branca", "azul", "verde",
    "rosa", "roxo", "roxa", "vermelho", "vermelha", "amarelo", "amarela", "cinza", "prata", "prateado",
    "dourado", "dourada", "grafite", "titanio", "meia", "noite", "estelar", "lilas", "creme", "bege",
    "laranja", "ram", "dual", "chip", "tela", "camera", "bateria", "original", "lacrado", "barato",
    "barata", "promocao", "oferta", "esim", "black", "white", "blue", "green", "gold", "silver", "pink",
    "purple", "gray", "grey", "midnight", "starlight", "teal", "anatel", "homologado", "sempre", "fone", "fones",
    "intel", "nota", "fiscal", "preco", "pouco", "pouca", "prova", "display", "amazon", "infinito", "infinita",
    "cubo", "mint", "lime", "fonte", "fontes", "envio", "space", "foto", "fotos", "oled", "amoled", "real", "reais",
    "primeira", "primeiro", "nome", "rede", "topo", "prazo", "lento", "poeira",
}
# Palavras de quem descreve o celular sem dizer o modelo ("celular mais barato para idoso"): não são modelo nem erro.
PEDIDOS = {
    "mais", "menos", "muito", "muita", "bem", "bom", "boa", "bons", "boas", "melhor", "melhores", "menor", "maior",
    "um", "uma", "uns", "umas", "meu", "minha", "meus", "minhas", "pra", "por", "ate", "que", "qual", "quais",
    "quero", "queria", "procuro", "procurando", "preciso", "comprar", "celulares", "smartphones", "telefones",
    "aparelhos", "cel", "cell", "baratos", "baratas", "baratinho", "baratinha", "economico", "economica", "simples",
    "basico", "basica", "facil", "idoso", "idosa", "idosos", "idosas", "vovo", "avo", "mae", "pai", "filho", "filha",
    "custo", "beneficio", "valor",
}
NEUTRAS |= PEDIDOS
EXIBIR = {
    "iphone": "iPhone", "moto": "Moto", "rog": "ROG", "oneplus": "OnePlus", "fe": "FE", "lg": "LG",
    "zte": "ZTE", "tcl": "TCL", "hmd": "HMD", "blu": "BLU", "iqoo": "iQOO", "xcover": "XCover", "se": "SE",
    "gt": "GT", "hot": "Hot",
}
ARMAZENAMENTOS_BUSCA = {32, 64, 128, 256, 512, 1000, 2000}


def separar(texto):
    texto = re.sub(r"\bone\s+plus\b", "oneplus", texto)
    texto = re.sub(r"\bi\s+(phone|fone|pone)\b", r"i\1", texto)
    texto = re.sub(r"\b([45]g)(?=\d)", r"\1 ", texto)  # "4G128GB" = "4g 128gb"
    texto = re.sub(r"\b(iphone|galaxy|redmi|moto|edge|note|pixel|poco|razr)(?=\d)", r"\1 ", texto)
    texto = re.sub(r"\bgalaxy(?=[asmzf]\d)", "galaxy ", texto)
    texto = re.sub(r"\b([a-z]{4,})(\d+)\b", r"\1 \2", texto)
    texto = re.sub(r"(?<![\d.,])(16|32|64|128|256|512)\s*(?:gb|g|gigas?|gigabytes?)\b", r"\1gb", texto)
    texto = re.sub(r"(?<![\d.,])([12])\s*(?:tb|teras?|terabytes?)\b", r"\1tb", texto)
    return " ".join(texto.split())


def limpar(texto):
    return separar(re.sub(r"[^\w\s]", " ", normalizar(texto)))


def som(palavra):
    """Aproxima a pronúncia em português, para achar erros de quem escreve como fala ("efone", "sansung", "pixeu")."""
    p = re.sub(r"(.)\1+", r"\1", palavra)                 # letras dobradas: motorolla, honnor
    for escrita, pronuncia in (("ph", "f"), ("sh", "x"), ("ch", "x"), ("qu", "c"), ("ck", "c"), ("x", "cs")):
        p = p.replace(escrita, pronuncia)
    p = p.translate(str.maketrans("ykwz", "icus"))
    p = re.sub(r"^h", "", p)                              # h inicial não soa: huawei
    p = re.sub(r"^(?:ai|ei|e)(?=[^aeiou])", "i", p)       # "i" dito "ai" ou escrito "e": aifone, efone
    p = re.sub(r"m(?=[^aeiou])", "n", p)                  # sansung = samsung
    p = re.sub(r"l(?=[^aeiou]|$)", "u", p)                # aucatel = alcatel, pixeu = pixel
    p = re.sub(r"e$", "i", p)                             # realmi = realme
    return re.sub(r"(.)\1+", r"\1", p)


SONS = {palavra: som(palavra) for palavra in VOCABULARIO if len(palavra) >= 4}


def parecida(palavra):
    """Palavra do vocabulário mais parecida: na escrita (nota >= 0,72) ou no som (nota >= 0,80). No empate, vale o som."""
    som_digitado = som(palavra)
    notas = []
    for candidata in VOCABULARIO:
        escrita = difflib.SequenceMatcher(None, palavra, candidata).ratio()
        pronuncia = difflib.SequenceMatcher(None, som_digitado, SONS[candidata]).ratio() if candidata in SONS else 0
        if escrita >= 0.72 or pronuncia >= 0.80:
            notas.append((max(escrita, pronuncia), pronuncia, candidata))
    return max(notas)[2] if notas else None


def corrigir_palavra(palavra):
    if palavra in APELIDOS:
        return APELIDOS[palavra]
    if palavra in VOCABULARIO or palavra in NEUTRAS or len(palavra) < 4 or any(c.isdigit() for c in palavra):
        return palavra
    return parecida(palavra) or palavra


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
    r"carteira)(?:e?s)?\b|\bpara\s+(?:iphone|galaxy|samsung|motorola|moto|xiaomi|redmi|poco)\b|\bcompativel\b"
)


# Aparelho com defeito, bloqueio ou função indisponível anunciados no título fica fora da faixa de aparelhos funcionais.
# Vale para o LLM e para as regras. Termos como "desbloqueado", "livre de iCloud" e "garantia contra defeitos" não contam.
DEFEITO = re.compile(
    r"\bcom\s+defeitos?\b|\bdefeitos?\s+n[ao]s?\b|\bdefeituos[oa]s?\b|\bapresenta\s+defeito|\bavariad[oa]s?\b|"
    r"\b(?:tela|vidro|traseira|camera)\s+(?:quebrad|trincad|rachad|queimad)[oa]s?\b|\b(?:quebrad|trincad|rachad)[oa]s?\b|"
    r"\bmanchas?\s+na\s+tela\b|\bnao\s+(?:liga|funciona|carrega|reconhece)\b|\bsem\s+funcionar\b|"
    r"\bsem\s+(?:face\s*id|touch\s*id|biometria)\b|\b(?:retirada|retirar)\s+(?:de\s+)?pecas\b|\bpara\s+pecas\b|\bsucata\b|"
    r"\bbloquead[oa]s?\b|\bicloud\s+(?:bloqueado|ativo|vinculado)\b|\bcom\s+icloud\b|"
    r"\bconta\s+google\s+(?:bloqueada|vinculada|ativa)\b|\bimei\s+bloqueado\b"
)


def defeito_anunciado(titulo):
    return bool(DEFEITO.search(normalizar(re.sub(r"[^\w\s]", " ", titulo or ""))))


# Linhas que muita gente omite ao digitar: todo Samsung é Galaxy ("samsung a56") e "motorola g06" é o Moto G06.
LINHAS_IMPLICITAS = {"galaxy", "moto"}


def chave_modelo(modelo, sem_rede=False):
    """Chave para comparar modelos. "4G" nunca muda o modelo (Galaxy A17 4G = Galaxy A17); "5G" só é ignorado com sem_rede."""
    palavras = [p for p in limpar(modelo or "").split()
                if p not in MARCAS and p not in LINHAS_IMPLICITAS and p != "4g" and not (sem_rede and p == "5g")]
    return re.sub(r"[^a-z0-9]", "", "".join(palavras))


# Submarcas contam como a fabricante (ex.: um POCO é um Xiaomi).
MARCA_PRINCIPAL = {"poco": "xiaomi", "redmi": "xiaomi", "iqoo": "vivo", "jovi": "vivo", "nubia": "zte",
                   "redmagic": "zte", "semp": "tcl", "semptcl": "tcl"}


def chave_marca(marca):
    chave = re.sub(r"[^a-z0-9]", "", normalizar(marca or ""))
    return MARCA_PRINCIPAL.get(chave, chave)


def palavras_do_modelo(busca):
    return [
        p for p in busca.split()
        if p not in NEUTRAS and p not in MARCAS and p != "4g" and not re.fullmatch(r"\d+(?:gb|tb)", p)
    ]


def falta_modelo(busca):
    """Busca só com marca, linha ou rede ("iphone", "samsung galaxy", "smartphone 5g"): são vários modelos,
    então não existe uma faixa de preço."""
    return all(p in VOCABULARIO and p != "se" for p in palavras_do_modelo(busca) if p != "5g")


def menciona_o_modelo(titulo, busca):
    """O título cita os números do modelo buscado (ex.: "a17" em "Galaxy A17")? Sem eles não pode ser o mesmo
    modelo, e o título nem vai para o LLM: com mais lojas, isso evita chamadas demais e deixa a resposta mais rápida."""
    codigos = [p for p in palavras_do_modelo(busca) if re.search(r"\d", p) and p != "5g"]
    compacto = re.sub(r"[^a-z0-9]", "", limpar(titulo))
    return all(codigo in compacto for codigo in codigos)


# Linhas que já dizem a marca: quem escreve "galaxy" quer um Samsung; "iphone", um Apple.
MARCA_DA_LINHA = {
    "iphone": "apple", "galaxy": "samsung", "xcover": "samsung", "moto": "motorola", "razr": "motorola",
    "redmi": "xiaomi", "poco": "xiaomi", "pixel": "google", "zenfone": "asus", "xperia": "sony", "narzo": "realme",
    "reno": "oppo", "spark": "tecno", "camon": "tecno", "pova": "tecno", "nord": "oneplus", "blade": "zte",
    "axon": "zte", "twist": "positivo",
}


def marca_em(texto):
    """Primeira marca citada no texto, escrita direto ("samsung") ou pela linha ("galaxy")."""
    for palavra in limpar(texto or "").split():
        if palavra in MARCAS:
            return palavra
        if palavra in MARCA_DA_LINHA:
            return MARCA_DA_LINHA[palavra]
    return None


def rede_em(texto):
    """Versão de rede citada no texto: "5g", "4g" ou None. Vale o texto todo, não só a palavra depois do modelo,
    porque muita loja escreve "Galaxy A17 128GB 5G"."""
    palavras = limpar(texto or "").split()
    return "5g" if "5g" in palavras else "4g" if "4g" in palavras else None


def marca_no_titulo(titulo, marca_pedida):
    """Marca escrita no título, pelo nome ou pela linha ("Galaxy" = Samsung). Sem ela escrita, None:
    a marca deduzida pelo LLM não confirma o anúncio."""
    achada = marca_em(titulo)
    if achada:
        return achada
    if marca_pedida and chave_marca(marca_pedida) in limpar(titulo).split():
        return marca_pedida
    return None


def classificar_por_regras(busca, titulos):
    palavras = palavras_do_modelo(busca)
    base = [p for p in palavras if p != "5g"]
    alvo = {
        "celular": True,
        "marca": marca_em(busca),
        "modelo": " ".join(palavras) or None,
        "armazenamento_gb": armazenamento_em(busca),
        "condicao": condicao_em(busca),
    }
    if not base:
        return alvo, [dict(alvo, modelo=None, marca=marca_em(titulo)) for titulo in titulos]
    partes = [r"\s*".join(re.escape(pedaco) for pedaco in re.findall(r"[a-z]+|\d+", p)) for p in base]
    proibidas = sorted(VARIANTES - set(base))
    padrao = re.compile(r"\b" + r"[\s-]*".join(partes) + r"\b(?![\s-]*(?:" + "|".join(proibidas) + r")\b)")
    itens = []
    for titulo in titulos:
        texto = limpar(titulo)
        # O nome bateu: o modelo é o da busca, com "5g" quando o título é da versão 5G.
        modelo = " ".join(base + (["5g"] if rede_em(texto) == "5g" else [])) if padrao.search(texto) else "outro modelo"
        itens.append({
            "celular": not ACESSORIO.search(texto),
            "marca": marca_em(texto),
            "modelo": modelo,
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


def chamar_llm(textos, modelo, formato_json=True, tempo=TEMPO_LLM, rapido=True):
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
    if "gpt-oss" in modelo:
        corpo["reasoning_effort"] = "low"  # modelos com raciocínio (Groq): menos tokens e resposta mais rápida
    elif rapido and "gemini" in modelo:
        # No Gemini 3 o raciocínio não desliga; no nível mínimo, a classificação dos títulos sai bem mais rápido.
        corpo["reasoning_effort"] = "minimal"
    return requests.post(
        f"{LLM_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_CHAVE}"},
        json=corpo,
        timeout=tempo,
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


def classificar_por_llm(textos, tempo=TEMPO_LLM):
    """Tenta o modelo principal duas vezes e, se ele estiver sobrecarregado, o modelo reserva. Tudo cabe em `tempo`
    segundos: cada chamada só usa o tempo que sobrou, e o que passar disso segue por regras."""
    inicio = time.monotonic()
    resta = lambda: tempo - (time.monotonic() - inicio)
    ultima = None
    for modelo in dict.fromkeys([LLM_MODELO, LLM_MODELO_RESERVA]):
        for _ in range(2):
            if resta() < 1.5:
                break
            resposta = chamar_llm(textos, modelo, tempo=resta())
            if resposta.status_code == 400 and resta() >= 1.5:
                # Pedido recusado: repete sem o formato JSON e sem o nível de raciocínio, que nem todo modelo aceita.
                resposta = chamar_llm(textos, modelo, formato_json=False, tempo=resta(), rapido=False)
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


def classificar_em_lotes(busca, titulos, tempo=TEMPO_LLM):
    """Manda a busca e até LOTE_LLM títulos por chamada, com as chamadas em paralelo."""
    lotes = [list(titulos[i:i + LOTE_LLM]) for i in range(0, len(titulos), LOTE_LLM)] or [[]]
    with ThreadPoolExecutor(max_workers=len(lotes)) as executor:
        respostas = list(executor.map(lambda lote: classificar_por_llm([busca] + lote, tempo), lotes))
    itens = [item for resposta, _ in respostas for item in resposta[1:]]
    return respostas[0][0][0], itens, ", ".join(dict.fromkeys(modelo for _, modelo in respostas))


def detalhe_do_erro(resposta):
    try:
        dados = resposta.json()
        dados = dados[0] if isinstance(dados, list) else dados
        return str(dados.get("error", {}).get("message", ""))[:80]
    except Exception:
        return ""


@st.cache_resource
def memoria():
    """Guarda entre as buscas as páginas coletadas, as regras dos robots.txt e as classificações do LLM."""
    return {"paginas": {}, "robots": {}, "classificacoes": {}, "trava": threading.Lock()}


def classificar(busca, titulos, mem):
    if LLM_CHAVE:
        chave = (busca, tuple(titulos))
        guardado = mem["classificacoes"].get(chave)
        if guardado and time.time() - guardado[0] < CACHE_SEGUNDOS:
            return guardado[1][0], guardado[1][1:], f"LLM ({guardado[2]})"
        try:
            alvo, itens, modelo = classificar_em_lotes(busca, titulos)
            mem["classificacoes"][chave] = (time.time(), [alvo] + itens, modelo)
            return alvo, itens, f"LLM ({modelo})"
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


def motivo_descarte(alvo, item, sem_rede=False):
    if not item["celular"]:
        return "acessório ou outro produto"
    if item.get("defeito"):
        return "defeito anunciado"
    if alvo.get("rede") and item.get("rede") and item["rede"] != alvo["rede"]:
        return f"outra versão ({item['rede'].upper()})"
    # Com 4G ou 5G na busca, a rede é conferida à parte, e o modelo é comparado sem ela.
    sem_rede = sem_rede or bool(alvo.get("rede"))
    if not item["modelo"] or chave_modelo(item["modelo"], sem_rede) != chave_modelo(alvo["modelo"], sem_rede):
        return "outro modelo"
    # Marca, rede e armazenamento pedidos precisam estar escritos no anúncio.
    if alvo["marca"] and not item["marca"]:
        return "marca não informada no anúncio"
    if alvo["marca"] and chave_marca(alvo["marca"]) != chave_marca(item["marca"]):
        return "outra marca"
    if alvo.get("rede") and not item.get("rede"):
        return f"versão ({alvo['rede'].upper()}) não informada no anúncio"
    if not item["armazenamento_gb"]:
        return "armazenamento não informado no anúncio"
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


LOJAS_CONHECIDAS = {
    "mercadolivre": "Mercado Livre", "shopee": "Shopee", "amazon": "Amazon", "magazineluiza": "Magazine Luiza",
    "casasbahia": "Casas Bahia", "americanas": "Americanas", "kabum": "KaBuM!", "carrefour": "Carrefour",
    "fastshop": "Fast Shop", "pontofrio": "Ponto", "extra": "Extra", "aliexpress": "AliExpress",
    "gazin": "Gazin", "novomundo": "Novo Mundo",
}


def nome_da_loja(url):
    dominio = urlparse(url).netloc.lower().removeprefix("www.")
    return next((nome for chave, nome in LOJAS_CONHECIDAS.items() if chave in dominio.split(".")), dominio)


def ler_comparelivre(conteudo, url):
    arvore = html.fromstring(conteudo)
    ofertas = []
    for cartao in arvore.xpath('//a[starts-with(@href, "/p/")]'):
        titulo = cartao.xpath("normalize-space(string(.//h4))") or cartao.xpath("normalize-space(string(.//h3))")
        preco = preco_brl(cartao.xpath('normalize-space(string(.//*[contains(@class, "price")]))'))
        if preco is None:
            preco = preco_brl(cartao.text_content())
        if not titulo or not preco_valido(preco):
            continue
        pagina = urljoin(url, cartao.get("href"))
        # O botão "ir à loja" ao lado do cartão traz o endereço da loja no parâmetro u.
        botao = cartao.xpath('following-sibling::a[1][contains(@class, "gostore")]/@href')
        destino = parse_qs(urlparse(botao[0]).query).get("u", [""])[0] if botao else ""
        if not destino.startswith(("https://", "http://")):
            destino = ""
        lojas = cartao.xpath('normalize-space(string(.//*[contains(@class, "noffers")]))')
        quantidade = re.search(r"(\d+)\s+lojas?", lojas, re.I)
        total = int(quantidade[1]) if quantidade else 1
        loja = lojas.split("·", 1)[1].strip() if "·" in lojas else (nome_da_loja(destino) if destino else "")
        if not loja:
            loja = f"{total} lojas" if total > 1 else "Loja não informada"
        elif total > 1:
            loja = f"{loja} e mais {total - 1}"
        # O cartão do Compare Livre mostra só "a partir de", sem dizer se o preço é à vista ou parcelado.
        ofertas.append({"titulo": titulo, "preco": preco, "loja": loja, "fonte": "Compare Livre",
                        "link": destino or pagina, "pagina": pagina, "pagamento": "não informada"})
    return ofertas


def preco_da_campanha(produto, agora=None):
    """Preço de uma campanha da KaBuM! que está valendo para todos: é o preço que o site mostra no lugar do normal.
    Campanha exclusiva de assinante (Prime) ou de cliente logado não conta, porque não vale para qualquer comprador."""
    oferta = produto.get("offer")
    if not isinstance(oferta, dict) or oferta.get("isPrimeExclusive") or oferta.get("isLoggedUserExclusive"):
        return None
    agora = time.time() if agora is None else agora
    comeco, fim = numero(oferta.get("startsAt")), numero(oferta.get("endsAt"))
    if (comeco and agora < comeco) or (fim and agora > fim) or numero(oferta.get("quantityAvailable")) == 0:
        return None
    preco = numero(oferta.get("priceWithDiscount"))
    if not preco_valido(preco):
        preco = numero(oferta.get("price"))
    return preco if preco_valido(preco) else None


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
                pilha.extend(reversed(atual))  # invertido para sair na ordem da página (os mais relevantes primeiro)
            elif isinstance(atual, dict):
                pilha.extend(reversed(list(atual.values())))
                if not (isinstance(atual.get("name"), str) and atual.get("code") and "price" in atual):
                    continue
                if atual.get("available") is False:
                    continue
                # O site mostra "No PIX ou 10x de R$ ...": priceWithDiscount é o preço no Pix; price é o total em 10x.
                # O preço Prime (primePrice) é de assinatura e não entra.
                preco, pagamento = preco_da_campanha(atual) or numero(atual.get("priceWithDiscount")), "Pix"
                if not preco_valido(preco):
                    preco, pagamento = numero(atual.get("price")), "não informada"
                if preco_valido(preco):
                    link = f"{KABUM}/produto/{atual['code']}/{atual.get('friendlyName') or ''}".rstrip("/")
                    ofertas.append({"titulo": atual["name"].strip(), "preco": preco, "loja": atual.get("sellerName") or "KaBuM!",
                                    "fonte": "KaBuM!", "link": link, "pagina": link, "pagamento": pagamento})
    return ofertas


def arvore_utf8(conteudo):
    """Lê a página como UTF-8: sem isso, páginas que não declaram a codificação mostram "CÃ¢mera" em vez de "Câmera"."""
    try:
        return html.fromstring(conteudo.decode("utf-8", errors="replace") if isinstance(conteudo, bytes) else conteudo)
    except ValueError:
        return html.fromstring(conteudo)


def dados_next(conteudo):
    """JSON que as páginas feitas em Next.js trazem no script __NEXT_DATA__."""
    bloco = arvore_utf8(conteudo).xpath('//script[@id="__NEXT_DATA__"]/text()')
    return json.loads(bloco[0]) if bloco else {}


def campo(dados, *chaves):
    for chave in chaves:
        dados = dados.get(chave) if isinstance(dados, dict) else None
    return dados


def ler_gazin(conteudo, url):
    ofertas = []
    for produto in campo(dados_next(conteudo), "props", "pageProps", "resultadosBusca", "products") or []:
        preco = numero(produto.get("price"))
        # Produto indisponível vem com preço antigo: fica de fora.
        if produto.get("status") != "AVAILABLE" or not produto.get("name") or not produto.get("url") or not preco_valido(preco):
            continue
        link = GAZIN + produto["url"]
        # A Gazin mostra o preço "No Pix"; o parcelado tem total maior.
        ofertas.append({"titulo": produto["name"].strip(), "preco": preco, "loja": "Gazin", "fonte": "Gazin",
                        "link": link, "pagina": link, "pagamento": "Pix"})
    return ofertas


def ler_novomundo(conteudo, url):
    """Lê a lista de produtos em JSON-LD (schema.org), que traz só os resultados da busca, sem as sugestões."""
    ofertas = []
    for bloco in arvore_utf8(conteudo).xpath('//script[@type="application/ld+json"]/text()'):
        try:
            dados = json.loads(bloco)
        except ValueError:
            continue
        if not isinstance(dados, dict) or dados.get("@type") != "ItemList":
            continue
        for elemento in dados.get("itemListElement") or []:
            produto = elemento.get("item", elemento) if isinstance(elemento, dict) else {}
            oferta = produto.get("offers") or {}
            oferta = (oferta[0] if oferta else {}) if isinstance(oferta, list) else oferta
            preco = numero(oferta.get("price"))
            if "OutOfStock" in str(oferta.get("availability", "")) or not produto.get("name") or not produto.get("url") or not preco_valido(preco):
                continue
            link = urljoin(url, produto["url"])
            # A Novo Mundo mostra o preço "Por" e parcela só com juros: o preço "Por" é o à vista.
            ofertas.append({"titulo": produto["name"].strip(), "preco": preco, "loja": "Novo Mundo", "fonte": "Novo Mundo",
                            "link": link, "pagina": link, "pagamento": "à vista"})
    return ofertas


FONTES = {
    "Compare Livre": (lambda busca: f"{COMPARELIVRE}/busca?q={quote_plus(busca)}", ler_comparelivre),
    "KaBuM!": (lambda busca: f"{KABUM}/busca/{quote('-'.join(busca.split()))}", ler_kabum),
    "Gazin": (lambda busca: f"{GAZIN}/busca/{quote('-'.join(busca.split()))}", ler_gazin),
    "Novo Mundo": (lambda busca: f"{NOVOMUNDO}/busca?busca={quote(busca)}", ler_novomundo),
}
CABECALHOS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "pt-BR,pt;q=0.9"}
# O Compare Livre às vezes devolve só capinhas e películas para o nome do modelo (ex.: "moto g06").
# Por isso, nele a busca também é feita com "smartphone" na frente, e os resultados são somados.
BUSCA_COM_SMARTPHONE = {"Compare Livre"}
TIPOS_DE_APARELHO = {"celular", "smartphone", "telefone", "aparelho"}


NAO_RESERVADOS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def normalizar_caminho(caminho):
    """Forma de comparar caminhos do RFC 9309: caracteres fora do ASCII (como acentos) viram %XX em UTF-8,
    os %xx ficam em maiúsculas e os que só codificam letras, números ou -._~ voltam a ser o próprio caractere."""
    codificado = "".join(c if ord(c) < 128 else "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in caminho)
    return re.sub(r"%([0-9A-Fa-f]{2})",
                  lambda m: chr(int(m[1], 16)) if chr(int(m[1], 16)) in NAO_RESERVADOS else "%" + m[1].upper(), codificado)


def regras_do_robots(texto):
    """Lê o robots.txt como manda o RFC 9309: junta todos os grupos do nosso robô ou, se não houver, todos os de *."""
    grupos, grupo, lendo_agentes = [], None, False
    for linha in texto.splitlines():
        campo, _, valor = linha.split("#", 1)[0].partition(":")
        campo, valor = campo.strip().lower(), valor.strip()
        if campo == "user-agent":
            if not lendo_agentes:
                grupo = {"agentes": set(), "regras": []}
                grupos.append(grupo)
            grupo["agentes"].add(valor.lower())
            lendo_agentes = True
        elif campo in ("allow", "disallow") and grupo is not None:
            if valor:
                valor = normalizar_caminho(valor)
                grupo["regras"].append((len(valor), campo == "allow", valor))
            lendo_agentes = False
    meus = [g for g in grupos if ROBO.lower() in g["agentes"]] or [g for g in grupos if "*" in g["agentes"]]
    return [regra for g in meus for regra in g["regras"]]


def caminho_permitido(regras, caminho):
    """Vale a regra mais longa que casar com o caminho; no empate, a que permite."""
    melhor = (0, True)
    for tamanho, permite, padrao in regras:
        expressao = ".*".join(re.escape(parte) for parte in padrao.rstrip("$").split("*"))
        if re.match(expressao + ("$" if padrao.endswith("$") else ""), caminho) and (tamanho, permite) > melhor:
            melhor = (tamanho, permite)
    return melhor[1]


def robots_permite(url, mem):
    partes = urlparse(url)
    dominio = f"{partes.scheme}://{partes.netloc}"
    guardado = mem["robots"].get(dominio)
    if not guardado or time.time() - guardado[0] > 24 * 3600:
        resposta = requests.get(f"{dominio}/robots.txt", headers=CABECALHOS, timeout=TEMPO_LOJA)
        if resposta.status_code >= 500:
            resposta.raise_for_status()  # robots.txt fora do ar: não coleta agora (RFC 9309)
        # O RFC 9309 manda ler o robots.txt como UTF-8, mesmo quando o servidor não informa a codificação.
        texto = resposta.content.decode("utf-8-sig", errors="replace") if resposta.status_code < 400 else ""
        guardado = (time.time(), regras_do_robots(texto))
        mem["robots"][dominio] = guardado
    caminho = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
    return caminho_permitido(guardado[1], normalizar_caminho(caminho))


def baixar(url, ler, mem):
    """Baixa e lê uma página de busca, conferindo o robots.txt também em cada redirecionamento."""
    try:
        for _ in range(4):
            if not robots_permite(url, mem):
                return [], "o site não permite coleta automática (robots.txt)"
            resposta = requests.get(url, headers=CABECALHOS, timeout=TEMPO_LOJA, allow_redirects=False)
            if not resposta.is_redirect:
                resposta.raise_for_status()
                return ler(resposta.content, url), None
            url = urljoin(url, resposta.headers["Location"])
        return [], "redirecionamentos demais"
    except requests.HTTPError as erro:
        return [], f"erro HTTP {erro.response.status_code}"
    except requests.RequestException:
        return [], "sem resposta"
    except Exception:
        return [], "página em formato não reconhecido"


def coletar(nome, busca, mem):
    montar_url, ler = FONTES[nome]
    url = montar_url(busca)
    guardado = mem["paginas"].get(url)
    if guardado and time.time() - guardado["momento"] < CACHE_SEGUNDOS:
        return guardado
    buscas = [busca]
    com_smartphone = " ".join(["smartphone"] + [p for p in busca.split() if p not in TIPOS_DE_APARELHO])
    if nome in BUSCA_COM_SMARTPHONE and com_smartphone != busca:
        buscas.append(com_smartphone)
    with ThreadPoolExecutor(max_workers=len(buscas)) as executor:
        respostas = list(executor.map(lambda texto: baixar(montar_url(texto), ler, mem), buscas))
    resultado = {"fonte": nome, "url": url, "ofertas": [], "momento": time.time()}
    ofertas = [oferta for lista, _ in respostas for oferta in lista]
    if not ofertas and respostas[0][1]:
        resultado["status"] = respostas[0][1]
        return resultado
    vistos, unicas = set(), []
    for oferta in ofertas:
        if oferta["pagina"] not in vistos:
            vistos.add(oferta["pagina"])
            unicas.append(oferta)
    resultado["ofertas"] = unicas[:MAXIMO_POR_LOJA]
    total = len(resultado["ofertas"])
    resultado["status"] = (f"{total} oferta" if total == 1 else f"{total} ofertas") if unicas else "nenhuma oferta encontrada"
    resultado["coletado"] = datetime.now(FUSO).strftime("%H:%M")
    with mem["trava"]:
        mem["paginas"][url] = resultado
    return resultado


def esquecer_vencidas(mem):
    """Apaga da memória as buscas e classificações com mais de 15 minutos e os robots.txt com mais de 24 horas."""
    agora = time.time()
    for url, guardado in list(mem["paginas"].items()):
        if agora - guardado["momento"] >= CACHE_SEGUNDOS:
            mem["paginas"].pop(url, None)
    for chave, guardado in list(mem["classificacoes"].items()):
        if agora - guardado[0] >= CACHE_SEGUNDOS:
            mem["classificacoes"].pop(chave, None)
    for dominio, guardado in list(mem["robots"].items()):
        if agora - guardado[0] > 24 * 3600:
            mem["robots"].pop(dominio, None)


def coletar_todas(busca, mem):
    esquecer_vencidas(mem)
    with ThreadPoolExecutor(max_workers=len(FONTES)) as executor:
        return list(executor.map(lambda nome: coletar(nome, busca, mem), FONTES))


# Exibição
def reais(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def descrever(alvo):
    modelo, marca = alvo["modelo"] or "", alvo["marca"] or ""
    if modelo == modelo.lower():
        modelo = exibir(modelo)
    if marca == marca.lower():
        marca = exibir(marca)
    partes = [" ".join(p for p in [marca, modelo] if p) or "modelo buscado"]
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
    por_fonte = " · ".join(f"{fonte}: {total}" for fonte, total in linhas["fonte"].value_counts().items())
    st.caption(
        f"Baseada em {len(linhas)} ofertas equivalentes ({por_fonte}). "
        "É uma referência para comparação, não um preço recomendado."
    )


def escapar(texto):
    return re.sub(r"([\\`*_\[\]<>|$#~])", r"\\\1", str(texto))


def endereco(url):
    """Deixa o link seguro dentro da tabela em Markdown (sem espaço, |, < ou >)."""
    return quote(url, safe=":/?#[]@!$&'()*+,;=%")


def sem_destino(linha):
    """Oferta do Compare Livre que não traz o endereço da loja: o link abre a página do produto no Compare Livre."""
    return linha["fonte"] == "Compare Livre" and linha["link"] == linha["pagina"]


def tabela_de_ofertas(linhas, com_motivo=False):
    colunas = ["Produto"] + (["Motivo"] if com_motivo else []) + ["Preço", "Pagamento", "Loja", "Fonte", "Compra"]
    tabela = ["| " + " | ".join(colunas) + " |", "|" + " --- |" * len(colunas)]
    for _, linha in linhas.iterrows():
        celulas = [escapar(linha["titulo"])] + ([escapar(linha["motivo"])] if com_motivo else [])
        celulas += [escapar(reais(linha["preco"]).replace(" ", "\u00a0")), escapar(linha.get("pagamento") or "não informada"),
                    escapar(linha["loja"]),
                    f"[{escapar(linha['fonte'])}](<{endereco(linha['pagina'])}>)", f"[{'Ver no Compare Livre' if sem_destino(linha) else 'Ir à loja'}](<{endereco(linha['link'])}>)"]
        tabela.append("| " + " | ".join(celulas) + " |")
    st.markdown("\n".join(tabela))


def chave_do_anuncio(url):
    """Endereço do anúncio sem o que não muda o produto: parâmetros de rastreio e, na KaBuM!, o texto depois do código."""
    partes = urlparse(url or "")
    caminho = partes.path.rstrip("/").lower()
    codigo = re.search(r"/produto/(\d+)", caminho)
    if codigo:
        caminho = f"/produto/{codigo[1]}"
    parametros = sorted((k, v) for k, v in parse_qsl(partes.query) if not re.match(r"utm_|gclid|fbclid|ref$", k, re.I))
    return partes.netloc.lower().removeprefix("www.") + caminho + ("?" + urlencode(parametros) if parametros else "")


CORES = {
    "preto", "preta", "branco", "branca", "azul", "verde", "rosa", "roxo", "roxa", "vermelho", "vermelha", "amarelo",
    "amarela", "cinza", "prata", "prateado", "prateada", "dourado", "dourada", "grafite", "titanio", "meia", "noite",
    "estelar", "lilas", "creme", "bege", "laranja", "violeta", "marinho", "natural", "deserto", "glacial", "bordo",
    "ultramarino", "coral", "menta", "lavanda", "areia", "gelo", "onix", "black", "white", "blue", "green", "gold",
    "silver", "pink", "purple", "gray", "grey", "midnight", "starlight", "teal", "mint", "lime", "cor",
}


def titulo_sem_cor(titulo):
    return " ".join(p for p in limpar(titulo).split() if p not in CORES)


def marcar_repetidas(linhas):
    """Cada oferta conta uma vez na faixa e no mínimo de ofertas:
    1) o mesmo anúncio achado duas vezes (ex.: pelo Compare Livre e na própria KaBuM!) fica só com a versão da loja;
    2) o mesmo título, sem contar a cor, na mesma loja, com o mesmo preço e armazenamento, é a mesma oferta.
    Anúncios de títulos diferentes continuam separados, mesmo com loja e preço iguais."""
    validas = linhas[linhas["motivo"].isna()]
    loja_primeiro = validas.assign(indireto=validas["link"] != validas["pagina"]).sort_values("indireto", kind="stable")
    repetidas = loja_primeiro["link"].map(chave_do_anuncio).duplicated()
    linhas.loc[repetidas[repetidas].index, "motivo"] = "mesmo anúncio já contado"
    validas = linhas[linhas["motivo"].isna()]
    chave = pd.DataFrame({"loja": validas["loja"].map(lambda nome: re.sub(r"[^a-z0-9]", "", normalizar(nome))),
                          "preco": validas["preco"], "gb": validas["armazenamento_gb"].fillna(0),
                          "titulo": validas["titulo"].map(titulo_sem_cor)})
    repetidas = chave.duplicated()
    linhas.loc[repetidas[repetidas].index, "motivo"] = "mesma oferta em outra cor (mesmo título, loja e preço)"


def marcar_fora_do_padrao(linhas):
    """Descarta preços com menos da metade ou mais do dobro da mediana do grupo (kits, defeitos, erros)."""
    grupos = linhas["armazenamento_gb"].fillna(0).astype(int)
    for gb in grupos[linhas["motivo"].isna()].unique():
        grupo = linhas["motivo"].isna() & (grupos == gb)
        if grupo.sum() >= MINIMO_OFERTAS:
            mediana = linhas.loc[grupo, "preco"].median()
            fora = grupo & ((linhas["preco"] < mediana * 0.5) | (linhas["preco"] > mediana * 2))
            linhas.loc[fora, "motivo"] = "preço fora do padrão (menos da metade ou mais do dobro da mediana)"


def separar_ofertas(busca, ofertas, alvo, itens):
    """Decide, oferta por oferta, se ela entra na faixa ou por que fica de fora (coluna "motivo")."""
    # Marca e rede valem pelo que está escrito, com o LLM e com as regras: na busca e em cada título.
    # A versão escolhida na tela (5G) vale no lugar da escrita na busca.
    alvo = dict(alvo, marca=marca_em(busca) or alvo["marca"], rede=alvo.get("rede") or rede_em(busca))
    itens = [dict(item, marca=marca_no_titulo(oferta["titulo"], alvo["marca"]), rede=rede_em(oferta["titulo"]),
                  defeito=defeito_anunciado(oferta["titulo"]))
             for item, oferta in zip(itens, ofertas)]
    motivos = [motivo_descarte(alvo, item) for item in itens]
    if all(motivos) and not alvo["rede"] and chave_modelo(alvo["modelo"]) == chave_modelo(alvo["modelo"], sem_rede=True):
        # Nenhuma oferta com o mesmo nome e a busca não falou em 4G/5G: aceita a versão 4G ou 5G do modelo
        # (ex.: quem busca "samsung a56" encontra o Galaxy A56 5G, que só existe em 5G).
        motivos = [motivo_descarte(alvo, item, sem_rede=True) for item in itens]
    linhas = pd.DataFrame(ofertas)
    linhas["motivo"] = motivos
    linhas["armazenamento_gb"] = [item["armazenamento_gb"] for item in itens]
    marcar_repetidas(linhas)
    marcar_fora_do_padrao(linhas)
    return linhas, alvo


def escolher_opcoes(busca, alvo, itens, ofertas):
    """Memória e versão (4G ou 5G) para trocar na tela. A faixa é refeita na hora, com as mesmas ofertas;
    sem mexer nas opções, vale o que a busca pediu. A condição é a da busca (novo, se ela não disser outra)."""
    chave = re.sub(r"\W+", "_", busca)
    base = chave_modelo(alvo["modelo"], sem_rede=True)
    do_modelo = [(item, oferta) for item, oferta in zip(itens, ofertas)
                 if item["celular"] and item["modelo"] and item["condicao"] == alvo["condicao"]
                 and chave_modelo(item["modelo"], sem_rede=True) == base]
    memorias = sorted({item["armazenamento_gb"] for item, _ in do_modelo if item["armazenamento_gb"] in ARMAZENAMENTOS_BUSCA}
                      | ({alvo["armazenamento_gb"]} if alvo["armazenamento_gb"] else set())) + [None]
    coluna_memoria, coluna_versao = st.columns([3, 2])
    gb = coluna_memoria.selectbox("Memória (armazenamento)", memorias, index=memorias.index(alvo["armazenamento_gb"] or None),
                                  key=f"faixa_gb_{chave}", format_func=lambda gb: "Todas as memórias" if gb is None else
                                  f"{int(gb)} GB" if gb < 1000 else f"{int(gb) // 1000} TB")
    escolhido = dict(alvo, armazenamento_gb=gb)
    # A versão só vira opção quando a busca não falou em 4G ou 5G e as lojas têm as duas versões do modelo.
    tem_5g = {rede_em(oferta["titulo"]) == "5g" for _, oferta in do_modelo}
    if not rede_em(busca) and "5g" not in limpar(alvo["modelo"]).split() and tem_5g == {True, False}:
        versao = coluna_versao.radio("Versão", ["4g", "5g"], horizontal=True, key=f"faixa_rede_{chave}",
                                     format_func=lambda r: "5G" if r == "5g" else "4G (comum)")
        if versao == "5g":
            escolhido.update(modelo=f"{alvo['modelo']} 5G", rede="5g")
    return escolhido


def avisar_condicao(busca, alvo, descartadas):
    """A faixa de aparelhos novos deixa de fora usados e recondicionados; o aviso diz quantos e como compará-los."""
    if alvo["condicao"] != "novo" or descartadas.empty:
        return
    usados = int((descartadas["motivo"] == "produto usado").sum())
    recondicionados = int((descartadas["motivo"] == "produto recondicionado").sum())
    if not usados and not recondicionados:
        return
    partes = ([f"{usados} {'anúncio usado' if usados == 1 else 'anúncios usados'}"] if usados else []) + \
             ([f"{recondicionados} {'recondicionado' if recondicionados == 1 else 'recondicionados'}"] if recondicionados else [])
    condicao = "usado" if usados else "recondicionado"
    verbo = "ficou" if usados + recondicionados == 1 else "ficaram"
    st.caption(f"Esta faixa considera aparelhos novos. {' e '.join(partes).capitalize()} {verbo} de fora. "
               f"Para {'compará-lo' if usados + recondicionados == 1 else 'compará-los'}, busque “{exibir(busca)} {condicao}”.")


def mostrar_resultados(busca, coletas, mem):
    """Mostra a faixa de preço da busca. Devolve False, sem mostrar nada, quando a busca não diz o modelo:
    aí quem chamou mostra os celulares para a pessoa escolher."""
    situacao = " · ".join(f"{c['fonte']}: {c['status']}" for c in coletas)
    horarios = sorted({c["coletado"] for c in coletas if c.get("coletado")})
    lojas = f"Lojas consultadas: {situacao}." + (f" Preços coletados às {horarios[-1]}." if horarios else "")
    ofertas = [oferta for coleta in coletas for oferta in coleta["ofertas"]]
    if not ofertas:
        st.caption(lojas)
        st.warning("Nenhuma loja devolveu ofertas para esta busca. Tente escrever de outro jeito ou busque de novo em alguns minutos.")
        return True
    # Os títulos que citam o modelo vão para a classificação; os outros já ficam como "outro modelo".
    ofertas.sort(key=lambda oferta: not menciona_o_modelo(oferta["titulo"], busca))
    citam = sum(menciona_o_modelo(oferta["titulo"], busca) for oferta in ofertas)
    titulos = [o["titulo"] for o in ofertas[:citam]]
    # Ao trocar a memória ou a versão, a mesma busca reaproveita a classificação, sem chamar o LLM de novo.
    guardada = st.session_state.get("classificacao_atual")
    if guardada and guardada[0] == (busca, tuple(titulos)):
        alvo, itens, origem = dict(guardada[1]), [dict(item) for item in guardada[2]], guardada[3]
    else:
        alvo, itens, origem = classificar(busca, titulos, mem)
        st.session_state.classificacao_atual = ((busca, tuple(titulos)), dict(alvo), [dict(item) for item in itens], origem)
    if not alvo["modelo"]:
        return False
    itens += [{"celular": True, "marca": None, "modelo": None, "armazenamento_gb": None, "condicao": "novo"}
              for _ in ofertas[citam:]]
    st.caption(lojas)
    st.caption(f"Ofertas comparadas por **{origem}**.")
    alvo = escolher_opcoes(busca, alvo, itens, ofertas)
    linhas, alvo = separar_ofertas(busca, ofertas, alvo, itens)
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
    avisar_condicao(busca, alvo, descartadas)
    if not iguais.empty:
        melhor = iguais.iloc[0]
        loja = re.sub(r" e mais \d+$", "", melhor["loja"])
        st.markdown(f"**Oferta mais barata:** {escapar(melhor['titulo'])}, por **{escapar(reais(melhor['preco']))}** ({escapar(loja)}).")
        st.link_button("Ver a oferta no Compare Livre" if sem_destino(melhor) else "Ir para a compra",
                       endereco(melhor["link"]), type="primary")
        st.subheader("Ofertas equivalentes")
        tabela_de_ofertas(iguais)
    with st.expander(f"Ofertas descartadas ({len(descartadas)})"):
        if descartadas.empty:
            st.write("Nenhuma oferta foi descartada.")
        else:
            tabela_de_ofertas(descartadas, com_motivo=True)
    return True



# Busca sem modelo ("nokia", "celular barato"): a pessoa escolhe o celular entre os que as lojas têm
ACESSORIO_NO_MEIO = re.compile(r"\b(?:capa|capas|capinha|capinhas|case|pelicula|peliculas|carregador|cabo|fone|suporte|"
                               r"vidro|protetor|adesivo|skin)\b")


def busca_das_opcoes(busca):
    """Texto mandado às lojas quando a busca não diz o modelo: "smartphone" mais a marca, a linha, a rede e a memória
    pedidas. As outras palavras ("mais", "idoso") ficam de fora, porque atrapalham a busca nas lojas."""
    return " ".join(["smartphone"] + [p for p in busca.split()
                                      if p in VOCABULARIO or p in ("4g", "5g") or re.fullmatch(r"\d+(?:gb|tb)", p)])


def modelo_do_titulo(titulo):
    """Marca e modelo escritos no título, por regras: a marca (ou a linha, como Galaxy) e as palavras de modelo logo
    depois, até a memória, a rede, a cor ou outra palavra comum. "Smartphone Nokia C30, 64GB, Preto" = ("nokia", "c30")."""
    # "Nokia 2.4" vira "2ponto4" para o número com ponto não se partir em dois.
    palavras = limpar(re.sub(r"(?<=\d)[.,](?=\d)", "ponto", titulo)).split()
    inicio = next((i for i, p in enumerate(palavras) if p in MARCAS or p in MARCA_DA_LINHA), None)
    if inicio is None:
        return None, None
    primeira = palavras[inicio]
    marca = primeira if primeira in MARCAS else MARCA_DA_LINHA[primeira]
    seguintes = palavras[inicio + (primeira in MARCAS):]
    modelo = []
    for k, palavra in enumerate(seguintes):
        if (len(modelo) == 4 or palavra in MARCAS or palavra in NEUTRAS or palavra in CORES or palavra in ("4g", "5g")
                or re.fullmatch(r"\d+(?:gb|tb)", palavra)):
            break
        proxima = seguintes[k + 1] if k + 1 < len(seguintes) else ""
        # Um nome antes do número também vale ("Hot 50", "Smart 9").
        nome_antes_do_numero = (not modelo and re.fullmatch(r"[a-z]{2,10}", palavra)
                                and re.fullmatch(r"[a-z]?\d+[a-z]?", proxima) and proxima not in ("4g", "5g"))
        if not (palavra in LINHAS or palavra in VARIANTES or re.search(r"\d", palavra) or nome_antes_do_numero):
            break
        # Número sozinho só entra logo depois da marca, da linha ou de um nome ("Nokia 105", "iPhone 16", "Edge 60");
        # depois de um código ("A17"), é tamanho de tela ou outra medida.
        anterior = modelo[-1] if modelo else primeira
        if re.fullmatch(r"\d+(?:ponto\d+)?", palavra) and re.search(r"\d", anterior) and anterior != primeira:
            break
        modelo.append(palavra)
    return marca, (" ".join(modelo) if any(re.search(r"\d", p) for p in modelo) else None)


def nome_do_celular(marca, modelo):
    nome = " ".join(p if p != p.lower() else p.capitalize() for p in exibir(modelo).split()).replace("ponto", ".")
    if marca == "apple":
        nome = re.sub(r"\b(\d+)E\b", r"\1e", nome)  # iPhone 16e, como a Apple escreve
    return f"{exibir(marca)} {nome}"


def modelos_encontrados(ofertas):
    """Agrupa os anúncios por celular (marca e modelo lidos no título), sem acessórios e sem preços fora do padrão,
    do mais barato ao mais caro."""
    grupos = {}
    for oferta in ofertas:
        titulo = oferta["titulo"]
        if ACESSORIO.search(limpar(titulo)) or ACESSORIO_NO_MEIO.search(limpar(titulo)) or defeito_anunciado(titulo):
            continue
        marca, modelo = modelo_do_titulo(titulo)
        if not modelo:
            continue
        grupo = grupos.setdefault((chave_marca(marca), chave_modelo(modelo, sem_rede=True)),
                                  {"marca": marca, "grafias": {}, "ofertas": []})
        grupo["grafias"][modelo] = grupo["grafias"].get(modelo, 0) + 1
        grupo["ofertas"].append(dict(oferta, gb=armazenamento_em(titulo), condicao=condicao_em(titulo), rede=rede_em(titulo)))
    lista = []
    for grupo in grupos.values():
        mediana = statistics.median(o["preco"] for o in grupo["ofertas"])
        ofertas_ok = [o for o in grupo["ofertas"] if mediana * 0.5 <= o["preco"] <= mediana * 2]
        modelo = max(grupo["grafias"], key=lambda m: (len(m.split()), grupo["grafias"][m]))
        lista.append({"marca": grupo["marca"], "modelo": modelo, "nome": nome_do_celular(grupo["marca"], modelo),
                      "ofertas": ofertas_ok, "menor": min(o["preco"] for o in ofertas_ok)})
    return sorted(lista, key=lambda g: g["menor"])


def escolher_celular(consulta):
    st.session_state.update(digitado=consulta, campo_busca=consulta, sem_correcao=True, nova_busca=True)


def mostrar_opcoes(busca):
    """Mostra os celulares que as lojas têm para uma busca sem modelo, com marca, modelo, memória e versão para escolher."""
    mem = memoria()
    with st.spinner(f"Procurando celulares “{exibir(busca)}” nas lojas..."):
        coletas = coletar_todas(busca_das_opcoes(busca), mem)
    situacao = " · ".join(f"{c['fonte']}: {c['status']}" for c in coletas)
    horarios = sorted({c["coletado"] for c in coletas if c.get("coletado")})
    grupos = modelos_encontrados([oferta for coleta in coletas for oferta in coleta["ofertas"]])
    if not grupos:
        st.warning(f"Não encontrei celulares para “{exibir(busca)}” nas lojas agora. "
                   "Escreva a marca e o modelo, por exemplo: iPhone 13 128GB ou Galaxy A17.")
        st.caption(f"Lojas consultadas: {situacao}.")
        return
    st.info(f"“{exibir(busca)}” pode ser vários celulares. Escolha o modelo, a memória e as outras opções "
            "para ver a faixa de preço.")
    chave = re.sub(r"\W+", "_", busca)
    st.subheader("Escolha o celular")
    condicao = condicao_em(busca)  # novo, a não ser que a busca peça usado ou recondicionado
    grupos = [dict(g, ofertas=[o for o in g["ofertas"] if o["condicao"] == condicao]) for g in grupos]
    grupos = sorted([dict(g, menor=min(o["preco"] for o in g["ofertas"])) for g in grupos if g["ofertas"]],
                    key=lambda g: g["menor"])
    if not grupos:
        st.warning(f"Não encontrei celulares na condição “{condicao}” para esta busca.")
        st.caption(f"Lojas consultadas: {situacao}.")
        return
    marcas = sorted({g["marca"] for g in grupos}, key=exibir)
    marca = "todas"
    if len(marcas) > 1:
        marca = st.selectbox("Marca", ["todas"] + marcas, format_func=lambda m: "Todas as marcas" if m == "todas" else exibir(m),
                             key=f"opcao_marca_{chave}_{condicao}")
    lista = [g for g in grupos if marca in ("todas", g["marca"])]
    coluna_modelo, coluna_memoria = st.columns([3, 2])
    i = coluna_modelo.selectbox("Modelo", range(len(lista)), key=f"opcao_modelo_{chave}_{condicao}_{marca}",
                                format_func=lambda i: f"{lista[i]['nome']} · a partir de {reais(lista[i]['menor'])}")
    grupo = lista[i]
    memorias = sorted({o["gb"] for o in grupo["ofertas"] if o["gb"]})
    menor_por_gb = {gb: min(o["preco"] for o in grupo["ofertas"] if o["gb"] == gb) for gb in memorias}
    gb = coluna_memoria.selectbox("Memória (armazenamento)", memorias + [None], key=f"opcao_gb_{chave}_{condicao}_{marca}_{i}",
                                  format_func=lambda gb: "Todas as memórias" if gb is None else
                                  f"{gb if gb < 1000 else gb // 1000} {'GB' if gb < 1000 else 'TB'} · a partir de {reais(menor_por_gb[gb])}")
    # Sem rede na busca, o app compara a versão comum (4G); a 5G é outro modelo. Por isso a escolha só aparece com 5G à venda.
    rede = None
    if any(o["rede"] == "5g" for o in grupo["ofertas"]):
        rede = st.radio("Versão", [None, "5g"], horizontal=True, key=f"opcao_rede_{chave}_{condicao}_{marca}_{i}",
                        format_func=lambda r: "5G" if r else "4G (comum)")
    consulta = " ".join([grupo["marca"], grupo["modelo"].replace("ponto", ".")] + ([f"{gb}gb" if gb < 1000 else f"{gb // 1000}tb"] if gb else [])
                        + ([rede] if rede else []) + ([condicao] if condicao != "novo" else []))
    st.button(f"Ver a faixa de preço de {exibir(consulta)}", type="primary", on_click=escolher_celular, args=(consulta,))
    st.subheader(f"Celulares {'novos' if condicao == 'novo' else condicao + 's'} encontrados, do mais barato ao mais caro")
    resumo = {}
    for g in lista:
        for o in g["ofertas"]:
            linha = resumo.setdefault((g["nome"], o["gb"], o["condicao"]), {"menor": o["preco"], "anuncios": 0})
            linha["menor"] = min(linha["menor"], o["preco"])
            linha["anuncios"] += 1
    linhas = sorted(resumo.items(), key=lambda item: item[1]["menor"])[:15]
    st.table(pd.DataFrame([{
        "Celular": nome,
        "Memória": (f"{gb} GB" if gb < 1000 else f"{gb // 1000} TB") if gb else "não informada",
        "A partir de": reais(dados["menor"]),
        "Anúncios": dados["anuncios"],
    } for (nome, gb, _), dados in linhas]), hide_index=True)
    st.caption(f"Lojas consultadas: {situacao}." + (f" Preços coletados às {horarios[-1]}." if horarios else "")
               + " Os modelos são lidos dos títulos por regras. A faixa de preço é calculada depois que você escolhe "
               "o celular, só com ofertas equivalentes.")


# Reprodução do teste de extração (abre só pelo endereço ?avaliar=1; não aparece na tela de busca)
# 50 títulos de anúncios lidos em 09/11/2026, rotulados um a um: modelo (None quando não é um dos 14 modelos
# da base de teste ou é acessório), armazenamento em GB e condição. O extrator por regras é o ponto de comparação
# do LLM: expressões regulares escritas para os 14 modelos da base de teste.

MODELOS_TESTE = {
    "iPhone 11": "Apple", "iPhone 13": "Apple", "iPhone 14": "Apple", "iPhone 15": "Apple", "iPhone 16": "Apple",
    "Galaxy A17": "Samsung", "Galaxy A17 5G": "Samsung",
    "Moto G06": "Motorola", "Edge 60 Fusion": "Motorola", "Edge 60 Pro": "Motorola", "Edge 70 Fusion": "Motorola", "Edge 70": "Motorola",
    "Redmi 15C": "Xiaomi", "Redmi 15C 5G": "Xiaomi",
}
ARMAZENAMENTOS_TESTE = [64, 128, 256, 512, 1000]


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
            return nome if nome in MODELOS_TESTE else None
        return "Edge 70" if edge[1] == "70" else None
    return None


def armazenamento_por_regras(t):
    valores = set()
    for numero, unidade in re.findall(r"(?<![\d.,])(\d{1,4})\s*(gb|tb)\b", t):
        valor = int(numero) * (1000 if unidade == "tb" else 1)
        if valor in ARMAZENAMENTOS_TESTE:
            valores.add(valor)
    return valores.pop() if len(valores) == 1 else None


def extrair_por_regras(titulo):
    t = normalizar(titulo)
    modelo = modelo_por_regras(t)
    return {"marca": MODELOS_TESTE.get(modelo), "modelo": modelo, "armazenamento_gb": armazenamento_por_regras(t), "condicao": condicao_por_regras(t)}


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


def rotulo_do_llm(item):
    """Resposta do LLM no formato do rótulo: modelo com a grafia da base de teste (None se for outro), GB e condição."""
    chaves = {chave_modelo(m): m for m in MODELOS_TESTE}
    modelo = chaves.get(chave_modelo(item["modelo"])) if item["celular"] and item["modelo"] else None
    return modelo, item["armazenamento_gb"], item["condicao"]


def versao_do_codigo():
    try:
        with open(__file__, "rb") as arquivo:
            return hashlib.sha256(arquivo.read()).hexdigest()[:12]
    except OSError:
        return "desconhecida"


def mostrar_avaliacao():
    st.title("Faixa Certa: teste de extração")
    st.write("Os 50 títulos rotulados passam pelo extrator por regras e, com o botão, pelo LLM. Um título conta como "
             "acerto quando modelo, armazenamento e condição batem com o rótulo.")
    erro = None
    if LLM_CHAVE and st.button("Rodar o LLM nos 50 títulos", type="primary"):
        inicio = time.perf_counter()
        try:
            # Mesmas instruções, modelos e lotes da busca; aqui a espera por resposta pode chegar a 90 segundos.
            _, itens, modelo = classificar_em_lotes("celular", [t[0] for t in TITULOS_TESTE], tempo=90)
            st.session_state.avaliacao_llm = (itens, modelo, time.perf_counter() - inicio,
                                              datetime.now(FUSO).strftime("%d/%m/%Y %H:%M"))
        except requests.HTTPError as falha:
            detalhe = detalhe_do_erro(falha.response) if falha.response is not None else ""
            codigo = falha.response.status_code if falha.response is not None else "?"
            erro = f"Não foi possível rodar o LLM agora (erro HTTP {codigo}{', ' + detalhe if detalhe else ''}). Tente de novo."
        except Exception as falha:
            erro = f"Não foi possível rodar o LLM agora ({type(falha).__name__}). Tente de novo."
    if erro:
        st.warning(erro)
    llm = st.session_state.get("avaliacao_llm")
    linhas = []
    for numero, (titulo, modelo, gb, condicao) in enumerate(TITULOS_TESTE, 1):
        esperado = (modelo, gb, condicao)
        regras = extrair_por_regras(titulo)
        saida = (regras["modelo"], regras["armazenamento_gb"], regras["condicao"])
        linha = {"n": numero, "titulo": titulo, "esperado_modelo": modelo, "esperado_gb": gb, "esperado_condicao": condicao,
                 "regras_modelo": saida[0], "regras_gb": saida[1], "regras_condicao": saida[2], "regras_acertou": saida == esperado}
        if llm:
            item = llm[0][numero - 1]
            saida = rotulo_do_llm(item)
            linha.update({"llm_celular": item["celular"], "llm_marca": item["marca"], "llm_modelo_resposta": item["modelo"],
                          "llm_modelo": saida[0], "llm_gb": saida[1], "llm_condicao": saida[2], "llm_acertou": saida == esperado})
        linhas.append(linha)
    tabela = pd.DataFrame(linhas, dtype=object)
    resumo = f"Regras: {int(tabela['regras_acertou'].sum())} de {len(tabela)} títulos corretos."
    if llm:
        resumo += (f" LLM ({llm[1]}): {int(tabela['llm_acertou'].sum())} de {len(tabela)} títulos corretos, "
                   f"em {llm[2]:.1f} s, rodado em {llm[3]}.")
    st.write(resumo)
    st.caption(f"Versão do código (SHA-256 do app.py, 12 primeiros caracteres): {versao_do_codigo()}. "
               f"Modelo principal configurado: {LLM_MODELO}; reserva: {LLM_MODELO_RESERVA}.")
    st.dataframe(tabela.fillna("").astype(str), hide_index=True)
    csv = tabela.to_csv(index=False)
    st.download_button("Baixar a tabela (CSV)", csv.encode("utf-8"), "extracao_50_titulos.csv", "text/csv")
    st.code(csv, language=None)


# Interface
def buscar_como_digitado():
    st.session_state.update(sem_correcao=True, nova_busca=True)


st.set_page_config(page_title="Faixa Certa")
if st.query_params.get("avaliar") == "1":
    mostrar_avaliacao()  # reprodução dos testes de extração; não aparece na tela de busca
    st.stop()
st.title("Faixa Certa")
st.write("Compara o preço de um smartphone em várias lojas.")
st.caption("Preços à vista ou no Pix, sem frete; quando a loja não informa a forma de pagamento, a tabela avisa. "
           "Os preços são coletados nas lojas na hora da busca, e uma busca repetida em até 15 minutos reaproveita o resultado.")
st.caption(f"Extrator principal: {'LLM' if LLM_CHAVE else 'regras (sem chave de IA configurada)'}. Fontes: {', '.join(FONTES)}.")

nova_busca = st.session_state.pop("nova_busca", False)
with st.form("busca"):
    st.text_input("Qual celular você procura?", placeholder="Ex.: iphone 13 128gb", key="campo_busca")
    st.caption("Sem indicação, a busca compara aparelhos novos. Para usados ou recondicionados, escreva “usado” ou "
               "“recondicionado”, como em “iphone 13 128gb usado”.")
    if st.form_submit_button("Buscar", type="primary"):
        st.session_state.update(digitado=st.session_state.campo_busca, sem_correcao=False)
        nova_busca = True

# Numa busca nova, o resultado anterior sai da tela na hora e fica só o aviso "Buscando..." até a resposta.
# Para isso, cada busca nova troca de lugar a área do resultado e um espaço vazio: o vazio ocupa o lugar do
# resultado anterior e o apaga. Ao trocar marca, modelo, memória ou versão na tela, nada muda de lugar e a tela não pisca.
if nova_busca:
    st.session_state.lugar = 1 - st.session_state.get("lugar", 0)
    st.session_state.pop("classificacao_atual", None)
if st.session_state.get("lugar", 0):
    st.empty()
    area = st.container()
else:
    area = st.container()
    st.empty()
with area:
    digitado = (st.session_state.get("digitado") or "").strip()
    if digitado:
        if st.session_state.get("sem_correcao"):
            busca, mudou = limpar(digitado), False
        else:
            busca, mudou = corrigir_busca(digitado)
        falta = falta_modelo(busca)
        if mudou:
            st.info(f"Você quis dizer **{exibir(busca)}**?" + ("" if falta else " Mostrando resultados para a busca corrigida."))
            st.button(f"Buscar “{digitado}” como digitei", on_click=buscar_como_digitado)
        if not falta:
            mem = memoria()
            with st.spinner(f"Buscando “{exibir(busca)}” nas lojas..."):
                guardada = st.session_state.get("coleta_atual")
                if not nova_busca and guardada and guardada[0] == busca:
                    coletas = guardada[1]  # troca de memória ou versão: as mesmas ofertas, sem buscar de novo
                else:
                    coletas = coletar_todas(busca, mem)
                    st.session_state.coleta_atual = (busca, coletas)
                # Sem modelo reconhecido na busca ("quero um celular bom"), a pessoa escolhe entre os celulares das lojas.
                falta = not mostrar_resultados(busca, coletas, mem)
        if falta:
            mostrar_opcoes(busca)
