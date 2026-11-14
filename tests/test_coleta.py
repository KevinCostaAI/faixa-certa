import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
import requests

import app


def memoria():
    return {"paginas": {}, "robots": {}, "classificacoes": {}, "trava": threading.Lock()}


def pagina_magalu(produtos):
    dados = {"props": {"pageProps": {"data": {"search": {"items": produtos}}}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(dados) + "</script>"


def produto_magalu(**mudancas):
    produto = {
        "available": True, "title": "Smartphone Samsung Galaxy A17 4G 128GB",
        "path": "/galaxy-a17/p/123/te/ga17/", "type": "product",
        "offers": [{"currency": "BRL", "price": 1200,
                    "bestPrice": {"totalAmount": 1080, "paymentMethodId": "pix",
                                  "paymentMethodDescription": "no Pix"},
                    "seller": {"id": "loja1"}}],
    }
    produto.update(mudancas)
    return produto


def test_magalu_le_preco_pix_confirmado_sem_confundir_com_total_parcelado():
    produto = produto_magalu()
    ofertas = app.ler_magalu(pagina_magalu([produto]), app.MAGALU + "/busca/galaxy/")
    assert len(ofertas) == 1
    assert ofertas[0]["preco"] == 1080
    assert ofertas[0]["pagamento"] == "Pix"
    assert ofertas[0]["fonte"] == "Magazine Luiza"


@pytest.mark.parametrize("descricao,identificador", [
    ("no cartão Magalu", "magalu"), ("no Pix com cupom", "pix"),
    ("no Pix para assinante", "pix"), ("no Pix pelo aplicativo", "pix"),
    ("", "pix"), ("no Pix", "desconhecido"),
])
def test_magalu_nao_promove_preco_restrito_ou_sem_confirmacao(descricao, identificador):
    produto = produto_magalu()
    produto["offers"][0]["bestPrice"].update(paymentMethodDescription=descricao, paymentMethodId=identificador)
    oferta = app.ler_magalu(pagina_magalu([produto]), app.MAGALU + "/busca/galaxy/")[0]
    assert oferta["pagamento"] == "não informada"
    assert oferta["preco"] == 1200


def test_magalu_ignora_indisponiveis_e_preserva_o_titulo_do_kit():
    produtos = [produto_magalu(available=False),
                produto_magalu(type="bundle", reference="Preto + Fone de Ouvido Buds Core")]
    ofertas = app.ler_magalu(pagina_magalu(produtos), app.MAGALU + "/busca/galaxy/")
    assert len(ofertas) == 1
    assert "Fone de Ouvido Buds Core" in ofertas[0]["titulo"]


def test_coleta_devolve_fontes_rapidas_sem_esperar_pela_fonte_lenta(monkeypatch):
    fontes = {nome: (lambda busca: "https://exemplo.test/" + busca, None) for nome in ("rápida", "lenta")}
    monkeypatch.setattr(app, "FONTES", fontes)

    def coletar(nome, busca, mem, prazo, usar_cache):
        if nome == "lenta":
            time.sleep(0.3)
        return {"fonte": nome, "status": "1 oferta", "ofertas": [{"titulo": nome}]}

    monkeypatch.setattr(app, "coletar", coletar)
    inicio = time.monotonic()
    resultados = app.coletar_todas("teste", memoria(), tempo_limite=0.03)
    assert time.monotonic() - inicio < 0.2
    assert resultados[0]["ofertas"] == [{"titulo": "rápida"}]
    assert resultados[1]["status"] == "tempo limite da coleta"
    assert resultados[1]["ofertas"] == []


def test_erro_de_uma_fonte_nao_elimina_as_demais(monkeypatch):
    monkeypatch.setattr(app, "FONTES", {n: (lambda busca: "https://exemplo.test", None) for n in ("ok", "erro")})

    def coletar(nome, *args):
        if nome == "erro":
            raise ValueError("formato inesperado")
        return {"fonte": nome, "status": "1 oferta", "ofertas": [{"titulo": "válida"}]}

    monkeypatch.setattr(app, "coletar", coletar)
    resultados = app.coletar_todas("teste", memoria())
    assert resultados[0]["ofertas"]
    assert resultados[1]["status"] == "falha na coleta"


def test_robots_simultaneos_fazem_um_unico_pedido(monkeypatch):
    chamadas = []

    def baixar(url, prazo, sessao=None):
        chamadas.append(url)
        time.sleep(0.02)
        resposta = requests.Response()
        resposta.status_code = 200
        return resposta, b"User-agent: *\nAllow: /\nDisallow: /privado"

    monkeypatch.setattr(app, "baixar_conteudo", baixar)
    mem = memoria()
    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(lambda _: app.robots_permite("https://exemplo.test/busca", mem), range(2)))
    assert resultados == [True, True]
    assert chamadas == ["https://exemplo.test/robots.txt"]
    assert not app.robots_permite("https://exemplo.test/privado", mem)


def test_corpo_que_continua_chegando_tambem_respeita_prazo(monkeypatch):
    class Resposta:
        fechada = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.fechada = True

        def iter_content(self, chunk_size):
            for _ in range(10):
                time.sleep(0.01)
                yield b"um pedaco"

    resposta = Resposta()
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: resposta)
    with pytest.raises(requests.Timeout):
        app.baixar_conteudo("https://exemplo.test", time.monotonic() + 0.015)
    assert resposta.fechada


def test_coleta_nova_nao_e_confundida_com_cache(monkeypatch):
    mem = memoria()
    nome = "Gazin"
    url = app.FONTES[nome][0]("iphone 16 128gb")
    mem["paginas"][url] = {"fonte": nome, "momento": time.time(), "ofertas": [], "status": "cache antigo"}
    monkeypatch.setattr(app, "baixar", lambda *args, **kwargs: ([], None))
    assert app.coletar(nome, "iphone 16 128gb", mem)["cache"] is True
    nova = app.coletar(nome, "iphone 16 128gb", mem, usar_cache=False)
    assert nova["cache"] is False
    assert nova["status"] != "cache antigo"


def test_coleta_nao_altera_o_resultado_da_extracao_registrada():
    caminho = Path(app.__file__).with_name("avaliacao_50_titulos.csv")
    tabela = pd.read_csv(caminho, dtype=str, keep_default_na=False)
    acertos = [app.conferir_extracao(linha, app.extracao_das_regras(linha["titulo"]))["titulo"]
               for linha in tabela.to_dict("records")]
    assert sum(acertos) / len(acertos) >= 0.9
