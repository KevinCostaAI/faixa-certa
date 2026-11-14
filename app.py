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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
TEMPO_TOTAL_COLETA = 12  # orçamento compartilhado por todas as lojas, incluindo robots e redirecionamentos
LIMITE_HTML = 8 * 1024 * 1024  # evita carregar páginas sem limite de tamanho
TEMPO_LLM = 15  # segundos, no total, para o LLM classificar os títulos de uma busca; depois disso, o app segue por regras
ESPERA_REPETIR = 5  # segundos sem resposta do LLM até o mesmo pedido sair de novo; vale a resposta que chegar primeiro
COPIAS_LLM = 3  # no máximo, pedidos iguais ao mesmo tempo para cada lote de títulos
LOTE_LLM = 15  # títulos por chamada ao LLM; com mais títulos, as chamadas são feitas em paralelo
METODO_PRINCIPAL = "regras"  # avaliação dos 50 títulos (14/11/2026): LLM e regras com 90%; sem 10 pontos de vantagem do LLM, ficam as regras
CACHE_SEGUNDOS = 15 * 60  # o resultado de uma busca bem-sucedida é reutilizado por 15 minutos e depois apagado
MINIMO_OFERTAS = 3  # abaixo disso, a faixa de preço não é exibida
PAGAMENTOS_DA_FAIXA = {"Pix", "à vista"}  # só entram na faixa ofertas com uma dessas formas de pagamento confirmada
MAXIMO_POR_LOJA = 30
FUSO = ZoneInfo("America/Fortaleza")
COMPARELIVRE = os.environ.get("COMPARELIVRE_URL", "https://comparelivre.com.br").rstrip("/")
KABUM = os.environ.get("KABUM_URL", "https://www.kabum.com.br").rstrip("/")
GAZIN = os.environ.get("GAZIN_URL", "https://www.gazin.com.br").rstrip("/")
NOVOMUNDO = os.environ.get("NOVOMUNDO_URL", "https://www.novomundo.com.br").rstrip("/")
MAGALU = os.environ.get("MAGALU_URL", "https://www.magazineluiza.com.br").rstrip("/")
WEBCONTINENTAL = os.environ.get("WEBCONTINENTAL_URL", "https://www.webcontinental.com.br").rstrip("/")
TROCAFY = os.environ.get("TROCAFY_URL", "https://www.trocafy.com.br").rstrip("/")


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


# Versões de rede conferidas nas páginas dos fabricantes (protocolo de validação, passo 5), por marca e modelo.
# Todo iPhone a partir do 12 só existe em 5G. Fora desta lista, valem as redes escritas nos títulos: anúncio sem rede
# no título não é evidência de uma versão 4G.
VERSOES_CONHECIDAS = {
    ("samsung", "a07"): {"4g", "5g"}, ("samsung", "a14"): {"4g", "5g"}, ("samsung", "a16"): {"4g", "5g"},
    ("samsung", "a17"): {"4g", "5g"}, ("samsung", "a36"): {"5g"},
    ("motorola", "g06"): {"4g"}, ("motorola", "g17"): {"4g"}, ("motorola", "e15"): {"4g"},
    ("motorola", "g35"): {"5g"}, ("motorola", "g47"): {"5g"},
    ("xiaomi", "redmi15c"): {"4g", "5g"}, ("xiaomi", "redmi15"): {"4g", "5g"}, ("xiaomi", "pococ85"): {"4g", "5g"},
    ("xiaomi", "redminote15"): {"4g", "5g"},
    ("oppo", "a6x"): {128: {"4g"}, None: {"4g", "5g"}},  # no Brasil, o A6x 5G só tem 256 GB
}


def versoes_conhecidas(alvo):
    marca, chave = chave_marca(alvo.get("marca")), chave_modelo(alvo.get("modelo"), sem_rede=True)
    if marca == "apple" and re.match(r"iphone(?:1[2-9]|[2-9]\d)", chave):
        return {"5g"}
    versoes = VERSOES_CONHECIDAS.get((marca, chave))
    if isinstance(versoes, dict):
        versoes = versoes.get(alvo.get("armazenamento_gb"), versoes[None])
    return versoes


def do_mesmo_modelo(alvo, itens):
    """Posições dos anúncios do modelo buscado (qualquer versão de rede), na condição pedida."""
    base = chave_modelo(alvo["modelo"], sem_rede=True)
    return [k for k, item in enumerate(itens) if item["celular"] and item["modelo"] and item["condicao"] == alvo["condicao"]
            and chave_modelo(item["modelo"], sem_rede=True) == base]


def versao_da_tela(busca, alvo, titulos_do_modelo):
    """Como a rede entra na tela de resultado:
    "opcao": o modelo tem versões 4G e 5G (conferidas no fabricante ou, fora da lista, as duas escritas nos títulos)
    e a busca não diz a rede; a pessoa escolhe, e a tela começa na versão 4G. Anúncio sem rede no título não é
    evidência de 4G nem de 5G e fica fora da versão escolhida, com o motivo.
    "unica": o modelo só tem uma versão (conferida no fabricante ou, fora da lista, a única escrita nos títulos);
    a rede não separa os anúncios do modelo, e anúncio sem rede no título é o mesmo aparelho.
    None: vale a rede escrita na busca, se houver."""
    rede_da_busca = rede_em(busca) or ("5g" if "5g" in limpar(alvo.get("modelo") or "").split() else None)
    citadas = {rede_em(titulo) for titulo in titulos_do_modelo} - {None}
    versoes = versoes_conhecidas(alvo) or citadas
    if len(versoes) == 1 and rede_da_busca in (None, *versoes):
        return "unica"
    if not rede_da_busca and versoes == {"4g", "5g"}:
        return "opcao"
    return None


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
    # "Galaxy" e "Moto" podem faltar na busca ou no título: "Samsung A14" é o Galaxy A14, e "Motorola G35" é o Moto G35.
    exigidas = [p for p in base if p not in LINHAS_IMPLICITAS] or base
    partes = [r"\s*".join(re.escape(pedaco) for pedaco in re.findall(r"[a-z]+|\d+", p)) for p in exigidas]
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
Para cada texto, na mesma ordem, devolva celular, marca, modelo, armazenamento_gb, condicao, rede e defeito.
- celular: false para acessórios (capa, película, carregador, cabo, fone, suporte), peças, kits sem o aparelho ou produtos que não são smartphones; true nos demais casos e sempre na busca.
- marca: fabricante, como Apple, Samsung, Motorola ou Xiaomi, ou null.
- modelo: nome do modelo sem a marca e sem armazenamento, cor ou memória RAM, por exemplo "iPhone 13", "Galaxy A17 5G", "Moto G06" ou "Redmi 15C". Use exatamente a mesma grafia para o mesmo modelo. Inclua Pro, Max, Plus, Ultra, Lite, FE, 5G ou letras como e e C somente quando fizerem parte do nome. Use null se não houver modelo.
- armazenamento_gb: armazenamento interno em GB (1 TB = 1000), ou null. Não confunda com memória RAM.
- condicao: novo, usado ou recondicionado. Sem indicação, novo.
- rede: "4G" ou "5G" quando o texto disser, ou null. Não deduza a rede pelo modelo.
- defeito: true quando o texto anunciar defeito, bloqueio (iCloud, conta Google, IMEI) ou função que não funciona, como tela quebrada, não liga ou retirada de peças; false nos demais casos e sempre na busca.
Responda somente com JSON no formato {"itens": [{"celular": true, "marca": "Apple", "modelo": "iPhone 13", "armazenamento_gb": 128, "condicao": "novo", "rede": null, "defeito": false}]}."""


def chamar_llm(textos, modelo, formato_json=True, tempo=TEMPO_LLM, rapido=True):
    """Faz o pedido ao LLM e devolve a primeira resposta que chegar. No Gemini, parte dos pedidos demora 15 s ou mais,
    e o mesmo pedido feito de novo costuma voltar em poucos segundos. Por isso, sem resposta em ESPERA_REPETIR
    segundos, ou se a conexão falhar, o mesmo pedido sai de novo, até COPIAS_LLM pedidos, tudo dentro de `tempo`."""
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
    fim = time.monotonic() + tempo

    def pedir():
        return requests.post(f"{LLM_URL}/chat/completions", headers={"Authorization": f"Bearer {LLM_CHAVE}"},
                             json=corpo, timeout=max(fim - time.monotonic(), 0.5))

    executor = ThreadPoolExecutor(max_workers=COPIAS_LLM)
    pendentes, erros, enviados, proximo = set(), [], 0, time.monotonic()
    try:
        while True:
            agora = time.monotonic()
            if enviados < COPIAS_LLM and agora >= proximo and (enviados == 0 or fim - agora >= 3):
                pendentes.add(executor.submit(pedir))
                enviados, proximo = enviados + 1, agora + ESPERA_REPETIR
            if not pendentes:
                raise erros[0] if erros else requests.Timeout("Tempo esgotado.")
            pode_repetir = enviados < COPIAS_LLM and fim - time.monotonic() >= 3
            espera = (proximo if pode_repetir else fim + 1) - time.monotonic()
            prontos, pendentes = wait(pendentes, timeout=max(espera, 0), return_when=FIRST_COMPLETED)
            for futuro in prontos:
                if futuro.exception() is None:
                    return futuro.result()
                erros.append(futuro.exception())
            if prontos and not pendentes:
                proximo = time.monotonic()  # todos os pedidos enviados falharam na conexão: o próximo sai já
            elif not prontos and not pode_repetir:
                raise requests.Timeout("Tempo esgotado.")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


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
        # Rede e defeito lidos pelo LLM: o defeito também tira a oferta da faixa; a rede só entra na avaliação
        # dos métodos, porque na faixa vale a rede escrita no título.
        "rede_llm": rede_em(str(item.get("rede") or "")),
        "defeito_llm": item.get("defeito") is True,
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
    if LLM_CHAVE and METODO_PRINCIPAL == "LLM":
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
        origem = "regras (sem chave de IA configurada)" if not LLM_CHAVE else "regras (método principal pela avaliação dos 50 títulos)"
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
    "gazin": "Gazin", "novomundo": "Novo Mundo", "webcontinental": "Webcontinental",
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
    """Preço e forma de pagamento de uma campanha da KaBuM! que está valendo para todos: é o preço que o site mostra
    no lugar do normal. No cartão da campanha, priceWithDiscount aparece como preço "No PIX" e price como total em 10x.
    Campanha exclusiva de assinante (Prime) ou de cliente logado não conta, porque não vale para qualquer comprador."""
    oferta = produto.get("offer")
    if not isinstance(oferta, dict) or oferta.get("isPrimeExclusive") or oferta.get("isLoggedUserExclusive"):
        return None
    agora = time.time() if agora is None else agora
    comeco, fim = numero(oferta.get("startsAt")), numero(oferta.get("endsAt"))
    if (comeco and agora < comeco) or (fim and agora > fim) or numero(oferta.get("quantityAvailable")) == 0:
        return None
    if preco_valido(numero(oferta.get("priceWithDiscount"))):
        return numero(oferta.get("priceWithDiscount")), "Pix"
    if preco_valido(numero(oferta.get("price"))):
        return numero(oferta.get("price")), "não informada"  # sem o preço no Pix, o total não confirma a forma de pagamento
    return None


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
                # O cartão mostra "R$ ... No PIX ou 10x de R$ ...": priceWithDiscount é o preço no Pix; price é o total
                # em 10x. Sem o preço no Pix, o total entra como forma de pagamento não informada. O preço Prime
                # (primePrice) é de assinatura e não entra.
                preco, pagamento = preco_da_campanha(atual) or (numero(atual.get("priceWithDiscount")), "Pix")
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
            # A Novo Mundo mostra o preço "Por" e parcela com juros, sem dizer se o "Por" é à vista: pagamento não informado.
            ofertas.append({"titulo": produto["name"].strip(), "preco": preco, "loja": "Novo Mundo", "fonte": "Novo Mundo",
                            "link": link, "pagina": link, "pagamento": "não informada"})
    return ofertas


def rede_dos_atributos(produto):
    redes = []
    for nome in ("Rede Móvel", "Rede móvel", "Rede", "Redes", "Tecnologia de Rede", "Conexões", "Conectividade"):
        valores = produto.get(nome) or []
        for valor in valores if isinstance(valores, list) else [valores]:
            texto = normalizar(valor)
            rede = re.search(r"\bredes? moveis?\s*:?\s*([45]\s*g\b(?:[\s/,;-]+[2345]\s*g\b)*)", texto)
            if not rede:
                rede = re.match(r"\s*([2345]\s*g\b(?:[\s/,;-]+[2345]\s*g\b)*)", texto)
            if rede and rede_em(rede[1]):
                redes.append((rede_em(rede[1]), f"{nome}: {valor}"))
    if len({rede for rede, _ in redes}) == 1:
        return {"rede_confirmada": redes[0][0], "evidencia_rede": redes[0][1]}
    return {}


def ler_webcontinental(conteudo, url):
    """Catálogo público da própria loja. Lê o total de uma parcela no Pix, sem usar o preço genérico parcelado."""
    produtos = json.loads(conteudo)
    ofertas = []
    for produto in produtos if isinstance(produtos, list) else []:
        link = produto.get("link") or urljoin(WEBCONTINENTAL, (produto.get("linkText") or "") + "/p")
        if urlparse(link).netloc != urlparse(WEBCONTINENTAL).netloc:
            continue
        # O primeiro SKU disponível e o vendedor padrão são os que a página pública abre.
        for item in produto.get("items") or []:
            vendedores = item.get("sellers") or []
            vendedor = next((v for v in vendedores if v.get("sellerDefault")), vendedores[0] if len(vendedores) == 1 else None)
            if not vendedor:
                continue
            oferta = vendedor.get("commertialOffer") or {}
            if oferta.get("IsAvailable") is False or (numero(oferta.get("AvailableQuantity")) or 0) <= 0:
                continue
            opcoes = []
            for parcela in oferta.get("Installments") or []:
                forma = normalizar(parcela.get("PaymentSystemName", ""))
                nome = normalizar(parcela.get("Name", ""))
                total = numero(parcela.get("TotalValuePlusInterestRate"))
                if (numero(parcela.get("NumberOfInstallments")) != 1 or numero(parcela.get("InterestRate")) != 0
                        or not preco_valido(total) or re.search(r"cupom|clube|assinante|aplicativo|mensal", nome)):
                    continue
                if forma == "pix" and "a vista" in nome:
                    opcoes.append((0, total, "Pix"))
                elif forma in ("boleto", "boleto bancario") and "a vista" in nome:
                    opcoes.append((1, total, "à vista"))
            _, preco, pagamento = min(opcoes) if opcoes else (2, numero(oferta.get("Price")), "não informada")
            if not preco_valido(preco):
                continue
            titulo = (item.get("name") or produto.get("productName") or "").strip()
            if titulo and not modelo_do_titulo(titulo)[1] and produto.get("productName"):
                titulo = produto["productName"].strip() + (" · " + titulo if titulo != produto["productName"].strip() else "")
            if not titulo:
                continue
            rede = rede_dos_atributos(produto)
            if rede:
                rede.update(pagina_rede=link, rede_conferida_em=datetime.now(FUSO).isoformat(timespec="seconds"))
            ofertas.append({"titulo": titulo, "preco": preco, "loja": "Webcontinental · " + vendedor.get("sellerName", "não informado"),
                            "fonte": "Webcontinental", "link": link, "pagina": link, "pagamento": pagamento, **rede})
            break
    return ofertas


def ler_rotas_trocafy(conteudo, url):
    arvore = html.fromstring(conteudo)  # o site declara ISO-8859-1, não UTF-8
    rotas = []
    for ancora in arvore.xpath('//a[@href]'):
        destino = urljoin(url, ancora.get("href"))
        if urlparse(destino).netloc == urlparse(TROCAFY).netloc and urlparse(destino).path.startswith("/smartphone/"):
            rotas.append({"modelo": " ".join(ancora.text_content().split()), "url": destino})
    return rotas


def ler_trocafy(conteudo, url):
    arvore = html.fromstring(conteudo)
    ofertas = []
    for cartao in arvore.xpath('//div[@data-id][contains(concat(" ",normalize-space(@class)," ")," product-card ")]'):
        titulo = " ".join(cartao.xpath('string(.//*[contains(@class,"product-card-title")])').split())
        links = cartao.xpath('.//a[contains(@class,"product-link-data")]/@href')
        parcelas = cartao.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," price-vista ")]')
        texto = " ".join(cartao.text_content().split())
        if not titulo or not links or not parcelas or re.search(r"indisponivel|esgotado|avise.me", normalizar(texto)):
            continue
        pagamento_texto = " ".join(parcelas[0].text_content().split())
        preco = preco_brl(pagamento_texto)
        if not preco_valido(preco):
            continue
        restrito = re.search(r"cupom|clube|assinante|aplicativo", normalizar(pagamento_texto))
        pagamento = "Pix" if not restrito and "pix" in normalizar(pagamento_texto) else "não informada"
        link = urljoin(url, links[0])
        if urlparse(link).netloc != urlparse(TROCAFY).netloc:
            continue
        condicao = condicao_em(titulo)
        if re.search(r"sou como novo|tenho minhas marcas de uso|fui mais usado", normalizar(titulo)):
            condicao = "usado"
        confirmada = {"condicao_confirmada": condicao, "evidencia_condicao": titulo} if condicao != "novo" else {}
        ofertas.append({"titulo": titulo, "preco": preco, "fonte": "Trocafy", "loja": "Trocafy",
                        "link": link, "pagina": link, "pagamento": pagamento, **confirmada})
    return ofertas


def ler_magalu(conteudo, url):
    """Lê os mesmos produtos e as condições de pagamento que a lista pública mostra, sem usar APIs privadas."""
    produtos = campo(dados_next(conteudo), "props", "pageProps", "data", "search", "items") or []
    ofertas = []
    for produto in produtos:
        if produto.get("available") is not True or not produto.get("title") or not produto.get("path"):
            continue
        for oferta in produto.get("offers") or []:
            if oferta.get("currency", "BRL") != "BRL":
                continue
            melhor = oferta.get("bestPrice") or {}
            metodo = normalizar(melhor.get("paymentMethodDescription", ""))
            identificador = normalizar(melhor.get("paymentMethodId", ""))
            # Desconto de cartão, cupom, aplicativo ou clube não comprova Pix nem preço à vista para todos.
            restrito = re.search(r"cupom|clube|assinante|aplicativo|superapp|magalupay|cartao", metodo)
            pagamento = "Pix" if not restrito and identificador == "pix" and "pix" in metodo else (
                "à vista" if not restrito and "a vista" in metodo else "não informada")
            preco = numero(melhor.get("totalAmount")) if pagamento in PAGAMENTOS_DA_FAIXA else numero(oferta.get("price"))
            if not preco_valido(preco):
                continue
            link = urljoin(url, produto["path"])
            if urlparse(link).netloc != urlparse(MAGALU).netloc:
                continue
            vendedor = campo(oferta, "seller", "id") or "não informado"
            if vendedor != "não informado":
                partes = urlparse(link)
                parametros = dict(parse_qsl(partes.query))
                parametros["seller_id"] = vendedor
                link = partes._replace(query=urlencode(parametros)).geturl()
            # O título é o da loja, inclusive quando a referência detalha um kit vendido junto com o aparelho.
            titulo = produto["title"].strip()
            if produto.get("type") == "bundle" and produto.get("reference"):
                titulo += " · " + produto["reference"].strip()
            ofertas.append({"titulo": titulo, "preco": preco, "loja": f"Magazine Luiza · {vendedor}",
                            "fonte": "Magazine Luiza", "link": link, "pagina": link, "pagamento": pagamento})
    return ofertas


FONTES = {
    "Compare Livre": (lambda busca: f"{COMPARELIVRE}/busca?q={quote_plus(busca)}", ler_comparelivre),
    "KaBuM!": (lambda busca: f"{KABUM}/busca/{quote('-'.join(busca.split()))}", ler_kabum),
    "Gazin": (lambda busca: f"{GAZIN}/busca/{quote('-'.join(busca.split()))}", ler_gazin),
    "Novo Mundo": (lambda busca: f"{NOVOMUNDO}/busca?busca={quote(busca)}", ler_novomundo),
    "Magazine Luiza": (lambda busca: f"{MAGALU}/busca/{quote_plus(busca)}/", ler_magalu),
    "Webcontinental": (lambda busca: f"{WEBCONTINENTAL}/api/catalog_system/pub/products/search/?ft={quote(busca)}&_from=0&_to=29", ler_webcontinental),
    "Trocafy": (lambda busca: f"{TROCAFY}/#consulta={quote(busca)}", ler_trocafy),
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


def tempo_restante(prazo):
    restante = prazo - time.monotonic()
    if restante <= 0:
        raise requests.Timeout("tempo total da coleta esgotado")
    return restante


def baixar_conteudo(url, prazo, sessao=None):
    """O timeout de requests mede inatividade, não o tempo total. Confere também o prazo ao ler o corpo."""
    restante = tempo_restante(prazo)
    cliente = sessao if sessao is not None else requests
    with cliente.get(url, headers=CABECALHOS, timeout=min(TEMPO_LOJA, restante),
                     allow_redirects=False, stream=True) as resposta:
        partes, tamanho = [], 0
        for parte in resposta.iter_content(chunk_size=32768):
            tempo_restante(prazo)
            tamanho += len(parte)
            if tamanho > LIMITE_HTML:
                raise ValueError("página excede o tamanho permitido")
            partes.append(parte)
        tempo_restante(prazo)
        return resposta, b"".join(partes)


def robots_permite(url, mem, prazo=None, sessao=None):
    prazo = prazo if prazo is not None else time.monotonic() + TEMPO_TOTAL_COLETA
    partes = urlparse(url)
    dominio = f"{partes.scheme}://{partes.netloc}"
    # Duas buscas da mesma fonte compartilham um único pedido de robots.txt.
    with mem["trava"]:
        trava = mem.setdefault("travas_robots", {}).setdefault(dominio, threading.Lock())
    if not trava.acquire(timeout=tempo_restante(prazo)):
        raise requests.Timeout("tempo de espera pelo robots.txt esgotado")
    try:
        guardado = mem["robots"].get(dominio)
        if not guardado or time.time() - guardado[0] > 24 * 3600:
            resposta, conteudo = baixar_conteudo(f"{dominio}/robots.txt", prazo, sessao)
            if resposta.status_code >= 500:
                resposta.raise_for_status()  # robots.txt fora do ar: não coleta agora (RFC 9309)
            texto = conteudo.decode("utf-8-sig", errors="replace") if resposta.status_code < 400 else ""
            guardado = (time.time(), regras_do_robots(texto))
            mem["robots"][dominio] = guardado
    finally:
        trava.release()
    caminho = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
    return caminho_permitido(guardado[1], normalizar_caminho(caminho))


def baixar(url, ler, mem, prazo=None, sessao=None):
    """Lê uma página pública, conferindo o robots.txt também em cada redirecionamento."""
    prazo = prazo if prazo is not None else time.monotonic() + TEMPO_TOTAL_COLETA
    propria = sessao is None
    sessao = requests.Session() if propria else sessao
    try:
        for _ in range(4):
            if not robots_permite(url, mem, prazo, sessao):
                return [], "o site não permite coleta automática (robots.txt)"
            resposta, conteudo = baixar_conteudo(url, prazo, sessao)
            if not resposta.is_redirect:
                resposta.raise_for_status()
                return ler(conteudo, url), None
            url = urljoin(url, resposta.headers["Location"])
        return [], "redirecionamentos demais"
    except requests.HTTPError as erro:
        return [], f"erro HTTP {erro.response.status_code}"
    except requests.Timeout:
        return [], "tempo limite da coleta"
    except requests.RequestException:
        return [], "sem resposta"
    except Exception:
        return [], "página em formato não reconhecido"
    finally:
        if propria:
            sessao.close()


def rede_da_ficha(conteudo, url):
    """Rede da ficha do próprio produto. Wi-Fi de 5 GHz e recomendações de outros produtos não valem."""
    arvore = arvore_utf8(conteudo)
    titulo = arvore.xpath('normalize-space(string(//h1[1]))')
    campos = []
    rotulos = {"rede", "rede movel", "redes moveis", "tipo de rede", "tecnologia de rede", "conexoes",
               "conectividade", "conectividade e recursos", "conectividade celular"}
    for linha in arvore.xpath('//tr'):
        celulas = linha.xpath('./td|./th')
        if len(celulas) == 2:
            nome = normalizar(celulas[0].text_content()).rstrip(":")
            if nome in rotulos:
                campos.append((nome, " ".join(celulas[1].itertext())))
    produto = campo(dados_next(conteudo), "props", "pageProps", "product") or {}
    blocos = arvore.xpath('//*[@id="description" or @id="technicalInfoSection"] | '
                         '//*[@id="description" or @id="technicalInfoSection"]//p | '
                         '//*[@id="description" or @id="technicalInfoSection"]//li')
    if produto.get("about"):
        blocos += arvore_utf8(produto["about"]).xpath('//li')
    for bloco in blocos:
        texto = " ".join(bloco.itertext())
        for nome in rotulos:
            encontrado = re.search(r"\b" + re.escape(nome) + r"\s*:\s*([^\n]{1,120})", normalizar(texto))
            if encontrado:
                campos.append((nome, encontrado[1]))
    resultados = []
    if rede_em(titulo):
        resultados.append((rede_em(titulo), titulo))
    for nome, valor in campos:
        # Só uma lista de redes no início do campo comprova a rede móvel; "Wi-Fi 5G" não comprova 5G celular.
        prefixo = re.match(r"^\s*((?:[2345]\s*g\b[\s,;/|+\-]*)+)", normalizar(valor))
        if not prefixo or re.match(r"^\s*[:=]?\s*(?:nao|n/a|indisponivel|ausente)\b", normalizar(valor)[prefixo.end():]):
            continue
        rede = rede_em(prefixo[1])
        if rede:
            resultados.append((rede, f"{nome}: {valor.strip()[:160]}"))
    redes = {rede for rede, _ in resultados}
    if len(redes) != 1 or not titulo:
        return {}
    return {"rede_confirmada": redes.pop(), "evidencia_rede": resultados[0][1],
            "titulo_pagina": titulo, "pagina_rede": url}


def confirmar_redes(busca, ofertas, mem, prazo, sessao):
    """Consulta até três fichas por fonte, dentro do mesmo prazo. Título e extração permanecem intactos."""
    alvo, itens = classificar_por_regras(busca, [oferta["titulo"] for oferta in ofertas])
    conhecidas = versoes_conhecidas(alvo)
    if not rede_em(busca) and (not conhecidas or len(conhecidas) == 1):
        return ofertas
    verificadas, consultas, vistos = list(ofertas), 0, set()
    for k, (oferta, item) in enumerate(zip(ofertas, itens)):
        if consultas >= 3 or prazo - time.monotonic() < 1.5:
            break
        item = dict(item, condicao=oferta.get("condicao_confirmada") or item["condicao"])
        if (oferta["fonte"] not in {"KaBuM!", "Magazine Luiza", "Gazin", "Trocafy"} or rede_em(oferta["titulo"])
                or oferta.get("pagamento") not in PAGAMENTOS_DA_FAIXA
                or defeito_anunciado(oferta["titulo"]) or motivo_descarte(dict(alvo, rede=None), item, sem_rede=True)):
            continue
        chave = (titulo_sem_cor(oferta["titulo"]), oferta["loja"], oferta["preco"])
        if chave in vistos:
            continue
        vistos.add(chave)
        consultas += 1
        ficha, erro = baixar(oferta["link"], rede_da_ficha, mem, prazo - 0.4, sessao)
        if erro or not isinstance(ficha, dict) or not ficha.get("rede_confirmada"):
            continue
        marca, modelo = modelo_do_titulo(ficha["titulo_pagina"])
        if (chave_marca(marca) != chave_marca(alvo["marca"])
                or chave_modelo(modelo, sem_rede=True) != chave_modelo(alvo["modelo"], sem_rede=True)):
            continue
        verificadas[k] = dict(oferta, **ficha, rede_conferida_em=datetime.now(FUSO).isoformat(timespec="seconds"))
    return verificadas


def coletar_trocafy(busca, mem, prazo, usar_cache):
    inicio = time.monotonic()
    chave = FONTES["Trocafy"][0](busca)
    resultado = {"fonte": "Trocafy", "url": TROCAFY + "/", "ofertas": [], "momento": time.time(), "cache": False}
    if condicao_em(busca) != "usado":
        return dict(resultado, status="fonte de aparelhos usados: não se aplica à condição pedida")
    guardado = mem["paginas"].get(chave)
    if usar_cache and guardado and time.time() - guardado["momento"] < CACHE_SEGUNDOS:
        return dict(guardado, cache=True)
    with requests.Session() as sessao:
        catalogo = mem.get("rotas_trocafy")
        if not catalogo or time.time() - catalogo[0] > 24 * 3600:
            rotas, erro = baixar(TROCAFY + "/", ler_rotas_trocafy, mem, prazo, sessao)
            if erro:
                return dict(resultado, status=erro)
            catalogo = (time.time(), rotas)
            mem["rotas_trocafy"] = catalogo
        alvo, _ = classificar_por_regras(busca, [])
        rota = next((r["url"] for r in catalogo[1]
                     if chave_modelo(r["modelo"], sem_rede=True) == chave_modelo(alvo["modelo"], sem_rede=True)), None)
        if not rota:
            return dict(resultado, status="modelo não consta nas categorias públicas da loja")
        ofertas, erro = baixar(rota, ler_trocafy, mem, prazo, sessao)
        if erro:
            return dict(resultado, url=rota, status=erro)
        alvo, itens = classificar_por_regras(busca, [oferta["titulo"] for oferta in ofertas])
        ordenadas = sorted(zip(ofertas, itens), key=lambda par: motivo_descarte(
            alvo, dict(par[1], condicao=par[0].get("condicao_confirmada") or par[1]["condicao"]), sem_rede=True) is not None)
        ofertas = [oferta for oferta, _ in ordenadas]
        ofertas = confirmar_redes(busca, ofertas[:MAXIMO_POR_LOJA], mem, prazo, sessao)
        resultado.update(url=rota, ofertas=ofertas, status=f"{len(ofertas)} ofertas",
                         coletado=datetime.now(FUSO).strftime("%H:%M"), segundos=time.monotonic() - inicio)
        with mem["trava"]:
            mem["paginas"][chave] = resultado
        return resultado


def coletar(nome, busca, mem, prazo=None, usar_cache=True):
    inicio = time.monotonic()
    prazo = prazo if prazo is not None else inicio + TEMPO_TOTAL_COLETA
    if nome == "Trocafy":
        return coletar_trocafy(busca, mem, prazo, usar_cache)
    montar_url, ler = FONTES[nome]
    url = montar_url(busca)
    guardado = mem["paginas"].get(url)
    if usar_cache and guardado and time.time() - guardado["momento"] < CACHE_SEGUNDOS:
        return dict(guardado, cache=True, segundos=time.monotonic() - inicio)
    buscas = [busca]
    com_smartphone = " ".join(["smartphone"] + [p for p in busca.split() if p not in TIPOS_DE_APARELHO])
    if nome in BUSCA_COM_SMARTPHONE and com_smartphone != busca:
        buscas.append(com_smartphone)
    sessao = requests.Session()
    if len(buscas) == 1:
        respostas = [baixar(url, ler, mem, prazo, sessao)]
    else:
        with ThreadPoolExecutor(max_workers=len(buscas)) as executor:
            respostas = list(executor.map(lambda texto: baixar(montar_url(texto), ler, mem, prazo), buscas))
    resultado = {"fonte": nome, "url": url, "ofertas": [], "momento": time.time(),
                 "cache": False, "segundos": time.monotonic() - inicio}
    ofertas = [oferta for lista, _ in respostas for oferta in lista]
    if not ofertas and respostas[0][1]:
        resultado["status"] = respostas[0][1]
        sessao.close()
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
    try:
        if resultado["ofertas"]:
            verificadas = confirmar_redes(busca, resultado["ofertas"], mem, prazo, sessao)
            resultado = dict(resultado, ofertas=verificadas, segundos=time.monotonic() - inicio)
            with mem["trava"]:
                mem["paginas"][url] = resultado
    finally:
        sessao.close()
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


def coletar_todas(busca, mem, forcar_coleta=False, tempo_limite=TEMPO_TOTAL_COLETA):
    esquecer_vencidas(mem)
    iniciado_em = time.time()
    prazo = time.monotonic() + tempo_limite
    executor = ThreadPoolExecutor(max_workers=len(FONTES))
    futuras = {nome: executor.submit(coletar, nome, busca, mem, prazo, not forcar_coleta) for nome in FONTES}
    try:
        concluidas, _ = wait(futuras.values(), timeout=max(0, prazo - time.monotonic()))
        resultados = []
        for nome, futura in futuras.items():
            if futura in concluidas:
                try:
                    resultados.append(futura.result())
                    continue
                except Exception:
                    status = "falha na coleta"
            else:
                status = "tempo limite da coleta"
                guardado = mem["paginas"].get(FONTES[nome][0](busca))
                if guardado and guardado["momento"] >= iniciado_em:
                    # A busca já chegou; a fonte ainda está verificando fichas. Preserva a lista inicial, sem inventar rede.
                    resultados.append(dict(guardado, aviso="tempo limite na conferência de detalhes"))
                    continue
            resultados.append({"fonte": nome, "url": FONTES[nome][0](busca), "ofertas": [],
                               "momento": time.time(), "status": status, "cache": False})
        return resultados
    finally:
        # Sair de `with ThreadPoolExecutor` esperaria pelas fontes atrasadas, anulando o prazo.
        executor.shutdown(wait=False, cancel_futures=True)


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
            f"Poucas ofertas equivalentes com pagamento à vista ou no Pix confirmado: encontrei {len(linhas)}. "
            f"A faixa de preço só é exibida com pelo menos {MINIMO_OFERTAS} ofertas."
        )
        return
    menor, mediana, maior = st.columns(3)
    menor.metric("Menor preço", reais(linhas["preco"].min()))
    mediana.metric("Mediana", reais(statistics.median(linhas["preco"])))
    maior.metric("Maior preço", reais(linhas["preco"].max()))
    por_fonte = " · ".join(f"{fonte}: {total}" for fonte, total in linhas["fonte"].value_counts().items())
    st.caption(
        f"Baseada em {len(linhas)} ofertas equivalentes com pagamento à vista ou no Pix ({por_fonte}). "
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
    tem_rede = "rede_confirmada" in linhas and linhas["rede_confirmada"].isin(["4g", "5g"]).any()
    colunas = ["Produto"] + (["Motivo"] if com_motivo else []) + ["Preço", "Pagamento"] + (["Rede"] if tem_rede else []) + ["Loja", "Fonte", "Compra"]
    tabela = ["| " + " | ".join(colunas) + " |", "|" + " --- |" * len(colunas)]
    for _, linha in linhas.iterrows():
        celulas = [escapar(linha["titulo"])] + ([escapar(linha["motivo"])] if com_motivo else [])
        celulas += [escapar(reais(linha["preco"]).replace(" ", "\u00a0")), escapar(linha.get("pagamento") or "não informada")]
        if tem_rede:
            rede = linha.get("rede_confirmada")
            celulas += [f"{rede.upper()} (ficha)" if rede in ("4g", "5g") else (rede_em(linha["titulo"]) or "não informada").upper()]
        celulas += [escapar(linha["loja"]),
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


def pagamento_confirmado(linhas):
    if "pagamento" not in linhas:
        return pd.Series(False, index=linhas.index)  # oferta sem forma de pagamento registrada conta como não informada
    return linhas["pagamento"].isin(PAGAMENTOS_DA_FAIXA)


def marcar_repetidas(linhas):
    """Cada oferta conta uma vez na faixa e no mínimo de ofertas:
    1) o mesmo anúncio achado duas vezes (ex.: pelo Compare Livre e na própria KaBuM!) fica só com a versão da loja;
    2) o mesmo título, sem contar a cor, na mesma loja, com o mesmo preço e armazenamento, é a mesma oferta.
    Entre repetidas, fica a que tem pagamento à vista ou no Pix confirmado.
    Anúncios de títulos diferentes continuam separados, mesmo com loja e preço iguais."""
    validas = linhas[linhas["motivo"].isna()]
    loja_primeiro = validas.assign(sem_pagamento=~pagamento_confirmado(validas), indireto=validas["link"] != validas["pagina"]) \
                          .sort_values(["sem_pagamento", "indireto"], kind="stable")
    repetidas = loja_primeiro["link"].map(chave_do_anuncio).duplicated()
    linhas.loc[repetidas[repetidas].index, "motivo"] = "mesmo anúncio já contado"
    validas = linhas[linhas["motivo"].isna()]
    validas = validas.loc[(~pagamento_confirmado(validas)).sort_values(kind="stable").index]
    chave = pd.DataFrame({"loja": validas["loja"].map(lambda nome: re.sub(r"[^a-z0-9]", "", normalizar(nome))),
                          "preco": validas["preco"], "gb": validas["armazenamento_gb"].fillna(0),
                          "titulo": validas["titulo"].map(titulo_sem_cor)})
    repetidas = chave.duplicated()
    linhas.loc[repetidas[repetidas].index, "motivo"] = "mesma oferta em outra cor (mesmo título, loja e preço)"


def marcar_fora_do_padrao(linhas):
    """Descarta preços com menos da metade ou mais do dobro da mediana do grupo (kits, defeitos, erros). Só as ofertas
    com pagamento à vista ou no Pix confirmado entram na conta e no filtro: preço de pagamento desconhecido não mexe nele."""
    grupos = linhas["armazenamento_gb"].fillna(0).astype(int)
    contam = linhas["motivo"].isna() & pagamento_confirmado(linhas)
    for gb in grupos[contam].unique():
        grupo = contam & (grupos == gb)
        if grupo.sum() >= MINIMO_OFERTAS:
            mediana = linhas.loc[grupo, "preco"].median()
            fora = grupo & ((linhas["preco"] < mediana * 0.5) | (linhas["preco"] > mediana * 2))
            linhas.loc[fora, "motivo"] = "preço fora do padrão (menos da metade ou mais do dobro da mediana)"


def motivos_da_busca(busca, alvo, itens, titulos, redes_confirmadas=None, condicoes_confirmadas=None):
    """Motivo de cada título ficar de fora da busca (None quando é oferta equivalente), antes dos filtros de preço.
    Marca e rede valem pelo que está escrito, com o LLM e com as regras: na busca e em cada título.
    A versão escolhida na tela (5G) vale no lugar da escrita na busca. O defeito vale pelas regras e, com o LLM,
    também pelo que ele leu."""
    alvo = dict(alvo, marca=marca_em(busca) or alvo["marca"], rede=alvo.get("rede") or rede_em(busca))
    # Modelo de uma versão só: a rede (inclusive a escrita na busca) não separa os anúncios do modelo.
    unica = bool(alvo.get("versao_unica"))
    if unica:
        alvo["rede"] = None
    redes_confirmadas = redes_confirmadas or [None] * len(titulos)
    condicoes_confirmadas = condicoes_confirmadas or [None] * len(titulos)
    itens = [dict(item, marca=marca_no_titulo(titulo, alvo["marca"]),
                  rede=rede_em(titulo) or (rede if rede in ("4g", "5g") else None),
                  condicao=condicao if condicao in CONDICOES else item["condicao"],
                  defeito=defeito_anunciado(titulo) or bool(item.get("defeito_llm")))
             for item, titulo, rede, condicao in zip(itens, titulos, redes_confirmadas, condicoes_confirmadas)]
    motivos = [motivo_descarte(alvo, item, sem_rede=unica) for item in itens]
    if all(motivos) and not unica and not alvo["rede"] and chave_modelo(alvo["modelo"]) == chave_modelo(alvo["modelo"], sem_rede=True):
        # Nenhuma oferta com o mesmo nome e a busca não falou em 4G/5G: aceita a versão 4G ou 5G do modelo
        # (ex.: quem busca "samsung a56" encontra o Galaxy A56 5G, que só existe em 5G).
        motivos = [motivo_descarte(alvo, item, sem_rede=True) for item in itens]
    return alvo, itens, motivos


def separar_ofertas(busca, ofertas, alvo, itens):
    """Decide, oferta por oferta, se ela entra na faixa ou por que fica de fora (coluna "motivo")."""
    alvo, itens, motivos = motivos_da_busca(busca, alvo, itens, [oferta["titulo"] for oferta in ofertas],
                                         [oferta.get("rede_confirmada") for oferta in ofertas],
                                         [oferta.get("condicao_confirmada") for oferta in ofertas])
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
    do_modelo = [(itens[k], ofertas[k]) for k in do_mesmo_modelo(alvo, itens)]
    memorias = sorted({item["armazenamento_gb"] for item, _ in do_modelo if item["armazenamento_gb"] in ARMAZENAMENTOS_BUSCA}
                      | ({alvo["armazenamento_gb"]} if alvo["armazenamento_gb"] else set())) + [None]
    coluna_memoria, coluna_versao = st.columns([3, 2])
    gb = coluna_memoria.selectbox("Memória (armazenamento)", memorias, index=memorias.index(alvo["armazenamento_gb"] or None),
                                  key=f"faixa_gb_{chave}", format_func=lambda gb: "Todas as memórias" if gb is None else
                                  f"{int(gb)} GB" if gb < 1000 else f"{int(gb) // 1000} TB")
    escolhido = dict(alvo, armazenamento_gb=gb)
    # A versão só vira opção quando o modelo tem versões 4G e 5G; anúncio sem rede no título não conta como 4G.
    modo = versao_da_tela(busca, escolhido, [oferta["titulo"] for _, oferta in do_modelo])
    if modo == "unica":
        escolhido["versao_unica"] = True
    elif modo == "opcao":
        versao = coluna_versao.radio("Versão", ["4g", "5g"], horizontal=True, key=f"faixa_rede_{chave}",
                                     format_func=lambda r: "5G" if r == "5g" else "4G (comum)")
        escolhido["rede"] = versao
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
    # Só ofertas equivalentes com pagamento à vista ou no Pix confirmado entram na faixa e no destaque da mais barata;
    # as de pagamento não informado ficam à parte, para consulta.
    equivalentes = linhas[linhas["motivo"].isna()]
    iguais = equivalentes[pagamento_confirmado(equivalentes)].sort_values("preco")
    sem_pagamento = equivalentes[~pagamento_confirmado(equivalentes)].sort_values("preco")
    descartadas = linhas[linhas["motivo"].notna()].sort_values("preco")
    st.subheader(f"Faixa de preço: {descrever(alvo)}")
    if "condicao_confirmada" in linhas and linhas["condicao_confirmada"].eq("usado").any():
        st.caption("Na Trocafy, os estados 'Sou como novo', 'Tenho minhas marcas de uso' e 'Fui mais usado' "
                   "são condições de aparelhos usados, conforme informado pela loja.")
    if alvo["armazenamento_gb"] or iguais.empty:
        mostrar_faixa(iguais)
        na_faixa = iguais if len(iguais) >= MINIMO_OFERTAS else iguais.iloc[0:0]
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
        st.write("A busca não informou o armazenamento. Faixa por armazenamento, com as ofertas de pagamento à vista ou no Pix:")
        st.table(pd.DataFrame(resumo), hide_index=True)
        tamanhos = iguais.groupby(iguais["armazenamento_gb"].fillna(0).astype(int))["preco"].transform("size")
        na_faixa = iguais[tamanhos >= MINIMO_OFERTAS]
    avisar_condicao(busca, alvo, descartadas)
    if not na_faixa.empty:
        melhor = na_faixa.iloc[0]
        loja = re.sub(r" e mais \d+$", "", melhor["loja"])
        st.markdown(f"**Oferta mais barata:** {escapar(melhor['titulo'])}, por **{escapar(reais(melhor['preco']))}** ({escapar(loja)}).")
        st.link_button("Ver a oferta no Compare Livre" if sem_destino(melhor) else "Ir para a compra",
                       endereco(melhor["link"]), type="primary")
    if not iguais.empty:
        st.subheader("Ofertas equivalentes à vista ou no Pix")
        tabela_de_ofertas(iguais)
    if not sem_pagamento.empty:
        st.subheader("Fora da faixa: pagamento não informado")
        st.caption("Ofertas equivalentes em que a loja não informa se o preço é à vista ou parcelado. Ficam aqui para consulta.")
        tabela_de_ofertas(sem_pagamento)
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


# Avaliação dos métodos (abre só pelo endereço ?avaliar=1; não aparece na tela de busca)
# Os 50 títulos novos ficam no arquivo avaliacao_50_titulos.csv, ao lado do app, com a busca de referência, os rótulos
# definidos só pelo título e o que a página do anúncio confirma. Os dois métodos recebem só o título e a busca de
# referência, como no app. O LLM é o da busca (mesmas instruções, modelos e lotes). As regras são as funções do app:
# filtro de acessórios, marca e modelo lidos no título (os mesmos da tela de escolha), armazenamento, condição, rede e
# defeito. A decisão de aceitar ou excluir é a da tela de resultado, antes dos filtros de preço.

ARQUIVO_AVALIACAO = "avaliacao_50_titulos.csv"  # na mesma pasta do app.py
DIFERENCA_MINIMA = 10  # pontos percentuais que o LLM precisa ganhar das regras para continuar como método principal


def versao_do_codigo():
    try:
        with open(__file__, "rb") as arquivo:
            return hashlib.sha256(arquivo.read()).hexdigest()[:12]
    except OSError:
        return "desconhecida"


def versao_do_prompt():
    return hashlib.sha256(INSTRUCOES_LOTE.encode("utf-8")).hexdigest()[:12]


def rotulo_tipo(valor):
    return "celular" if normalizar(valor).startswith("celular") else "outro"


def rotulo_gb(valor):
    numero = re.search(r"\d+", normalizar(valor))
    return None if not numero else int(numero[0]) * (1000 if "tb" in normalizar(valor) else 1)


def rotulo_condicao(valor):
    return condicao_por_regras(normalizar(valor)) if normalizar(valor) not in ("", "nao se aplica") else "novo"


def extracao_das_regras(titulo):
    texto = limpar(titulo)
    marca, modelo = modelo_do_titulo(titulo)
    return {"tipo": "outro" if ACESSORIO.search(texto) or ACESSORIO_NO_MEIO.search(texto) else "celular",
            "marca": marca, "modelo": modelo, "armazenamento": armazenamento_em(titulo), "condicao": condicao_em(titulo),
            "rede": rede_em(titulo), "defeito": defeito_anunciado(titulo)}


def extracao_do_llm(item):
    return {"tipo": "celular" if item["celular"] else "outro", "marca": item["marca"], "modelo": item["modelo"],
            "armazenamento": item["armazenamento_gb"], "condicao": item["condicao"], "rede": item.get("rede_llm"),
            "defeito": item.get("defeito_llm")}


def conferir_extracao(rotulo, saida):
    """Acerto de cada campo pelos critérios do protocolo: sem diferença de maiúsculas, acentos, marca escrita junto do
    modelo e 4G; o 5G é cobrado na rede, não no nome do modelo. Em acessório ou outro produto, só o tipo é cobrado."""
    certo = {
        "tipo": rotulo_tipo(rotulo["rotulo_tipo"]) == saida["tipo"],
        "marca": chave_marca(rotulo["rotulo_marca"] if normalizar(rotulo["rotulo_marca"]) not in ("nao informado", "nao se aplica") else "")
                 == chave_marca(saida["marca"]),
        "modelo": chave_modelo(rotulo["rotulo_modelo"] if normalizar(rotulo["rotulo_modelo"]) not in ("nao informado", "nao se aplica") else "", sem_rede=True)
                  == chave_modelo(saida["modelo"], sem_rede=True),
        "armazenamento": rotulo_gb(rotulo["rotulo_armazenamento"]) == saida["armazenamento"],
        "condicao": rotulo_condicao(rotulo["rotulo_condicao"]) == saida["condicao"],
        "rede": rede_em(rotulo["rotulo_rede"]) == saida["rede"],
        "defeito": normalizar(rotulo["rotulo_defeito"]).startswith("s") == bool(saida["defeito"]),
    }
    celular = rotulo_tipo(rotulo["rotulo_tipo"]) == "celular"
    certo["titulo"] = certo["tipo"] and (not celular or (certo["modelo"] and certo["armazenamento"] and certo["condicao"]))
    return certo


def decidir_grupo(busca, titulos, alvo, itens):
    """Decisão da tela de resultado: só os títulos que citam o modelo da busca vão para a comparação; os outros ficam
    como outro modelo, como no app."""
    vazio = {"celular": True, "marca": None, "modelo": None, "armazenamento_gb": None, "condicao": "novo"}
    if not alvo.get("modelo"):
        return ["busca sem modelo reconhecido"] * len(titulos)
    itens = [item if menciona_o_modelo(titulo, busca) else dict(vazio) for item, titulo in zip(itens, titulos)]
    # A tela de resultado abre assim: modelo de versão única sem separar por rede, ou opção 4G/5G começando em 4G.
    modo = versao_da_tela(busca, alvo, [titulos[k] for k in do_mesmo_modelo(alvo, itens)])
    if modo == "unica":
        alvo = dict(alvo, versao_unica=True)
    elif modo == "opcao":
        alvo = dict(alvo, rede="4g")
    return motivos_da_busca(busca, alvo, itens, titulos)[2]


def resultado_da_decisao(motivo, linha):
    """Acerto, erro ou inconclusiva. Oferta aceita só é acerto se a página confirmar os atributos exigidos pela busca;
    se a página contradisser, é erro; se não informar, é inconclusiva."""
    aceitou, rotulo_aceita = motivo is None, normalizar(linha["rotulo_decisao"]).startswith("aceit")
    if aceitou != rotulo_aceita:
        return "erro"
    if not aceitou:
        return "acerto"
    pagina = normalizar(linha["pagina_confirma"])
    return "acerto" if pagina.startswith("sim") else "erro" if pagina.startswith("nao confirma") or pagina == "nao" else "inconclusiva"


def avaliar_metodos(tabela, classificar_llm):
    """Roda os dois métodos, busca por busca, e devolve uma linha por título e o registro da execução."""
    linhas, respostas, falhas = [], [], []
    inicio = time.perf_counter()
    for busca, grupo in tabela.groupby("busca", sort=False):
        titulos = grupo["titulo"].tolist()
        alvo_r, itens_r = classificar_por_regras(limpar(busca), titulos)
        decisao_r = decidir_grupo(limpar(busca), titulos, alvo_r, itens_r)
        try:
            alvo_l, itens_l, modelo = classificar_llm(limpar(busca), titulos)
            respostas.append(modelo)
            decisao_l, falha = decidir_grupo(limpar(busca), titulos, alvo_l, itens_l), None
        except Exception as erro:
            itens_l, decisao_l = [None] * len(titulos), ["falha da IA"] * len(titulos)
            falha = f"falha da IA ({detalhe_da_falha(erro)})"
            falhas.append(busca)
        for k, (_, linha) in enumerate(grupo.iterrows()):
            saida_r = extracao_das_regras(linha["titulo"])
            certo_r = conferir_extracao(linha, saida_r)
            registro = {"n": linha["n"], "busca": busca, "titulo": linha["titulo"],
                        **{c: linha[c] for c in tabela.columns if c.startswith("rotulo_") or c.startswith("pagina_")}}
            if itens_l[k] is None:
                registro.update({"llm_falha": falha, "llm_acertou": False, "llm_decisao": "falha da IA", "llm_resultado_decisao": "erro"})
            else:
                saida_l = extracao_do_llm(itens_l[k])
                certo_l = conferir_extracao(linha, saida_l)
                registro.update({f"llm_{c}": saida_l[c] for c in saida_l})
                registro.update({f"llm_{c}_certo": certo_l[c] for c in ("tipo", "modelo", "armazenamento", "condicao", "rede", "defeito")})
                registro.update({"llm_falha": "", "llm_acertou": certo_l["titulo"],
                                 "llm_decisao": decisao_l[k] or "aceitar", "llm_resultado_decisao": resultado_da_decisao(decisao_l[k], linha)})
            registro.update({f"regras_{c}": saida_r[c] for c in saida_r})
            registro.update({f"regras_{c}_certo": certo_r[c] for c in ("tipo", "modelo", "armazenamento", "condicao", "rede", "defeito")})
            registro.update({"regras_acertou": certo_r["titulo"], "regras_decisao": decisao_r[k] or "aceitar",
                             "regras_resultado_decisao": resultado_da_decisao(decisao_r[k], linha)})
            linhas.append(registro)
    resultado = pd.DataFrame(linhas, dtype=object).sort_values("n", key=lambda n: pd.to_numeric(n, errors="coerce"))
    execucao = {"quando": datetime.now(FUSO).strftime("%d/%m/%Y %H:%M"), "segundos": time.perf_counter() - inicio,
                "respondeu": ", ".join(dict.fromkeys(m for r in respostas for m in r.split(", "))) or "nenhum",
                "buscas_com_falha": falhas}
    return resultado, execucao


def detalhe_da_falha(erro):
    if isinstance(erro, requests.HTTPError) and erro.response is not None:
        detalhe = detalhe_do_erro(erro.response)
        return f"erro HTTP {erro.response.status_code}" + (f", {detalhe}" if detalhe else "")
    return "sem resposta" if isinstance(erro, requests.RequestException) else "resposta inválida"


def resumo_da_avaliacao(resultado):
    total = len(resultado)
    llm, regras = int(resultado["llm_acertou"].astype(bool).sum()), int(resultado["regras_acertou"].astype(bool).sum())
    diferenca = (llm - regras) / total * 100
    celulares = resultado[resultado["rotulo_tipo"].map(rotulo_tipo) == "celular"]
    por_campo = lambda metodo, campo: (f"{int(celulares.get(f'{metodo}_{campo}_certo', pd.Series(dtype=object)).fillna(False).astype(bool).sum())}"
                                       f" de {len(celulares)}")
    decisao = lambda metodo: " · ".join(f"{n} {r}" for r, n in resultado[f"{metodo}_resultado_decisao"].value_counts().items())
    principal = "LLM" if diferenca >= DIFERENCA_MINIMA else "regras"
    return {"total": total, "llm": llm, "regras": regras, "diferenca": diferenca, "principal": principal,
            "falhas": int((resultado["llm_falha"].astype(str) != "").sum()),
            "rede": (por_campo("llm", "rede"), por_campo("regras", "rede")),
            "defeito": (por_campo("llm", "defeito"), por_campo("regras", "defeito")),
            "decisao": (decisao("llm"), decisao("regras"))}


CAMPOS_DO_ROTULO = ["rotulo_tipo", "rotulo_marca", "rotulo_modelo", "rotulo_armazenamento", "rotulo_condicao",
                    "rotulo_rede", "rotulo_defeito", "rotulo_decisao"]
COLUNAS_DA_TABELA = {"n": "Nº", "titulo": "Título", "fonte": "Fonte", "url": "URL", "busca": "Busca de referência",
                     "rotulo_tipo": "Tipo", "rotulo_marca": "Marca", "rotulo_modelo": "Modelo",
                     "rotulo_armazenamento": "Armazenamento", "rotulo_condicao": "Condição", "rotulo_rede": "Rede",
                     "rotulo_defeito": "Defeito anunciado", "rotulo_mesmo_modelo": "Mesmo modelo da busca",
                     "rotulo_decisao": "Decisão (oferta equivalente)", "rotulo_motivo": "Motivo da exclusão",
                     "rotulo_observacao": "Observação"}


COLUNAS_DOS_ERROS = ["n", "titulo", "busca", "rotulo_modelo", "rotulo_armazenamento", "rotulo_condicao", "rotulo_rede",
                     "rotulo_defeito", "rotulo_decisao", "pagina_confirma", "llm_falha", "llm_modelo", "llm_armazenamento",
                     "llm_condicao", "llm_rede", "llm_defeito", "llm_acertou", "llm_decisao", "llm_resultado_decisao",
                     "regras_modelo", "regras_armazenamento", "regras_condicao", "regras_rede", "regras_defeito",
                     "regras_acertou", "regras_decisao", "regras_resultado_decisao"]


def rotulo_completo(linha):
    """Rótulo pronto: todos os campos preenchidos e, quando a decisão é excluir, o motivo."""
    if any(not str(linha.get(campo, "")).strip() for campo in CAMPOS_DO_ROTULO):
        return False
    return not normalizar(linha["rotulo_decisao"]).startswith("excl") or bool(str(linha.get("rotulo_motivo", "")).strip())


def mostrar_titulos(tabela):
    """Os títulos com fonte, endereço do anúncio e busca de referência, e os rótulos como estão no arquivo."""
    colunas = [c for c in COLUNAS_DA_TABELA if c in tabela.columns]
    vista = tabela[colunas].copy()
    config = {c: st.column_config.TextColumn(COLUNAS_DA_TABELA[c]) for c in colunas}
    if "n" in vista:
        vista["n"] = pd.to_numeric(vista["n"], errors="coerce")
        config["n"] = st.column_config.NumberColumn("Nº", format="%d")
    if "titulo" in vista:
        config["titulo"] = st.column_config.TextColumn("Título", width="large")
    if "url" in vista:
        config["url"] = st.column_config.LinkColumn("URL", width="medium", display_text=r"https?://(?:www\.)?(.+)")
    if "busca" in vista:
        config["busca"] = st.column_config.TextColumn("Busca de referência", width="medium")
    if "coletado_em" in tabela:
        horas = sorted(h.strip() for h in tabela["coletado_em"] if h.strip())
        if horas and horas[0][:10] == horas[-1][:10]:
            st.caption(f"Coletados em {horas[0][:10]}, das {horas[0][11:16]} às {horas[-1][11:16]}.")
    rotulados = [linha for linha in tabela.to_dict("records") if rotulo_completo(linha)]
    if rotulados:
        celulares = [linha for linha in rotulados if rotulo_tipo(linha["rotulo_tipo"]) == "celular"]
        usados = sum(normalizar(linha["rotulo_condicao"]) == "usado" for linha in celulares)
        recondicionados = sum(normalizar(linha["rotulo_condicao"]) == "recondicionado" for linha in celulares)
        st.caption(f"Pelos rótulos: {usados} usados, {recondicionados} recondicionados, {len(rotulados) - len(celulares)} "
                   f"acessórios e outros produtos e {len(celulares) - usados - recondicionados} sem indicação de uso no título.")
    st.dataframe(vista, hide_index=True, column_config=config, height=35 * (len(vista) + 1) + 3)


ARQUIVO_RESULTADOS = "resultados_registrados.json"  # resultados já obtidos, publicados ao lado do app.py
ARQUIVO_PROTOCOLO = "PROTOCOLO.md"  # protocolo de validação, publicado ao lado do app.py
ARQUIVO_VALIDACAO = "validacao_tecnica.json"
ARQUIVO_NAVEGADOR = "validacao_navegador.json"


def mostrar_validacao_tecnica():
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_VALIDACAO)
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as arquivo:
        registro = json.load(arquivo)
    st.header("Reconferência técnica com a coleta atualizada")
    st.caption(f"{registro['inicio']} a {registro['fim']} · código {registro['codigo_sha256'][:12]} · {registro['origem']}")
    st.info("Resultados automáticos: a revisão humana dos rótulos e das ofertas "
            "e os testes com os participantes continuam pendentes.")
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_NAVEGADOR)):
        st.warning("A cobertura abaixo foi medida no ambiente de desenvolvimento. A verificação das fontes no app "
                   "publicado ainda está em andamento; a Magazine Luiza retornou HTTP 403 nesse servidor.")
    resumo = registro["resumo"]
    extracao = registro["extracao_regras"]
    tabela_fixa([
        {"Medida": "Extração pelas regras", "Resultado": f"{extracao['acertos']} de {extracao['total']} nos rótulos publicados",
         "Meta": "90%; revisão humana pendente"},
        {"Medida": "Cobertura automática com preços confirmados", "Resultado": f"{resumo['duas_lojas']} de {resumo['buscas']} buscas em duas lojas",
         "Meta": "18 de 20; conferência humana pendente"},
        {"Medida": "Tempo no servidor de testes", "Resultado": f"{resumo['ate_15s_servidor']} de {resumo['buscas']} em até 15 s",
         "Meta": "18 de 20 do clique ao resultado no navegador"},
        {"Medida": "Faixas geradas", "Resultado": f"{resumo['geraram_faixa']} de {resumo['buscas']}", "Meta": "Informada"},
        {"Medida": "Equivalência das ofertas", "Resultado": f"{resumo['ofertas_para_conferencia']} ofertas aguardam conferência humana",
         "Meta": "95%"},
        {"Medida": "Digitação, redução do tempo e utilidade", "Resultado": "Testes com 5 lojistas e 5 consumidores pendentes",
         "Meta": "Conforme protocolo publicado"},
    ])
    st.dataframe(pd.DataFrame([{
        "Nº": busca["n"], "Entrada": busca["entrada"], "Tempo no servidor (s)": busca["segundos_servidor"],
        "Lojas distintas": len(busca["lojas"]), "Ofertas com pagamento confirmado": busca["ofertas_confirmadas"],
        "Gerou faixa?": "Sim" if busca["gerou_faixa"] else "Não",
        "Falhas das fontes": "; ".join(f"{f['fonte']}: {f['status']}" for f in busca["fontes"]
                                      if any(t in f["status"] for t in ("limite", "erro", "falha", "sem resposta"))),
    } for busca in registro["buscas"]]), hide_index=True)
    with st.expander("Ofertas e evidências para conferência humana"):
        ofertas = [{"Busca": busca["entrada"], "Título": oferta["titulo"], "Preço": oferta["preco"],
                    "Fonte": oferta["fonte"], "Pagamento": oferta["pagamento"], "URL": oferta["link"],
                    "Rede na ficha": oferta.get("rede_confirmada", ""), "Evidência de rede": oferta.get("evidencia_rede", ""),
                    "Conferida em": oferta.get("rede_conferida_em", "")}
                   for busca in registro["buscas"] for oferta in busca["ofertas"] if oferta["na_faixa"]]
        st.dataframe(pd.DataFrame(ofertas), hide_index=True, column_config={"URL": st.column_config.LinkColumn("URL")})
    for limite in registro["limites"]:
        st.caption(limite)
    if registro.get("historico"):
        with st.expander("Rodadas técnicas anteriores"):
            for anterior in registro["historico"]:
                resumo_anterior = anterior["resumo"]
                st.write(f"{anterior['inicio']} · código {anterior['codigo_sha256'][:12]}: "
                         f"{resumo_anterior['duas_lojas']} de {resumo_anterior['buscas']} buscas em duas lojas; "
                         f"{resumo_anterior['ate_15s_servidor']} em até 15 s no servidor.")
                st.markdown(f"[Registro completo](https://github.com/KevinCostaAI/faixa-certa/blob/main/{anterior['arquivo']})")
    st.divider()


def mostrar_validacao_navegador():
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_NAVEGADOR)
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as arquivo:
        registro = json.load(arquivo)
    st.header("Tempo no app publicado, com coleta nova")
    st.caption(f"{registro['inicio']} a {registro['fim']} · código {registro['codigo_sha256'][:12]} · navegador Edge")
    st.write(registro["metodo"])
    total = len(registro["buscas"])
    st.write(f"Tempo: {registro['ate_15s']} de {total} buscas em até 15 segundos. "
             f"Meta: 18 de 20 — {'atingida' if total == 20 and registro['ate_15s'] >= 18 else 'não atingida'}.")
    if "duas_lojas" in registro:
        st.write(f"Cobertura automática no app publicado: {registro['duas_lojas']} de {total} buscas em duas lojas. "
                 f"Meta: 18 de 20 — {'atingida na contagem automática' if total == 20 and registro['duas_lojas'] >= 18 else 'não atingida'}. "
                 "A conferência humana dos produtos e preços ainda está pendente.")
    st.dataframe(pd.DataFrame([{
        "Nº": busca["n"], "Entrada": busca["entrada"], "Tempo no navegador (s)": busca["segundos"],
        "Conclusão exibida pelo app": busca["conclusao"],
    } for busca in registro["buscas"]]), hide_index=True)
    ofertas = [dict(oferta, Busca=busca["entrada"], Coletado=busca["quando"])
               for busca in registro["buscas"] for oferta in busca.get("ofertas", [])]
    if ofertas:
        with st.expander("Ofertas exibidas no app publicado, para revisão humana"):
            st.dataframe(pd.DataFrame(ofertas), hide_index=True, column_config={"link": st.column_config.LinkColumn("URL")})
    st.caption("Execução automatizada no navegador; não é um teste com usuários. A conferência humana das ofertas permanece pendente.")
    st.divider()


def tabela_fixa(linhas):
    tabela = pd.DataFrame(linhas).astype(str)
    st.table(tabela.set_index(tabela.columns[0]))


def mostrar_registro(registro):
    """Uma execução registrada: data, versão, tabelas e observações, como foram obtidas."""
    st.subheader(registro["titulo"])
    st.caption(" · ".join(registro[c] for c in ("quando", "versao", "modelos", "conferencia") if registro.get(c)))
    for texto in registro.get("textos", []):
        st.write(texto)
    if registro.get("medidas"):
        tabela_fixa(registro["medidas"])
    if registro.get("resumo"):
        tabela_fixa(registro["resumo"])
    if registro.get("decisao"):
        st.write(registro["decisao"])
    if registro.get("erros"):
        st.markdown(f"**Erros caso a caso ({len(registro['erros'])} títulos)**")
        tabela_fixa(registro["erros"])
    if registro.get("buscas"):
        st.markdown(f"**Buscas ({len(registro['buscas'])})**")
        tabela_fixa(registro["buscas"])
    if registro.get("ofertas"):
        with st.expander(f"Ofertas conferidas nas páginas das lojas ({len(registro['ofertas'])})"):
            st.dataframe(pd.DataFrame(registro["ofertas"]).astype(str), hide_index=True, column_config={
                "URL": st.column_config.LinkColumn("URL", display_text=r"https?://(?:www\.)?(.+)")})
    for nome, chave in (("Falhas encontradas", "falhas"), ("Desvios do protocolo", "desvios"), ("Observações", "observacoes")):
        if registro.get(chave):
            st.markdown(f"**{nome}**")
            st.markdown("\n".join(f"- {item}" for item in registro[chave]))


def mostrar_resultados_registrados():
    """Resultados já obtidos: aparecem ao abrir a página, sem rodar os métodos de novo. Uma execução nova nesta
    página aparece à parte e não muda os registros; reconferências de versões corrigidas entram depois dos originais."""
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_RESULTADOS)
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    st.header("Resultados registrados")
    st.warning(dados["aviso_ia"])
    mostrar_registro(dados["avaliacao"])
    mostrar_registro(dados["bateria"])
    for registro in dados.get("reconferencias", []):
        mostrar_registro(registro)
    st.divider()


def mostrar_protocolo():
    st.title("Faixa Certa: protocolo de validação")
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_PROTOCOLO)
    if not os.path.exists(caminho):
        st.info("O protocolo ainda não foi publicado.")
        return
    with open(caminho, encoding="utf-8") as arquivo:
        st.markdown(arquivo.read())


def mostrar_avaliacao():
    st.title("Faixa Certa: avaliação dos métodos")
    # Tira o ícone de baixar da barra das tabelas; os resultados ficam só na página.
    st.html('<style>[data-testid="stElementToolbarButton"]:has(button[aria-label^="Download"]), '
            'button[aria-label^="Download"] {display: none !important;}</style>')
    st.write("Os 50 títulos novos passam pelos dois métodos, cada um com a busca de referência do título, como no app. "
             "Um título está correto quando tipo, modelo completo, armazenamento e condição batem com o rótulo; em "
             f"acessório, basta o tipo. Se o LLM não superar as regras em pelo menos {DIFERENCA_MINIMA} pontos "
             "percentuais, as regras passam a ser o método principal. Resultado das regras não conta como acerto do LLM.")
    st.caption(f"Versão desta página: código {versao_do_codigo()} (SHA-256 do app.py, 12 primeiros caracteres), prompt "
               f"{versao_do_prompt()}, LLM principal {LLM_MODELO}, reserva {LLM_MODELO_RESERVA}, {LOTE_LLM} títulos por "
               f"chamada. Regras: filtro de acessórios, marca e modelo como na tela de escolha, armazenamento, condição, "
               "rede e defeito lidos no título. Cada resultado registrado traz a versão em que foi obtido.")
    mostrar_validacao_navegador()
    mostrar_validacao_tecnica()
    mostrar_resultados_registrados()
    arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_AVALIACAO)
    if not os.path.exists(arquivo):
        st.info("O arquivo com os 50 títulos novos e os rótulos ainda não foi publicado.")
        return
    tabela = pd.read_csv(arquivo, dtype=str, keep_default_na=False)
    faltam = sum(not rotulo_completo(linha) for linha in tabela.to_dict("records"))
    st.subheader("Títulos e rótulos")
    st.write(f"{len(tabela)} títulos em {tabela['busca'].nunique()} buscas de referência. Rótulos preenchidos: "
             f"{len(tabela) - faltam} de {len(tabela)}. Os rótulos pendentes aparecem em branco.")
    mostrar_titulos(tabela)
    if faltam:
        st.info(f"Os dois métodos só rodam quando os {len(tabela)} títulos estiverem rotulados. Faltam {faltam}.")
        return
    erro = None
    if not LLM_CHAVE:
        st.warning("Sem chave de IA configurada: não dá para rodar o LLM.")
    elif st.button("Rodar os dois métodos", type="primary"):
        with st.spinner("Rodando os dois métodos, busca por busca..."):
            # Aqui a espera do LLM pode chegar a 90 segundos por busca; na tela de busca, o limite é TEMPO_LLM.
            st.session_state.avaliacao = avaliar_metodos(tabela, lambda busca, titulos: classificar_em_lotes(busca, titulos, tempo=90))
    if "avaliacao" not in st.session_state:
        return
    resultado, execucao = st.session_state.avaliacao
    r = resumo_da_avaliacao(resultado)
    st.subheader("Nova execução nesta página")
    st.caption(f"Feita com a versão {versao_do_codigo()}. Fica só nesta sessão e não substitui os resultados registrados acima.")
    st.write(f"Extração: LLM {r['llm']} de {r['total']} títulos corretos ({r['llm'] / r['total']:.0%}); regras "
             f"{r['regras']} de {r['total']} ({r['regras'] / r['total']:.0%}). Diferença: {r['diferenca']:+.0f} pontos. "
             f"Método principal pelo critério de {DIFERENCA_MINIMA} pontos: **{r['principal']}**.")
    st.write(f"Falhas da IA: {r['falhas']} títulos, contados como erro do LLM. Rede nos celulares: LLM {r['rede'][0]}, "
             f"regras {r['rede'][1]}. Defeito nos celulares: LLM {r['defeito'][0]}, regras {r['defeito'][1]}.")
    st.write(f"Decisão de aceitar ou excluir: LLM {r['decisao'][0]}; regras {r['decisao'][1]}.")
    st.caption(f"Rodado em {execucao['quando']}, em {execucao['segundos']:.0f} s. Modelo do LLM que respondeu: "
               f"{execucao['respondeu']}." + (f" Buscas com falha da IA: {', '.join(execucao['buscas_com_falha'])}."
                                               if execucao["buscas_com_falha"] else ""))
    erros = resultado[~resultado["llm_acertou"].astype(bool) | ~resultado["regras_acertou"].astype(bool)
                      | (resultado["llm_resultado_decisao"] != "acerto") | (resultado["regras_resultado_decisao"] != "acerto")]
    st.subheader(f"Erros caso a caso ({len(erros)} títulos)")
    st.table(erros[[c for c in COLUNAS_DOS_ERROS if c in erros.columns]].fillna("").astype(str).set_index("n"))
    st.subheader("Todos os títulos")
    st.dataframe(resultado.fillna("").astype(str), hide_index=True)


# Interface
def buscar_como_digitado():
    st.session_state.update(sem_correcao=True, nova_busca=True)


def mostrar_diagnostico_fontes():
    st.title("Diagnóstico das fontes no servidor publicado")
    st.write("Verifica páginas públicas e robots.txt, sem registrar preços como resultados de validação.")
    candidatas = {
        "Webcontinental": "https://www.webcontinental.com.br/smartphone-poco-c85-6-6gb-128gb-preto-006293000067/p",
        "Trocafone": "https://www.trocafone.com.br/",
        "Casas Bahia": "https://www.casasbahia.com.br/galaxy-a17-128gb/b",
        "Efácil": "https://www.efacil.com.br/loja/departamento/Smartphones",
        "Trocafy": TROCAFY + "/",
        "Magalu móvel": "https://m.magazineluiza.com.br/busca/galaxy+a17+128gb/",
    }
    def diagnosticar(item):
        nome, url = item
        inicio = time.monotonic()
        mem = memoria()
        with requests.Session() as sessao:
            try:
                prazo = inicio + TEMPO_TOTAL_COLETA
                if not robots_permite(url, mem, prazo, sessao):
                    return {"fonte": nome, "status": "coleta não permitida por robots.txt"}
                resposta, conteudo = baixar_conteudo(url, prazo, sessao)
                arvore = arvore_utf8(conteudo)
                titulo = arvore.xpath('normalize-space(string(//title))')
                dados = {"fonte": nome, "url": url, "status": resposta.status_code, "titulo": titulo,
                         "bytes": len(conteudo), "segundos": round(time.monotonic() - inicio, 2),
                         "scripts": [(n.get("id"), n.get("type")) for n in arvore.xpath('//script[@id or @type="application/ld+json"]')][:8],
                         "formulario": arvore.xpath('//form/@action')[:3]}
                for no in arvore.xpath('//script|//style|//noscript'):
                    no.drop_tree()
                texto = " ".join(arvore.text_content().split())
                dados["pagamento"] = [texto[max(0, m.start() - 70):m.start() + 100]
                                       for m in list(re.finditer(r"\bpix\b|a vista|à vista", texto, re.I))[:3]]
                return dados
            except Exception as erro:
                return {"fonte": nome, "status": type(erro).__name__, "segundos": round(time.monotonic() - inicio, 2)}
    if st.button("Verificar fontes públicas"):
        with st.spinner("Verificando as fontes no servidor..."):
            executor = ThreadPoolExecutor(max_workers=len(candidatas))
            futuras = {nome: executor.submit(diagnosticar, (nome, url)) for nome, url in candidatas.items()}
            prontas, _ = wait(futuras.values(), timeout=TEMPO_TOTAL_COLETA)
            st.session_state.diagnostico_fontes = [f.result() if f in prontas else {"fonte": nome, "status": "tempo limite"}
                                                  for nome, f in futuras.items()]
            executor.shutdown(wait=False, cancel_futures=True)
    if "diagnostico_fontes" in st.session_state:
        st.code(json.dumps(st.session_state.diagnostico_fontes, ensure_ascii=False, indent=2), language="json")


def main():
    st.set_page_config(page_title="Faixa Certa", layout="wide" if "1" in (st.query_params.get("avaliar"), st.query_params.get("protocolo"))
                       else "centered")
    if st.query_params.get("protocolo") == "1":
        mostrar_protocolo()  # protocolo de validação, aberto a qualquer pessoa pelo endereço ?protocolo=1
        st.stop()
    if st.query_params.get("avaliar") == "1":
        mostrar_avaliacao()  # reprodução dos testes de extração; não aparece na tela de busca
        st.stop()
    if st.query_params.get("diagnostico") == "1":
        mostrar_diagnostico_fontes()
        st.stop()
    st.title("Faixa Certa")
    st.write("Compara o preço de um smartphone em várias lojas.")
    st.caption("A faixa usa só preços à vista ou no Pix confirmados pela loja, sem frete; ofertas sem forma de pagamento informada "
               "aparecem à parte. Os preços são coletados nas lojas na hora da busca, e uma busca repetida em até 15 minutos "
               "reaproveita o resultado.")
    st.caption(f"Extrator principal: {'LLM' if LLM_CHAVE and METODO_PRINCIPAL == 'LLM' else 'regras' if LLM_CHAVE else 'regras (sem chave de IA configurada)'}. "
               f"Fontes: {', '.join(FONTES)}.")
    forcar_coleta = st.query_params.get("coleta_nova") == "1"
    if forcar_coleta:
        st.caption("Validação técnica: buscas por modelo com coleta nova de preços, sem reaproveitar o cache.")

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
            inicio_busca = time.perf_counter()
            descricao_coleta = ""
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
                        coletas = [dict(coleta, cache=True) for coleta in guardada[1]]
                    else:
                        coletas = coletar_todas(busca, mem, forcar_coleta=forcar_coleta)
                        st.session_state.coleta_atual = (busca, coletas)
                    caches = [bool(coleta.get("cache")) for coleta in coletas]
                    descricao_coleta = ("Coleta reaproveitada." if caches and all(caches) else
                                        "Coleta parcialmente reaproveitada." if any(caches) else "Coleta nova.")
                    # Sem modelo reconhecido na busca ("quero um celular bom"), a pessoa escolhe entre os celulares das lojas.
                    falta = not mostrar_resultados(busca, coletas, mem)
            if falta:
                mostrar_opcoes(busca)
            st.caption(f"Consulta concluída: {exibir(busca)}. {descricao_coleta} "
                       f"Processamento: {time.perf_counter() - inicio_busca:.1f} s.")


if __name__ == "__main__":
    main()
