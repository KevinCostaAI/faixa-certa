from pathlib import Path

from streamlit.testing.v1 import AppTest

import app


def test_interface_principal_abre_com_a_funcao_main():
    at = AppTest.from_file(str(Path(app.__file__)), default_timeout=10).run()
    assert not at.exception
    assert at.title[0].value == "Faixa Certa"
    assert at.text_input[0].label == "Qual celular você procura?"


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
