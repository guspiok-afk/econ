# Operação diária

A base se atualiza sozinha. Este documento é o que fazer para ligá-la, e o que fazer quando
algo não vier.

## O que roda, e por quê nessa ordem

`scripts/daily.ps1` faz quatro coisas, nesta sequência:

1. **Coleta** (`econbase update --trigger scheduler`). É a única etapa demorada. Uma série que
   falha é registrada em `run_series` e não impede as outras.
2. **Cache de consultas** (`rebuild-db`). As visões do DuckDB nomeiam arquivos Parquet
   concretos, e a coleta acabou de substituí-los; sem esta etapa, uma consulta feita depois da
   coleta lê arquivos que já não estão no manifesto.
3. **Frescor** (`check`). Não interrompe nada: uma série atrasada é informação, não falha.
4. **Backup** (`backup.ps1`), por último, para copiar o estado já consolidado.

Nenhuma etapa cancela a seguinte. Uma fonte fora do ar não deve impedir o backup das outras 54
séries.

## Ligar o agendamento

Duas execuções por dia, pensadas para caírem depois das divulgações: o IBGE publica de manhã, e
os dados americanos saem às 8h30 de Nova York.

```powershell
schtasks /Create /TN "econbase-manha" /SC DAILY /ST 09:15 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\daily.ps1 -Backup 'G:\Meu Drive\econbase-backup'"
schtasks /Create /TN "econbase-tarde" /SC DAILY /ST 18:45 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\daily.ps1 -Backup 'G:\Meu Drive\econbase-backup'"
```

Ajuste o caminho do backup para a sua pasta sincronizada. Sem o parâmetro `-Backup`, a etapa é
pulada com um aviso no log.

Teste imediatamente, sem esperar o horário:

```powershell
schtasks /Run /TN "econbase-manha"
```

O laptop precisa estar ligado. Uma execução perdida não deixa buraco nos dados — a coleta
seguinte pega tudo que faltou —, mas aparece como ausência na tabela `runs`.

## Onde olhar quando algo não veio

**Primeiro, o log.** Um arquivo por execução, ao lado da pasta de dados:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\econbase\logs" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
```

Logs com mais de 60 dias são apagados sozinhos.

**Depois, o que a própria base registra.** Toda execução deixa rastro:

```powershell
cd C:\dev\econ
uv run python -c "
from econbase.store import Store; from econbase.settings import get_settings; from econbase import schemas
s = Store(get_settings().data_dir)
print(schemas.to_pandas(s.read('runs')).tail(5).to_string(index=False))
print(schemas.to_pandas(s.query(\"SELECT series_id, error FROM run_series WHERE error IS NOT NULL ORDER BY run_id DESC LIMIT 10\")).to_string(index=False))"
```

**Sintomas e causas:**

| o que você vê | provável causa |
|---|---|
| uma série com `error` na última execução | a fonte mudou, ou está fora do ar; o texto do erro diz qual |
| `check` acusa série parada | pode ser atraso real da fonte; compare `last_period` com o calendário de divulgação |
| a execução não aconteceu | máquina desligada no horário, ou a tarefa foi desativada |
| erro de arquivo em uso ao consultar | um notebook ou o DBeaver está com o `.duckdb` aberto; feche e rode `rebuild-db` |
| "another writer holds" | uma execução anterior travou; se nenhuma estiver rodando, apague `lake\.writer.lock` |

## Verificar o backup uma vez

Um backup nunca testado não é um backup. Faça isto uma vez, depois da primeira execução com
`-Backup`:

```powershell
$env:ECONBASE_DATA_DIR = "G:\Meu Drive\econbase-backup"
cd C:\dev\econ
uv run python -m econbase.cli rebuild-db
uv run python -m econbase.cli check
Remove-Item Env:\ECONBASE_DATA_DIR
```

Se as visões abrem e o `check` responde, o backup serve. Ele copia só arquivos fechados; o
banco vivo nunca vai para pasta sincronizada.

## Coletar à mão

```powershell
cd C:\dev\econ
uv run python -m econbase.cli update                      # tudo
uv run python -m econbase.cli update --source bcb_sgs     # uma fonte
uv run python -m econbase.cli update --series fred:GDPC1  # uma série
```

O `--trigger` fica em `manual` por padrão, o que separa na tabela `runs` o que você fez do que
o agendador fez.

## Quando a base aparece vazia

A base é dado derivado: se ela sumir, um `update` completo a reconstrói a partir das fontes em
alguns minutos. O que não volta é o histórico de vintages — os intervalos `realtime_start`
gravados nos dias em que os dados foram coletados. Para as séries brasileiras isso é
pseudo-vintage, a data da coleta; para o FRED os intervalos verdadeiros voltam junto com os
dados, porque a fonte os publica.

**O sinal de que a base estava vazia** é uma execução em que `rows_new` é igual a `rows_fetched`
em todas as séries, com `rows_revised` zero. Numa base já formada, uma coleta diária traz poucas
dezenas de linhas novas. Vale o mesmo para a tabela `runs`: uma linha só significa que aquela
execução foi a primeira.

```powershell
uv run python -m econbase.cli check
```

Em 04/09/2026 a base pareceu vazia por este teste. **A causa esta estabelecida e nao era perda de
dado:** a coleta rodava dentro do aplicativo e lia a copia privada, enquanto a base de verdade
seguia intacta e sendo atualizada pelo agendador. Antes de concluir qualquer coisa a partir de
uma base que parece vazia, confira em qual delas voce esta — a secao seguinte diz como.

## Duas bases, e como saber em qual você está

**Este é o achado que custou uma tarde e uma conclusão errada em 04/09/2026.**

Dentro do aplicativo de desktop — e portanto em tudo que o Claude Code executa — as escritas em
`%LOCALAPPDATA%` são **desviadas para uma cópia privada**, enquanto as leituras enxergam uma
visão mesclada em que a cópia privada ganha. O agendador escreve a pasta de verdade; o agente
dentro do aplicativo escreve a sombra. Cada lado lê a sua, e as duas parecem saudáveis.

**Nada declarativo revela isso.** A variável de ambiente traz o caminho real dos dois lados. O
processo não tem identidade de pacote para interrogar. E um arquivo-marcador é pior que inútil:
a *listagem* do diretório é mesclada mesmo quando a *escrita* não foi, então o arquivo escrito
por um processo aparece para o outro e sugere, erradamente, que há uma base só. Foi exatamente
assim que eu me convenci do contrário e escrevi aqui o oposto da verdade.

O único teste que separa as duas é escrever e reler por um endereço que o desvio não cobre:

```powershell
$local = Join-Path $env:LOCALAPPDATA 'econbase\data\lake\manifest.json'
$real  = '\\localhost\c$' + $local.Substring(2)
(Get-Content $local -Raw | ConvertFrom-Json).run_id
(Get-Content $real  -Raw | ConvertFrom-Json).run_id
```

**`run_id` diferentes significam duas bases.** A de verdade é a do caminho UNC, e é a que o
backup no Drive copia.

### O que o código faz a respeito

Toda transação de escrita roda a sonda antes de pegar o lock e **recusa** quando a escrita seria
desviada. O lock não pega esse caso: dois processos escrevendo pastas diferentes nunca disputam.

```
StoreError: writes to ...\econbase\data from this process are redirected into a
private copy that the scheduled task cannot see, so this would fork the base in two.
```

Se você vir isso, colete **do seu terminal**, não de dentro do aplicativo. Para forçar mesmo
assim — inspeção, teste —, use `ECONBASE_ALLOW_REDIRECTED_WRITES=1`, ciente de que o resultado
some para todo o resto do sistema.

### Se quiser as duas pontas na mesma base

Aponte `ECONBASE_DATA_DIR` para um caminho **fora** de `AppData\Local` — por exemplo
`C:\dados\econbase`. O desvio não alcança lá, e o `.env` do repositório principal é lido também
pelas árvores de trabalho, então basta escrever uma vez.
