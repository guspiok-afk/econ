# Recomendação: especificação, estimação e teste de aceitação de curvas de Phillips para Brasil e EUA

## Resumo em três frases

Para o Brasil, recomendo uma versão de equação única da curva de Phillips agregada do BCB (RI jun/2024), com **núcleo por médias aparadas com suavização** no lugar de preços livres — porque o catálogo não tem a decomposição livres/monitorados — e com o câmbio nominal entrando diretamente, porque não há IC-Br. Para os EUA, a equação tem de ser **outra**, e o catálogo americano está faltando o regressor mais importante de todos (expectativas), o que reduz a especificação defensável à forma de Ball–Mazumder com expectativas ancoradas absorvidas na constante. E, o ponto central: **a literatura primária estabelece que uma regressão agregada de série temporal não identifica a inclinação estrutural** — logo o teste de aceitação não deve fixar coeficiente nenhum; deve fixar identidades, restrições, sinais, ordenamentos e desempenho preditivo.

---

## 1. Brasil — equação recomendada

### 1.1 A equação

Frequência trimestral. Todas as taxas de inflação em **pontos percentuais, taxa trimestral não anualizada**, com ajuste sazonal.

**Forma estrutural (como se lê):**

```
π^N_t = c + α₁·π^N_{t−1}
          + α₂·(1/4)·Σ_{i=1..4} π^H_{t−i}
          + (1 − α₁ − α₂)·(π^e_t / 4)
          + α₃·Δe_{t−1}
          + α₄·h_{t−1}
          + ε_t
```

**Forma efetivamente estimada (subtraindo π^e_t/4 dos dois lados e de cada termo de inércia, que é como a restrição de verticalidade é imposta por construção):**

```
(π^N_t − π^e_t/4) = c
                  + α₁·(π^N_{t−1} − π^e_t/4)
                  + α₂·((1/4)Σ_{i=1..4} π^H_{t−i} − π^e_t/4)
                  + α₃·Δe_{t−1}
                  + α₄·h_{t−1}
                  + ε_t
```

É uma regressão linear com quatro regressores e uma constante.

### 1.2 Definição de cada variável nos termos das séries do catálogo

| Símbolo | Construção exata a partir do catálogo |
|---|---|
| `π^N_t` | Núcleo do IPCA por **médias aparadas com suavização** (série do catálogo desde 1991). Dessazonalizar o **índice mensal** por X-13 (spec fixada e versionada), depois compor: `π^N_t = 100·[Π_{m∈t}(1 + π^N_m/100) − 1]`. |
| `π^H_t` | IPCA cheio, mesma construção (índice mensal do catálogo, X-13, composição trimestral). O termo de inércia usa o **cheio**, não o núcleo — é assim no BCB, e é o canal pelo qual monitorados e alimentos entram na equação sem estarem no lado esquerdo. |
| `π^e_t` | Focus, expectativa **mediana** para o IPCA acumulado nos próximos 12 meses (série diária desde 2001), **leitura do último dia útil do trimestre t−1**, dividida por 4. Ver §1.3, desvio (6). |
| `Δe_{t−1}` | `100·[ln(ē_{t−1}) − ln(ē_{t−2})]`, onde `ē_t` = média das cotações diárias BRL/USD dentro do trimestre. |
| `h_{t−1}` | Hiato do IBC-Br: `100·[ln(Y_{t−1}) − ln(Y*_{t−1})]`, com `Y_t` = média trimestral do IBC-Br dessazonalizado e `Y*` a tendência pelo **filtro de Hamilton (h = 8 trimestres, p = 4)**. HP com λ=1600 entra como robustez, não como baseline. |
| Pesos | Mínimos quadrados **ponderados**: `w_t = 1` fora de 2020T2–2022T4 e `w_t = 1/9` dentro (equivale a inflar σ por 3). Ver §1.3, desvio (7). |

**Amostra: 2004T1 até a última observação disponível** (~90 trimestres). O IBC-Br começa em jan/2003; quatro defasagens do IPCA cheio consomem 2003. Não vá antes disso: o WP 122 do BCB afirma explicitamente que incluir o período pré-Plano Real "não é recomendável", e o boxe de jun/2024 exclui deliberadamente 1999–2003T3 por volatilidade. **O IPCA desde 1980 não serve para nada aqui.**

### 1.3 Restrições impostas

1. **Verticalidade de longo prazo**, imposta por construção e não testada: o peso das expectativas é escrito como `(1 − α₁ − α₂)`, de modo que inércia do núcleo + inércia do IPCA cheio + expectativas = 1 exatamente. Esta é a convenção da **era bayesiana** do BCB (jun/2024): o termo cambial fica **fora** da soma unitária.
2. **Suporte dos coeficientes** (equivalente às prioris uniformes [0,1] do BCB): `α₁ ∈ [0,1]`, `α₂ ∈ [0,1]`, `α₁ + α₂ < 1`, `α₃ ≥ 0`, `α₄ ≥ 0`. Em MQO não se impõe — verifica-se e reporta-se (ver §4).
3. **Constante**: incluída como *diagnóstico*, não como parte da teoria. Em estado estacionário com hiato zero, `c` deveria ser zero. Um `c` significativamente diferente de zero mede a cunha de nível entre núcleo e IPCA cheio, e é um sinal de que a substituição do lado esquerdo (§1.4, desvio 1) está custando algo. Reporte o teste H₀: c = 0.
4. **Sem termo climático, sem IPPCV, sem commodities separadas** — ver §5.

### 1.4 Qual especificação publicada ela segue, e onde se afasta

**Segue:** Banco Central do Brasil, *Relatório de Inflação*, jun/2024, boxe "Atualização dos modelos semiestruturais de pequeno porte", equação (1) — a versão **agregada** do modelo semiestrutural de pequeno porte, que é a especificação corrente do BCB (confirmada como vigente pela nota de rodapé 5 do boxe de repasse cambial do RPM de mar/2026).
https://www.bcb.gov.br/content/ri/relatorioinflacao/202406/ri202406b12p.pdf

**Afasta-se em sete pontos, todos forçados pelo catálogo ou pela mudança de estimador:**

1. **Variável dependente: núcleo MS em vez de preços livres.** O BCB explica preços livres e projeta os monitorados num bloco satélite de 24 equações calibradas (RPM jun/2025). O catálogo não tem a decomposição. O núcleo por médias aparadas **com suavização** é o melhor substituto disponível: a suavização distribui ao longo de doze meses justamente os itens de reajuste infrequente e em degrau — mensalidade escolar, plano de saúde, IPTU —, que são boa parte do bloco monitorado, e o aparamento das caudas descarta os choques de alimentos in natura e combustíveis. *Esse argumento é meu, não está em nenhuma das fontes* — é uma inferência sobre a construção do índice, e é o elo mais frágil da recomendação. Ele é testável: se você acrescentar as séries de livres e monitorados (§6), pode rodar a mesma equação nas duas e ver se o coeficiente de hiato do núcleo fica entre o de livres e o do cheio, como deveria.
2. **Sem inflação importada de commodities (`π̂*`).** Não há IC-Br no catálogo. Consequência crítica de interpretação: no BCB o `π̂*` é o IC-Br **em reais** e portanto já contém o câmbio, e o `Δê` é apenas o resíduo cambial que não passa por commodities — por isso α₃ = 0,011 lá. **Na minha equação α₃ é o repasse cambial cheio.** Ele deve ser comparado com o φ das projeções locais do BCB (≈0,06 para a média dos núcleos em 12 meses; RPM mar/2026), **jamais com o 0,011 do boxe de jun/2024.** Confundir os dois é o erro de comparação mais provável neste projeto.
3. **Câmbio nominal bruto em vez de desvio da PPC.** O BCB usa o desvio da variação cambial trimestral em relação à variação de longo prazo implicada pela PPC (meta doméstica menos 2%). Como isso é uma subtração de uma sequência quase constante, o efeito é praticamente absorvido pela constante; é um desvio pequeno, mas registre-o.
4. **Hiato do IBC-Br filtrado em vez do hiato latente do sistema.** O `h_t` do BCB é um componente cíclico comum não observável, estimado por filtro de Kalman dentro do sistema completo a partir de PIB, Nuci/FGV, taxa de desocupação e Novo Caged, e simultaneamente condicionado pela própria curva de Phillips. **Isso não é reproduzível fora do sistema.** O custo é conhecido e quantificado: Alves & Correa (BCB TD 339) mostram que a mesma especificação, com hiato HP ingênuo no lugar do hiato inferido por Kalman, leva o coeficiente de desemprego de −0,306 (e.p. 0,067, significativo) para −0,166 (e.p. 0,131, **insignificante**). **A curva vai parecer mais plana do que é, e isso é atenuação por erro de medida do hiato, não um achado econômico.** https://www.bcb.gov.br/pec/wps/port/TD339.pdf
5. **Hiato defasado (`h_{t−1}`) em vez de contemporâneo.** No BCB o hiato é latente e conjuntamente determinado, então o `h_t` contemporâneo é inócuo. Em equação única por MQO, `h_t` é endógeno por construção. Hazell et al. e Ball–Mazumder ambos usam folga defasada. Rode `h_t` como robustez para comparabilidade com o BCB.
6. **Expectativa predeterminada em vez de média intra-trimestre.** O BCB usa a média das leituras diárias do Focus **ao longo do trimestre t** — que já incorpora os IPCAs de janeiro e fevereiro quando se explica o primeiro trimestre. Com dados diários você pode usar a leitura do último dia útil de t−1 e eliminar essa simultaneidade de graça. Rode as duas: **a diferença entre os dois conjuntos de coeficientes é, ela própria, uma medida de quanto do ajuste vem de simultaneidade.**
7. **MQP com variância inflada em vez de calibração bayesiana da variância.** O BCB calibra variâncias dos choques mais altas em 2020T2–2022T4. O análogo em MQO é ponderar. O fator 3 é arbitrário e por isso entra na grade de especificações (§4.F) junto com {sem ponderação, dummies trimestrais, exclusão das observações}.

**Divisão por 4:** use `π^e/4` (o que o BCB faz), não `((1+π^e/100)^{0,25} − 1)·100`. A diferença é ~0,02 p.p. a 5% — irrelevante economicamente, mas **fixe qual das duas o código usa**, para que duas implementações não divirjam em silêncio.

---

## 2. Estados Unidos — equação diferente, e a razão

**Os dois países precisam de equações diferentes.** Cinco razões, em ordem de peso:

1. **Bloco indexado.** Os preços monitorados são ~26% do IPCA (minha soma dos 24 pesos publicados no anexo do boxe de jun/2025 do RPM; o BCB não publica esse total) e são projetados por **regras institucionais calibradas**, não estimadas — gasolina como `Σc_i(ΔPetróleo + ΔCâmbio)`, energia com a parcela de Itaipu contratada em dólar (α_Itaipu = 0,086), planos de saúde pela regra da ANS, medicamentos pelo teto CMED. Nada disso responde a folga. Não existe análogo americano. Regredir IPCA cheio contra folga é misturar um bloco sensível ao ciclo com um bloco que só responde a inflação passada, e a atenuação é mecânica.
2. **Câmbio.** No Brasil o repasse é de primeira ordem (0,10 no IPCA cheio em 12 meses, 0,26 em alimentação no domicílio, ~0,01 em serviços — RPM mar/2026) e é **estado-dependente** (Estudo Especial 26/2018). Nos EUA é de segunda ordem, e o catálogo americano não tem câmbio nem preços de importados.
3. **Ancoragem.** Ball & Mazumder estimam o peso do "âncora" δ em **0,06 em 1985–1999 e 0,81 em 2000–2014**, com quebra em 1997T4 pelo sup-Wald de Andrews: os EUA passam a ter expectativas ancoradas e o Brasil, nesta amostra, não tem — a ponto de o BCB ter construído em 2018 uma variável explícita de **desancoragem** para deixar o repasse cambial variar com ela.
4. **Amostra.** Desemprego americano desde 1948; brasileiro desde março de 2012.
5. **Expectativas.** O Brasil tem Focus diário desde 2001. **O catálogo americano não tem nenhuma série de expectativas.** Isso é decisivo (abaixo).

### 2.1 Equação recomendada para os EUA

```
π^S_t = α₀ + α_u · ū_{t−1} + α_s · (π^H_t − π^C_t) + ε_t
```

| Símbolo | Construção |
|---|---|
| `π^S_t` | Inflação trimestral do **sticky-price CPI, núcleo** (série do catálogo). |
| `ū_{t−1}` | **Média** da taxa de desemprego ao longo dos quatro trimestres t−4 … t−1 (nível, não hiato). |
| `π^H_t − π^C_t` | Termo de choque de oferta de Gordon: crescimento do índice cheio menos o do núcleo (use PCE cheio menos PCE núcleo se ambos estiverem no catálogo; senão CPI menos CPI núcleo). |
| `α₀` | Composto de `π^e − α_u·u*`. **Não é interpretável.** É a constante que absorve expectativas ancoradas e a taxa natural. |

**Amostra baseline: 2000T1–2019T4.** Reporte separadamente 2000T1–hoje, com os resíduos de 2021–2023 explicitamente exibidos.

**Segue:** Ball & Mazumder, *A Phillips Curve with Anchored Expectations and Short-Term Unemployment*, IMF WP/15/39, equação (5). https://www.imf.org/external/pubs/ft/wp/2015/wp1539.pdf

**Afasta-se em quatro pontos:**

1. **Desemprego total em vez de desemprego de curto prazo (< 27 semanas)**, que não está no catálogo. Custo medido pelos próprios autores (Tabela 2): a inclinação cai de **−0,981 (e.p. 0,076, R² 0,81)** para **−0,309 (e.p. 0,069, R² 0,55)**. Ainda com sinal certo e significativa — usável, mas atenuada por um fator de três.
2. **Sticky-price core CPI em vez de mediana ponderada do Cleveland Fed.** Justificativa: Stock & Watson observam que a mediana do CPI se comporta como o índice cíclico deles porque é tipicamente determinada pelas mesmas séries ciclicamente sensíveis; e Bryan & Meyer mostram que a metade "sticky" prevê melhor em horizontes longos. É o análogo mais próximo disponível. https://www.princeton.edu/~mwatson/papers/CSI_20190612.pdf · https://www.clevelandfed.org/publications/economic-commentary/2010/ec-201002-are-some-prices-in-the-cpi-more-forward-looking-than-others-we-think-so
3. **Acréscimo de um termo de oferta de Gordon**, que Ball–Mazumder não têm. Motivo: Gordon (NBER WP 19390) argumenta que omitir choques de oferta explícitos induz correlação positiva entre inflação e desemprego que compensa a relação estrutural negativa, viesando o coeficiente "para baixo, talvez até zero". O termo cheio-menos-núcleo é exatamente o dele e é construível a partir do catálogo. https://www.nber.org/system/files/working_papers/w19390/w19390.pdf
4. **Amostra que pode ir além de 2014.** Isto é um risco assumido, não uma melhoria: a hipótese de "expectativas ancoradas = constante" é justamente a que 2021–2023 estressa. Se você rodar até hoje sem uma série de expectativas, α₀ vai tentar absorver o surto e a inclinação vai ficar distorcida.

### 2.2 O que **não** recomendo para os EUA, e por quê

- **Forma aceleracionista** (Δπ contra folga, ou média de quatro trimestres de inflação passada como proxy de expectativas). Ball–Mazumder, Tabela 2, linha (4), mediana ponderada do CPI: coeficiente de **−0,0003 (e.p. 0,068)** na amostra cheia e **+0,126 (e.p. 0,104)** — sinal errado — em 2008T1–2014T2. É exatamente a especificação que produz o patológico.
- **A curva de preços do FRB/US.** Ela **não tem termo de desemprego nenhum**: a folga chega aos preços só via a equação de salários (PIECI) e via as equações de expectativas VAR (ZPICXFE/ZPIECI). Implementar PICXFE isolada com um AR ad hoc no lugar de ZPICXFE é implementar uma curva de Phillips sem mecanismo de Phillips dentro. https://www.federalreserve.gov/econres/us-models-python.htm
- **Yellen (2015)**, que seria a melhor referência do sistema do Fed e é a mais próxima do estilo de boxe do BCB — `π^c_t = 0,41·π^e_t + 0,36·π^c_{t−1} + 0,23·π^c_{t−2} − 0,08·SLACK_t + 0,57·RPIM_t` — **exige** `π^e` (SPF de longo prazo) e `RPIM` (preço relativo de importados core). Faltam as duas no catálogo. É a especificação a implementar **assim que** as expectativas entrarem. https://www.federalreserve.gov/newsevents/speech/yellen20150924a.htm

### 2.3 Qual série de expectativas acrescentar, quando acrescentar

Não é o SPF por default. Coibion & Gorodnichenko rodam uma corrida de cavalos com Michigan e SPF simultaneamente na mesma equação: o coeficiente de **Michigan (domicílios)** é grande e significativo a 1% em todas as oito colunas (0,78 a 1,48); o do **SPF é pequeno e em geral insignificante** (−0,09 a 0,34). E mostram que a "disinflação que faltou" de 2009–2011 **sobrevive** ao uso do SPF e só desaparece com Michigan. https://eml.berkeley.edu/~ygorodni/CG_missing_disinflation.pdf

Acrescente **as duas** (Michigan 1 ano e SPF 10 anos) e reporte a corrida de cavalos. Mas atenção à taxonomia de §3.4: com expectativas de longo prazo você estima ψ, não κ.

---

## 3. Método de estimação, e o que é honesto dizer sobre identificação

### 3.1 MQO é defensável — para o objeto certo

Sim, MQO (ou MQP, com os pesos de §1.2) é defensável **como estimador de um coeficiente de forma reduzida condicionado à restrição de verticalidade imposta e a uma série de expectativas observada**. Não é defensável como estimador da inclinação estrutural κ. A distinção não é pedantismo; é a diferença entre um número reportável e um número que não significa nada.

Erros-padrão: Newey–West HAC, com defasagem fixada em 4 trimestres **e** com largura de banda automática (Newey–West 1994); reporte os dois.

### 3.2 O que a literatura diz, sem rodeios

**Uma regressão agregada de série temporal não identifica a inclinação da curva de Phillips.** Três resultados primários, independentes:

- **Mavroeidis, Plagborg-Møller & Stock**, *Empirical Evidence on Inflation Expectations in the New Keynesian Phillips Curve*, JEL 52(1), 2014. Estimam **mais de 600 mil** pontos ao longo de especificações a priori razoáveis. As estimativas da inclinação são "**simetricamente dispersas em torno de zero**" — ou seja, sinal errado é aproximadamente metade da distribuição. Os conjuntos de confiança robustos à identificação de 90% cobrem em média **um terço do espaço de parâmetros** por especificação, e a **união** ao longo de ~1400 especificações cobre **o espaço inteiro**. Diagnóstico: os instrumentos são fortes para prever a variável forçante (F mediano 63,7 e 166,5) e **fracos para prever a expectativa de inflação** (F mediano 3,1 e 4,2, contra o limiar usual de 10). Conclusão deles: a literatura atingiu o limite do que se pode aprender sobre a NKPC a partir de séries temporais macro agregadas. https://www.mikkelpm.com/files/infl_expns_nkpc.pdf
- **McLeay & Tenreyro**, NBER WP 25892, provam que sob política ótima discricionária o MQO de inflação contra hiato converge para **−κ/λ**, a inclinação da *regra de metas*, com **sinal oposto** ao verdadeiro. E documentam empiricamente: no CPI núcleo americano contra o hiato do CBO, por mandato do presidente do Fed, três de seis períodos dão coeficiente **positivo** — Burns/Miller +0,21, Volcker fase 2 +0,01, Greenspan +0,15. https://www.nber.org/system/files/working_papers/w25892/w25892.pdf
- **Hazell, Herreño, Nakamura & Steinsson**, QJE 137(3), 2022, reproduzem a patologia dentro do próprio painel estadual: sem efeitos fixos, κ = **−0,0037** e ψ = **−0,103**, sinal errado; com efeitos fixos de estado e de tempo, κ = 0,0062 e ψ = 0,112. O que os efeitos fixos de tempo removem são as expectativas de longo prazo comuns — e é isso, não a inclinação, que muda ao longo do tempo: sem efeitos de tempo o κ cai por um fator de ~100 entre pré e pós-1990; com efeitos de tempo, por um fator de ~2, **estatisticamente não significativo**. https://academic.oup.com/qje/article/137/3/1299/6529257

**Consequência operacional imediata: um α₄ com sinal errado nos seus resultados não é, por si só, evidência de erro de código.** É o resultado modal esperado. O que *é* evidência de erro de código é sinal errado **em todas as células da grade** (§4.C).

### 3.3 O que fazer, dado isso

Em ordem de retorno:

1. **Usar a expectativa predeterminada** (última leitura diária do Focus antes do trimestre). Barato, e quebra a simultaneidade intra-trimestre. Vantagem que só o lado brasileiro do catálogo oferece.
2. **Defasar tudo o que puder**: `h_{t−1}`, `Δe_{t−1}`. Hazell et al. usam `u_{i,t−4}`, e dizem explicitamente que é "por consistência com estudos anteriores como Ball & Mazumder".
3. **Variáveis instrumentais para o hiato, não para as expectativas.** MPS mostram que a fraqueza está toda na margem de expectativas (F mediano ~3), não na margem de folga (F mediano 63–166). Como aqui as expectativas são **observadas** (Focus), o problema de instrumento fraco é contornado — ao preço de o Focus não ser expectativa racional. Registre esse preço.
4. **Projeções locais para o repasse cambial**, como objeto separado e melhor identificado. A equação do BCB (RPM mar/2026) é mensal, tem ~170 observações no seu catálogo a partir de 2012 (e mais se você usar a folga do IBC-Br desde 2003), e é diretamente implementável. Faça-a: ela é a peça mais confiável do conjunto.
5. **O desenho que realmente identificaria — e que você não tem**: painel regional com efeitos fixos de região e **de tempo**, à la Hazell et al. e McLeay–Tenreyro. Os efeitos de tempo são o elemento que carrega o peso, porque diferenciam exatamente as expectativas de longo prazo comuns. O IPCA é coletado em regiões metropolitanas e a PNAD Contínua tem desemprego regional. **Nenhuma das duas está no catálogo** (§6).

### 3.4 A armadilha de comparabilidade que vai morder o projeto Brasil–EUA

Há **três objetos diferentes** chamados de "a inclinação", separados por uma a duas ordens de grandeza:

| Objeto | O que é | Referência |
|---|---|---|
| **κ** | Inclinação estrutural, sobre folga **corrente**, com expectativas de um período à frente. | Hazell et al.: **0,0062** |
| **ψ** | Forma reduzida, com expectativas de **longo prazo** ou efeitos fixos de tempo; absorve também folga futura esperada. `ψ = κ/(1 − βρ_u)`. | Hazell et al.: 0,112–0,339 estadual, **0,34** agregado |
| Inclinação aceleracionista / de núcleo | Especificação com expectativas ancoradas ou defasagens somando um. | Ball–Mazumder: **−0,98** |

Hazell et al. mostram que ψ/κ ≈ 4Γ, com Γ entre 6 e 9 — **um fator de 20 a 50** — e afirmam que pesquisadores que usam expectativas de longo prazo estimam ψ "talvez inadvertidamente". A equação brasileira que recomendei é do tipo **ψ** (peso unitário imposto sobre uma expectativa observada de 12 meses). A americana também. Isso é bom: são comparáveis entre si. Mas **nenhuma das duas é comparável ao α₄ = 0,120 do BCB nem ao κ = 0,0062 de Hazell et al.**

---

## 4. O que o teste de aceitação deve fixar

Dado §3, **fixar um valor para a inclinação é consagrar ruído**. O teste deve fixar o que é determinístico, o que é imposto por construção, o que é ordenamento robusto, e o que é desempenho. Proponho oito blocos.

### A. Identidades de construção de dados (exatas, determinísticas — falha dura)

- A1. `π^N_t` reconstruída do índice bate com a composição das taxas mensais, tolerância 1e-8.
- A2. Dessazonalização reproduzível: mesma spec X-13 versionada, mesma semente, saída idêntica a 1e-10.
- A3. Agregação do Focus: reproduz a leitura predeterminada (último dia útil de t−1); regra de preenchimento de feriados fixada em no máximo 5 dias; recomputação bate a 1e-10.
- A4. `Δe` usa médias trimestrais de diárias, log-diferença × 100; bate a 1e-10.
- A5. Conversão da expectativa: assertar **qual** das duas fórmulas está em uso (`π^e/4` vs. composição exata) e que as duas diferem em menos de 0,03 p.p. no intervalo relevante.
- A6. Extremos da amostra e **número de observações** assertados exatamente.

### B. Integridade da restrição (falha dura)

- B1. `|α₁ + α₂ + α_e − 1| < 1e-10`. A verticalidade tem de valer por construção, não por estimação.
- B2. A forma em desvio e a forma por MQNL restrita produzem valores ajustados numericamente idênticos (1e-8). É a checagem cruzada das duas implementações.
- B3. A versão **irrestrita** (com α_e livre) também é estimada e o teste de Wald da restrição é **reportado**, não exigido. O BCB impõe como identidade; o teste é diagnóstico.

### C. Sinais e suportes (falha condicional — e esta é a parte que exige cuidado)

- C1–C4. Verificar `α₁, α₂ ∈ [0,1]`, `α₁ + α₂ < 1`, `α₃ ≥ 0`, `α₄ ≥ 0`. Estes são exatamente os suportes das prioris uniformes do BCB, então são critérios com fonte, não arbitrários.
- **Regra de decisão:** violação **em uma célula** da grade → registrar e reportar, **não falhar**; é o resultado modal segundo MPS. Violação **em todas as células** → **falha dura**, porque isso indica erro de convenção de sinal (hiato invertido, câmbio invertido) e não incerteza econômica.

### D. Ordenamentos publicados (falha dura — é aqui que está a validação real)

Ordenamentos são muito mais robustos que níveis, e todos têm fonte primária. Rodando o **mesmo código** em diferentes variáveis dependentes:

- D1. Repasse cambial em 12 meses: **núcleos < IPCA cheio**. BCB RPM mar/2026: ~0,06 contra 0,10. Os três núcleos do catálogo estão entre os cinco que o BCB avaliou individualmente (EX0 0,06; EX3 0,06; MS 0,06; DP 0,07; P55 0,06).
- D2. Coeficiente de hiato **maior em serviços** que em bens industriais e alimentação. BCB desagregado jun/2024: 0,13 contra 0,079 e 0,073. *(Exige acrescentar as séries setoriais — §6.)*
- D3. Repasse **quase nulo em serviços** e **máximo em alimentação no domicílio**. BCB: 0,01 contra 0,26 em 12 meses. *(Mesma dependência.)*
- D4. Repasse **maior em monitorados** que em livres na resposta de 4 trimestres. BCB jun/2024: +1,65 p.p. contra +0,72 p.p. para depreciação permanente de 10%. *(Exige as séries 11428/4449.)*

D1 é executável hoje. D2–D4 são o argumento mais forte para acrescentar as séries de §6.

### E. Domínio preditivo sobre benchmark ingênuo (falha dura)

- E1. Pseudo-fora-da-amostra, janela expansiva a partir de 2015T1, **simulação dinâmica** de 4 trimestres (o modelo alimenta as próprias previsões defasadas, à la Gordon). O RMSE do modelo tem de ser ≤ ao de **dois** benchmarks: (i) "inflação do núcleo = Focus/4" e (ii) passeio aleatório na inflação acumulada em 4 trimestres.
- Se a equação não bate "simplesmente use o Focus", ela não tem conteúdo e não deve ser publicada como curva de Phillips. Esse é um critério de aceitação genuíno que não fixa inclinação nenhuma.

### F. Grade de especificações, reportada como intervalo (falha = a grade não roda)

Pré-registre a grade e exija que **o entregável seja a distribuição, não um ponto**. Dimensões mínimas:

- Dependente: {MS, exclusão 1, exclusão 2, IPCA cheio} (+ livres, se acrescentado)
- Folga: {hiato IBC-Br Hamilton, hiato IBC-Br HP1600, hiato de desemprego 2012+, hiato do PIB trimestral 1996+}
- Expectativa: {predeterminada, média intra-trimestre}
- Covid: {MQP fator 3, MQP fator 2, dummies, exclusão}
- Timing do hiato: {t−1, t}

Reportar min/mediana/máx de α₃ e α₄, os e.p. HAC, e a **fração de células em que cada coeficiente é significativamente do sinal esperado**. Justificativa: MPS mostram que a união dos conjuntos de confiança ao longo das especificações cobre o espaço todo; um ponto isolado não é informativo. O BCB, no boxe "Medidas de hiato do produto no Brasil" (RI jun/2024, p. 79–84), lista as **doze** metodologias alternativas de hiato que o Copom acompanha — a própria autoridade trata o hiato como dimensão de grade. https://www.bcb.gov.br/content/ri/relatorioinflacao/202406/ri202406b10p.pdf

### G. Estabilidade (reportada, sem limiar)

- G1. Janelas móveis de 40 trimestres para α₄ (Gordon faz isso com 100 trimestres).
- G2. Teste sup-Wald de Andrews para quebra em data desconhecida; data e p-valor **reportados**, sem limiar de aprovação. Referência de calibragem: Ball–Mazumder acham quebra em 1997T4 nos EUA com δ indo de 0,06 para 0,81.

### H. Guarda de comparabilidade Brasil–EUA (falha dura)

- H1. Assertar que as duas variáveis de inflação estão nas **mesmas unidades** (escolha: trimestral não anualizada, em p.p.) e que a folga está em p.p. nos dois países.
- H2. Cada estimativa carrega um campo de metadados com o **estimando**: `kappa`, `psi` ou `aceleracionista`. Qualquer comparação numérica entre estimativas com etiquetas diferentes **falha o teste**. Fundamento: ψ/κ ≈ 20 a 50 (Hazell et al.).

### I. Anti-requisito explícito

**Nenhum teste pode assertar α₄ ≈ 0,120**, nem α₃ ≈ 0,011, nem κ ≈ 0,0062. São modas de posterioris bayesianas de sistemas com hiato latente, sobre outra variável dependente, com outro estimador. Alves & Correa quantificam a distância: −0,306 vira −0,166 e insignificante só por trocar o hiato. Fixar o número do BCB transformaria um viés conhecido em critério de qualidade.

---

## 5. O que não é estimável na amostra brasileira, e por quê

**5.1 A curva do BCB propriamente dita.** Faltam a decomposição livres/monitorados, o IC-Br, o ONI (clima), o IPPCV, a Nuci/FGV e o Caged. Mesmo com todos eles, o hiato `h_t` é um componente cíclico comum latente estimado **dentro** do sistema por filtro de Kalman, condicionado simultaneamente pela curva de Phillips, pela curva de expectativas e pela IS. **A estimação é de sistema; não é possível replicar exatamente o hiato do BCB estimando a curva isoladamente com hiato exógeno.** (Boxe de jun/2024, e o próprio boxe reconhece isso ao listar as equações de observação 6–9.)

**5.2 O bloco de preços administrados.** São 24 equações trimestrais **calibradas a partir do arcabouço institucional**, não estimadas: Brent, tarifa de Itaipu indexada ao CPI americano, IVDA/ANS, regra CMED, ICMS, bandeiras tarifárias. Nada disso está no catálogo. Consequência: **o IPCA cheio não é decomponível**, e uma curva de Phillips no IPCA cheio agrega ~26% do índice que não responde a nenhum dos regressores exceto inflação passada. https://www.bcb.gov.br/content/ri/relatorioinflacao/202506/rpm202506b9p.pdf

**5.3 A variável de desancoragem — e este é o buraco mais substantivo.** O mecanismo mais especificamente brasileiro da literatura é o repasse cambial estado-dependente do Estudo Especial 26/2018: cada 1 p.p. de desancoragem **eleva** o coeficiente de repasse em 1,5 a 6,7 p.p.; um hiato 1% negativo o **reduz** em 2,1 a 9,1 p.p. Mas a variável `π̂^e` é definida como a expectativa Focus, em t, para a inflação **acumulada em 12 meses, 24 meses à frente**, menos uma **meta interpolada** para 24 meses à frente, truncada em zero. **O catálogo tem só a expectativa de 12 meses à frente. `π̂^e` não é construível.** Sem ela, todo o bloco de não-linearidade fica fora de alcance. https://www.bcb.gov.br/conteudo/relatorioinflacao/EstudosEspeciais/Repasse_cambial_sob_a_otica_de_um_modelo_semiestrutural.pdf

**5.4 Modelos de limiar (Correa & Minella, BCB WP 122).** O estimador exige que cada regime tenha volume suficiente — o paper trabalha com 44 observações divididas em 19/25, com hiato de função de produção. Numa amostra de desemprego 2012+ (~55 trimestres, dos quais ~11 contaminados pela pandemia) o limiar não é identificado. A rota viável para estado-dependência é **interagir o termo cambial com uma variável contínua** (equação 2 do Estudo Especial 26/2018), não estimar o limiar. https://www.bcb.gov.br/pec/wps/ingl/wps122.pdf

**5.5 Qualquer coisa antes de 1999.** WP 122 é explícito; o boxe de jun/2024 descarta até 2003T3. O IPCA desde 1980 e os núcleos desde 1990/1991 não compram amostra utilizável.

**5.6 Desemprego antes de março de 2012.** A PNAD Contínua começa em 2012; a PME anterior cobre seis regiões metropolitanas e não é comparável. **E há uma armadilha adicional:** o número publicado da PNAD-C é, por desenho do IBGE, uma **média móvel de três meses**. Regredir IPCA mensal contra a série bruta constrói um artefato de média móvel dentro do termo de folga. O BCB publicou um filtro de espaço-de-estados para "mensalizar" (`X_t = (x_t + x_{t−1} + x_{t−2})/3`, com `x_t` passeio aleatório com deriva AR(1)); aplique-o antes de qualquer projeção local mensal. https://www.bcb.gov.br/content/ri/relatorioinflacao/202006/ri202006b2p.pdf

**5.7 A amostra limpa efetiva com desemprego é ainda menor do que parece:** 2012T2–2019T4 (31 trimestres) mais ~2022T2 em diante (~16 trimestres) ≈ **47 trimestres úteis**. É por isso que o baseline usa o hiato do IBC-Br desde 2003 e o desemprego entra como robustez, não o contrário.

**5.8 O painel regional** — o único desenho que a literatura afirma identificar a inclinação — não é executável: falta IPCA por região metropolitana e falta PNAD-C regional.

**5.9 A inclinação estrutural κ.** Não identificável de nenhuma série temporal agregada brasileira, pelos motivos de §3.2. Só objetos de forma reduzida do tipo ψ.

---

## 6. Séries a acrescentar, em ordem de retorno

1. **IPCA itens livres (SGS 11428) e monitorados (SGS 4449)**, ambos com primeira observação em **janeiro de 1991** — um dos pesquisadores consultou a API de dados abertos do BCB para 1990–1996 e a primeira observação retornada foi 01/01/1991 em ambos. Isso cobre toda a amostra estimável e transforma a equação de §1 na especificação do BCB de verdade, tornando os coeficientes diretamente comparáveis aos publicados e habilitando os testes D1 e D4.
2. **IC-Br em reais** (total e os três subíndices: agropecuária, metal, energia). Sem ele, α₃ é repasse cheio e não é comparável ao α₃ do BCB. Verifique os códigos no SGS antes de usar — não os tenho confirmados.
3. **IPCA serviços (SGS 10844), bens industriais, alimentação no domicílio, comercializáveis (SGS 4447).** Habilitam D2 e D3 e a versão desagregada de três curvas.
4. **Expectativas americanas: Michigan 1 ano e SPF 10 anos.** Sem isso a equação americana é um encaixe de constante, e Yellen (2015) fica fora de alcance.
5. **Focus para inflação acumulada em 12 meses, 24 meses à frente** (ou expectativas para anos-calendário t+2/t+3) e a trajetória de metas. Habilita a desancoragem e todo o bloco de estado-dependência.
6. **NAIRU do CBO e preço relativo de importados core (EUA)**, para fechar Yellen (2015).
7. **IPCA por região metropolitana e PNAD-C regional.** Retorno mais alto de todos em termos de *identificação*, e o mais caro de montar.

---

## 7. Fontes citadas

**Banco Central do Brasil**
- *Atualização dos modelos semiestruturais de pequeno porte*, RI jun/2024 — https://www.bcb.gov.br/content/ri/relatorioinflacao/202406/ri202406b12p.pdf
- *Medidas de hiato do produto no Brasil*, RI jun/2024 — https://www.bcb.gov.br/content/ri/relatorioinflacao/202406/ri202406b10p.pdf
- *Atualização do modelo para projeção de médio prazo dos preços administrados*, RPM jun/2025 — https://www.bcb.gov.br/content/ri/relatorioinflacao/202506/rpm202506b9p.pdf
- *Repasse cambial: estimativas por projeções locais*, RPM mar/2026 — https://www.bcb.gov.br/content/ri/relatorioinflacao/202603/rpm202603b8p.pdf
- *Repasse cambial sob a ótica de um modelo semiestrutural*, Estudo Especial 26/2018 — https://www.bcb.gov.br/conteudo/relatorioinflacao/EstudosEspeciais/Repasse_cambial_sob_a_otica_de_um_modelo_semiestrutural.pdf
- *Revisão do modelo agregado de pequeno porte*, RI dez/2021 — https://www.bcb.gov.br/content/ri/relatorioinflacao/202112/ri202112b7p.pdf
- *Estimativa para dados "mensalizados" da PNAD Contínua*, RI jun/2020 — https://www.bcb.gov.br/content/ri/relatorioinflacao/202006/ri202006b2p.pdf
- Correa & Minella, *Nonlinear Mechanisms of the Exchange Rate Pass-Through*, WPS 122 (2006) — https://www.bcb.gov.br/pec/wps/ingl/wps122.pdf
- Alves & Correa, *Um Conto de Três Hiatos*, TD 339 (2013) — https://www.bcb.gov.br/pec/wps/port/TD339.pdf

**Sistema do Federal Reserve**
- Yellen, *Inflation Dynamics and Monetary Policy*, 24/09/2015, apêndice — https://www.federalreserve.gov/newsevents/speech/yellen20150924a.htm
- Modelo FRB/US (pacote Python; equações em `models/model.xml`) — https://www.federalreserve.gov/econres/us-models-python.htm
- Shapiro, *A Simple Framework to Monitor Inflation*, FRBSF WP 2020-29 — https://www.frbsf.org/economic-research/publications/working-papers/2020/29/
- Bryan & Meyer, Cleveland Fed EC 2010-02 — https://www.clevelandfed.org/publications/economic-commentary/2010/ec-201002-are-some-prices-in-the-cpi-more-forward-looking-than-others-we-think-so

**Literatura acadêmica**
- Mavroeidis, Plagborg-Møller & Stock, JEL 52(1), 2014 — https://www.mikkelpm.com/files/infl_expns_nkpc.pdf
- Hazell, Herreño, Nakamura & Steinsson, QJE 137(3), 2022 — https://academic.oup.com/qje/article/137/3/1299/6529257
- McLeay & Tenreyro, NBER WP 25892 (2019) — https://www.nber.org/system/files/working_papers/w25892/w25892.pdf
- Ball & Mazumder, IMF WP/15/39 (2015) — https://www.imf.org/external/pubs/ft/wp/2015/wp1539.pdf
- Gordon, NBER WP 19390 (2013) — https://www.nber.org/system/files/working_papers/w19390/w19390.pdf
- Stock & Watson, *Slack and Cyclically Sensitive Inflation* (2019) — https://www.princeton.edu/~mwatson/papers/CSI_20190612.pdf
- Coibion & Gorodnichenko, AEJ:Macro 7(1), 2015 — https://eml.berkeley.edu/~ygorodni/CG_missing_disinflation.pdf

---

## Onde eu posso estar errado

Três pontos que não consigo sustentar com fonte e que devem ser tratados como hipóteses testáveis, não como recomendação firme:

1. **A equivalência "núcleo MS ≈ preços livres"** é uma inferência minha sobre a construção do índice. Nenhuma fonte a afirma. É o elo mais frágil da §1, e a maneira de resolvê-la é acrescentar a série de livres e comparar.
2. **O fator de inflação de variância 3** para o período pandêmico não tem fonte; o BCB calibra variâncias mas não publica o fator. Por isso ele está na grade.
3. **A escolha do filtro de Hamilton sobre HP** para o hiato do IBC-Br é defensável (sem problema de extremo, sem escolha de λ) mas não é o que o BCB faz — o BCB usa HP λ=1600 para PIB e Caged dentro do sistema de Kalman. Ambos estão na grade justamente porque não tenho base para escolher um.

Também não verifiquei diretamente a data de início da série Focus de 12 meses à frente. "Desde 2001" é plausível, mas confirme na API de Expectativas antes de fixar o extremo da amostra.