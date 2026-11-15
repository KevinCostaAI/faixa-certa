from pathlib import Path

from streamlit.testing.v1 import AppTest

import app


def test_interface_principal_abre_com_a_funcao_main():
    at = AppTest.from_file(str(Path(app.__file__)), default_timeout=10).run()
    assert not at.exception
    assert at.title[0].value == "Faixa Certa"
    assert at.text_input[0].label == "Qual celular você procura?"


def test_busca_generica_com_erro_mostra_compra_do_preco_e_memoria_da_linha(monkeypatch):
    ofertas = []
    for codigo, titulo, preco, pagamento in [
        (1, "Apple iPhone 13 128GB Preto", 2999, "não informada"),
        (2, "Apple iPhone 13 128GB Azul", 2999, "Pix"),
        (3, "Apple iPhone 13 256GB Branco", 3999, "Pix"),
        (4, "Apple iPhone 16e 128GB Branco", 4899, "não informada"),
        (5, "Capa Apple iPhone 13 128GB", 20, "Pix"),
        (6, "Apple iPhone 13 128GB Usado", 1999, "Pix")]:
        url = f"https://www.kabum.com.br/produto/{codigo}/iphone"
        ofertas.append({"titulo": titulo, "preco": preco, "pagamento": pagamento,
                        "fonte": "KaBuM!", "loja": "Vendedor", "link": url, "pagina": url})
    monkeypatch.setattr(app, "coletar_todas", lambda *args, **kwargs: [
        {"fonte": "KaBuM!", "ofertas": ofertas, "status": "6 ofertas", "coletado": "12:00"}])
    at = AppTest.from_string("import app\napp.main()", default_timeout=10).run()
    at.text_input[0].set_value("ephone")
    at.button[0].click().run()
    assert not at.exception
    assert any("Você quis dizer" in aviso.value and "iPhone" in aviso.value for aviso in at.info)
    tabela = next(m.value for m in at.markdown if "| Celular | Memória |" in m.value).replace("\\$", "$")
    linha128 = next(l for l in tabela.splitlines() if "Apple iPhone 13 | 128 GB" in l)
    assert app.reais(2999) in linha128 and "| Pix |" in linha128
    assert "https://www.kabum.com.br/produto/2/iphone" in linha128
    linha256 = next(l for l in tabela.splitlines() if "Apple iPhone 13 | 256 GB" in l)
    assert app.reais(3999) in linha256 and "https://www.kabum.com.br/produto/3/iphone" in linha256
    assert "| não informada |" in tabela
    assert "/produto/5/" not in tabela and "/produto/6/" not in tabela
    assert any(b.label.startswith("Ver a faixa de preço de") for b in at.button)


def test_protocolo_abre_pela_rota_publica():
    at = AppTest.from_file(str(Path(app.__file__)), default_timeout=10)
    at.query_params["protocolo"] = "1"
    at.run()
    assert not at.exception
    assert at.title[0].value == "Faixa Certa: protocolo de validação"


def test_trocar_rede_atualiza_todos_os_precos_e_o_destaque(monkeypatch):
    ofertas = []
    for rede, base in (("4G", 1200), ("5G", 1400)):
        for k in range(3):
            link = f"https://www.kabum.com.br/produto/{base+k}/galaxy-a17"
            ofertas.append({"titulo": f"Samsung Galaxy A17 {rede} 128GB", "preco": base + k * 20,
                            "fonte": "KaBuM!", "loja": "KaBuM!", "pagamento": "Pix", "link": link, "pagina": link})
    ofertas.append({"titulo": "Samsung Galaxy A17 128GB", "preco": 1000, "fonte": "KaBuM!",
                    "loja": "KaBuM!", "pagamento": "Pix", "link": "https://www.kabum.com.br/produto/1",
                    "pagina": "https://www.kabum.com.br/produto/1"})
    monkeypatch.setattr(app, "coletar_todas", lambda *args, **kwargs: [
        {"fonte": "KaBuM!", "ofertas": ofertas, "status": "7 ofertas", "coletado": "12:00"}])
    at = AppTest.from_string("import app\napp.main()", default_timeout=10).run()
    at.text_input[0].set_value("galaxy a17 128gb")
    at.button[0].click().run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric} == {
        "Menor preço": app.reais(1200), "Mediana": app.reais(1220), "Maior preço": app.reais(1240)}
    destaque = next(m.value for m in at.markdown if "**Oferta mais barata:**" in m.value)
    assert "4G" in destaque
    at.radio[0].set_value("5g").run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric} == {
        "Menor preço": app.reais(1400), "Mediana": app.reais(1420), "Maior preço": app.reais(1440)}
    destaque = next(m.value for m in at.markdown if "**Oferta mais barata:**" in m.value)
    assert "5G" in destaque
    at.radio[0].set_value("4g").run()
    assert at.metric[0].value == app.reais(1200)


def test_modo_de_validacao_forca_coleta_nova(monkeypatch):
    chamadas = []

    def coletar(busca, mem, forcar_coleta=False):
        chamadas.append(forcar_coleta)
        return [{"fonte": "KaBuM!", "ofertas": [], "status": "nenhuma oferta", "cache": False}]

    monkeypatch.setattr(app, "coletar_todas", coletar)
    at = AppTest.from_string("import app\napp.main()", default_timeout=10)
    at.query_params["coleta_nova"] = "1"
    at.run()
    at.text_input[0].set_value("iphone 16 128gb")
    at.button[0].click().run()
    assert not at.exception
    assert chamadas == [True]
    assert any("Consulta concluída:" in caption.value and "Coleta nova." in caption.value for caption in at.caption)


def test_busca_sem_ofertas_5g_diferencia_acessorio_rede_4g_e_rede_desconhecida(monkeypatch):
    ofertas = [{"titulo": titulo, "preco": preco, "fonte": "KaBuM!", "loja": "Loja",
                "pagamento": "Pix", "link": f"https://www.kabum.com.br/produto/{n}",
                "pagina": f"https://www.kabum.com.br/produto/{n}"}
               for n, (titulo, preco) in enumerate([
                   ("Samsung Galaxy A07 4G 128GB Preto", 700),
                   ("Samsung Galaxy A07 4G 128GB Verde Oferta", 720),
                   ("Samsung Galaxy A07 4G 128GB Violeta Nacional", 740),
                   ("Samsung Galaxy A07 128GB", 680),
                   ("Película para Samsung Galaxy A07", 20)], start=1)]
    monkeypatch.setattr(app, "coletar_todas", lambda *args, **kwargs: [
        {"fonte": "KaBuM!", "ofertas": ofertas, "status": "5 ofertas", "coletado": "12:00"}])
    at = AppTest.from_string("import app\napp.main()", default_timeout=10).run()
    at.text_input[0].set_value("galaxy a07 128gb")
    at.button[0].click().run()
    assert not at.exception
    assert len(at.metric) == 3
    at.radio[0].set_value("5g").run()
    assert not at.exception
    assert not at.metric
    assert any("Você selecionou 5G" in info.value for info in at.info)
    assert not any("**Oferta mais barata:**" in m.value for m in at.markdown)
    tabela = next(m.value for m in at.markdown if "| Motivo |" in m.value)
    assert "| acessório ou outro produto |" in tabela and "| Não se aplica |" in tabela
    assert "| outra versão (4G) |" in tabela and "| 4G |" in tabela
    assert "| Não informada |" in tabela
    at.radio[0].set_value("4g").run()
    assert not at.exception
    assert at.metric[0].value == app.reais(700)


def test_avaliacao_abre_com_a_rodada_mais_recente_e_preserva_as_anteriores():
    at = AppTest.from_file(str(Path(app.__file__)), default_timeout=20)
    at.query_params["avaliar"] = "1"
    at.run()
    assert not at.exception
    cabecalhos = [h.value for h in at.header]
    assert cabecalhos[:3] == ["Bateria com lojas diretas", "Reconferência com novas fontes", "Validação final"]
    assert "Resultados registrados" in cabecalhos[3:]
    assert any("validação final" in s.value for s in at.subheader)


def test_revisao_ia_abre_online_e_nao_se_apresenta_como_teste_humano():
    at = AppTest.from_file(str(Path(app.__file__)), default_timeout=20)
    at.query_params["revisao"] = "1"
    at.run()
    assert not at.exception
    assert at.title[0].value == "Faixa Certa: revisão técnica por IA"
    assert any("Não é conferência humana" in aviso.value for aviso in at.info)
    assert [t.label for t in at.tabs] == ["Rótulos (50)", "Ofertas (136)", "Páginas não confirmadas (4)"]
