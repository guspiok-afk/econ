# econ — base de dados econômicos abertos (BR, US, expansível) + camada de análises

Base de séries econômicas construída só com dados abertos, com histórico de revisões
(vintages) desde o primeiro dia, pronta para alimentar modelos macro (Curva de Phillips,
Regra de Taylor, UIP/CIP, VAR/SVAR/BVAR, nowcasting por modelos de fatores dinâmicos,
índices tipo LMCI/GSCPI/Sticky-CPI, DSGE) e, no futuro, um aplicativo e projetos irmãos
(o primeiro: preços de ativos locais e globais).

**Estado:** passo 0 concluído (organização do repositório e instruções para agentes).
Código chega nos pacotes de trabalho WP-01 em diante.

## Como o repositório é organizado

- `AGENTS.md` — regras compartilhadas por todos os agentes de código (Claude Code,
  Antigravity, Jules, Ollama). Leia antes de qualquer alteração.
- `docs/work-packages/` — um arquivo por pacote de trabalho (WP); `TEMPLATE.md` é o modelo.
- `docs/CONTRACT.md`, `docs/IDENTIFIERS.md`, `docs/adr/` — contrato de dados, gramática de
  identificadores e registro de decisões (criados no WP-01).
- `src/econbase/` — camada de dados; `src/econmodels/` — análises (a partir do WP-01).
- `catalog/` — YAML declarativo de séries e conceitos por país.

## Regras que não mudam

1. Parquet é a verdade; o arquivo DuckDB é cache reconstruível.
2. Dados ficam fora do repositório e fora de pastas sincronizadas (OneDrive, Google Drive):
   `ECONBASE_DATA_DIR`, padrão `%LOCALAPPDATA%\econbase\data`.
3. Vintages bitemporais no padrão ALFRED (`realtime_start`, `realtime_end`).
4. Identificadores imutáveis: `series_id = "{fonte}:{id_nativo}"`.
5. Um único escritor (Task Scheduler local); GitHub Actions só roda testes.

## Configuração inicial

1. Copie `.env.example` para `.env` e preencha `FRED_API_KEY` (chave gratuita do FRED).
2. Ambiente Python com `uv` (a partir do WP-01): `uv sync --frozen`.
3. Publicar no GitHub (uma vez): `gh repo create econ --public --source=. --push`.

## Fluxo de trabalho

Pacote de trabalho → issue com rótulo do executor (`agent:claude`, `agent:jules`,
`agent:antigravity`, `agent:ollama`) → branch `wp/NN-<slug>` → PR para `main` → CI verde →
revisão e merge pelo arquiteto (Claude Code).

## Licença

MIT para o código. Cada série do catálogo carrega a licença e o flag de redistribuição da
fonte; séries não redistribuíveis ficam apenas no armazenamento local.
