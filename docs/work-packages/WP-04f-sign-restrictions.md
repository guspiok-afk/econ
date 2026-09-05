# WP-04f — O VAR com restrições de sinal

| Campo | Valor |
|---|---|
| Estado | pronto |
| Executor sugerido | `agent:jules` |
| Branch | `wp/04f-sign-restrictions` |
| Depende de | WP-04d (mesclado) |
| Esforço estimado | ~6 h |

## Por que este pacote existe

O VAR recursivo e as projeções locais colocam a inflação **subindo** depois de um aperto
monetário, na mesma amostra. É o price puzzle, e os dois pacotes anteriores foram escritos para
preservá-lo em vez de escondê-lo — porque ele é o argumento deste.

A identificação recursiva ordena as variáveis e aceita o que sair. As restrições de sinal fazem o
contrário: **recusam qualquer identificação que não se comporte como política monetária.**

## O método

Sobre a mesma forma reduzida do WP-04d:

1. Fatoração de Cholesky da matriz de covariância, `P`.
2. Sorteia uma matriz ortogonal `Q` (decomposição QR de uma matriz gaussiana).
3. O candidato a impacto estrutural é `A = P · Q`; cada coluna, com os dois sinais, é um choque
   candidato.
4. **Aceita** se, do horizonte 0 até `restrict_through`, o juro sobe, o produto cai e a inflação
   cai.
5. O conjunto identificado é o de todos os sorteios aceitos: mediana e bandas de percentil.

## A armadilha que este pacote precisa evitar, e que os testes cobram

**Nos horizontes em que o sinal é imposto, encontrá-lo não prova nada** — ele foi suposto. Um
teste que só olhasse a janela restrita estaria conferindo a aritmética do código, não o dado.

A afirmação informativa é que a inflação **continua negativa muito além** do horizonte restrito,
onde nada a força. É o que faz a identificação valer o trabalho.

E o resultado é **um conjunto, não um ponto**. Restrições de sinal identificam uma região;
publicar a mediana sem a banda transforma uma admissão de ignorância numa estimativa falsa. A
tabela devolve `median`, `low` e `high`, e o teste recusa banda degenerada.

## Contrato

`src/econmodels/sign_restrictions.py`

```python
@register
class SignRestrictedVAR:
    model_id = "var_sign"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        lags: int = 4,
        horizon: int = 20,
        restrict_through: int = 3,
        draws: int = 2000,
        signs: dict[str, int] | None = None,   # padrão: policy +1, output -1, inflation -1
        bands: tuple[float, float] = (16.0, 84.0),
    ) -> None: ...

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

| tabela | colunas |
|---|---|
| `irf` | `horizon`, `response`, `median`, `low`, `high` |
| `diagnostics` | `metric`, `value` — `identification`, `restrict_through`, `draws`, `accepted`, `acceptance_rate`, `n_obs`, `lags`, `bands` |

Regras não negociáveis:

- **A aleatoriedade vem de `ctx.seed`, e de mais lugar nenhum.** `RunContext` já constrói um
  gerador; use-o. Duas execuções com a mesma semente devolvem o mesmo conjunto, e o teste cobra.
- **Zero sorteios aceitos é um erro, não uma tabela vazia.** Pedir um choque que sobe o juro e
  sobe o produto é uma pergunta legítima; a resposta é uma recusa com o motivo, não um resultado
  vazio que ninguém percebe.
- **`accepted` e `acceptance_rate` vão no diagnóstico.** Uma taxa de dois por cento é informação
  sobre quão exigentes as restrições são, e quem não a vê não consegue julgar a resposta.

## O que os dados dizem, para você saber quando acertou

`us_quarterly_var.csv`, 1961T1 a 2019T4, quatro defasagens, restrições dos horizontes 0 a 3, dois
mil sorteios:

```
aceitos 249 de 12.000 combinações  |  taxa 2,1%
```

Mediana do conjunto identificado:

| horizonte | inflação | produto | juro |
|---:|---:|---:|---:|
| 0 | −0,3075 | −0,2298 | +0,4371 |
| 2 | −0,2069 | **−0,3411** | +0,1848 |
| 4 | −0,1427 | −0,2902 | +0,1194 |
| 8 | −0,1648 | −0,2613 | +0,0055 |
| 12 | −0,1346 | −0,2162 | −0,0325 |
| 20 | −0,0672 | −0,1432 | −0,0486 |

**O máximo da inflação entre h=1 e h=4 é −0,1427, contra +0,3779 do Cholesky.** O price puzzle
desaparece — e, o que importa, **continua ausente em h=8, 12 e 20**, onde nada o proíbe.

O vale do produto fica mais raso e muito mais cedo: −0,34 em h=2 contra −0,46 em h=14.

## Testes de aceitação

`tests/test_sign_restrictions.py` — dezesseis testes, em cinco grupos: o resultado é um conjunto,
o que foi imposto (marcado como aritmética e não como achado), o que **não** foi imposto,
a comparação direta contra a identificação recursiva, e reprodutibilidade e recusas.

## Arquivos que você pode mudar

`src/econmodels/sign_restrictions.py` (novo) e a seção Resultado deste arquivo. Nenhuma
dependência nova.

## Definição de pronto

- [ ] `uv run pytest -q` verde; ruff limpo
- [ ] Só os arquivos listados mudaram
- [ ] Uma execução no **Brasil** colada na seção Resultado, com a taxa de aceitação — lá o VAR
      recursivo dá um vale de −0,93 em quatro trimestres, e vale ver o que sobra sob restrição

Se um teste parecer errado, diga no pull request em vez de mudá-lo.

## Resultado

(preenchido pelo executor)
