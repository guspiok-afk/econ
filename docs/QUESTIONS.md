# Perguntas abertas

Coisas que eu decidi sozinho para não parar o trabalho, e que você pode reverter. Cada uma traz
o que eu supus e o que muda se você discordar. As que **bloqueiam** ficam no fim, marcadas.

O formato existe porque a alternativa — parar e perguntar — custa mais do que decidir com uma
suposição declarada. Nada aqui é irreversível.

---

## 1. `get_panel` não monta um painel de dois países numa chamada

**Onde apareceu:** ao verificar a paridade descoberta contra a base viva (WP-04a). O modelo
precisa de `fx_spot_usd@BR`, `policy_rate@BR` e `policy_rate@US`. `entities=['BR','US']` pede o
produto cartesiano e falha em `fx_spot_usd@US`, que nenhuma série carrega; `entity='BR'`
devolve nomes de conceito sem o sufixo do país, que é justamente o que os modelos resolvem.

**O que eu supus:** que `keys` deve aceitar tuplas `(conceito, país)` além de strings, mantendo
tudo o que já funciona. É retrocompatível e faz a frase "o painel vem do `api.get_panel`" — que
está escrita em todos os pacotes de análise — deixar de ser falsa.

**Se você discordar:** a alternativa é os modelos fazerem duas chamadas e juntarem, o que
funciona mas espalha a montagem do painel por cada análise, e é onde vazamento de `asof` entra
sem ninguém ver.

## 2. O índice do painel vivo são objetos `date`, e o das fixtures é `DatetimeIndex`

**Onde apareceu:** mesma verificação. Todas as fixtures de teste usam `parse_dates`, então os
modelos são validados contra um índice temporal de verdade e rodam, ao vivo, sobre um índice de
objetos comuns.

**Por que importa:** para a paridade não muda nada, porque ela desloca linhas. Para a regra de
Taylor muda: filtro Hodrick-Prescott, reamostragem e qualquer operação com calendário se
comportam diferente. É uma divergência entre o que o teste prova e o que a produção faz.

**O que eu supus:** que `get_panel` deve devolver `DatetimeIndex`. É o que as fixtures assumem e
o que qualquer biblioteca de séries temporais espera.

**Se você discordar:** dá para converter dentro de cada modelo, mas aí cada análise nova precisa
lembrar, e a que esquecer não falha — só fica sutilmente errada.

## 3. A agregação por composição não existe

**Onde apareceu:** ao descrever a arquitetura para você. `AGGREGATIONS` é
`("last", "mean", "sum", "eop")`, e `cpi_headline` usa `sum`.

**Por que importa:** somar variações percentuais mensais para chegar à do trimestre ou do ano é
aproximação. O certo é compor. Com 0,5% ao mês, doze meses somam 6,00% e compõem 6,17%; com a
inflação de 2002 o erro passa de meio ponto.

**O que eu supus:** acrescentar `compound` e trocar o padrão de todo conceito que é variação
percentual. O teste confere contra a série de doze meses que o próprio Banco Central publica.

## 4. Formato do armazenamento de resultados

**O que eu supus:** duas tabelas no mesmo lago — `model_runs` (identificação da execução:
`model_id`, `model_version`, `asof`, `seed`, `git_sha`, `catalog_hash`, parâmetros) e
`model_outputs` (longo: `run_id`, `table`, `period`, `name`, `value`). Longo em vez de largo
porque cada modelo devolve tabelas de formas diferentes, e largo obrigaria uma migração por
análise nova.

**Se você discordar:** a alternativa é uma tabela por modelo, que consulta melhor e migra pior.

## 5. Qual série de expectativas usar para os Estados Unidos (curva de Phillips)

**Onde vai aparecer:** WP-04c. Para o Brasil o Focus já está na base. Para os Estados Unidos o
catálogo não tem o SPF da Filadélfia.

**O que eu suponho:** usar `MICH` (expectativa de inflação da pesquisa da Universidade de
Michigan, mensal, já no FRED) e declarar a escolha no diagnóstico do modelo. O SPF é trimestral
e mais próximo do que a literatura usa, mas exige um conector novo.

**Se você discordar:** o SPF é um pacote de trabalho de umas 4 horas, e aí a curva americana
fica comparável à literatura sem ressalva.

---

## 6. Não existe série de expectativas de inflação para os Estados Unidos

**Onde apareceu:** ao preparar a curva de Phillips. O mapa de conceitos por país mostra
`inflation_expectations_12m` só para o Brasil, vindo do Focus. O catálogo americano não tem nem
o SPF da Filadélfia nem a pesquisa de Michigan.

**O que eu supus:** que a expectativa entra como `ConceptRequest(..., optional=True)` — o campo
já existe no contrato e nunca foi exercitado. O modelo roda na forma híbrida quando a série
está lá e na forma puramente retrospectiva quando não está, dizendo qual usou no diagnóstico.
Assim a curva roda nos dois países hoje, e melhora quando a série americana entrar.

**Se você discordar:** acrescentar `MICH` (Michigan, mensal, já no FRED) é meia hora; o SPF é um
conector novo de uma tarde.

## 7. `cpi_headline` não existe para os Estados Unidos

**Onde apareceu:** o mesmo mapa. O Brasil publica a variação mensal (`bcb_sgs:433`) e os Estados
Unidos publicam o índice (`fred:CPIAUCSL`). O conceito `cpi_headline_index` existe nos dois; o
`cpi_headline` só no Brasil.

**O que eu supus:** que todo modelo portátil pede `cpi_headline_index` e calcula a variação por
dentro, que é o que a regra de Taylor já faz. É mais robusto do que manter dois conceitos que
significam a mesma coisa em unidades diferentes.

**Se você discordar:** a alternativa é gravar `cpi_headline` para os Estados Unidos como série
derivada, o que exerceria o caminho de derivadas — mas duplica dado que já está na base.

---

## Bloqueantes

Estes eu não decido sozinho porque a escolha é sua, de economista, e muda o trabalho.

### B1. Curva de Phillips: qual especificação?

**Por que não decido:** experimentei duas e as duas são ruins, de maneiras que dizem algo.

Mensal, inflação em 12 meses, expectativa do Focus, desemprego em nível, 161 meses de 2013:

| | coef. | p |
|---|---:|---:|
| expectativa | 0,224 | 0,003 |
| inflação defasada | 0,912 | 0,000 |
| desemprego | +0,037 | 0,260 |

O R² de 0,96 é ilusão: regredir a inflação de doze meses contra ela mesma um mês antes é quase
uma identidade. O desemprego sai insignificante e com o sinal errado.

Trimestral, inflação anualizada do trimestre, hiato do desemprego por filtro HP, 57 trimestres:

| | coef. | p |
|---|---:|---:|
| expectativa | 2,386 | 0,000 |
| inflação defasada | 0,030 | 0,766 |
| hiato do desemprego | **+0,928** | 0,090 |

Aqui γ_f + γ_b = 2,42, o que viola a verticalidade de longo prazo, e o hiato do desemprego entra
com **sinal positivo** — mais desemprego, mais inflação.

**As escolhas que mudam o resultado, e que são suas:**

1. **Qual medida de folga.** Desemprego, hiato do produto, utilização da capacidade. A PNAD só
   começa em 2012, o que dá 57 trimestres — pouco para separar folga de choque.
2. **Qual inflação.** Cheia, núcleo (o catálogo tem três agora) ou preços livres. Para o Brasil
   os administrados são um argumento forte para não usar a cheia.
3. **Câmbio.** Uma curva de economia aberta sem repasse cambial é malespecificada, e o `fx_spot_usd@BR`
   está na base. Isso pode ser o que explica o sinal errado do hiato: 2015 e 2021 tiveram
   desemprego alto e inflação alta ao mesmo tempo, com o câmbio no meio.
4. **Impor γ_f + γ_b = 1** ou deixar a soma livre como diagnóstico.

**O que eu faria se você mandasse escolher:** núcleo por médias aparadas, hiato do produto pelo
IBC-Br, repasse cambial com quatro defasagens, soma restrita a 1, e o teste de aceitação
cobrando sinal e magnitude do repasse em vez de um número da folga. Mas essa é a análise em que
o julgamento vale mais que a implementação, e enfiar uma especificação ruim num teste de
aceitação a congela.

### B2. Sticky/flex CPI brasileiro: qual classificação de itens?

**Por que não decido:** o método do Fed de Atlanta separa os itens pela **frequência de reajuste
de preço**, medida em microdados. Para o Brasil não existe equivalente publicado, e a
classificação é a análise inteira: escolhida de um jeito, o índice mede rigidez; escolhida de
outro, mede só os administrados.

**As opções:** replicar a classificação americana por correspondência de itens da COICOP;
adotar uma classificação da literatura brasileira; ou usar a divisão do próprio Banco Central
entre livres e administrados, que é observável e defensável mas mede outra coisa.

**O que eu faria:** a terceira, chamando o resultado pelo nome certo — administrados contra
livres — e deixando o sticky de verdade para quando houver microdado. Mas isso muda o que o
índice significa, e o nome importa.
