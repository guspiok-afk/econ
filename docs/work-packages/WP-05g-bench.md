# WP-05g — O fator dinâmico contra um modelo de fundação

**Executor:** Claude
**Estado:** medido em 07/09/2026

## A pergunta

O WP-05a comparou o fator dinâmico com a **média incondicional** e nunca respondeu se o painel de
frequência mista paga a própria complexidade. Média incondicional é adversário fraco.

O Chronos é o adversário sério pelo motivo exato: ele é **univariado**. Vê a história do
crescimento trimestral do PIB e mais nada — nem emprego, nem produção industrial, nem varejo — e
não foi treinado em nada de economia. Se ele empatar com o fator dinâmico, o painel não está
comprando nada.

## O resultado

`amazon/chronos-bolt-tiny`, 8,65 milhões de parâmetros, em CPU. Backtest pseudo-tempo-real
2018Q1–2025Q4, corte no segundo mês de cada trimestre, PIB do trimestre corrente escondido pela
defasagem de publicação. Erro quadrático médio do crescimento trimestral, em pontos percentuais:

| recorte | n | DFM | Chronos | média | passeio |
|---|---|---|---|---|---|
| 2018–2025 completo | 32 | **0,818** | 2,670 | 2,065 | 3,300 |
| sem 2020 | 28 | **0,466** | 0,494 | 0,477 | 0,624 |
| 2022–2025 (calmo) | 16 | 0,501 | 0,459 | **0,423** | 0,716 |

## O que isso diz, e é desconfortável

**Na crise o painel paga.** O fator dinâmico corta o erro para menos de um terço do Chronos em
2018–2025. Faz sentido: um modelo que extrapola de história nunca viu 2020, e os indicadores
mensais viram — em abril de 2020 o emprego já dizia o que o PIB só confirmaria em julho.

**Fora dela, não.** No recorte sem 2020 os três ficam empatados dentro de três centésimos:
0,466, 0,494 e 0,477. Nos anos calmos o fator dinâmico é o **pior** dos três, e a média
incondicional ganha.

Ou seja: um modelo de 8,65 milhões de parâmetros que nunca viu um indicador econômico faz tão bem
quanto o painel de oito séries mensais com tratamento de ponta irregular, sempre que a economia
não está em choque. Isso não invalida o fator dinâmico — a fase 5 existe para as viradas, e é
nelas que ele entrega. Mas coloca um preço no resto do tempo.

## Ressalvas que precisam acompanhar o quadro

- **Um modelo, o menor.** `chronos-bolt-tiny` é a variante mínima. `chronos-2`, `timesfm-3.0` ou
  `moirai-2.0` podem mudar o quadro, e nenhum foi testado.
- **Um país, um horizonte.** Estados Unidos, um trimestre à frente, no segundo mês. O Brasil não
  entra porque o nowcast dele está bloqueado pela lacuna C1.
- **Trinta e dois trimestres.** Diferença de três centésimos em n=28 não separa modelo nenhum.
- **O Chronos vê menos por desenho.** É o ponto da comparação, e não uma desvantagem a corrigir.

## Como rodar

```
uv run --extra bench --extra models python tools/bench_nowcast.py
```

Os pesos ficam em `%LOCALAPPDATA%\econbase\models\chronos-bolt-tiny` e não no repositório: peso de
modelo não é código. Dezenove segundos em CPU para os 32 trimestres.

## Uma coisa do ambiente que travou o caminho

O cliente Python não consegue verificar o certificado de `huggingface.co` — falha em
`CERTIFICATE_VERIFY_FAILED`, embora o `Invoke-WebRequest` do PowerShell, que usa o repositório de
certificados do Windows, funcione. Os conectores do FRED e do BCB usam `httpx` e não têm esse
problema, então é específico daquele domínio nesta máquina. Registrado como lacuna L09.
Contornado baixando os pesos pelo caminho que funciona; **nenhuma verificação foi desabilitada**.
