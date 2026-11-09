"""Faixa Certa: faixa de preço de smartphones a partir de ofertas reais equivalentes."""

import json
import os
import re
import sqlite3
import statistics
import tempfile
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

ARQUIVO = Path(__file__).with_name("ofertas_faixa_certa.csv")
BANCO = Path(tempfile.gettempdir()) / "faixa_certa.db"
MINIMO_OFERTAS = 3  # RF06
LLM_URL = os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
LLM_MODELO = os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")
LLM_TEMPO_MAXIMO = 5  # segundos, RNF01
COLUNAS = ["Título", "Preço", "Loja", "Data da coleta"]


# Extrator por regras: ponto de comparação e alternativa quando o serviço de IA não responde.
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


# Extrator com LLM: ao serviço de IA vai apenas o título do produto.
INSTRUCOES = f"""Você extrai atributos de títulos de anúncios de smartphones.
Responda somente com um objeto JSON com as chaves modelo, armazenamento_gb e condicao.
- modelo: exatamente um destes valores, ou null se o título for de acessório, de outro modelo ou citar vários modelos: {sorted(MODELOS)}.
- Se o título não informar 4G ou 5G, use o nome sem 5G.
- armazenamento_gb: um destes números, ou null se não houver um valor único: {ARMAZENAMENTOS}.
- condicao: novo, usado ou recondicionado. Sem indicação no título, use novo."""


def chave_llm():
    chave = os.environ.get("LLM_API_KEY")
    if chave:
        return chave
    try:
        return st.secrets.get("LLM_API_KEY")
    except Exception:
        return None


LLM_CHAVE = chave_llm()


def chamar_llm(titulo, formato_json=True):
    corpo = {
        "model": LLM_MODELO,
        "temperature": 0,
        "messages": [{"role": "system", "content": INSTRUCOES}, {"role": "user", "content": titulo}],
    }
    if formato_json:
        corpo["response_format"] = {"type": "json_object"}
    return requests.post(
        f"{LLM_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_CHAVE}"},
        json=corpo,
        timeout=LLM_TEMPO_MAXIMO,
    )


def extrair_por_llm(titulo):
    resposta = chamar_llm(titulo)
    if resposta.status_code == 400:
        resposta = chamar_llm(titulo, formato_json=False)
    resposta.raise_for_status()
    texto = resposta.json()["choices"][0]["message"]["content"]
    bruto = json.loads(re.search(r"\{.*\}", texto, re.S)[0])
    modelo = bruto.get("modelo") if bruto.get("modelo") in MODELOS else None
    armazenamento = bruto.get("armazenamento_gb") if bruto.get("armazenamento_gb") in ARMAZENAMENTOS else None
    condicao = bruto.get("condicao") if bruto.get("condicao") in CONDICOES else "novo"
    return {"marca": MODELOS.get(modelo), "modelo": modelo, "armazenamento_gb": armazenamento, "condicao": condicao}


def extrair(titulo):
    if not LLM_CHAVE:
        return extrair_por_regras(titulo), "regras (sem chave de IA configurada)"
    try:
        return extrair_por_llm(titulo), "LLM"
    except requests.HTTPError as erro:
        motivo = f"erro HTTP {erro.response.status_code}"
    except requests.RequestException:
        motivo = "sem resposta"
    except Exception:
        motivo = "resposta inválida"
    return extrair_por_regras(titulo), f"regras (serviço de IA indisponível: {motivo})"


# Base de ofertas em SQLite, carregada do CSV.
@st.cache_resource
def carregar_base():
    dados = pd.read_csv(ARQUIVO, dtype={"armazenamento_gb": "Int64"})
    ofertas = dados[dados["uso"].eq("base")].drop(columns="uso")
    titulos_teste = dados[dados["uso"].eq("teste")].reset_index(drop=True)
    with sqlite3.connect(BANCO) as conexao:
        ofertas.to_sql("ofertas", conexao, if_exists="replace", index=False)
    return ofertas, titulos_teste


def consultar(marca, modelo, armazenamento_gb, condicao):
    with sqlite3.connect(BANCO) as conexao:
        return pd.read_sql_query(
            "SELECT titulo, preco, loja, data_coleta FROM ofertas "
            "WHERE marca = ? AND modelo = ? AND armazenamento_gb = ? AND condicao = ? ORDER BY preco",
            conexao,
            params=(marca, modelo, int(armazenamento_gb), condicao),
        )


def reais(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tabela_de_ofertas(linhas):
    return pd.DataFrame(
        {
            "Título": linhas["titulo"],
            "Preço": linhas["preco"].map(reais),
            "Loja": linhas["loja"],
            "Data da coleta": pd.to_datetime(linhas["data_coleta"]).dt.strftime("%d/%m/%Y"),
        },
        columns=COLUNAS,
    )


def mostrar_resultado(linhas):
    quantidade = len(linhas)
    if quantidade < MINIMO_OFERTAS:
        st.warning(
            f"Poucas ofertas equivalentes: encontrei {quantidade}. "
            f"A faixa de preço só é exibida com pelo menos {MINIMO_OFERTAS} ofertas."
        )
    else:
        st.subheader("Faixa de preço de referência")
        menor, mediana, maior = st.columns(3)
        menor.metric("Menor preço", reais(linhas["preco"].min()))
        mediana.metric("Mediana", reais(statistics.median(linhas["preco"])))
        maior.metric("Maior preço", reais(linhas["preco"].max()))
        st.caption(f"Baseada em {quantidade} ofertas equivalentes. É uma referência para comparação, não um preço recomendado.")
    if quantidade:
        st.subheader("Ofertas equivalentes")
        st.table(tabela_de_ofertas(linhas), hide_index=True)


# Validação: acerto significa marca, modelo, armazenamento e condição todos corretos.
def rotulo(linha):
    vazio = lambda valor: None if pd.isna(valor) else valor
    return {
        "marca": vazio(linha["marca"]),
        "modelo": vazio(linha["modelo"]),
        "armazenamento_gb": None if pd.isna(linha["armazenamento_gb"]) else int(linha["armazenamento_gb"]),
        "condicao": linha["condicao"],
    }


def avaliar(titulos_teste, extrator, pausa=0, barra=None):
    acertos = falhas = 0
    tempos = []
    total = len(titulos_teste)
    for posicao, (_, linha) in enumerate(titulos_teste.iterrows(), start=1):
        inicio = time.perf_counter()
        try:
            acertos += extrator(linha["titulo"]) == rotulo(linha)
        except Exception:
            falhas += 1
        tempos.append(time.perf_counter() - inicio)
        if barra:
            barra.progress(posicao / total, text=f"{posicao} de {total} títulos")
            time.sleep(pausa)
    return acertos, falhas, tempos


def acao_extrair():
    titulo = st.session_state.titulo.strip()
    if not titulo:
        st.session_state.update(marca=None, modelo=None, armazenamento=None, condicao="novo", origem="Informe o título do produto.")
        return
    atributos, origem = extrair(titulo)
    st.session_state.update(
        marca=atributos["marca"],
        modelo=atributos["modelo"],
        armazenamento=atributos["armazenamento_gb"],
        condicao=atributos["condicao"],
        origem=f"Atributos preenchidos por **{origem}**. Confira e corrija antes de consultar.",
    )


# Interface
st.set_page_config(page_title="Faixa Certa")
st.title("Faixa Certa")
st.write("Faixa de preço de smartphones a partir de ofertas reais equivalentes.")

if not ARQUIVO.exists():
    st.error(f"Arquivo {ARQUIVO.name} não encontrado. Coloque-o na mesma pasta do app.py.")
    st.stop()

ofertas, titulos_teste = carregar_base()
data_coleta = pd.to_datetime(ofertas["data_coleta"].max()).strftime("%d/%m/%Y")
st.caption(
    f"Base: {len(ofertas)} ofertas de {ofertas['modelo'].nunique()} modelos, coletadas em {data_coleta}. "
    f"Extrator principal: {'LLM' if LLM_CHAVE else 'regras (sem chave de IA configurada)'}."
)

for nome, inicial in {"marca": None, "modelo": None, "armazenamento": None, "condicao": "novo", "origem": ""}.items():
    st.session_state.setdefault(nome, inicial)

st.text_input("Título do produto", placeholder="Ex.: Galaxy A17 4G 128GB preto", key="titulo")
st.button("Extrair atributos", type="primary", on_click=acao_extrair)
if st.session_state.origem:
    st.write(st.session_state.origem)

coluna_marca, coluna_modelo, coluna_armazenamento = st.columns(3)
coluna_marca.selectbox("Marca", sorted(set(MODELOS.values())), placeholder="Selecione", key="marca")
coluna_modelo.selectbox("Modelo", sorted(MODELOS), placeholder="Selecione", key="modelo")
coluna_armazenamento.selectbox("Armazenamento (GB)", ARMAZENAMENTOS, placeholder="Selecione", key="armazenamento")
st.radio("Condição", CONDICOES, horizontal=True, key="condicao")

if st.button("Ver faixa de preço", type="primary"):
    atributos = [st.session_state.marca, st.session_state.modelo, st.session_state.armazenamento, st.session_state.condicao]
    if all(atributos):
        mostrar_resultado(consultar(*atributos))
    else:
        st.warning("Preencha marca, modelo, armazenamento e condição.")

with st.expander("Validação da extração"):
    st.write(
        "Os 50 títulos de teste foram lidos depois que as regras foram definidas e não foram usados para ajustá-las. "
        "Um título conta como acerto quando marca, modelo, armazenamento e condição estão todos corretos."
    )
    total = len(titulos_teste)
    acertos_regras, _, _ = avaliar(titulos_teste, extrair_por_regras)
    st.write(f"**Regras:** {acertos_regras} de {total} títulos corretos ({acertos_regras / total:.0%}).")
    if LLM_CHAVE and st.button("Medir o LLM nos 50 títulos (cerca de 4 minutos)"):
        barra = st.progress(0.0, text="Medindo o LLM")
        acertos, falhas, tempos = avaliar(titulos_teste, extrair_por_llm, pausa=4.5, barra=barra)
        barra.empty()
        st.session_state.medicao_llm = (
            f"**LLM:** {acertos} de {total} títulos corretos ({acertos / total:.0%}); {falhas} chamadas com falha. "
            f"Diferença para as regras: {(acertos - acertos_regras) / total * 100:.0f} pontos percentuais. "
            f"Tempo por título: 90% em até {statistics.quantiles(tempos, n=10)[-1]:.2f} s; máximo de {max(tempos):.2f} s."
        )
    if "medicao_llm" in st.session_state:
        st.write(st.session_state.medicao_llm)
