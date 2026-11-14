"""Estruturas das páginas públicas de 14/11/2026; não representam resultados de validação com pessoas."""
import json
import threading
import time

import pytest

import app


def produto_fastshop():
    return {"productName": "Smartphone Samsung Galaxy A36 5G 128GB Preto", "link": app.FASTSHOP + "/galaxy-a36/p",
            "items": [{"name": "Smartphone Samsung Galaxy A36 5G 128GB Preto", "sellers": [
                {"sellerDefault": True, "sellerName": "Casas Bahia", "commertialOffer": {
                    "AvailableQuantity": 10, "IsAvailable": True, "Price": 2200,
                    "Installments": [{"PaymentSystemName": "Pix", "Name": "Pix à vista", "NumberOfInstallments": 1,
                                      "InterestRate": 0, "TotalValuePlusInterestRate": 2082.57}]}}]}]}


def test_fastshop_usa_total_no_pix_e_identifica_o_vendedor():
    oferta = app.ler_fastshop(json.dumps([produto_fastshop()]), app.FASTSHOP)[0]
    assert oferta["preco"] == 2082.57 and oferta["pagamento"] == "Pix"
    assert oferta["loja"] == "Fast Shop · Casas Bahia"
    assert oferta["link"] == app.FASTSHOP + "/galaxy-a36/p"


@pytest.mark.parametrize("link", ["https://outro.test/produto/p", "javascript://site.fastshop.com.br/produto/p"])
def test_catalogo_nao_aceita_link_de_outro_dominio_ou_esquema(link):
    produto = produto_fastshop()
    produto["link"] = link
    assert app.ler_fastshop(json.dumps([produto]), app.FASTSHOP) == []


def pagina_fonemix(estoque="Pronta entrega", disponibilidade="InStock", condicao="NewCondition", preco_escolhido="883,90"):
    produto = {"@type": "Product", "name": "Motorola Moto E15", "offers": {
        "availability": "https://schema.org/" + disponibilidade, "itemCondition": "https://schema.org/" + condicao,
        "priceCurrency": "BRL", "price": "883.90"}}
    return ('<h1 id="pp-title" aria-label="Motorola Moto E15">Motorola Moto E15.</h1>'
            '<div class="rdc-hero-pricecard__pix-row"><span class="rdc-hero-pricecard__pix-label">No Pix</span>'
            '<span class="rdc-hero-pricecard__pix"><small>R$</small>883,90</span></div>'
            '<button class="rc-qv-row is-selected" aria-pressed="true"><span class="rc-qv-row__label">64GB 2GB · Azul'
            f'<span class="variant-dispatch-badge">{estoque}</span></span>'
            f'<span class="rc-qv-row__price">R$ {preco_escolhido}</span></button>'
            '<script type="application/ld+json">' + json.dumps(produto) + '</script>')


def test_fonemix_confirma_preco_e_armazenamento_da_variante_selecionada():
    oferta = app.ler_produto_fonemix(pagina_fonemix(), app.FONEMIX + "/shop/motorola-moto-e15")[0]
    assert oferta["titulo"] == "Motorola Moto E15 · 64GB 2GB · Azul"
    assert oferta["titulo_pagina"] == "Motorola Moto E15"
    assert oferta["preco"] == 883.90 and oferta["pagamento"] == "Pix"
    assert app.extracao_das_regras(oferta["titulo"])["armazenamento"] == 64


@pytest.mark.parametrize("mudanca", [{"estoque": "Sob encomenda"}, {"disponibilidade": "OutOfStock"},
                                    {"condicao": "UsedCondition"}, {"preco_escolhido": "999,90"}])
def test_fonemix_nao_junta_dados_de_variantes_ou_estoques_incompativeis(mudanca):
    assert app.ler_produto_fonemix(pagina_fonemix(**mudanca), app.FONEMIX + "/shop/motorola-moto-e15") == []


def pagina_eletroinfo(disponivel=True, assinatura=False):
    dados = {"selected_variant_id": 1, "product": {"title": "iPhone 16 128GB", "available": True,
        "variants": [{"id": 1, "name": "iPhone 16 128GB - Verde", "available": disponivel,
                      "requires_selling_plan": assinatura, "price": 612000},
                     {"id": 2, "available": True, "price": 499000}]}}
    return ('<h1>iPhone 16 128GB</h1><p>Até 10% OFF no PIX com cupom. Em até 12x de R$ 510,00</p>'
            '<script type="application/json" data-product-json>' + json.dumps(dados) + '</script>')


def test_eletroinfo_nao_calcula_pix_com_cupom_nem_usa_parcela_como_total():
    oferta = app.ler_produto_eletroinfo(pagina_eletroinfo(), app.ELETROINFO + "/products/iphone-16-128gb")[0]
    assert oferta["preco"] == 6120
    assert oferta["pagamento"] == "não informada"
    assert oferta["titulo"] == "iPhone 16 128GB - Verde"


@pytest.mark.parametrize("mudanca", [{"disponivel": False}, {"assinatura": True}])
def test_eletroinfo_exige_estoque_da_variante_aberta_e_compra_sem_assinatura(mudanca):
    assert app.ler_produto_eletroinfo(pagina_eletroinfo(**mudanca), app.ELETROINFO + "/products/iphone-16-128gb") == []


def test_links_de_busca_sao_deduplicados_e_ignorados_se_nao_citam_o_modelo():
    pagina = ('<a data-waoti-item-name="Motorola Moto E15" href="/shop/motorola-moto-e15">Moto E15</a>'
              '<a data-waoti-item-name="Motorola Moto E15" href="/shop/motorola-moto-e15">Foto</a>')
    assert app.ler_busca_fonemix(pagina, app.FONEMIX) == [
        {"titulo": "Motorola Moto E15", "link": app.FONEMIX + "/shop/motorola-moto-e15"}]
    assert app.busca_pelo_modelo("moto e15 64gb") == "moto e15"


def test_coleta_html_nao_exibe_sugestoes_sem_buscar_a_pagina_do_produto(monkeypatch):
    chamadas = []
    url_busca = app.FONTES["FoneMix"][0]("moto e15 64gb")
    produto = app.FONEMIX + "/shop/motorola-moto-e15"

    def baixar(url, leitor, *args):
        chamadas.append(url)
        if url == url_busca:
            return [{"titulo": "iPhone 18 Pro", "link": app.FONEMIX + "/shop/iphone-18"},
                    {"titulo": "Motorola Moto E15", "link": produto}], None
        return leitor(pagina_fonemix(), url), None

    monkeypatch.setattr(app, "baixar", baixar)
    mem = {"paginas": {}, "robots": {}, "classificacoes": {}, "trava": threading.Lock()}
    resultado = app.coletar("FoneMix", "moto e15 64gb", mem, prazo=time.monotonic() + 10)
    assert chamadas == [url_busca, produto]
    assert len(resultado["ofertas"]) == 1
    assert resultado["ofertas"][0]["preco"] == 883.90
    assert app.coletar("FoneMix", "moto e15 64gb", mem)["cache"]
    assert len(chamadas) == 2
