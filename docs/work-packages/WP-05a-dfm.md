# WP-05a — Fator dinâmico de frequência mista (nowcasting)

**Executor:** Claude (núcleo de correção: a guarda de vazamento e o backtest são o contrato)
**Depende de:** `econbase.vintages` (PR 41), `get_panel(mixed_freq=True)`
**Estado:** especificado com números medidos antes da implementação

## Objetivo

Estimar o crescimento do trimestre corrente antes que ele seja publicado, a partir de
indicadores mensais que chegam com defasagens diferentes. O painel de entrada é **irregular**:
em agosto de 2026 o emprego já saiu e a produção industrial não, e o PIB do trimestre não existe.

## O que já foi medido (antes de escrever o modelo)

Painel EUA, oito indicadores mensais, PIB trimestral, amostra desde 1992,
`DynamicFactorMQ(factors=1, factor_orders=1, idiosyncratic_ar1=True)`, backtest em tempo
pseudo-real 2018Q1–2025Q4, RMSE do crescimento trimestral em pontos percentuais:

| recorte | n | DFM | média incondicional |
|---|---|---|---|
| 2018–2025 completo | 32 | **0,818** | 2,065 |
| sem 2020 | 28 | 0,466 | 0,477 |
| 2018–2021 | 16 | 1,043 | 2,890 |
| 2022–2025 (calmo) | 16 | 0,501 | **0,423** |

E o erro em função de quanto do trimestre já é visível (2018–2020):

| as-of | RMSE |
|---|---|
| mês 1 | 8,261 |
| mês 2 | 1,157 |
| mês 3 | 1,166 |
| mês 4 | 1,124 |

> **Estes números substituem os primeiros que este documento publicou, que estavam
> contaminados.** Uma série trimestral fica na grade no mês em que o trimestre **começa** —
> 2018-01-01 carrega 2018Q1 — e o corte do backtest era por data de referência, então cortar em
> março de 2018 mantinha um número que o BEA só publica no fim de abril. O modelo recebia o alvo
> do trimestre que dizia estimar: `status` vinha `observed`, e o que era comparado contra a média
> era ajuste dentro da amostra. Achado por revisão adversarial delegada ao Antigravity, não por
> mim. Números antigos, para registro: 0,772 no recorte completo e 0,493 no calmo.

**Leitura honesta destes números, que precisa acompanhar qualquer citação do primeiro quadro:**
o ganho do fator dinâmico sobre a média incondicional vem do choque comum. Sobre a amostra
completa ele corta o erro em 60%; nos anos calmos desde 2022 ele perde por 18%. A conclusão
qualitativa sobreviveu à correção do vazamento, o que só se soube depois de remedir.

Sobre o perfil dentro do trimestre: a queda é quase toda do mês 1 para o mês 2 (8,26 para 1,16),
e depois disso o erro é plano. Não é acumulação suave de informação — é a diferença entre não
ter nenhum indicador do trimestre e ter dois meses deles.

O recorte "sem 2020" foi tentado primeiro e descartado: 2021 ainda é a recuperação, movida pelo
mesmo choque, e ele é instável demais para virar teste. **O teste de aceitação fixa a vitória na
amostra completa e a derrota no período calmo**, para que nenhum dos dois circule sozinho.

## Contrato

```python
@register
class DynamicFactorNowcast:
    model_id = "dfm_nowcast"
    model_version = "1"
    requires: Sequence[ConceptRequest]  # indicadores freq="M"; o alvo sem alegação de grade

    def __init__(
        self,
        entity: str,
        target: str = "gdp_real",
        indicators: Sequence[str] | None = None,
        factors: int = 1,
        factor_orders: int = 1,
        sample_start: str | None = None,
        maxiter: int = 100,
    ) -> None: ...

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

`panel` é o painel irregular de `get_panel(freq="M", mixed_freq=True)`: grade mensal completa,
coluna do alvo com onze buracos a cada doze meses, ponta desigual.

Tabelas do `Result`:

- `nowcast` — `period` (fim do trimestre), `value`, `n_visible` (observações mensais do
  trimestre presentes no painel), `is_observed` (o alvo já foi publicado para aquele trimestre)
  e `status`: `observed`, `pending` (o trimestre corrente — o nowcast de fato), `gap` (buraco no
  meio da série) ou `backfill` (anterior ao início da história do alvo). A coluna existe porque
  a execução ao vivo entregou três linhas com `is_observed=False`, duas delas do começo da
  amostra e uma com zero observações mensais atrás. Quem filtrasse por "não observado" — e foi
  o que o próprio script de verificação fez — leria três estimativas onde há uma.
- `factor` — `period`, `value` (o fator comum estimado, mensal)
- `loadings` — `variable`, `loading`, `transform`
- `diagnostics` — `llf`, `converged`, `factors`, `n_indicators`, `n_obs`, `ragged_edge`
  (quantos meses do fim do painel têm ao menos uma coluna vazia), `asof`, `vintage_kind`, `seed`

## Transformações por conceito

Estacionariedade é responsabilidade do modelo, não do chamador, e a escolha vai na tabela
`loadings` para ficar auditável.

| tipo | conceitos | transformação |
|---|---|---|
| nível | `employment`, `industrial_production`, `retail_sales`, `wages`, `gdp_real` | `100·Δlog` |
| taxa/índice de difusão | `unemployment_rate`, `capacity_utilization`, `consumer_confidence`, `labor_conditions_index` | primeira diferença |

Um conceito não classificado é recusado, com o nome dele na mensagem. Adivinhar a transformação
de uma série nova é a forma silenciosa de estimar um fator sobre uma variável não estacionária.

## Testes de aceitação

1. Existe nowcast para um trimestre sem nenhuma observação do alvo (a ponta irregular).
2. **Sem vazamento:** com `asof`, nenhuma linha usada tem período posterior ao que
   `published_at` permitiria. Esta é a razão de o pacote esperar a fase 5.
3. O erro cai entre o mês 1 e o mês 3 do trimestre na amostra completa.
4. Sobre 2018–2025 completo o RMSE fica abaixo do da média histórica com folga.
5. E nos anos calmos desde 2022 fica **acima** — afirmado, não escondido.
6. Exatamente um trimestre é `pending`, e ele é o último.
6. Mesma semente, mesmo resultado.
7. Recusas: painel não mensal, alvo ausente, conceito sem transformação declarada.

## Definição de pronto

`ruff` limpo, testes verdes, e uma execução ao vivo contra o store — não só contra a fixture —
conferida à mão. Todo PR de agente até agora chegou verde com um defeito silencioso, e foi a
verificação ao vivo que os pegou.

## O que a verificação ao vivo achou (e os testes não)

Mantido o padrão: todo pacote até aqui chegou verde com um defeito silencioso, e foi rodar
contra o store que os pegou. Desta vez foram dois.

**1. Três nowcasts onde há um.** A tabela `nowcast` marcava apenas `is_observed`, e o filtro de
Kalman também produz valores para os trimestres *anteriores* ao início da história do alvo.
A execução ao vivo devolveu 1996Q1, 1996Q2 e 2026Q3 na mesma coluna — e no Brasil os dois
primeiros tinham **zero** observações mensais atrás. Qualquer consumidor que filtrasse por "não
observado", que foi o que o próprio script de verificação fez e é o que uma interface faria,
leria três estimativas. Corrigido com a coluna `status` e um teste.

**2. O PIB brasileiro não é dessazonalizado.** Registrado como bloqueante **C1** em
`docs/QUESTIONS.md`, porque a correção muda `gdp_real@BR` para `taylor.py`, `var.py`,
`local_projections.py` e `sign_restrictions.py` — não é uma decisão deste pacote. O modelo agora
mede a sazonalidade do alvo e recusa acima de 25%, então o Brasil não roda o nowcast em vez de
rodar e devolver o calendário. Estados Unidos 0,031, Brasil 0,553.

## Execução ao vivo

Estados Unidos, 8 indicadores, painel (368, 9), ponta irregular de 1 mês, 120 trimestres:

- último publicado 2026Q2 = +0,625% no trimestre
- **nowcast 2026Q3 = +0,663% no trimestre (+2,65% anualizado)**, com 11 observações mensais
  visíveis e o PIB do trimestre ainda não publicado

Brasil: recusado pela guarda de sazonalidade, ver C1.
