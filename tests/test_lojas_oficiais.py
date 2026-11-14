import json
import time

import app


def parcela(sistema, nome, total, parcelas=1, juros=0):
    return {"PaymentSystemName": sistema, "Name": nome, "NumberOfInstallments": parcelas,
            "InterestRate": juros, "TotalValuePlusInterestRate": total}


def sku(nome, vendedor, quantidade, preco, parcelas):
    return {"name": nome, "sellers": [{"sellerDefault": True, "sellerName": vendedor, "commertialOffer": {
        "IsAvailable": quantidade > 0, "AvailableQuantity": quantidade, "Price": preco, "Installments": parcelas}}]}


def moto_g35():
    """Mesma estrutura do catálogo público da Motorola em 14/11/2026: o primeiro SKU estava esgotado."""
    detalhe = "4GB RAM + 8GB RAM Boost, Camera 50MP com Sony LYTIA 600"
    return {"productName": "Smartphone Motorola Moto g35 5G 256GB", "linkText": "smartphone-moto-g35-5g-256gb",
            "link": app.MOTOROLA + "/smartphone-moto-g35-5g-256gb/p", "Conectividade": ["USB-C"],
            "items": [sku(detalhe, "Motorola", 0, 1332.22, []),
                      sku(detalhe, "Motorola", 99999, 1332.22,
                          [parcela("Visa", "Visa à vista", 1332.22), parcela("Pix", "Pix à vista", 1199)])]}


def galaxy_a07(quantidade=99999):
    """Mesma estrutura do catálogo público da Samsung em 14/11/2026: o link vem em outro domínio."""
    return {"productName": "Celular Samsung Galaxy A07 128GB, 4GB, Câmera 50MP, Tela 6.7", "linkText": "galaxy-a07",
            "link": "https://shop.samsung.com.br/galaxy-a07/p", "Rede": ["4G"],
            "items": [sku("Preto", "SAMSUNG ELETRÔNICA DA AMAZÔNIA LTDA.", quantidade, 1099,
                          [parcela("Visa", "Visa à vista", 1099), parcela("Pix", "Pix à vista", 1044.05)])]}


def test_motorola_usa_o_sku_disponivel_e_o_total_no_pix():
    oferta = app.ler_motorola(json.dumps([moto_g35()]), app.MOTOROLA)[0]
    assert oferta["preco"] == 1199
    assert oferta["pagamento"] == "Pix"
    assert oferta["fonte"] == "Motorola" and oferta["loja"] == "Motorola"
    assert oferta["link"] == "https://www.motorola.com.br/smartphone-moto-g35-5g-256gb/p"
    assert oferta["titulo"].startswith("Smartphone Motorola Moto g35 5G 256GB · ")
    assert "rede_confirmada" not in oferta  # "USB-C" não é rede móvel; a rede fica no título


def test_samsung_monta_o_link_da_loja_e_le_a_rede_do_catalogo():
    oferta = app.ler_samsung(json.dumps([galaxy_a07()]), app.SAMSUNG)[0]
    assert oferta["link"] == "https://shop.samsung.com/br/galaxy-a07/p"
    assert oferta["preco"] == 1044.05 and oferta["pagamento"] == "Pix"
    assert oferta["loja"] == "Samsung"
    assert oferta["rede_confirmada"] == "4g"


def test_produto_esgotado_na_loja_oficial_nao_entra():
    assert app.ler_samsung(json.dumps([galaxy_a07(quantidade=0)]), app.SAMSUNG) == []


def test_outro_vendedor_na_loja_oficial_fica_identificado():
    produto = galaxy_a07()
    produto["items"][0]["sellers"][0]["sellerName"] = "Parceiro X"
    assert app.ler_samsung(json.dumps([produto]), app.SAMSUNG)[0]["loja"] == "Samsung · Parceiro X"


def test_webcontinental_continua_sem_refazer_link_de_outro_dominio():
    produto = galaxy_a07()
    produto["link"] = "https://outro.test/galaxy-a07/p"
    assert app.ler_webcontinental(json.dumps([produto]), app.WEBCONTINENTAL) == []


def test_loja_oficial_so_e_consultada_para_aparelho_novo_da_marca(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("não deveria consultar a loja")
    monkeypatch.setattr(app, "baixar", proibido)
    mem = {"paginas": {}, "classificacoes": {}, "robots": {}, "trava": __import__("threading").Lock()}
    assert "outra marca" in app.coletar("Motorola", "iphone 16 128gb", mem)["status"]
    assert "outra marca" in app.coletar("Samsung", "moto g35 256gb", mem)["status"]
    assert "condição" in app.coletar("Samsung", "galaxy a14 128gb usado", mem)["status"]
    assert "condição" in app.coletar("Motorola", "moto g35 256gb recondicionado", mem)["status"]


def test_loja_oficial_e_consultada_para_a_propria_marca(monkeypatch):
    chamadas = []
    monkeypatch.setattr(app, "baixar", lambda url, ler, *args, **kwargs: (chamadas.append(url) or ([], None)))
    mem = {"paginas": {}, "classificacoes": {}, "robots": {}, "trava": __import__("threading").Lock()}
    resultado = app.coletar("Motorola", "moto g35 256gb", mem, prazo=time.monotonic() + 5)
    assert resultado["status"] == "nenhuma oferta encontrada"
    assert chamadas == [app.MOTOROLA + "/api/catalog_system/pub/products/search/?ft=moto%20g35%20256gb&_from=0&_to=29"]
    resultado = app.coletar("Samsung", "galaxy a36 5g 128gb", mem, prazo=time.monotonic() + 5)
    assert chamadas[-1].startswith("https://shop.samsung.com/br/api/catalog_system/pub/products/search/?ft=galaxy%20a36")
