# WP-04c — A curva de Phillips brasileira, na especificação do Banco Central

| Campo | Valor |
|---|---|
| Estado | pronto |
| Executor sugerido | `agent:jules` |
| Branch | `wp/04c-phillips` |
| Depende de | #28 (guarda de painel), #29 (séries do IPCA), #30 (especificações em arquivo) |
| Esforço estimado | ~10 h |

## O que torna este pacote diferente de todos os anteriores

**Não existe coeficiente a fixar.** Três resultados primários e independentes estabelecem que uma
regressão agregada de série temporal **não identifica** a inclinação da curva de Phillips:

- Mavroeidis, Plagborg-Møller e Stock (JEL 2014) estimaram mais de seiscentas mil especificações
  a priori razoáveis; as inclinações saem simetricamente dispersas em torno de zero, e a união
  dos conjuntos de confiança cobre o espaço de parâmetros inteiro.
- McLeay e Tenreyro provam que, sob política ótima, o mínimos quadrados converge para a
  inclinação da *regra de metas*, com sinal oposto ao verdadeiro.
- Hazell, Herreño, Nakamura e Steinsson (QJE 2022) reproduzem a patologia dentro do painel
  estadual americano: sem efeitos fixos de tempo, o sinal sai invertido.

**Consequência operacional: um coeficiente de folga com sinal errado não é evidência de defeito
no seu código.** É o resultado modal esperado. O que *é* defeito é sinal errado em todas as
células da grade — aí a convenção de sinal está invertida.

Por isso o teste de aceitação cobra **identidades, restrições, ordenamentos publicados e
desempenho preditivo**, e nunca um valor de inclinação. Fixar um seria consagrar ruído.

O documento completo com equações, coeficientes e fontes está em `docs/referencias/phillips.md`.

## Contrato

`src/econmodels/phillips.py`

```python
@register
class PhillipsCurve:
    model_id = "phillips"
    model_version = "1"

    def __init__(self, spec: Spec) -> None: ...
    @property
    def requires(self) -> Sequence[ConceptRequest]: ...  # derivado da especificação
    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

**O modelo é construído a partir de uma especificação**, não de argumentos soltos. As duas que
existem estão em `specs/phillips/`:

- `br_bcb_small_scale.yaml` — segue a equação (1) do boxe de junho de 2024, com preços livres na
  variável dependente e verticalidade imposta por construção
- `br_exploratoria_hp.yaml` — controle negativo, mantido de propósito

`requires` sai da especificação: um `ConceptRequest` por conceito que ela lê, com `freq="Q"`.
Isso faz a guarda de `econmodels.base` recusar um painel mensal antes de qualquer conta — que é
exatamente o defeito que custou seis pontos numa taxa prescrita no pacote do Taylor.

### As transformações são do modelo, não do catálogo

`annualised_quarterly`, `hp_gap` e `hamilton_gap` são implementadas **dentro de `fit`, sobre o
painel recebido**. Não vão para `econbase.transforms` e não são pré-computadas: um filtro rodado
sobre a amostra inteira e depois lido numa data passada é vazamento, e é o que os vintages
existem para impedir.

### A restrição de verticalidade

`{kind: sum_to_one, over: [...]}` é imposta **por construção**, subtraindo a expectativa dos dois
lados e de cada termo de inércia, não estimada e testada:

```
(π_t − πᵉ_t)  =  c  +  α₁·(π_{t−1} − πᵉ_t)  +  α₂·(π̄ᴵ − πᵉ_t)  +  β·Δe_{t−1}  +  γ·h_{t−1}  +  ε
```

O termo cambial fica **fora** da soma unitária, como na versão bayesiana do Banco Central. A
versão irrestrita também é estimada, e o teste de Wald da restrição vai para `diagnostics` como
diagnóstico — reportado, não exigido.

Tabelas devolvidas:

| tabela | colunas |
|---|---|
| `coefficients` | `name`, `estimate`, `std_error`, `t_stat` |
| `fitted` | `period`, `actual`, `fitted`, `residual` |
| `diagnostics` | `metric`, `value` — n_obs, r_squared, soma dos coeficientes de inflação, Wald da restrição, RMSE fora da amostra e o dos dois benchmarks |

## O que os dados dizem, para você saber quando acertou

Sobre `tests/fixtures/analysis/br_phillips_trimestral.csv`, 90 trimestres de 2004T1 a 2026T2,
com hiato do IBC-Br por Hodrick-Prescott e erros de Newey-West com quatro defasagens:

| dependente | repasse cambial | folga | R² |
|---|---:|---:|---:|
| preços livres | **+0,0433** | +0,0928 | 0,324 |
| IPCA cheio | **+0,0595** | −0,0205 | 0,346 |

Duas coisas a tirar daí. **O repasse é menor nos livres que na cheia**, que é a ordenação que o
Banco Central publica — os administrados repassam mais câmbio, não menos (+1,65 contra +0,72
pontos para uma depreciação permanente de 10%, boxe de junho de 2024). E **a folga sai com sinal
positivo nos livres**, que é o resultado modal descrito acima. Não conserte.

Fora da amostra, janela expansiva a partir de 2015T1, 46 trimestres:

| | RMSE | erro médio absoluto |
|---|---:|---:|
| modelo | **3,261** | 2,623 |
| "use o Focus e pronto" | 3,395 | 2,635 |
| passeio aleatório na inflação | 4,166 | 3,391 |

**A margem sobre o Focus é de 4%, e isso é ele próprio um achado**: a equação acrescenta pouco a
simplesmente ler a pesquisa de expectativas. O teste cobra que o modelo não seja materialmente
pior que o Focus e que bata o passeio aleatório com folga, e reporta a razão.

## Testes de aceitação

`tests/test_phillips.py` — `uv run pytest tests/test_phillips.py -q`

Em cinco grupos: construção dos dados (identidades exatas), a restrição valendo por construção,
os ordenamentos publicados, o desempenho preditivo, e as recusas. Nenhum fixa inclinação.

## Arquivos que você pode mudar

`src/econmodels/phillips.py` (novo) e a seção Resultado deste arquivo. Não
`src/econmodels/base.py`, não `src/econmodels/specs.py`, não `econbase`, não os testes, não as
especificações em `specs/`. Nenhuma dependência nova.

## Definição de pronto

- [ ] `uv run pytest -q` verde; `ruff check` e `ruff format --check` limpos
- [ ] Só os arquivos listados mudaram
- [ ] As **duas** especificações rodadas contra a base viva, com a tabela de coeficientes das
      duas colada na seção Resultado — é o caso de uso do pacote, não um extra
- [ ] O resultado salvo com `econmodels.results.save_result(..., spec=spec)`, e o `spec_id` e o
      `spec_hash` conferidos na tabela `model_runs`

Se um teste parecer errado, diga no pull request em vez de mudá-lo. Isso já pegou erro real de
especificação aqui, e mudar em silêncio esconderia o próximo.

## Resultado

### 1. `br_bcb_small_scale` (`spec_hash: 191b98eadd14351f`)

#### Coeficientes

| name | estimate | std_error | t_stat |
|---|---:|---:|---:|
| expectativa | 0.739522 | 0.263781 | 2.803545 |
| inercia_livres | 0.175321 | 0.072233 | 2.427161 |
| inercia_cheia | 0.085157 | 0.258706 | 0.329166 |
| repasse | 0.061462 | 0.044265 | 1.388502 |
| folga | 0.031715 | 0.067787 | 0.467859 |

#### Diagnósticos

| metric | value |
|---|---|
| n_obs | 83.0 |
| r_squared | 0.274823 |
| inflation_weights_sum | 1.0 |
| wald_verticality_pvalue | 0.001241 |
| n_oos | 47.0 |
| rmse_oos | 3.408148 |
| rmse_oos_expectations | 3.418776 |
| rmse_oos_random_walk | 4.194635 |
| spec_id | br_bcb_small_scale |
| spec_hash | 191b98eadd14351f |

---

### 2. `br_exploratoria_hp` (`spec_hash: c7a23c657a46b488`)

#### Coeficientes

| name | estimate | std_error | t_stat |
|---|---:|---:|---:|
| expectativa | 2.286661 | 0.459051 | 4.981277 |
| inercia | 0.046405 | 0.101104 | 0.458980 |
| folga | 0.832108 | 0.542133 | 1.534877 |

#### Diagnósticos

| metric | value |
|---|---|
| n_obs | 58.0 |
| r_squared | 0.385606 |
| inflation_weights_sum | 2.333065 |
| wald_verticality_pvalue | 0.001326 |
| n_oos | 46.0 |
| rmse_oos | 3.368307 |
| rmse_oos_expectations | 3.535433 |
| rmse_oos_random_walk | 4.634931 |
| spec_id | br_exploratoria_hp |
| spec_hash | c7a23c657a46b488 |
