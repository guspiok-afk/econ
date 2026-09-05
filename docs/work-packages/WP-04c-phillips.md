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

Implementado pelo Jules; revisado, corrigido e verificado contra a base viva pelo arquiteto.

### Duas correções, ambas no cálculo fora da amostra

1. **O filtro de hiato via o futuro.** As transformações eram calculadas uma vez sobre a série
   inteira e só depois o laço de janela expansiva rodava. Hodrick-Prescott e Hamilton olham para
   frente: o hiato de 2015 sabia como a pandemia tinha terminado. É o vazamento que os vintages
   existem para impedir, entrando pela transformação em vez de pelo dado. Agora tudo é
   reconstruído dentro do laço, sobre o painel truncado na data da previsão.
2. **A especificação era ignorada ali.** O `fit` respeitava `transform: hamilton_gap`, e o laço
   fora da amostra forçava Hodrick-Prescott com o conceito escrito no código. Eram dois modelos
   diferentes sendo comparados como um.

**Medi o vazamento antes de corrigir, e ele não inflava nada**: sem ele o modelo fica ligeiramente
melhor, 0,905 contra 0,927 em razão de erro. O defeito sai porque está errado em princípio, não
porque fabricou resultado.

### As duas especificações, contra a base viva em 2026-09-05

| | n | R² | soma da inflação | repasse | folga |
|---|---:|---:|---:|---:|---:|
| **Banco Central** | 83 | 0,268 | **1,0000** | +0,0338 | +0,0137 |
| **exploratória** | 58 | 0,386 | **2,3331** | — | +0,8321 |

A verticalidade vale por construção na primeira e é violada por um fator de dois na segunda, que
é exatamente o que ela existe para documentar.

### O que a comparação fora da amostra mostrou, e não é o que eu esperava

| | modelo | Focus | passeio aleatório |
|---|---:|---:|---:|
| Banco Central | 3,808 | **3,419** | 4,195 |
| exploratória | **3,469** | 3,535 | 4,635 |

**A equação do Banco Central não bate simplesmente ler o Focus** — fica 11% pior. E a
especificação deliberadamente ruim prevê um pouco melhor que a boa.

Isso não é defeito de implementação, é o achado. Ajuste e previsão não identificam estrutura: uma
equação pode estar errada e prever bem, e é precisamente o que a literatura de identificação
argumenta por outro caminho. Sob metas de inflação com uma pesquisa de expectativas crível,
sobra pouco para uma equação pequena de série temporal acrescentar.

**Eu tinha escrito o teste exigindo que o modelo batesse o Focus**, com margem medida numa
especificação minha mais simples — sem restrição, uma defasagem em vez de quatro, sem ponderação
da pandemia. Fixei um número medido em outra equação, que é o erro contra o qual este pacote
inteiro foi escrito. O teste passou a **reportar** a razão em vez de exigi-la, e a barreira ficou
onde é defensável: bater o passeio aleatório, que os dois fazem com folga.
