# Testes do Faixa Certa

Resultados registrados em 10/11/2026 com o `app.py` do commit `a460854` (SHA-256 do arquivo começando por `7e11edfb960b`). Cada planilha traz a entrada, a resposta esperada e a saída de cada método, linha a linha.

## Extração de atributos: 50 títulos

Arquivo: [`testes_extracao_50_titulos.csv`](testes_extracao_50_titulos.csv)

São 50 títulos de anúncios lidos em 09/11/2026 e rotulados um a um com modelo, armazenamento em GB e condição. O modelo fica vazio quando o título não é de um dos 14 modelos da base de teste ou quando é de um acessório. Um título conta como acerto quando modelo, armazenamento e condição batem com o rótulo.

| Método | Acertos |
| --- | --- |
| Regras: expressões regulares escritas para os 14 modelos | 38 de 50 (76%) |
| LLM `gemini-3.5-flash-lite` | 50 de 50 (100%) |

O LLM rodou no app publicado em 10/11/2026, às 14:04, e levou 25,6 s. Respondeu o modelo reserva, `gemini-3.5-flash-lite`, porque o principal, `gemini-3.1-flash-lite`, não respondeu naquele momento. As instruções e os lotes de 15 títulos são os mesmos da busca.

Para refazer, abra <https://faixa-certa.streamlit.app/?avaliar=1> e clique em "Rodar o LLM nos 50 títulos". A página mostra a versão do código e o modelo usado e baixa a mesma planilha.

Colunas: `esperado_*` é o rótulo; `regras_*` é a saída do extrator por regras; `llm_modelo_resposta` é o texto devolvido pelo LLM, e `llm_modelo` é esse modelo na grafia da base de teste (vazio quando é outro modelo); `llm_celular` é falso para acessórios.

## Correção de digitação

Arquivo: [`testes_digitacao.csv`](testes_digitacao.csv)

É a saída da correção de digitação do app, na mesma versão, para quatro listas escritas pela equipe:

| Lista | Resultado |
| --- | --- |
| `erros_comuns_30`: erros comuns em buscas, de 15 marcas | 30 de 30 corrigidos |
| `erros_simulados_40`: uma letra trocada, faltando, sobrando ou invertida (sorteio com semente 7) | 40 de 40 corrigidos |
| `lista_ampliada_184`: grafias pelo som e erros de marcas e linhas | 183 de 184 corrigidos ("uphone" virou "phone") |
| `palavras_comuns_205`: palavras comuns em buscas, que não podem mudar | 205 de 205 sem alteração |

As listas foram escritas pela equipe junto com o vocabulário. Por isso, o teste com buscas reais de usuários ainda é necessário.

## Ainda não medido

- Cobertura das lojas, equivalência das ofertas e tempo de resposta: bateria de 20 buscas.
- Redução do tempo de pesquisa e utilidade: testes com 5 lojistas.
