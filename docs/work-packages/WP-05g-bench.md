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

## Como rodar, e o que foi feito para reduzir o risco

```
uv run --with torch --with chronos-forecasting python tools/bench_nowcast.py
```

**Ambiente efêmero, não extra do projeto.** A primeira versão declarava `bench` em
`optional-dependencies`, e o `uv sync --extra bench` instalou torch e mais dezoito pacotes no
mesmo `.venv` que o agendador usa duas vezes por dia — exatamente o que o extra existia para
evitar. Um extra declarado é um convite a sincronizá-lo. Ele saiu do `pyproject`, o ambiente foi
restaurado, e um teste falha se torch voltar a ser dependência.

**O hash é conferido a cada execução, não uma vez à mão.** `carregar_chronos` recusa se o
`model.safetensors` não bater com o sha256 registrado. O arquivo mora fora do repositório, num
diretório gravável; conferir uma vez e confiar para sempre não é conferir.

**Nenhum código do modelo roda.** `safetensors` é o formato que existe para não executar nada ao
ser lido, ao contrário do pickle dos modelos antigos, e `trust_remote_code=False` é explícito no
código e verificado em teste.

O risco que **permanece** são as bibliotecas: `torch`, `chronos-forecasting` e as dependências
delas são código executável do PyPI que ninguém auditou. É maior que o dos pesos, e é por isso que
o ambiente efêmero importa mais que o hash.

Os pesos ficam em `%LOCALAPPDATA%\econbase\models\chronos-bolt-tiny`: peso de modelo não é
código e não entra no git. Cerca de quarenta segundos para os 32 trimestres, contando a montagem
do ambiente.

## O que travou o caminho, e o que isso revelou

O cliente Python não conseguia verificar o certificado de `huggingface.co`. Investigado até o
fim, e a explicação corrige o que a primeira versão desta seção afirmava:

**O Norton intercepta TLS nesta máquina — todo ele, não só o Hugging Face.** O certificado que
chega ao navegador para `huggingface.co` é emitido por `CN=Norton Web/Mail Shield Root, OU=generated
by Norton Antivirus for SSL/TLS scanning`, e o do `api.stlouisfed.org` também. O ambiente confirma:
`SSLKEYLOGFILE` aponta para um pipe do Norton e `NODE_EXTRA_CA_CERTS` para o PEM dele.

Os conectores deste projeto funcionam porque `sources/http.py` já resolve isso da forma certa:
`ssl.create_default_context()` usa o repositório do sistema, onde a raiz do Norton está, então a
verificação continua **ligada**. O `transformers` e o `huggingface_hub` usam o pacote `certifi`,
que não conhece essa raiz — daí a falha. Não é o domínio; é a biblioteca.

Consequências que valem estar escritas:

- Todo o tráfego HTTPS desta máquina passa **descriptografado** pelo antivírus. Isso inclui a
  chave do FRED, que viaja na query string. Não é comprometimento, é o modelo de ameaça real de
  quem roda um antivírus com inspeção de TLS.
- A conferência de hash que fiz nos pesos veio pelo mesmo canal interceptado. Ela protege contra
  corrupção e contra um CDN adulterado, e **não** contra o próprio interceptador.
- A correção limpa para as bibliotecas que usam `certifi` é apontar `SSL_CERT_FILE` para um
  pacote que inclua a raiz do Norton — nunca desabilitar verificação.

Contornado baixando os pesos pelo caminho que já verifica pelo repositório do sistema, e
**nenhuma verificação foi desabilitada**. Registrado como lacuna L09.
