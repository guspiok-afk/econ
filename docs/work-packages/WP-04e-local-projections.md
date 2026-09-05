# WP-04e — Respostas a impulso por projeção local

| Campo | Valor |
|---|---|
| Estado | pronto |
| Executor sugerido | `agent:jules` |
| Branch | `wp/04e-local-projections` |
| Depende de | WP-04d (mesclado) |
| Esforço estimado | ~5 h |

## Por que este pacote existe

O VAR já entrega respostas a impulso. A pergunta que ele não consegue responder sobre si mesmo é:
**quanto daquela figura é o dado e quanto é a estrutura que ele impõe a todos os horizontes de
uma vez?**

O estimador de Jordà roda uma regressão por horizonte e não impõe nada entre elas. Onde os dois
concordam, o achado é do dado; onde diferem, a diferença é a suposição do VAR. É por isso que os
resultados fixados aqui são **comparações**, e não níveis.

## A equação

Para cada horizonte `h`, uma regressão:

```
y_{t+h} − y_t  =  α_h  +  β_h · política_t  +  Σ_{l=1..p} γ_{h,l} · z_{t−l}  +  ε_{t,h}
```

`β_h` é a resposta no horizonte `h`. `z` são as três variáveis do sistema, com `p = 4`
defasagens, e a resposta é acumulada a partir do período do choque — o que faz `β_0 = 0` por
construção para produto e inflação.

**Erros de Newey-West com `maxlags >= h`.** Horizontes sucessivos compartilham observações por
construção do estimador, exatamente como as janelas sobrepostas da paridade descoberta. Errar
isto fabrica significância.

## Contrato

`src/econmodels/local_projections.py`

```python
@register
class LocalProjections:
    model_id = "local_projections"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        horizon: int = 20,
        lags: int = 4,
        shock: str = "policy",
        responses: tuple[str, ...] = ("inflation", "output", "policy"),
    ) -> None: ...

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

As três variáveis são construídas dentro do `fit`, como no VAR: `inflation` é a variação de
quatro trimestres do índice de preços em logaritmo vezes 100, `output` é 100 × log do PIB real,
`policy` é o juro como vem.

Tabelas devolvidas:

| tabela | colunas |
|---|---|
| `irf` | `horizon`, `response`, `value`, `std_error`, `ci_low`, `ci_high`, `n_obs` |
| `diagnostics` | `metric`, `value` — `horizon`, `lags`, `cov`, `regressions`, `n_obs_max` |

Regras não negociáveis:

- **O painel vem do `api.get_panel` e passa por `panel_for`.** Todo deslocamento aqui é por
  linha, e só é deslocamento por período num índice trimestral sem buracos.
- **`n_obs` por horizonte vai na tabela**, porque a amostra encolhe uma observação a cada
  horizonte e o leitor precisa ver isso.

## O que os dados dizem, para você saber quando acertou

`tests/fixtures/analysis/us_quarterly_var.csv`, 1961T1 a 2019T4, quatro defasagens de controle:

| horizonte | produto | inflação | juro |
|---:|---:|---:|---:|
| 1 | +0,0906 | +0,2640 | +0,2047 |
| 4 | −0,3455 | **+0,4861** | −0,0869 |
| 8 | −0,8844 | +0,1812 | −0,5225 |
| 10 | **−1,0156** | — | — |
| 12 | −0,9111 | −0,4392 | −0,9973 |
| 20 | −0,4062 | −0,4216 | −1,1658 |

Erro-padrão do produto: 0,064 em h=1 e 0,284 em h=16 — as bandas **alargam com o horizonte**,
que é o caráter do estimador e não um defeito.

**Duas coisas para comparar com o VAR**, e são o pacote inteiro:

1. **O price puzzle aparece aqui também**, com pico de +0,50 no primeiro ano contra +0,38 do VAR.
   Um estimador que não impõe nada entre horizontes encontra o mesmo na mesma amostra — então
   não é artefato da estrutura do VAR.
2. **O vale é mais fundo e mais cedo**: −1,02 em h=10 contra −0,46 em h=14. É o caráter
   documentado da projeção local, que segue a amostra de mais perto e paga em largura.

## Testes de aceitação

`tests/test_local_projections.py` — `uv run pytest tests/test_local_projections.py -q`

Dezesseis, em quatro grupos: a forma do estimador, a economia fixada, a comparação com o VAR — que
roda os dois no mesmo painel e exige que concordem em sinal — e as recusas.

## Arquivos que você pode mudar

`src/econmodels/local_projections.py` (novo) e a seção Resultado deste arquivo. Nenhuma
dependência nova.

## Definição de pronto

- [ ] `uv run pytest -q` verde; ruff limpo
- [ ] Só os arquivos listados mudaram
- [ ] Uma execução no **Brasil** colada na seção Resultado, com a comparação contra o VAR
      brasileiro do WP-04d — lá o vale chega em quatro trimestres contra dezessete nos Estados
      Unidos, e vale ver se a projeção local concorda

Se um teste parecer errado, diga no pull request em vez de mudá-lo.

## Resultado

(preenchido pelo executor)
