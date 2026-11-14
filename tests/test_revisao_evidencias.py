import json

import pytest

import app
from revisar_evidencias import conferir_preco, ler_pagina, normalizar_preco_exibido


@pytest.mark.parametrize("texto", ["R$ 2.082,57", "R$ 2,082,57", "R$ 2,082.57", "R$\u00a02.082,57"])
def test_le_valor_capturado_sem_perder_centavos(texto):
    assert normalizar_preco_exibido(texto) == 2082.57


@pytest.mark.parametrize("texto", ["10x de R$ 208,25", "R$ 200,00 ou R$ 190,00", "2082"])
def test_texto_com_parcela_ou_multiplos_precos_nao_vira_valor_unico(texto):
    assert normalizar_preco_exibido(texto) is None


def test_confirmacao_vem_do_preco_proximo_ao_pix_e_nao_do_preco_riscado():
    dados = {"trechos_pagamento": ["R$ 1.903,90 10% de desconto R$ 1.713,51 à vista no Pix"],
             "produtos_jsonld": []}
    assert conferir_preco({"preco": "R$ 1.713,51", "pagamento": "Pix"}, dados)["status"].startswith("valor à vista/Pix compatível")
    assert not conferir_preco({"preco": "R$ 1.903,90", "pagamento": "Pix"}, dados)["status"].startswith("valor à vista/Pix compatível")


def test_rotulo_no_pix_colado_ao_preco_e_lido_sem_usar_parcela():
    dados = {"trechos_pagamento": ["No PixR$883,90No cartão64GB 2GB"]}
    assert conferir_preco({"preco": "R$ 883,90", "pagamento": "Pix"}, dados)["status"].startswith("valor à vista/Pix compatível")


def test_cupom_nao_confirma_preco_da_faixa():
    dados = {"trechos_pagamento": ["R$ 900,00 no Pix com cupom"]}
    assert not conferir_preco({"preco": "R$ 900,00", "pagamento": "Pix"}, dados)["status"].startswith("valor à vista/Pix compatível")


def test_estado_vtex_em_template_com_script_confirma_total_e_modalidade():
    estado = {"Product:celular": {"__typename": "Product", "productName": "Celular"},
              "$Product:celular.items.0.sellers.0.commertialOffer.Installments.1": {
                  "__typename": "Installment", "PaymentSystemName": "Pix", "Name": "Pix à vista",
                  "NumberOfInstallments": 1, "InterestRate": 0, "TotalValuePlusInterestRate": 1044.05}}
    pagina = '<h1>Celular</h1><template data-varname="__STATE__"><script>' + json.dumps(estado) + '</script></template>'
    dados = ler_pagina(pagina, "https://exemplo.test/celular/p")
    assert conferir_preco({"preco": "R$ 1.044,05", "pagamento": "Pix"}, dados)["status"].startswith("valor à vista/Pix compatível")


def test_gazin_nao_declara_pix_sem_modalidade_na_lista_de_busca():
    dados = {"props": {"pageProps": {"resultadosBusca": {"products": [
        {"name": "Samsung Galaxy A17 4G 128GB", "price": 929.9, "status": "AVAILABLE", "url": "/produto/galaxy-a17"}]}}}}
    pagina = '<script id="__NEXT_DATA__">' + json.dumps(dados) + '</script>'
    oferta = app.ler_gazin(pagina, app.GAZIN)[0]
    assert oferta["preco"] == 929.9
    assert oferta["pagamento"] == "não informada"
