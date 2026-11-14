Projeto Integrador VII · Kevin Costa · protocolo criado em 13/11/2026, cópia publicada em 14/11/2026.

Os resultados já obtidos aparecem também na [página de avaliação](https://faixa-certa.streamlit.app/?avaliar=1), que abre sem login e sem rodar os métodos de novo.

A nova avaliação decide o método principal: se o LLM não superar as regras do app em pelo menos 10 pontos percentuais em 50 títulos novos, as regras passam a ser o método principal. Depois vêm a bateria de 20 buscas, a avaliação da correção de digitação e os testes com 5 lojistas e 5 consumidores.

## Decisões fixadas

Estas decisões valem para todos os testes e não mudam depois de ver os resultados.

| Decisão | O que vale |
| --- | --- |
| Método principal | Nova avaliação independente antes de escolher. Se o LLM não superar as regras do app em pelo menos 10 pontos percentuais no acerto da extração dos 50 títulos novos, as regras passam a ser o método principal. |
| Público | Principal: pequenos lojistas, que precisam da faixa de preço de um modelo para precificar. Secundário: consumidores, que procuram a oferta mais barata de um modelo. Dois idosos entram entre os consumidores, com resultados descritos como exploratórios. |
| Base de preço | Preço total à vista, incluindo Pix, sem frete. A forma de pagamento de cada oferta é registrada. Preço só parcelado ou com condição desconhecida fica fora da faixa, com o motivo registrado. |
| Cupom e assinatura | Desconto que depende de cupom ou de assinatura é identificado e não vale como base. Vale o preço à vista sem essa condição, quando a oferta informa; senão, a oferta fica fora, com o motivo. |
| Defeitos | Aparelho com defeito, bloqueio ou função indisponível anunciados fica fora da faixa de aparelhos funcionais. |

## Avaliação dos métodos: amostra de 50 títulos

Os 50 títulos são novos, coletados numa única data e rotulados antes de rodar os métodos. A amostra só é escolhida depois que código, prompt, modelo e critérios de correção estiverem fixados.

| Categoria | Títulos | Casos incluídos |
| --- | --- | --- |
| Novos | 20 | 6 variantes que mudam o produto (Pro, Max, Plus, “e”, “C”, FE); 4 de rede (2 com 5G no título, 2 sem rede em modelos que existem em 4G e 5G); 4 de marcas e modelos que não aparecem no desenvolvimento; 2 com código de fábrica; 2 com brinde; 2 sem armazenamento no título |
| Usados | 12 | 4 “usado”; 2 “seminovo”; 2 “vitrine” ou “mostruário”; 2 com estado declarado (“excelente”, “bom”); 2 com defeito ou bloqueio anunciado |
| Recondicionados | 8 | 4 “recondicionado”; 2 “renovado” ou “refurbished”; 2 com grau ou garantia de recondicionamento |
| Acessórios e outros | 10 | 4 capas ou películas que citam modelos (2 com o nome do aparelho no início do título); 2 carregadores ou cabos; 2 peças de reposição; 1 smartwatch ou tablet; 1 kit sem o aparelho |

**Coleta**

- Uma única data, nas quatro fontes do app: Compare Livre, KaBuM!, Gazin e Novo Mundo.
- Buscas diferentes das 20 da bateria e das usadas no desenvolvimento.
- Entram os primeiros títulos que preencherem cada cota, na ordem em que a loja mostra. Títulos que só mudam a cor entram uma vez. Nenhum título da amostra anterior, dos exemplos de desenvolvimento ou dos exemplos ilustrativos entra.
- Cada título recebe uma busca de referência. Cerca de metade dos celulares é do mesmo produto da busca, e a outra metade difere em modelo, variante, armazenamento, condição, rede ou defeito.

**Evidências de cada anúncio:** URL, data e hora da coleta, fonte, captura da página com título e preço, e os atributos conferidos na página (armazenamento, rede pela ficha técnica, condição e defeito).

## Rótulos e correção

Cada título tem dois rótulos, medidos em separado: os atributos que o título informa, para a extração, e a decisão de aceitar ou excluir a oferta. Os dois métodos recebem só o título e a busca de referência, como no app.

| Campo | Rótulo esperado, só pelo título | Observação |
| --- | --- | --- |
| Tipo | Celular, acessório ou outro produto |  |
| Marca | Fabricante; submarca conta como a fabricante (POCO é Xiaomi) | O modelo define a marca |
| Modelo | Nome completo, com a variante (iPhone 16e, Redmi 15C) | Código de fábrica só identifica o modelo com correspondência verificada |
| Armazenamento | GB escritos no título, ou “não informado” | Memória RAM não entra |
| Condição | Novo, usado ou recondicionado; sem indicação, novo, como no app | Seminovo e vitrine contam como usado |
| Rede | 4G, 5G ou “não informado” | Ausência de 5G não vale como 4G |
| Defeito anunciado | Sim ou não | Defeito, bloqueio ou função indisponível |

O que a página confirma fica em colunas próprias e não entra na correção da extração. Em acessório ou outro produto, modelo, armazenamento, condição, rede e defeito ficam como “não se aplica” e não são cobrados.

**Correção da extração**

- Cada campo é comparado com o rótulo sem diferença de maiúsculas, acentos, marca escrita junto do modelo e “4G”. O 5G é cobrado no campo de rede, não no nome do modelo.
- “Não informado” igual ao rótulo é acerto.
- Um título está correto quando tipo, modelo completo, armazenamento e condição batem com o rótulo; em acessório, basta o tipo. Essa é a medida da meta de 90% e do critério de 10 pontos entre os métodos.
- Rede e defeito têm o acerto informado por campo.

**Decisão de aceitar ou excluir**

- O rótulo segue a definição de oferta equivalente, com a busca de referência e o que o título informa: aceitar, ou excluir com o motivo (acessório, outro modelo ou variante, outro armazenamento, outra condição, outra rede, defeito anunciado ou atributo exigido não informado no título). Rede e defeito fazem parte da decisão.
- Oferta aceita pelo método só conta como acerto se a página confirmar os atributos exigidos. Se a página contradisser, é erro. Se não informar, a oferta fica como inconclusiva, entra no total e não conta como acerto.
- A decisão é medida para os dois métodos, com os erros listados caso a caso.

## Preparação antes da amostra

Antes de escolher os 50 títulos, o app ganha duas mudanças e os métodos são fixados. Nenhum título da amostra final é usado nessa preparação.

1. **Detecção de defeitos.** Os dois métodos passam a marcar defeito anunciado: o LLM ganha um campo no prompt, e as regras ganham uma lista de termos, como defeito, tela quebrada ou trincada, não liga, para retirada de peças, bloqueado, iCloud e conta Google. A oferta com defeito anunciado sai da faixa com esse motivo. O desenvolvimento usa exemplos separados, que não entram nos 50.
2. **Condição do preço.** Cada fonte é conferida para saber se o preço coletado é à vista, Pix ou parcelado e se depende de cupom ou assinatura. O app passa a registrar a forma de pagamento de cada oferta e a excluir da faixa o que não for preço total à vista, com o motivo. A tela passa a informar a base de preço, que o frete não entra e que uma busca repetida em até 15 minutos reaproveita o resultado.
3. **Regras usadas na comparação.** A avaliação usa as funções que o app já tem: filtro de acessórios, leitura de marca e modelo no título (a mesma da tela de escolha) e leitura de armazenamento, condição e rede, além da nova detecção de defeitos. A página de avaliação passa a mostrar essas regras, com o filtro, no lugar do extrator de teste antigo.
4. **Congelamento.** Antes da coleta, ficam registrados o commit do código, o prompt, os modelos do LLM (principal e reserva) e estes critérios de correção. Em cada execução fica registrado qual modelo respondeu. Se algum método for ajustado depois de ver os resultados, a amostra passa a ser de desenvolvimento e uma nova avaliação independente é necessária.

## Bateria de 20 buscas

São 20 modelos diferentes, escolhidos antes da bateria: 5 Samsung, 5 Motorola, 4 Xiaomi, 1 Oppo e 5 Apple, de entrada a topo de linha. A lista inclui 4 buscas com erro de digitação, 2 de usados, 1 de recondicionado, 1 com 5G na busca e modelos com variantes parecidas.

| # | Busca | O que testa |
| --- | --- | --- |
| 1 | galaxy a07 128gb | Samsung de entrada |
| 2 | galaxi a17 128gb | Erro de digitação; o A17 existe em 4G e em 5G |
| 3 | galaxy a16 128gb | Samsung de entrada |
| 4 | galaxy a36 5g 128gb | 5G escrito na busca |
| 5 | galaxy a14 128gb usado | Usado |
| 6 | motorolla g06 128gb | Erro de digitação; marca sem a linha “Moto” |
| 7 | moto g17 256gb | Anúncios com código de fábrica no título |
| 8 | moto g35 256gb | Modelo que só existe em 5G, sem 5G na busca |
| 9 | moto g47 128gb | Motorola intermediário |
| 10 | moto e15 64gb | Motorola de entrada, linha E |
| 11 | xiaome redmi 15c 256gb | Erro de digitação; não confundir com o Redmi 15 |
| 12 | redmi 15 256gb | Não confundir com o Redmi 15C |
| 13 | poco c85 128gb | Submarca (POCO é Xiaomi) |
| 14 | redmi note 15 256gb | Não confundir com o Note 15 Pro |
| 15 | oppo a6x 128gb | Outra marca; não confundir com o A6K |
| 16 | iphone 16e 128gb | Variante com letra |
| 17 | epone 16 128gb | Erro de digitação; não confundir com 16e, 16 Plus e 16 Pro |
| 18 | iphone 17 pro max 256gb | Topo de linha; não confundir com o 17 Pro |
| 19 | iphone 13 128gb usado | Usado |
| 20 | iphone 14 128gb recondicionado | Recondicionado; sem oferta, entra como busca sem resultado |

**Versão esperada:** quando o modelo existe em 4G e em 5G, a busca sem 5G espera a versão 4G, e a busca com 5G espera a 5G. Quando o modelo só existe numa versão, vale essa. Antes da bateria, a versão de cada busca é confirmada na ficha técnica do fabricante, com o código do aparelho e o link registrados (passo 5 da ordem de execução).

**Código de fábrica:** pode identificar o mesmo modelo, mediante correspondência verificada. O [manual oficial do Moto G17](https://pt-br.support.motorola.com/ci/fattach/get/88760940/1770844264/redirect/1/filename/moto%2Bg17.Brazil.JagBuild.GSG.pt-BR.SSC8F06686-A_Web.pdf), por exemplo, associa o XT2623-1 a esse modelo. Códigos também ajudam a distinguir versões: a [página da Samsung](https://shop.samsung.com/br/galaxy-a17/p) traz o Galaxy A17 como SM-A175F e oferece o Galaxy A17 5G como outro modelo.

## Bateria: registro, conferência e cálculos

Cada busca é feita uma vez, com coleta nova, e cada oferta exibida é conferida por uma pessoa na página do anúncio. Buscas que falharem continuam na bateria.

**Registro de cada busca**

- Entrada digitada, data e hora, versão do código e modelo do LLM que respondeu. Se o LLM ficar indisponível, fica registrado que a busca seguiu por regras.
- Tempo do clique em “Buscar” até o resultado completo, indicando se a coleta foi nova ou reaproveitada.
- Loja e vendedor de cada oferta exibida, ofertas exibidas e descartadas, e se a busca gerou faixa de preço.
- Erros e avisos mostrados pelo app.

**Conferência humana de cada oferta exibida**

- Produto: equivalente, não equivalente ou inconclusivo, pela definição de oferta equivalente e pela ficha técnica da página. Rede sem informação suficiente fica inconclusiva.
- Preço: igual ao da página, na forma de pagamento registrada. Frete fora. Cupom e assinatura identificados.
- Evidência: URL, data e hora, e captura da página.

**Como cada fonte informa o preço** (conferido nas páginas em 13/11/2026)

| Fonte | Preço que o app usa | Forma de pagamento | Tratamento |
| --- | --- | --- | --- |
| [KaBuM!](https://www.kabum.com.br/busca/galaxy-a17-128gb) | Preço “No PIX” | Pix; o parcelado em 10x tem outro total | Vale como base só com o Pix confirmado. Campanha que vale para todos usa o próprio preço no Pix; sem ele, o total entra como pagamento não informado. Preço Prime (assinatura) e oferta restrita a login ficam fora |
| [Gazin](https://www.gazin.com.br/busca/galaxy-a17-128gb) | Preço “No Pix” | Pix; o parcelado em 12x sem juros tem total maior | Vale como base |
| [Novo Mundo](https://www.novomundo.com.br/produto/smartphone-samsung-galaxy-a17-com-ia-128gb-4gb-ram-152183) | Preço “Por” | A página não diz “à vista”, mas o parcelamento informado é com juros | Pagamento não informado: parcelamento com juros não comprova preço à vista. Fica fora da faixa e aparece à parte, para consulta |
| [Compare Livre](https://comparelivre.com.br/busca?q=galaxy+a17+128gb) | “A partir de”, da loja de destino | Não informa | Fica fora da faixa e aparece à parte, com o aviso “fora da faixa: pagamento não informado”, para consulta. Na busca “galaxi a17 128gb” de 12/11, 13 das 21 ofertas equivalentes vieram dele |

Menor preço, mediana, maior preço, destaque da oferta mais barata e filtro de preços fora do padrão usam só ofertas equivalentes com Pix ou à vista confirmado. Com menos de 3 delas, o app mostra o aviso e nenhuma faixa.

**Cálculos**

| Medida | Como calcular | Meta |
| --- | --- | --- |
| Cobertura | Busca com ofertas exibidas e conferidas como equivalentes em pelo menos duas lojas distintas. Loja é onde a compra é feita: vendedores do mesmo marketplace contam como uma loja, e o Compare Livre, que é agregador, conta pela loja de destino | 18 de 20 buscas |
| Faixa gerada | Busca em que o app mostrou a faixa de preço, o que exige pelo menos 3 ofertas equivalentes. Informada à parte da cobertura | Informada |
| Equivalência | Ofertas equivalentes ÷ ofertas exibidas, somando as buscas. Inconclusivas entram no total e não contam como acerto. Busca sem oferta exibida fica à parte | Pelo menos 95% |
| Tempo de resposta | Do clique ao resultado completo, só nas coletas novas; reaproveitadas ficam à parte | 18 de 20 em até 15 segundos |

## Correção de digitação e testes com usuários

A correção de digitação ganha uma avaliação própria, porque as 4 buscas com erro da bateria são só casos funcionais.

**Correção de digitação**

- Entradas independentes: um ditado de 20 nomes de celulares para os 10 participantes dos testes, que não participaram do desenvolvimento. Todas as grafias digitadas entram, certas e erradas, sem edição.
- Medidas: buscas com erro corrigidas para o nome certo, com meta de pelo menos 90%, e buscas certas que continuam sem alteração.

**Testes com usuários**

| Grupo | Participantes | Tarefa |
| --- | --- | --- |
| Lojistas (principal) | 5 donos ou funcionários de pequenas lojas de eletrônicos | Descobrir a faixa de preço de um modelo para decidir o preço de venda |
| Consumidores (secundário) | 5 consumidores, incluindo 2 idosos | Achar a oferta mais barata de um modelo |

- **Redução do tempo:** cada participante faz duas tarefas equivalentes, com modelos diferentes de preço parecido, uma à mão e outra no app. A ordem alterna entre participantes. Só entram tarefas concluídas corretamente. A meta de tempo pelo menos 50% menor no app é calculada por grupo, pela mediana, e o resultado de cada participante também é informado.
- **Utilidade:** cada participante responde se usaria a ferramenta (sim ou não, com o motivo), e as respostas são registradas uma a uma. A meta é de pelo menos 4 de 5 lojistas e 4 de 5 consumidores, avaliados separadamente.
- **Idosos:** as dificuldades observadas são registradas e descritas como resultados exploratórios.
- **Registro:** participantes identificados por código, sem nome, com autorização para usar as respostas.

## Limitações declaradas e ordem de execução

**Limitações**

- As 20 buscas foram escolhidas entre modelos que o próprio app encontrou nas buscas por marca. É uma amostra de conveniência, que pode favorecer modelos que ele já encontra. A disponibilidade é confirmada direto nas lojas antes da bateria.
- Os 50 títulos vêm de uma única data e das quatro fontes do app, e não representam todas as lojas.
- Os rótulos foram preenchidos pelo Claude, a pedido do Kevin, e publicados para revisão; a concordância entre avaliadores não é medida.
- A memória RAM não entra na equivalência.
- O LLM gratuito pode ficar indisponível. Nesse caso o app segue por regras, e isso fica registrado.
- Preços mudam ao longo do dia e podem variar por região.
- Os resultados dos dois idosos são exploratórios.

**Ordem de execução**

1. Implementar a detecção de defeitos e a condição do preço, com exemplos de desenvolvimento.
2. Fixar código, prompt, modelos e critérios de correção, registrando o commit.
3. Coletar e rotular os 50 títulos, com as evidências.
4. Rodar os dois métodos, listar os erros caso a caso e aplicar o critério de 10 pontos para escolher o método principal.
5. Confirmar nas lojas a disponibilidade dos 20 modelos e a versão esperada de cada um.
6. Rodar a bateria de 20 buscas, com a conferência humana.
7. Fazer os testes com usuários, incluindo o ditado da correção de digitação.
8. Atualizar o PDF do projeto com os resultados.

## Registro da execução

**Congelamento, 13/11/2026.** Commit a068c0e do repositório faixa-certa; app.py com SHA-256 iniciado por 8c444b33c9b2 e prompt com SHA-256 iniciado por 6953e9ae9a95. LLM principal gemini-3.1-flash-lite, reserva gemini-3.5-flash-lite, 15 títulos por chamada, esforço de raciocínio mínimo. Na busca, o LLM tem 15 s no total; na avaliação, até 90 s por busca de referência. A página de avaliação mostra essas versões em cada execução. Antes de rodar a avaliação, o commit 4f7ce13 (app.py com SHA-256 iniciado por 3c92789f72fd) fez a versão 4G ou 5G escolhida na tela valer para toda a faixa. A mudança não toca a extração nem a decisão avaliadas, e o teste da avaliação deu a mesma saída nas duas versões. Depois, o commit 4b89a17 (app.py iniciado por 44a7dae7fded) publicou os 50 títulos na página de avaliação, com fonte, URL, busca de referência e rótulos, e bloqueou a execução até os 50 estarem rotulados; de novo sem mudar a extração nem a decisão, com a mesma saída no teste.

**Coleta dos 50 títulos, 13/11/2026, das 15:04 às 15:16.** As quatro fontes foram consultadas em todas as buscas. Os títulos que preencheram as cotas vieram da KaBuM! (44) e do Compare Livre (6: 5 anúncios da Shopee e 1 do Mercado Livre). A amostra final tem 16 títulos explicitamente usados, 4 recondicionados, 10 acessórios e outros produtos e 20 sem indicação de uso no título, que contam como novos pela convenção do app. Desvios das cotas, todos por falta de títulos nas fontes:

- Seminovo e vitrine ou mostruário (4 vagas): nenhum título nas quatro fontes; as vagas ficaram com os próximos usados, na ordem das lojas.
- Recondicionados (8 vagas): só 4 títulos distintos nas quatro fontes, todos do mesmo vendedor; as outras 4 vagas ficaram com os próximos usados.
- Capas e películas com o nome do aparelho no início (2 vagas): nenhuma nas fontes; as vagas ficaram com as próximas películas.

**Evidências, 13/11/2026, das 15:26 às 15:41.** 45 páginas capturadas e conferidas (44 da KaBuM! e 1 do Mercado Livre), com armazenamento, rede pela ficha técnica, condição e defeito. Os preços estavam iguais aos da coleta. Os 5 anúncios da Shopee abriram uma verificação de tráfego da loja e ficaram como “não verificada”: se um método aceitar um deles, o resultado é inconclusivo. Entre a coleta e a conferência, 4 anúncios ficaram esgotados ou indisponíveis.

**Rótulos, 13/11/2026.** Preenchidos e conferidos um a um pelo Claude, a pedido do Kevin, só pelo título e pela busca de referência, e publicados na página de avaliação (commit 262e604, app.py iniciado por 8cdf0af5fbee). A coluna “Mesmo modelo da busca” fica separada da decisão: a oferta só é equivalente com o mesmo modelo, o armazenamento e a condição pedidos, a rede esperada e sem defeito anunciado. Resultado: 16 ofertas aceitas e 34 excluídas.

- “Usado — Grade A/B/C” continua usado, não recondicionado.
- Nº 24: modelo inconclusivo, porque o título cita Hot 60i e Hot 50i.
- Nº 25 e 39: número sem unidade (“256”, “8 256”) não confirma o armazenamento.
- Nº 37 e 46: “Sem Face ID / Touch ID” é defeito funcional anunciado.
- Acessórios e outros produtos: modelo, armazenamento, condição, rede e defeito ficam como “não se aplica”.
- Nº 16, 41 e 45: o modelo existe em 4G e 5G e o título não diz a rede, então a oferta não é equivalente; ausência de “5G” não confirma 4G.

**Versão esperada das 20 buscas (passo 5).** Conferida nas páginas dos fabricantes em 13/11/2026. Todos os 20 modelos tinham ofertas em pelo menos uma das quatro fontes nesse dia. A busca 20 não tinha nenhum iPhone 14 recondicionado (os 13 anúncios da KaBuM! eram usados) e segue como busca sem oferta esperada.

| # | Busca | Versão esperada | Código | Fonte do fabricante |
| --- | --- | --- | --- | --- |
| 1 | galaxy a07 128gb | 4G; existe o A07 5G | SM-A075M | [Samsung](https://shop.samsung.com/br/galaxy-a07/p) |
| 2 | galaxi a17 128gb | 4G; o A17 5G é SM-A176B | SM-A175F | [Samsung](https://shop.samsung.com/br/galaxy-a17/p) |
| 3 | galaxy a16 128gb | 4G; o A16 5G é SM-A166M | SM-A165M | [Samsung](https://shop.samsung.com/br/galaxy-a16/p) |
| 4 | galaxy a36 5g 128gb | 5G, única versão | SM-A366E | [Samsung](https://shop.samsung.com/br/galaxy-a36/p) |
| 5 | galaxy a14 128gb usado | 4G; o A14 5G é SM-A146M | SM-A145M | [Samsung](https://www.samsung.com/br/smartphones/galaxy-a/galaxy-a14-black-mist-128gb-sm-a145mzkgzto/) |
| 6 | motorolla g06 128gb | 4G, única versão | XT2535-1 | [Motorola](https://www.motorola.com.br/smartphone-moto-g06-128-gb/p) |
| 7 | moto g17 256gb | 4G, única versão | XT2623-1 | [Motorola](https://www.motorola.com.br/smartphone-motorola-moto-g17-256gb/p) |
| 8 | moto g35 256gb | 5G, única versão | XT2433-2 | [Motorola](https://www.motorola.com.br/smartphone-moto-g35-5g-256gb/p) |
| 9 | moto g47 128gb | 5G, única versão | XT2625-1 | [Motorola](https://www.motorola.com.br/) |
| 10 | moto e15 64gb | 4G, única versão | XT2523 | [Lenovo](https://lenovo.com/gb/en/p/phones/moto/moto-e-series/phn-moto-xt2523-6-se-cd-2+64-ds-rtl/pmipmhk40mb) |
| 11 | xiaome redmi 15c 256gb | 4G; existe o Redmi 15C 5G | não informado | [Xiaomi](https://www.mi.com/global/product/redmi-15c/specs/) |
| 12 | redmi 15 256gb | 4G; existe o Redmi 15 5G | não informado | [Xiaomi](https://www.mi.com/global/product/redmi-15/specs/) |
| 13 | poco c85 128gb | 4G; existe o POCO C85 5G | não informado | [Xiaomi](https://www.mi.com/global/product/poco-c85/specs/) |
| 14 | redmi note 15 256gb | 4G; existe o Redmi Note 15 5G | não informado | [Xiaomi](https://www.mi.com/global/product/redmi-note-15/specs/) |
| 15 | oppo a6x 128gb | 4G; o A6x 5G é CPH2783 e só tem 256 GB no Brasil | CPH2819 | [OPPO](https://www.oppo.com/br/smartphones/series-a/a6x/specs/) |
| 16 | iphone 16e 128gb | 5G, única versão | A3212, A3408, A3409, A3410 | [Apple](https://support.apple.com/pt-br/108044) |
| 17 | epone 16 128gb | 5G, única versão | A3081, A3286, A3287, A3288 | [Apple](https://support.apple.com/pt-br/108044) |
| 18 | iphone 17 pro max 256gb | 5G, única versão | A3257, A3525, A3526, A3527 | [Apple](https://support.apple.com/pt-br/108044) |
| 19 | iphone 13 128gb usado | 5G, única versão | A2482, A2631, A2633, A2634, A2635 | [Apple](https://support.apple.com/pt-br/108044) |
| 20 | iphone 14 128gb recondicionado | 5G, única versão | A2649, A2881, A2882, A2883, A2884 | [Apple](https://support.apple.com/pt-br/108044) |

**Avaliação dos 50 títulos, 14/11/2026, 05:34.** Rodada na página de avaliação do app publicado, com a versão do commit 8ebfdbe (app.py iniciado por 623e2585f367). Esse commit só criou a chave do método principal, ainda com o LLM, e passou a tabela de erros para formato fixo, sem mudar a extração nem a decisão. A execução levou 97 s. Responderam gemini-3.1-flash-lite e gemini-3.5-flash-lite, sem nenhuma falha da IA.

| Medida | LLM | Regras |
| --- | --- | --- |
| Extração correta (modelo, armazenamento, condição, rede e defeito) | 45 de 50 (90%) | 45 de 50 (90%) |
| Rede | 40 de 40 | 40 de 40 |
| Defeito | 40 de 40 | 40 de 40 |
| Decisão (aceitar ou excluir) | 42 acertos, 7 erros, 1 inconclusiva | 44 acertos, 5 erros, 1 inconclusiva |
| Falhas da IA | 0 | não se aplica |

O LLM não superou as regras em 10 pontos percentuais (diferença zero). Pela regra fixada, as regras passaram a ser o método principal no commit 8a8f36b (app.py iniciado por 096fc36d375f). A chave do LLM continua configurada, mas a busca classifica os títulos pelas regras. Erros caso a caso:

| Nº | LLM | Regras |
| --- | --- | --- |
| 16 | Aceitou; o rótulo exclui (rede não informada): erro | Igual: erro |
| 22 | Aceitou; página da Shopee não verificada: inconclusiva | Igual: inconclusiva |
| 24 | Extraiu Hot 60i (rótulo: modelo inconclusivo) e aceitou: erro | Igual: erro |
| 25 | Extraiu 256 GB (rótulo: não informado) e aceitou: erro | Armazenamento não informado: acerto |
| 29 | Acerto | Não extraiu o modelo; decisão certa |
| 35 | Acerto | Extraiu “iphone 16e a3212” como modelo; decisão certa |
| 36 | Tratou como acessório; decisão errada | Não extraiu o modelo; “outro modelo”: erro |
| 38 | Acerto | “Samsung A37” sem “Galaxy” virou outro modelo: erro |
| 39 | Extraiu 256 GB (rótulo: não informado) e aceitou: erro | Acerto |
| 41 | Aceitou; o rótulo exclui (rede não informada): erro | Igual: erro |
| 45 | Aceitou; o rótulo exclui (rede não informada): erro | “Outro modelo”; decisão certa |
| 48 | Tratou como acessório; decisão certa | Não extraiu o modelo; decisão certa |

**Bateria de 20 buscas, 14/11/2026, das 05:37 às 06:06.** Versão publicada com as regras como método principal (app.py iniciado por 096fc36d375f), todas com coleta nova. O tempo foi medido no navegador, do clique em “Buscar” até o fim da página, com a lista de descartadas exibida e o carregamento encerrado. Na coluna Faixa, o número entre parênteses é quantas ofertas equivalentes com Pix ou à vista o app encontrou. “À parte” são as ofertas exibidas fora da faixa por pagamento não informado.

| # | Busca | Tempo | Faixa | Ofertas na faixa | Observação |
| --- | --- | --- | --- | --- | --- |
| 1 | galaxy a07 128gb | 13,4 s | Sim | 3 (KaBuM!) | 1 à parte (Shopee) |
| 2 | galaxi a17 128gb | 18,1 s | Não (2) | 2 (KaBuM!, Gazin) | Grafia corrigida; 11 à parte (Shopee, Mercado Livre) |
| 3 | galaxy a16 128gb | 11,9 s | Não (1) | 1 (KaBuM!) | 1 à parte (Novo Mundo) |
| 4 | galaxy a36 5g 128gb | 11,5 s | Não (2) | 2 (KaBuM!) | Compare Livre sem resposta |
| 5 | galaxy a14 128gb usado | 10,7 s | Não (0) | 0 | Falha das regras: “Samsung A14” sem “Galaxy”; Compare Livre sem resposta |
| 6 | motorolla g06 128gb | 17,5 s | Sim | 4 (KaBuM!, Gazin) | Grafia corrigida; 15 à parte |
| 7 | moto g17 256gb | 22,5 s | Sim | 4 (KaBuM!, Gazin) | 7 à parte |
| 8 | moto g35 256gb | 11,7 s | Não (0) | 0 | Falha das regras: anúncios “Motorola G35 5G” sem “Moto” viraram outro modelo; 4 à parte |
| 9 | moto g47 128gb | 11,5 s | Sim | 5 (KaBuM!, Gazin) | 9 à parte |
| 10 | moto e15 64gb | 11,9 s | Não (2) | 2 (KaBuM!) | Compare Livre sem resposta |
| 11 | xiaome redmi 15c 256gb | 12,2 s | Sim | 4 (KaBuM!) | Grafia corrigida; 3 à parte |
| 12 | redmi 15 256gb | 11,7 s | Sim | 10 (KaBuM!) | Compare Livre sem resposta |
| 13 | poco c85 128gb | 10,8 s | Sim | 8 (KaBuM!) | Compare Livre sem resposta |
| 14 | redmi note 15 256gb | 10,8 s | Não (0) | 0 | Nenhum título confirma 4G (17 são 5G, 7 sem rede); Compare Livre sem resposta |
| 15 | oppo a6x 128gb | 10,8 s | Sim | 4 (KaBuM!, Gazin) | 1 à parte (Novo Mundo); Compare Livre sem resposta |
| 16 | iphone 16e 128gb | 10,9 s | Não (0) | 0 | Falha: “4G (comum)” marcado para modelo só 5G; com 5G, 1 oferta; Compare Livre sem resposta |
| 17 | epone 16 128gb | 15,6 s | Não (0) | 0 | Grafia corrigida; mesma falha da 16 (com 5G, 2 ofertas); Compare Livre sem resposta |
| 18 | iphone 17 pro max 256gb | 10,8 s | Sim | 5 (KaBuM!) | Compare Livre sem resposta |
| 19 | iphone 13 128gb usado | 10,6 s | Sim | 17 (KaBuM!) | Compare Livre sem resposta |
| 20 | iphone 14 128gb recondicionado | 10,6 s | Não (0) | 0 | Sem oferta esperada; o app não misturou usados nem novos; Compare Livre sem resposta |

**Conferência das ofertas, 14/11/2026, das 06:07 às 06:17.** Feita pelo Claude, a pedido do Kevin, nas páginas das lojas, para as 71 ofertas das tabelas de ofertas equivalentes: 66 da KaBuM!, lidas nos dados da página de cada produto, e 5 da Gazin, no texto da página.

- Preço: 71 de 71 iguais ao exibido, no Pix ou à vista no Pix, todas disponíveis.
- Produto: 70 equivalentes e 1 inconclusiva, o OPPO A6x vendido pela Magalu na KaBuM! (código 1000528), cuja página não informa a rede.
- Rede: nas buscas 12, 13 e 15, os títulos não diziam a rede, e a ficha técnica confirmou 4G. Na KaBuM! 677921 (Galaxy A16), título, descrição e código SM-A165M dizem 4G, mas a lista de itens inclusos cita “Galaxy A16 5G”. Ficou equivalente pelo código.

| Medida | Resultado | Meta |
| --- | --- | --- |
| Cobertura | 5 de 20 buscas (2, 6, 7, 9 e 15, todas com KaBuM! e Gazin) | 18 de 20: não atingida |
| Faixa gerada | 10 de 20 (1, 6, 7, 9, 11, 12, 13, 15, 18 e 19) | Informada |
| Equivalência | 70 de 71 (98,6%), só nas ofertas das tabelas da faixa | Pelo menos 95%: atingida |
| Tempo de resposta | 16 de 20 em até 15 s; mediana 11,6 s, máximo 22,5 s (acima de 15 s: 2, 6, 7 e 17) | 18 de 20: não atingida |

Falhas encontradas na bateria. Nenhuma foi corrigida, para não mudar a versão avaliada:

- O Compare Livre não respondeu em 12 das 20 buscas (4, 5, 10 e 12 a 20). Sem ele, quase todas as ofertas vieram dos vendedores da KaBuM!, o que derrubou a cobertura. Nessas buscas o tempo fica perto de 10,7 s, que é o limite de espera dessa fonte.
- Para modelos que só existem em 5G (iPhone 16e e iPhone 16), o app mostrou a opção “4G (comum)” já marcada e não gerou faixa. Com 5G marcado, a regra estrita deixa de fora os anúncios sem “5G” no título.
- Anúncios “Motorola G35 5G” viraram “outro modelo” por não trazerem “Moto”; o “5G” no título também separava o modelo.
- “Samsung A14” sem a palavra Galaxy virou “outro modelo” (busca 5), o mesmo erro do nº 38 na avaliação.
- Regra estrita de rede: quando a escolha 4G/5G aparece, os títulos sem a rede ficam fora mesmo que a ficha confirme (buscas 2, 3 e 14). É o comportamento definido, mas reduz a faixa.

Desvios do protocolo na bateria:

- A conferência foi feita pelo Claude, não por uma pessoa. Precisa de revisão humana, como os rótulos.
- Não há captura de tela de cada oferta. Ficaram a URL, a data e a hora e os dados lidos na página.
- As 52 ofertas exibidas à parte, com pagamento não informado (Shopee e Mercado Livre pelo Compare Livre, e Novo Mundo), não foram conferidas uma a uma. A equivalência cobre só as 71 ofertas das tabelas da faixa.

**Depois da bateria, 14/11/2026.** O commit 202e772 (app.py iniciado por db1ba952b6ba) tirou da página de avaliação o botão de baixar o resultado em arquivo, e o commit bf57a4a (app.py iniciado por 5822fe4f5f3b) escondeu o ícone de baixar da barra das tabelas dessa página. Os resultados continuam nas tabelas da própria página. A busca, a extração, a decisão e o prompt não mudaram, e o teste da página de avaliação com os 50 títulos rodou até o fim sem erro.

**Correções depois da bateria, 14/11/2026 (código f43279f1b93f).** Pedidas pelo Kevin depois dos resultados. Os resultados registrados acima continuam valendo para as versões em que foram obtidos.

- Escolha de rede: anúncio sem rede no título deixou de contar como versão 4G. A opção 4G/5G só aparece quando o modelo tem as duas versões, conferidas no fabricante ou escritas nos títulos, e começa em 4G. Modelo de uma versão só, como todo iPhone a partir do 12, o Galaxy A36 e o Moto G35, abre sem a opção, e os anúncios sem rede no título entram como o mesmo aparelho. As versões dos 20 modelos da bateria vêm da tabela do passo 5.
- Nomes: “Galaxy” e “Moto” podem faltar na busca ou no título. “Samsung A14” identifica o Galaxy A14, e “Motorola G35”, o Moto G35.
- A página de avaliação mostra, ao abrir, os resultados registrados da avaliação e da bateria, com data, versão, erros e o aviso de que rótulos e conferência foram feitos por IA. Uma execução nova aparece à parte e não substitui os registros.
- Na avaliação, a decisão passou a seguir como a tela de resultado abre: versão única ou opção 4G/5G começando em 4G.
- O protocolo ganhou um link público, que abre sem login: https://faixa-certa.streamlit.app/?protocolo=1. É uma cópia publicada a partir deste documento.
