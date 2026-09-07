# ADR-0008: o aplicativo é uma vista fina sobre a API de leitura

**Data:** 2026-09-06
**Estado:** aceita
**Decisor:** o mantenedor, em 06/09/2026: "a ideia é que seja um aplicativo, primeiramente para
meu uso próprio o quanto antes, mas que gostaria de deixar preparado pra caso queira expandir o
projeto e transformar num app vendável"

## Contexto

A fase 08 pode ser duas coisas muito diferentes. Uma página gerada — estática, versionada, aberta
do celular, como o painel que `tools/render_roadmap.py` já produz. Ou um aplicativo que roda
consultas ao vivo, filtra, reestima e compara especificações.

O pedido é o segundo, com dois horizontes: uso próprio agora, e a possibilidade de virar produto
depois. Os dois horizontes puxam em direções opostas, e é isso que esta decisão precisa resolver.

Uso próprio pede a coisa mais rápida que funcione, rodando na máquina onde o dado já está.
Produto pede autenticação, estado por usuário, hospedagem, e — a parte que ninguém lembra —
o direito de mostrar o dado a um terceiro.

## Decisão

**Streamlit agora, como vista fina; nenhuma lógica nova mora nele.**

Toda leitura passa por `econbase.api`; toda estimação passa por um modelo registrado em
`econmodels`. O aplicativo monta widgets, chama, e desenha. Se um cálculo aparecer dentro do
código do aplicativo, ele está no lugar errado — vira função de modelo com teste, e o aplicativo
volta a só chamar.

Essa regra é o que torna a troca possível. Streamlit é o caminho mais curto até uso próprio e é
uma base ruim para produto: o modelo de sessão reexecuta o script inteiro a cada interação, o
roteamento é rudimentar, e a hospedagem multiusuário não é o que ele foi feito para fazer.
Mantendo-o fino, trocá-lo é reescrever a vista — não o sistema.

**As costuras deixadas prontas, todas baratas hoje:**

| costura | por quê | gatilho para construir |
|---|---|---|
| Nenhum estado de usuário no caminho do dado | um usuário hoje, muitos depois | segundo usuário |
| `api.get` com assinatura fixa, sem expor caminho de arquivo | a mesma chamada serve uma vista local e um servidor | primeiro consumidor não-Python |
| Toda estimação atrás de `model_id` e especificação em arquivo | comparar variações é o pedido original, e é o que um produto vende | já vale |
| Resultado gravado com `git_sha`, `seed` e `vintage_kind` | reproduzir o que o usuário viu | primeiro backtest publicado |

## A restrição que decide o que o produto pode ser

**Trinta e três das setenta e três séries são `redistributable: false`.** FRED e NY Fed permitem
uso, não republicação. Isso não é detalhe de implementação: é o limite do que se pode vender.

Um aplicativo de uso próprio pode mostrar tudo, porque quem olha é quem coletou. Um aplicativo
vendável **não pode servir os valores dessas séries a um terceiro**. O que ele pode vender é o
que é derivado e nosso: decomposições, estimativas de modelo, hiatos, contribuições, nowcasts —
e as séries cuja licença permite redistribuição.

Por isso a flag `redistributable` já existe no catálogo desde a fase 01 e por isso a página de
conferência é local. A partir daqui ela ganha uma segunda função: **o aplicativo tem de saber
distinguir o que pode sair da máquina.** Uma vista que não faça essa distinção é uma vista que
funciona para uso próprio e não pode ser mostrada a mais ninguém — e descobrir isso depois de
construída é caro.

## Consequências

- A fase 08 começa por uma vista Streamlit fina, sem autenticação e sem estado de usuário.
- Nenhum cálculo novo entra no aplicativo. Todo número que ele mostra vem de função testada.
- Cada tela declara se depende de série não redistribuível. Um modo "só o que pode sair daqui"
  existe desde o começo, porque acrescentá-lo depois exige revisitar cada tela.
- Trocar Streamlit por outra vista continua sendo uma decisão aberta, e o gatilho é o segundo
  usuário — não a insatisfação com o Streamlit.

## Alternativas descartadas

**Página estática gerada, como o painel.** Barata e publicável, e não atende: o pedido é filtrar,
reestimar e comparar especificações, que exige execução.

**FastAPI mais um frontend agora.** É a forma certa para produto e é cara demais para um usuário.
O plano já registrava a API HTTP como adiada atrás de costura, com gatilho no primeiro consumidor
não-Python; nada mudou esse gatilho.

**Notebook.** Serve para explorar e não para voltar amanhã e reencontrar a mesma vista.
