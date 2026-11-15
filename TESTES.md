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
- Os testes de regressão preservam o resultado das regras nos 50 rótulos publicados: 45 extrações corretas e 44 decisões corretas. A origem dos rótulos é IA, com origem por IA identificada.
- `tests/test_lojas_oficiais.py`: leitura dos catálogos das lojas oficiais da Motorola e da Samsung, com estruturas copiadas dos catálogos reais de 14/11/2026: SKU com estoque, total no Pix em uma parcela, link da página da loja, rede do catálogo e consulta só para aparelho novo da própria marca.
- `tests/test_interface.py`: a página de avaliação abre com a reconferência das novas fontes, seguida da validação final anterior e dos demais registros preservados.
- `tests/test_fontes_adicionais.py`: Fast Shop pelo catálogo público, estoque e preço da variante selecionada na FoneMix e EletroInfo Outlet, rejeição de links inválidos, preço parcelado sem promoção indevida a Pix e coleta de páginas de produto com cache. Os dados são estruturas de teste; não são respostas de participantes.
- `python validar_mvp.py --coletar`: rodada real das 20 buscas, sem cache de preços, com tempo medido no servidor de desenvolvimento. Publica títulos, URLs, preços, descartes e evidências de rede em `validacao_tecnica.json`. Preserva a rodada anterior em `validacoes/`.
- `?coleta_nova=1` abre o app em modo de validação: buscas por modelo ignoram o cache de preços. A última mensagem identifica a consulta concluída e o tipo de coleta. Isso permite medir do clique até a conclusão visível; `validacao_navegador.json`, quando presente, publica essa medição separadamente.

Os resultados automáticos são separados da revisão humana e das sessões com os dez participantes. A rodada técnica não gera respostas de utilidade, tempos de pessoas nem rótulos humanos.

- `tests/test_revisao_evidencias.py`: leitura de valores capturados com separadores alterados, rejeição de parcelas como preço total, confirmação de modalidade na página, tratamento de cupons e correção da suposição de Pix na Gazin.
- `python revisar_evidencias.py --coletar`: consulta as páginas públicas das ofertas registradas, respeitando robots.txt e o prazo por página. Não usa o extrator do MVP para produzir um rótulo de produto nem gera participantes. Os arquivos de cache retêm a data original da visita; uma página relida não ganha uma data nova de coleta.
- A rota `?revisao=1` publica a revisão por IA dos 50 títulos e das 207 ofertas, preservando os casos inconclusivos e os registros originais.

## Rodada com lojas diretas de 14/11/2026

Código de coleta: commit `865969a`; SHA-256 de `app.py` iniciado por `0a835274e9ad`. O app publicado foi medido no Chrome, com as mesmas 20 entradas e coleta nova: **20/20 em até 15 s**, mediana **3,027 s**, máximo **3,988 s**; **18/20 com duas lojas** contando ofertas à parte, **16/20** só com pagamento confirmado e **16 faixas**. Foram exibidas **136 ofertas**, sendo 120 com pagamento confirmado e 16 à parte.

A revisão posterior por IA visitou todas as páginas e identificou **132 ofertas compatíveis e 4 inconclusivas**: **97,1%**, mantendo as inconclusivas no denominador. A cobertura de duas lojas permanece 18/20 quando se contam apenas páginas identificadas. Os preços de 116 ofertas à vista/Pix e 16 sem modalidade confirmada foram encontrados nas páginas; a visita posterior não comprova o valor exato no horário da bateria. Os quatro casos inconclusivos permanecem publicados, sem repetição: Fast Shop/A07 (404), Motorola/G06 (sem produto), KaBuM!/iPhone 13 usado (503 e prazo esgotado).

- `validacao_lojas_diretas.json`: entradas, tempos da interface, lojas, ofertas, falhas, preparação e versão avaliada; aparece primeiro em `?avaliar=1`.
- `revisao_ia_diretas.json`: revisão individual das 136 ofertas, exibida primeiro em `?revisao=1`. A revisão anterior das 207 ofertas permanece disponível.
- `python revisar_evidencias.py --coletar --registro validacao_lojas_diretas.json --cache ../investigacao/paginas_revisao_diretas`: coleta de evidências da rodada escolhida, com cache separado. A análise do produto exige leitura dos dados; o programa não cria um gabarito humano.
- `python -m pytest -q`: **79 testes passaram**. A atualização preserva os resultados dos classificadores e verifica a abertura da avaliação e da revisão com os registros mais recentes.

As medições e a revisão são técnicas e por IA. A origem por IA desta revisão está identificada nos registros.
