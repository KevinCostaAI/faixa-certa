import app


def pagina(estado="Sou como novo", pagamento="à vista no Pix"):
    return f'''<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1"></head><body>
        <div class="product-card" data-id="1">
          <a class="product-link-data" href="{app.TROCAFY}/iphone-13-p1">
          <div class="product-card-title">Apple - iPhone 13 128GB Azul - {estado}</div>
          <div class="price-vista">R$ 1.999,90 <span>{pagamento}</span></div></a>
        </div></body></html>'''.encode("iso-8859-1")


def test_estado_de_usado_e_pix_sao_lidos_sem_modificar_o_titulo():
    oferta = app.ler_trocafy(pagina(), app.TROCAFY)[0]
    assert oferta["titulo"] == "Apple - iPhone 13 128GB Azul - Sou como novo"
    assert oferta["condicao_confirmada"] == "usado"
    assert oferta["preco"] == 1999.90
    assert oferta["pagamento"] == "Pix"


def test_condicao_da_loja_e_usada_apenas_na_busca_com_dados_complementares():
    oferta = app.ler_trocafy(pagina(), app.TROCAFY)[0]
    busca = "iphone 13 128gb usado"
    alvo, itens = app.classificar_por_regras(busca, [oferta["titulo"]])
    assert app.extracao_das_regras(oferta["titulo"])["condicao"] == "novo"
    assert app.motivos_da_busca(busca, alvo, itens, [oferta["titulo"]])[2] == ["produto novo"]
    assert app.motivos_da_busca(busca, alvo, itens, [oferta["titulo"]], condicoes_confirmadas=["usado"])[2] == [None]


def test_cupom_nao_e_convertido_em_pagamento_confirmado():
    oferta = app.ler_trocafy(pagina(pagamento="à vista no Pix com cupom"), app.TROCAFY)[0]
    assert oferta["pagamento"] == "não informada"


def test_rotas_vem_das_categorias_reais_e_ignoram_dominios_externos():
    conteudo = f'''<a href="/smartphone/iphone/iphone-13/">iPhone 13</a>
        <a href="https://outro.test/smartphone/iphone/iphone-13/">iPhone 13</a>'''
    assert app.ler_rotas_trocafy(conteudo, app.TROCAFY) == [
        {"modelo": "iPhone 13", "url": app.TROCAFY + "/smartphone/iphone/iphone-13/"}]


def test_fonte_de_usados_nao_e_consultada_para_busca_de_novos():
    resultado = app.coletar_trocafy("iphone 13 128gb", {}, prazo=0, usar_cache=False)
    assert resultado["ofertas"] == []
    assert "não se aplica" in resultado["status"]
