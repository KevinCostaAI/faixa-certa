# Testes do Faixa Certa

Resultados registrados em 10/11/2026 com o `app.py` do commit `a460854` (SHA-256 do arquivo começando por `7e11edfb960b`). Cada planilha traz a entrada, a resposta esperada e a saída de cada método, linha a linha.

## Extração de atributos: 50 títulos

Arquivo: [`testes_extracao_50_titulos.csv`](testes_extracao_50_titulos.csv)

São 50 títulos de anúncios lidos em 09/11/2026 e rotulados um a um com modelo, armazenamento em GB e condição. O modelo fica vazio quando o título não é de um dos 14 modelos da base de teste ou quando é de um acessório. Um título conta como acerto quando modelo, armazenamento e condição batem com o rótulo.

| Método | Acertos |
| --- | --- |
| Regras: expressões regulares escritas para os 14 modelos | 38 de 50 (76%) |
| As mesmas regras com o filtro de acessórios que o app já usa | 49 de 50 (98%) |
| LLM `gemini-3.5-flash-lite` | 50 de 50 (100%) |

Com o filtro de acessórios, a diferença entre o LLM e as regras cai para 2 pontos percentuais, abaixo da meta de 10 definida no projeto. O resultado vale para esta amostra, e as regras foram escritas para os 14 modelos que ela contém; a vantagem do LLM sobre as regras fica em aberto até um teste com modelos que as regras não conhecem. As colunas `regras_filtro_*` foram calculadas depois, fora do app, com as funções da mesma versão (`extrair_por_regras` e o filtro `ACESSORIO`); o único erro é o título 42, uma capa cujo título começa pelo nome do aparelho.

O LLM rodou no app publicado em 10/11/2026, às 14:04, e levou 25,6 s. Respondeu o modelo reserva, `gemini-3.5-flash-lite`, porque o principal, `gemini-3.1-flash-lite`, não respondeu naquele momento. As instruções e os lotes de 15 títulos são os mesmos da busca.

Este teste de desenvolvimento não é mais refeito pelo app. Desde 13/11/2026, a página de avaliação (`?avaliar=1`) roda a avaliação independente prevista no protocolo, com 50 títulos novos, as regras do próprio app e o LLM da busca. Esta planilha fica como registro do desenvolvimento.

Colunas: `esperado_*` é o rótulo; `regras_*` é a saída do extrator por regras; `llm_modelo_resposta` é o texto devolvido pelo LLM, e `llm_modelo` é esse modelo na grafia da base de teste (vazio quando é outro modelo); `llm_celular` é falso para acessórios; `regras_filtro_*` é a saída das regras com o filtro de acessórios.

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

## Atualização de 14/11/2026

As seções acima registram o desenvolvimento de 10/11. Os resultados posteriores e suas versões estão publicados em `?avaliar=1` e `?protocolo=1`.

Instalação para desenvolvimento: `python -m pip install -r requirements-dev.txt`.

- `python -m pytest -q`: testes da leitura de preços da Magazine Luiza, restrições de pagamento, prazo total da coleta, cache, robots.txt, confirmação de rede móvel e interface Streamlit. Inclui a troca 4G/5G e seus efeitos no menor preço, mediana, maior preço e destaque. Usa lojas simuladas nos testes de interface; não representa cobertura real nem pesquisa com usuários.
- Os testes de regressão preservam o resultado das regras nos 50 rótulos publicados: 45 extrações corretas e 44 decisões corretas. A origem dos rótulos é IA, com revisão humana pendente.
- `python validar_mvp.py --coletar`: rodada real das 20 buscas, sem cache de preços, com tempo medido no servidor de desenvolvimento. Publica títulos, URLs, preços, descartes e evidências de rede em `validacao_tecnica.json`. Preserva a rodada anterior em `validacoes/`.

Os resultados automáticos são separados da revisão humana e das sessões com os dez participantes. A rodada técnica não gera respostas de utilidade, tempos de pessoas nem rótulos humanos.
