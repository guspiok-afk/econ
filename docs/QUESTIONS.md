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

## Bloqueantes

Nenhum por enquanto.
