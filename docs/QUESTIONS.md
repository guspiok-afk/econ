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

## Resolvidas

### B1. Curva de Phillips: qual especificação? — RESOLVIDA pela fonte

Existe especificação publicada e vigente: **Banco Central, Relatório de Inflação de junho de 2024,
boxe "Atualização dos modelos semiestruturais de pequeno porte", equação (1)**, com as modas da
posteriori e os intervalos de credibilidade. Confirmada como corrente pela nota de rodapé 5 do
boxe de repasse cambial do Relatório de Política Monetária de março de 2026.

```
pi_livres_t = a1L*pi_livres_{t-1} + a1I*(1/4)*soma(pi_ipca_{t-i})
            + (1 - a1L - a1I)*(pi_focus_t/4)
            + a2*commodities_em_reais_t + a3*cambio_{t-1} + a4*hiato_t + clima + erro
```

com `a1L = 0,24`, `a1I = 0,38`, expectativas `= 0,38`, `a2 = 0,023`, `a3 = 0,011`, `a4 = 0,120`.

Três coisas que mudam o pacote:

1. **A dependente é a inflação de preços livres**, não o IPCA cheio. Os monitorados, cerca de um
   quarto do índice, são projetados por vinte e quatro equações calibradas a partir de regra
   institucional — Brent, Itaipu indexada ao IPC americano, regra da ANS, teto CMED — e não
   respondem a hiato. Regredir o cheio contra folga mistura dois blocos e atenua por construção.
2. **A verticalidade é imposta, não estimada.** O peso das expectativas é escrito como
   `(1 - a1L - a1I)`. A soma de 2,42 que obtive na tentativa exploratória não era um achado, era
   uma equação mal posta.
3. **O câmbio entra duas vezes.** O termo de commodities é o IC-Br **em reais**, que já contém o
   câmbio, e por isso `a3 = 0,011` é apenas o resíduo cambial. Comparar um repasse cheio com esse
   número é o erro de leitura mais provável neste projeto — a referência certa para repasse cheio
   é o boxe de projeções locais de março de 2026, com cerca de 0,06 para os núcleos e 0,10 para o
   IPCA cheio em doze meses.

**E o achado que muda o teste de aceitação.** Três resultados primários e independentes mostram
que uma regressão agregada de série temporal **não identifica a inclinação**: Mavroeidis,
Plagborg-Moller e Stock (JEL 2014, mais de seiscentas mil especificações, estimativas
simetricamente dispersas em torno de zero); McLeay e Tenreyro (o MQO converge para a inclinação
da regra de metas, com sinal oposto ao verdadeiro); Hazell, Herreno, Nakamura e Steinsson (QJE
2022, sinal errado no painel estadual sem efeitos fixos de tempo).

Portanto **o teste nao fixa inclinacao**. Fixa identidades de construcao, a verticalidade valendo
por construcao, ordenamentos publicados — repasse menor nos nucleos que no cheio, executavel
hoje — e dominio preditivo sobre "use o Focus e pronto". Um coeficiente de folga com sinal errado
numa celula da grade e o resultado modal esperado, e nao evidencia de defeito; sinal errado em
**todas** as celulas e, porque indica convencao de sinal invertida.

O documento completo, com equacoes, fontes e URLs, esta em `docs/referencias/phillips.md`.

### B2. Sticky/flex CPI brasileiro — RESOLVIDA por decisao do mantenedor

Adotada a divisao **livres contra administrados do proprio Banco Central**. E observavel,
defensavel e reproduzivel, ao contrario de uma classificacao por frequencia de reajuste que
exigiria microdado que o Brasil nao publica.

**Consequencia que a decisao carrega: o indice muda de nome.** O resultado nao e um sticky-price
CPI no sentido do Fed de Atlanta, e sim uma decomposicao administrados contra livres. O pacote,
o `model_id` e o texto passam a chamar isso pelo nome certo. O sticky de verdade fica para quando
houver microdado, registrado como pergunta futura e nao como divida silenciosa.

**Conveniencia**: as duas decisoes pedem as mesmas series. `bcb_sgs:11428` (livres) e
`bcb_sgs:4449` (administrados) servem de dependente para a curva de Phillips e de insumo para a
decomposicao. Verifiquei na API: ambas existem e comecam em **janeiro de 1991**, cobrindo a
amostra estimavel inteira. Junto com elas vale coletar `10844` (servicos) e `4447`
(comercializaveis), que habilitam os ordenamentos setoriais do teste.

---

## Bloqueantes

Estes eu não decido sozinho porque a escolha é sua, de economista, e muda o trabalho.

Nenhum por enquanto.

---

## Para conversar depois

Nada aqui bloqueia trabalho. São escolhas onde a sua leitura de economista muda o que eu construo,
e que ficam registradas para não virarem decisão minha por omissão.

### T1. Mercado de trabalho brasileiro — o que catalogar, e de onde

**O fato, medido em 06/09/2026:** o catálogo brasileiro tem **uma** série de mercado de trabalho,
a taxa de desocupação (`sidra:6381/4099`, desde mar/2012). Os conceitos `employment`, `wages` e
`labor_conditions_index` existem em `concepts.yaml` e nenhuma série brasileira os carrega. Isso
bloqueia o LMCI-BR (marco M045, lacuna L05) e limita qualquer modelo que queira folga no mercado
de trabalho em vez de hiato do produto — inclusive uma Phillips com desemprego no lugar do hiato.

**O que existe para catalogar, e o problema de cada um:**

- **PNAD Contínua** (SIDRA): população ocupada, taxa de participação, rendimento médio real
  habitual, horas habitualmente trabalhadas, subutilização. É a fonte certa conceitualmente e
  **começa em 2012**. Treze anos de amostra mensal em trimestre móvel: dá para um índice, não dá
  para estimar relação estrutural com uma recessão só (2015-16) mais a pandemia.
- **CAGED** (Ministério do Trabalho): admissões, desligamentos e saldo, mensal, desde os anos
  noventa. Cobre só o emprego **formal celetista** — cerca de metade da ocupação brasileira — e
  tem uma **quebra metodológica em 2020** com o Novo CAGED, que mudou a captação e o prazo de
  declaração. Emendar as duas séries sem tratar a quebra produz um salto que parece economia.
- **PME** (a antiga pesquisa mensal de emprego, seis regiões metropolitanas): cobre 2002-2016 e
  encerrou. Serve para estender a série para trás ao custo de mudar o conceito no meio.

**As três perguntas que preciso que você responda, e não são técnicas:**

1. Vale um LMCI-BR sobre treze anos, ou a amostra curta o torna um exercício decorativo? A minha
   inclinação é que vale como acompanhamento e não como insumo de modelo estrutural — mas quem
   decide o que é decorativo aqui é você.
2. Emendar PME com PNAD Contínua para ganhar dez anos, ou recusar a emenda? Emendar séries de
   conceito diferente é o tipo de decisão que fica invisível seis meses depois.
3. O CAGED entra apesar da quebra de 2020, e com que tratamento — série partida em duas, ajuste
   estimado, ou só o pós-2020?

**Enquanto não se decide, nada está errado em silêncio:** o M045 está marcado como bloqueado e o
motivo está escrito na L05. E há um aviso que vale repetir: sete de catorze títulos adicionados
numa leva anterior estavam errados na primeira tentativa. Tabela e variável do SIDRA vão ser
confirmadas antes de qualquer entrada nova, e não adivinhadas.
