# Manual do mantenedor — projeto `econ`

Este manual diz o que **você** faz: instalar, configurar, publicar, despachar trabalho para os
agentes, acompanhar e recuperar. O que os agentes fazem está em `AGENTS.md`; a arquitetura e
as decisões estão em `docs/CONTRACT.md`, `docs/IDENTIFIERS.md` e `docs/adr/`.

Convenções deste manual: comandos em blocos são para o **PowerShell** do Windows, salvo
indicação. Caminhos fixos: repositório em `C:\dev\econ`; dados em
`%LOCALAPPDATA%\econbase\data` (nunca no OneDrive ou no Google Drive).

---

## 0. Checklist geral

| # | Tarefa | Quando | Feito |
|---|---|---|---|
| 1 | Verificar pré-requisitos (git, gh, uv, Python, Ollama) | agora | ☐ |
| 2 | `gh auth login` | agora | ☐ |
| 3 | Publicar o repositório no GitHub | agora | ☐ |
| 4 | Chave da API do FRED no `.env` | agora | ☐ |
| 5 | Confirmar pasta de dados fora de pastas sincronizadas | agora | ☐ |
| 6 | Ollama: servidor ligado e modelo baixado | esta semana | ☐ |
| 7 | Antigravity instalado e apontando para `C:\dev\econ` | esta semana | ☐ |
| 8 | Jules conectado ao repositório `econ` | após o item 3 | ☐ |
| 9 | Google Drive para Desktop instalado (destino do backup) | antes do WP-03 | ☐ |
| 10 | Tarefas agendadas: backup (após WP-01) e atualização (após WP-03) | conforme WPs | ☐ |
| 11 | Colab e NotebookLM (opcionais) | quando precisar | ☐ |

---

## 1. Pré-requisitos e verificação

Tudo abaixo já está instalado nesta máquina (verificado em 2026-09-03). Confirme:

```powershell
git --version        # 2.55
gh --version         # 2.98
uv --version         # 0.12.8
python --version     # 3.14.7
ollama --version     # 0.33.2 (cliente)
```

Se algum faltar:

- git: `winget install Git.Git`
- gh: `winget install GitHub.cli`
- uv: `winget install astral-sh.uv`
- Ollama: https://ollama.com/download

Não instale Python separadamente para o projeto: o `uv` usa o 3.14 existente e baixa outros
interpretadores se um pacote de trabalho pedir (`uv run --python 3.13 ...`).

---

## 2. GitHub: autenticar e publicar (uma vez)

### 2.1 Autenticar

```powershell
gh auth login
```

Respostas: `GitHub.com` → `HTTPS` → `Yes` (autenticar git com as credenciais do gh) →
`Login with a web browser`. Copie o código, abra o navegador, autorize.

Confirme: `gh auth status`.

### 2.2 Publicar o repositório

O repositório local já tem um commit na branch `main`. Publique a partir dela:

```powershell
cd C:\dev\econ
git checkout main
gh repo create econ --public --source=. --remote=origin --push
git checkout wp/01-foundation
```

Use `--private` no lugar de `--public` se preferir. Público dá minutos ilimitados de Actions e
combina com dados abertos; pode ser alterado depois em *Settings → General → Danger Zone*.

Depois disso, eu (Claude Code) faço o push das branches de trabalho e abro os PRs.

### 2.3 Rótulos de executor (eu crio, você só confere)

Assim que houver remoto, eu crio os rótulos `agent:claude`, `agent:jules`,
`agent:antigravity`, `agent:ollama` e `jules` (gatilho do Jules). Se quiser criar você mesmo:

```powershell
gh label create "agent:claude"      --color 5319E7 --description "Executor: Claude Code (arquiteto)"
gh label create "agent:jules"       --color 0E8A16 --description "Executor: Jules (assíncrono)"
gh label create "agent:antigravity" --color 1D76DB --description "Executor: Antigravity (interativo)"
gh label create "agent:ollama"      --color FBCA04 --description "Executor: modelo local (mecânico)"
gh label create "jules"             --color 0E8A16 --description "Gatilho do Jules"
```

### 2.4 Proteção da branch `main` (recomendado, após o primeiro PR)

Em *Settings → Branches → Add branch ruleset*: exigir pull request antes de merge e exigir que
o check `ci` passe. Isso impede que qualquer agente grave direto na `main`.

---

## 3. Segredos e pasta de dados

### 3.1 Chave da API do FRED (gratuita)

1. Acesse https://fred.stlouisfed.org/docs/api/api_key.html e clique em *Request API key*.
2. Crie a conta (ou entre), descreva o uso ("pesquisa econômica pessoal") e copie a chave.
3. Crie o `.env` a partir do exemplo e edite:

```powershell
cd C:\dev\econ
Copy-Item .env.example .env
notepad .env
```

Preencha `FRED_API_KEY=` com a chave. Salve. O arquivo `.env` está no `.gitignore` e nunca
sai da máquina. **Nunca cole a chave em prompts de agentes, issues ou PRs.**

### 3.2 Pasta de dados

O padrão é `%LOCALAPPDATA%\econbase\data` (normalmente `C:\Users\gus_o\AppData\Local\econbase\data`).
Não fica no OneDrive nem no Google Drive, o que é obrigatório: um arquivo DuckDB vivo em pasta
sincronizada corrompe.

Se quiser outro local (por exemplo um disco maior), defina no `.env`:

```
ECONBASE_DATA_DIR=D:\econbase\data
```

Após o WP-01, `uv run econbase init` cria a estrutura (`raw/`, `lake/`, `db/`) e imprime o
caminho em uso.

---

## 4. Ollama (modelo local para tarefas mecânicas)

### 4.1 Servidor e modelos

O aplicativo do Ollama precisa estar aberto (ícone na bandeja) ou rode `ollama serve` em um
terminal. Modelos já presentes: `qwen3:8b` (5 GB) e `gemma4:26b` (18 GB). Recomendado
adicionar o modelo de código:

```powershell
ollama pull qwen3-coder:30b
```

São ~19 GB. Com 8 GB de VRAM e 32 GB de RAM ele roda com parte na memória principal: mais
lento, porém mais capaz que o `qwen3:8b`. Teste:

```powershell
ollama run qwen3-coder:30b "Escreva uma função Python que inverta uma string, com docstring."
```

### 4.2 Como usar o modelo em código (ferramenta agente)

O Ollama sozinho só conversa; para editar arquivos e rodar testes é preciso um agente de código
que fale com ele. Duas opções, ambas gratuitas. **Ainda não validei nenhuma nesta máquina**;
o primeiro WP marcado `agent:ollama` servirá de teste e eu ajusto o manual.

Opção A, Aider (Python; usa um interpretador 3.12 gerenciado pelo uv):

```powershell
uv tool install --python 3.12 aider-chat
$env:OLLAMA_API_BASE = "http://127.0.0.1:11434"
cd C:\dev\econ
aider --model ollama_chat/qwen3-coder:30b --no-auto-commits --no-dirty-commits --read AGENTS.md --read docs/work-packages/WP-NN-slug.md
```

Opção B, OpenCode (https://opencode.ai): instalar conforme o site, configurar o provedor
`ollama` apontando para `http://127.0.0.1:11434` e o modelo `qwen3-coder:30b`.

Substitua `WP-NN-slug.md` pelo arquivo real do pacote; sem um WP pronto, teste o modelo com um comando somente leitura dentro do Aider, por exemplo `/ask Resuma a seção 2 do AGENTS.md em 5 linhas`, e saia com `/exit`. As opções `--no-auto-commits --no-dirty-commits` impedem o Aider de commitar sozinho: commits e PRs seguem o fluxo do WP.

Regras para tarefas Ollama: sempre pequenas, com teste pronto, em branch própria; você revisa o
diff antes de qualquer commit. Nunca núcleo, schema ou lógica de vintage.

---

## 5. Antigravity (Gemini, trabalho interativo)

1. Instale a partir de https://antigravity.google e entre com a conta Google que tem o AI Pro
   (limites maiores de Gemini 3.1 Pro).
2. *File → Open Folder* → `C:\dev\econ`. Ele lê `AGENTS.md` e `GEMINI.md` automaticamente.
3. Para trabalhar em um pacote, abra a *Manager view* e crie um agente com este prompt:

```
Read AGENTS.md and docs/work-packages/WP-NN-<slug>.md. Work only on branch wp/NN-<slug>
(create it from main if needed). Change only the files the WP allows; never touch the
protected files in AGENTS.md §3. Run `uv run pytest tests/test_<name>.py -q` until green,
then `uv run ruff check . && uv run ruff format --check .`. Commit with Conventional
Commits and open a pull request to main with the WP linked. Fill the WP "Result" section.
```

4. Até cinco agentes em paralelo, cada um em seu workspace. Revise os artefatos (plano,
   diff, saída de testes) antes de aprovar ações.

---

## 6. Jules (assíncrono via GitHub Issues)

Só depois do repositório publicado (item 2.2).

1. Acesse https://jules.google, entre com a mesma conta Google, clique em *Connect GitHub* e
   conceda acesso **somente** ao repositório `econ`.
2. Na configuração do repositório dentro do Jules, defina o script de preparação do ambiente
   (a VM dele é Linux):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen --group dev
```

3. Fluxo: eu transformo um WP em issue com o rótulo `agent:jules`; você (ou eu) adiciona o
   rótulo `jules` para disparar. O Jules propõe um plano: leia e aprove ou ajuste. Ele abre um
   PR; eu reviso; você faz o merge (ou autoriza que eu faça).

Os testes não usam rede e nenhuma chave, então o Jules não precisa do `.env`.

---

## 7. Backup e agendamento

### 7.1 Google Drive para Desktop (destino do backup)

Instale em https://www.google.com/drive/download/ e entre com a conta do AI Pro (5 TB). Crie a
pasta `econbase-backup` dentro de *Meu Drive*. Anote o caminho local (tipicamente
`G:\Meu Drive\econbase-backup`).

O backup copia apenas arquivos fechados (Parquet, `raw/*.gz`, `manifest.json`) e exclui
`*.duckdb*` e `_staging/`. Isso é seguro em pasta sincronizada; o banco vivo não é.

### 7.2 Tarefa agendada de backup (após o WP-01 entregar `scripts/backup.ps1`)

```powershell
schtasks /Create /TN "econbase-backup" /SC DAILY /ST 23:30 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\backup.ps1 -Target 'G:\Meu Drive\econbase-backup'"
```

Teste imediato: `schtasks /Run /TN "econbase-backup"`. Depois faça **um** teste de restauração:
copie a pasta do backup para um local temporário, aponte `ECONBASE_DATA_DIR` para ela e rode
`uv run econbase rebuild-db`. Se as views abrem, o backup serve.

### 7.3 Tarefa agendada de atualização (após o WP-03 entregar `scripts/daily.ps1`)

```powershell
schtasks /Create /TN "econbase-update-am" /SC DAILY /ST 09:15 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\daily.ps1"
schtasks /Create /TN "econbase-update-pm" /SC DAILY /ST 18:45 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\daily.ps1"
```

Horários pensados para depois das divulgações do IBGE (9h) e dos releases americanos (8h30 ET).
O laptop precisa estar ligado; uma execução perdida aparece como ausência na tabela `runs`.

---

## 8. Colab e NotebookLM (opcionais)

**Colab.** Em https://one.google.com/benefits confira se o seu tier do AI Pro lista unidades de
computação do Colab. Uso previsto: estimações pesadas (DSGE bayesiano, backtests do DFM) lendo o
backup no Drive. Em um notebook:

```python
from google.colab import drive

drive.mount("/content/drive")
import duckdb

con = duckdb.connect()
con.sql(
    "SELECT * FROM read_parquet('/content/drive/MyDrive/econbase-backup/lake/observations/*/*.parquet') LIMIT 5"
).show()
```

**NotebookLM.** Crie um caderno "Metodologias" e carregue os PDFs de referência para consulta
ao escrever pacotes de trabalho: documentação técnica do LMCI (Kansas City Fed), Staff Report
1017 do GSCPI (NY Fed), artigo do Sticky-Price CPI (Atlanta Fed), explicador do GDPNow.

---

## 9. Rotina de operação

### 9.1 O ciclo de um pacote de trabalho

1. Eu escrevo `docs/work-packages/WP-NN-<slug>.md` e os testes de aceitação (falhando).
2. Eu abro a issue com o rótulo do executor sugerido e link para o WP.
3. Despacho:
   - `agent:claude`: eu mesmo executo.
   - `agent:jules`: alguém adiciona o rótulo `jules`; você aprova o plano dele.
   - `agent:antigravity`: você cria o agente na Manager view com o prompt do item 5.
   - `agent:ollama`: você roda o Aider/OpenCode com o prompt do item 4.2.
4. O executor abre PR. O CI roda lint e testes.
5. Eu reviso o PR (comentários, pedidos de ajuste). Você decide o merge. Podemos combinar que eu
   faça o merge quando o CI estiver verde e a revisão aprovada.
6. Eu preencho ou confiro a seção "Result" do WP e fecho a issue.

### 9.2 Comandos do dia a dia (após o WP-01)

```powershell
cd C:\dev\econ
uv sync --frozen --group dev          # ambiente
uv run pytest -q                      # testes
uv run econbase list                  # séries do catálogo
uv run econbase check                 # frescor e lacunas (código de saída ≠ 0 se algo estiver parado)
uv run econbase update                # atualiza tudo (após WP-02; normalmente via Task Scheduler)
uv run econbase rebuild-db            # recria db\econbase.duckdb a partir do manifest
uv run econbase gc --days 7           # remove arquivos Parquet órfãos antigos
```

Consulta rápida aos dados, de qualquer ferramenta que fale DuckDB (Python, DBeaver, CLI):

```python
import duckdb

con = duckdb.connect(
    r"C:\Users\gus_o\AppData\Local\econbase\data\db\econbase.duckdb", read_only=True
)
con.sql(
    "SELECT * FROM obs_latest WHERE series_id = 'bcb_sgs:433' ORDER BY period DESC LIMIT 12"
).show()
con.sql("SELECT * FROM obs_asof(DATE '2025-06-30') WHERE series_id = 'fred:GDPC1'").show()
```

Abra sempre em modo somente leitura. O escritor único é o `econbase update`.

### 9.3 Quando algo quebra

| Sintoma | O que fazer |
|---|---|
| `econbase check` reporta série parada | Veja a coluna `error` em `run_series` da última execução; se a fonte mudou, abra uma issue `agent:jules` ou `agent:claude` |
| Erro de lock ao abrir o `.duckdb` | Feche notebooks/DBeaver; rode `uv run econbase rebuild-db` |
| Arquivo Parquet corrompido ou apagado | Restaure a partir do backup (7.2) e rode `rebuild-db`; `raw/` permite reprocessar |
| Suspeita de bug no diff de vintages | Não edite dados à mão; abra issue `agent:claude` com o `series_id`; o `raw/` é a prova |
| Execução agendada não rodou | `schtasks /Query /TN econbase-update-am /V` e o log em `%LOCALAPPDATA%\econbase\logs` (WP-03) |

---

## 10. Segurança e limites

- Chaves só no `.env` local. Jules e Antigravity nunca recebem chaves; os testes usam respostas
  gravadas.
- Jules com acesso apenas ao repositório `econ`. Revogue em GitHub → *Settings → Applications*
  se deixar de usar.
- Nenhum agente grava na `main`; tudo passa por PR e CI.
- Dados nunca entram no git; `.gitignore` cobre `data/`, `*.parquet`, `*.duckdb*`, `.env`.
- O `yfinance` e scrapers com termos de uso restritivos não entram no `econbase update`.

---

## 11. Marcos e decisões que ficam com você

| Marco | O que você decide/valida |
|---|---|
| WP-01 (fundação) | Aprovar o contrato de dados (`docs/CONTRACT.md`) e a estrutura; merge do PR |
| WP-02 (conectores) | Conferir o catálogo inicial (séries que interessam), licenças e flags de redistribuição |
| WP-03 (transformações, CLI, automação) | Criar as tarefas agendadas (7.3); validar o `daily.ps1` |
| WP-04+ (análises) | Validar resultados econômicos (Taylor vs Selic, Sticky-CPI vs FRED etc.) |
| Terceiro país | Decidir a estratégia de mapeamento por país (templates DBnomics) |
| Primeiro leitor remoto ou app | Decidir a publicação em object storage e a API |
| Domínio de ativos | Aprovar as tabelas `prices_daily`/`corporate_actions` e as fontes abertas |

---

## 12. Glossário

- **Vintage / bitemporal**: cada observação carrega o intervalo em que foi o valor vigente
  (`realtime_start`, `realtime_end`), permitindo perguntar "o que se sabia em tal data".
- **Manifest**: `lake/manifest.json`, lista dos arquivos Parquet vivos; troca atômica por
  execução.
- **Run**: uma execução do `econbase update`, identificada por `run_id`; tudo que ela gravou
  aponta para esse id.
- **WP (work package)**: unidade de trabalho com contrato, arquivos permitidos e testes de
  aceitação prontos; vira issue, branch e PR.
- **Conceito**: chave que as análises usam (`cpi_headline`), resolvida por país para um
  `series_id`.
- **Arquivo bruto (`raw/`)**: corpo HTTP original de cada coleta, comprimido e deduplicado por
  hash; prova e reprocessamento.
