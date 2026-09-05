# ADR-0007 — Uma especificação é um arquivo, não um commit

**Data:** 2026-09-05 · **Estado:** aceita

## Contexto

Um modelo pode ser estimado de várias maneiras, e **as maneiras são a análise**. Uma curva de
Phillips com os termos do Banco Central e outra sem repasse cambial são o mesmo código
respondendo perguntas diferentes; compará-las é o objetivo, não um desvio.

O desenho até aqui não sustentava isso. `model_runs` guardava os parâmetros como um blob JSON,
que serve para reproduzir **uma** execução e não para comparar **dez**: a pergunta "mostre todas
as execuções em que a folga foi o hiato do produto" exigia desempacotar JSON linha a linha.

Havia também um problema mais fundo. A literatura primária estabelece que uma regressão agregada
de série temporal **não identifica** a inclinação da curva de Phillips (Mavroeidis,
Plagborg-Møller e Stock, 2014; McLeay e Tenreyro; Hazell e outros, 2022). Se um único ponto não é
informativo, o entregável de uma análise deixa de ser um número e passa a ser **uma distribuição
sobre especificações** — o que só é possível se a especificação for um objeto de primeira classe.

## Decisão

**Uma variação é um arquivo YAML em `specs/<model_id>/`, validado por pydantic.** Acrescentar uma
variação não é um commit no modelo.

```yaml
spec_id: phillips_br_bcb_small_scale
model_id: phillips
entity: BR
provenance: {follows: "...", source_url: "...", departs: "..."}
dependent: {concept: cpi_free, transform: annualised_quarterly}
terms:
  - {name: expectativa, concept: inflation_expectations_12m, lags: [0]}
  - {name: folga, concept: activity_index, transform: hp_gap, lags: [1]}
restrictions:
  - {kind: sum_to_one, over: [expectativa, inercia]}
estimation: {method: ols, cov: newey_west, maxlags: 4}
```

`specs/` fica **fora de `catalog/`**, deliberadamente. O `catalog_hash` significa "quais dados
existiam" e vai gravado no manifesto de cada coleta; se uma especificação morasse lá, editar uma
equação mudaria o hash dos dados. São duas perguntas e merecem dois hashes.

`model_runs` ganha duas colunas: **`spec_id`** e **`spec_hash`**.

## Consequências

**A comparação vira consulta**, não reescrita:

```sql
select r.spec_id, o.column_name, o.value_num
from model_runs r join model_outputs o using (model_run_id)
where r.model_id = 'phillips' and o.table_name = 'coefficients'
```

**O hash é tão importante quanto o identificador.** Uma execução precisa continuar reprodutível
quando o arquivo for editado depois. Sem ele, editar `br_bcb_small_scale.yaml` faz toda execução
anterior **parecer** pertencer à especificação nova, e duas coisas diferentes passam a ser
comparadas como uma. É a mesma disciplina do `catalog_hash` no manifesto de dados, pelo mesmo
motivo.

**O `params` continua**, guardando a especificação resolvida, para que uma execução se reconstrua
mesmo que o arquivo desapareça.

**Uma especificação ruim pode ser mantida de propósito.** A exploratória que produziu hiato com
sinal invertido e soma de coeficientes 2,42 fica como controle negativo, e o teste de aceitação
cobra que ela reproduza o erro conhecido — que é o que documenta por que ela foi abandonada.

## Alternativas descartadas

**Especificação em código, num registro de dataclasses.** Não exige parser, e é o que a maioria
dos projetos faz. Descartada porque uma variação nova vira commit no modelo, a enumeração para
uma interface fica em código, e o diff de "o que mudou entre as duas" some.

**Uma tabela por modelo, larga.** Consulta melhor e migra pior: cada análise nova exigiria uma
migração, e as análises não concordam numa forma — coeficientes são indexados por nome, respostas
a impulso por horizonte, ajustados por período.

**Um motor de fórmulas genérico**, no espírito do `formula` do R. É outro projeto. Aqui cada
modelo valida os campos que entende, com pydantic, como o catálogo de séries já faz.

## Gatilho de reabertura

Se o formato precisar de estruturas que o YAML não expressa bem — não-linearidades, hierarquias
de blocos, priors bayesianos por parâmetro —, a decisão volta à mesa. O modelo do próprio Banco
Central é bayesiano de sistema e não caberia aqui; o que cabe é a equação única que a nossa
implementação estima.
