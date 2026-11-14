import threading
import time

import pytest

import app


@pytest.mark.parametrize("campo,valor,esperado", [
    ("Rede Móvel", "4G", "4g"),
    ("Conexões", "4G - 3G - 2G", "4g"),
    ("Rede Móvel", "5G / 4G / 3G", "5g"),
    ("Conectividade", "Wi-Fi 2.4GHz | 5GHz, Bluetooth 5.4", None),
    ("Conectividade", "Wi-Fi 5G", None),
    ("Rede Móvel", "não informado", None),
    ("Rede Móvel", "5G: não", None),
])
def test_rede_da_ficha_distingue_rede_movel_de_wifi(campo, valor, esperado):
    pagina = f"<h1>Smartphone Xiaomi POCO C85 128GB</h1><table><tr><th>{campo}</th><td>{valor}</td></tr></table>"
    ficha = app.rede_da_ficha(pagina, "https://exemplo.test/produto")
    assert ficha.get("rede_confirmada") == esperado


def test_rede_da_kabum_vem_do_campo_do_produto_e_nao_da_recomendacao():
    pagina = '''<h1>Smartphone Xiaomi POCO C85 128GB</h1>
        <div id="description"><p>Conexões: 4G/3G/2G</p><p>Wi-Fi: 2.4GHz e 5GHz</p></div>
        <aside>Conheça também o iPhone 16 5G</aside>'''
    ficha = app.rede_da_ficha(pagina, "https://exemplo.test/produto")
    assert ficha["rede_confirmada"] == "4g"
    assert "conexoes" in ficha["evidencia_rede"]


def test_ficha_contraditoria_fica_inconclusiva():
    pagina = '''<h1>Smartphone Xiaomi POCO C85 128GB</h1>
        <table><tr><th>Rede Móvel</th><td>4G</td></tr><tr><th>Conexões</th><td>5G</td></tr></table>'''
    assert app.rede_da_ficha(pagina, "https://exemplo.test/produto") == {}


def test_campos_com_strong_e_quebra_de_linha_tambem_sao_lidos():
    pagina = '''<h1>Redmi Note 15 256GB</h1><div id="description">
        <strong>Conexões:</strong> 4G / 3G / 2G<br>
        <strong>2G GSM:</strong> B2 / B3 / B5<br>
        <strong>5G NR:</strong> N/a<br>
        <strong>Wi-Fi:</strong> 2.4GHz / 5GHz</div>'''
    assert app.rede_da_ficha(pagina, "https://exemplo.test/produto")["rede_confirmada"] == "4g"


def test_rede_confirmada_na_pagina_nao_altera_extracao_do_titulo():
    busca, titulo = "poco c85 128gb 4g", "Smartphone Xiaomi POCO C85 128GB Preto"
    alvo, itens = app.classificar_por_regras(busca, [titulo])
    assert app.extracao_das_regras(titulo)["rede"] is None
    assert app.motivos_da_busca(busca, alvo, itens, [titulo])[2][0] == "versão (4G) não informada no anúncio"
    assert app.motivos_da_busca(busca, alvo, itens, [titulo], ["4g"])[2] == [None]
    assert app.motivos_da_busca(busca, alvo, itens, [titulo], ["5g"])[2] == ["outra versão (5G)"]


def test_rede_de_pagina_de_outro_modelo_nao_e_aproveitada(monkeypatch):
    oferta = {"titulo": "Smartphone Xiaomi POCO C85 128GB Preto", "preco": 1000,
              "fonte": "KaBuM!", "loja": "KaBuM!", "pagamento": "Pix", "link": "https://exemplo.test/produto"}
    monkeypatch.setattr(app, "baixar", lambda *args, **kwargs: (
        {"rede_confirmada": "4g", "titulo_pagina": "Smartphone Xiaomi Redmi 15 128GB"}, None))
    mem = {"paginas": {}, "robots": {}, "classificacoes": {}, "trava": threading.Lock()}
    resultado = app.confirmar_redes("poco c85 128gb", [oferta], mem, time.monotonic() + 5, None)
    assert "rede_confirmada" not in resultado[0]


def test_avaliacao_das_decisoes_continua_recebendo_apenas_titulos():
    import pandas as pd
    from pathlib import Path
    tabela = pd.read_csv(Path(app.__file__).with_name("avaliacao_50_titulos.csv"), dtype=str, keep_default_na=False)
    resultados = []
    for busca, grupo in tabela.groupby("busca", sort=False):
        titulos = grupo["titulo"].tolist()
        alvo, itens = app.classificar_por_regras(app.limpar(busca), titulos)
        motivos = app.decidir_grupo(app.limpar(busca), titulos, alvo, itens)
        resultados.extend(app.resultado_da_decisao(motivo, linha) for motivo, linha in zip(motivos, grupo.to_dict("records")))
    assert resultados.count("acerto") == 44

