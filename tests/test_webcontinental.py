import json

import pytest

import app


def produto():
    return {"productName": "Smartphone Xiaomi POCO C85 128GB", "link": app.WEBCONTINENTAL + "/poco-c85/p",
            "Conectividade": ["Wi-Fi, Bluetooth, redes móveis 4G, NFC"],
            "items": [{"name": "Smartphone Xiaomi POCO C85 128GB Preto", "sellers": [
                {"sellerDefault": True, "sellerName": "Loja", "commertialOffer": {
                    "IsAvailable": True, "AvailableQuantity": 3, "Price": 1563.99,
                    "Installments": [
                        {"PaymentSystemName": "Visa", "Name": "Visa à vista", "NumberOfInstallments": 1,
                         "InterestRate": 0, "TotalValuePlusInterestRate": 1563.99},
                        {"PaymentSystemName": "Pix", "Name": "Pix à vista", "NumberOfInstallments": 1,
                         "InterestRate": 0, "TotalValuePlusInterestRate": 1495.99},
                    ]}}]}]}


def test_pix_vem_da_condicao_de_pagamento_e_nao_do_preco_generico():
    p = produto()
    oferta = app.ler_webcontinental(json.dumps([p]), app.WEBCONTINENTAL)[0]
    assert oferta["preco"] == 1495.99
    assert oferta["pagamento"] == "Pix"
    assert oferta["rede_confirmada"] == "4g"
    assert oferta["titulo"] == p["items"][0]["name"]


@pytest.mark.parametrize("mudanca", [{"NumberOfInstallments": 2}, {"InterestRate": 3},
                                    {"Name": "Pix mensal"}, {"Name": "Pix à vista com cupom"}])
def test_pix_parcelado_com_juros_ou_condicionado_nao_e_confirmado(mudanca):
    p = produto()
    p["items"][0]["sellers"][0]["commertialOffer"]["Installments"][1].update(mudanca)
    oferta = app.ler_webcontinental(json.dumps([p]), app.WEBCONTINENTAL)[0]
    assert oferta["pagamento"] == "não informada"


@pytest.mark.parametrize("quantidade", [0, -1, None])
def test_produto_sem_estoque_nao_entra(quantidade):
    p = produto()
    p["items"][0]["sellers"][0]["commertialOffer"]["AvailableQuantity"] = quantidade
    assert app.ler_webcontinental(json.dumps([p]), app.WEBCONTINENTAL) == []


def test_wifi_5ghz_nao_confirma_rede_movel():
    assert app.rede_dos_atributos({"Conectividade": ["Wi-Fi 2.4GHz e 5GHz, Bluetooth"]}) == {}

