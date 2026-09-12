# C05-A01 — Matriz de fontes consultadas e limiares conferidos

Campanha: **MP-COM-20260912/C05** — conformidade normativa integral do escopo e perfis institucionais.
Branch: `mp-com-20260912/c05-normas-perfis`. BASE_SHA: `8d66c7973c659174e06d7223c9a9a8181e8eeabf`.
Data de consulta das normas: **2026-09-11**.

## 1. Regra desta matriz

Cada limiar que o produto aplica tem de vir do **texto da edição**, não de README, não de
fonte secundária, não de memória de modelo. A conferência é reexecutável:

```bash
PYTHONPATH= python3 scripts/comercial/referencia/verify_sources.py \
  --normas-dir docs/normas --require-sources
```

O script faz duas verificações independentes: (i) cada constante aplicada pelo código
confere com a entrada correspondente em `normative_rules.THRESHOLD_PROVENANCE`
(coerência interna, sempre executável); (ii) o SHA-256 dos exemplares em `docs/normas/`
confere com o registrado em `normative_rules.SOURCE_DOCUMENTS` (integridade da fonte,
só quando os exemplares licenciados estão presentes). O script **não** copia, imprime
ou redistribui conteúdo das normas — apenas digests.

## 2. Documentos com conteúdo efetivamente conferido

| id | documento | edição | SHA-256 | conteúdo conferido | vigência |
|---|---|---|---|---|---|
| `abnt-nbr-14653-2-2011` | ABNT NBR 14653-2 — Avaliação de bens — Parte 2: Imóveis urbanos | 2011 (1ª ed.) | `8fed8e7c…e2668896` | **sim** — Tabela 1, Tabela 2, Tabela 5, 8.2.1.5, 9.1, 9.2, 9.3/Tabelas 6–7, 10.1, Anexos A.2/A.3/A.8/A.10 | **não confirmada** |
| `abnt-nbr-14653-1-2019` | ABNT NBR 14653-1 — Avaliação de bens — Parte 1: Procedimentos gerais | 2019 (2ª ed.) | `125eeed4…a02fcc92` | **sim** — Seção 0.3, Seção 3.1 (definições), Seção 6 | **não confirmada** |

Acesso: exemplares licenciados disponibilizados localmente pelo responsável do projeto.
`docs/normas/` está em `.gitignore` desde antes desta campanha; **nenhum byte das normas
entra no repositório**. Esta matriz publica somente metadados, âncoras de cláusula e
critérios parafraseados — não o texto normativo.

## 3. Limiares conferidos, um por um

Todos verificados contra o texto das edições acima. `literal` indica se o número está
enunciado como tal na norma ou se é interpretação registrada.

| limiar | valor aplicado | cláusula | pág. | literal |
|---|---|---|---|---|
| item 2 — quantidade mínima de dados | `n ≥ 6(k+1) / 4(k+1) / 3(k+1)` | Tabela 1 item 2 | 30 | sim |
| item 4 (a) — piso da medida | `≥ 0,5 × mínimo amostral` | Tabela 1 item 4 (a) | 30 | sim |
| item 4 (a) — teto da medida | `≤ 2,0 × máximo amostral` | Tabela 1 item 4 (a) | 30 | **não** (ver §4) |
| item 4 (b) — desvio de valor | `≤ 15%` (Grau II, uma variável) / `≤ 20%` (Grau I, de per si e simultaneamente) | Tabela 1 item 4 (b) | 31 | sim |
| item 5 — teste t por regressor | `≤ 10% / 20% / 30%` (bicaudal, soma das duas caudas) | Tabela 1 item 5 | 31 | sim |
| item 6 — teste F | `≤ 1% / 2% / 5%` | Tabela 1 item 6 | 31 | sim |
| pontuação por grau | Grau I = 1, II = 2, III = 3 | 9.2.1.6 b) | 32 | sim |
| enquadramento — pontos mínimos | `16 / 10 / 6` | Tabela 2 / 9.2.1.6 | 32 | sim |
| enquadramento — itens obrigatórios | III: itens 2,4,5,6 no Grau III e os demais ≥ II; II: itens 2,4,5,6 ≥ II e os demais ≥ I; I: todos ≥ I | Tabela 2 | 32 | sim |
| grau de precisão | amplitude do IC 80% `≤ 30% / 40% / 50%`; `> 50%` sem classificação, com justificativa | Tabela 5 / 9.2.3 | 34 | sim |
| campo de arbítrio | `±15%` em torno da estimativa de tendência central; **não** se confunde com o IC de 80% | 8.2.1.5.1 / 8.2.1.5.4 | 24 | sim |
| micronumerosidade | `n ≥ 3(k+1)`; `nᵢ ≥ 3` (n ≤ 30), `≥ 10% n` (30 < n ≤ 100), `≥ 10` (n > 100) | Anexo A.2 a) | 42 | sim |
| α dos testes auxiliares | `≤ 10%` para os testes **não** citados na Tabela 1 | Anexo A.3.1 | 45 | sim |
| atenção a correlações | `> 0,80` na matriz de correlações (atenção, **não** reprovação) | Anexo A.2.1.5.2 | 44 | sim |
| enquadramento do custo | pontos `7 / 5 / 3`; III exige item 1 no Grau III e os demais ≥ II | Tabela 7 / 9.3 | 35 | sim |

### Achados que corrigiram o produto

- **Anexo A.3.1 é normativo.** O teto de 10% para o nível de significância dos testes
  *não* citados na Tabela 1 está no texto da norma. O produto tratava esse valor como
  convenção; passou a ser teto normativo, e um `alpha` acima dele é **recusado**, não
  acomodado.
- **Anexo A.2 a) é calculável.** A micronumerosidade estava listada como não verificável
  automaticamente. Os mínimos de `nᵢ` estão enunciados na norma e agora são calculados
  (`classify_micronumerosidade`). O ramo de 10% arredonda **para cima**: um dado
  fracionário não satisfaz uma contagem.
- **Anexo A.2 g) contém uma vedação.** "Vedada a utilização do modelo em caso de
  incoerência" entre as características do avaliando e a estrutura de multicolinearidade
  inferida. É a única cláusula do bloco que proíbe o uso do modelo, e depende de juízo
  técnico — correlação > 0,80 é gatilho de exame, não a vedação.
- **VIF não é limiar normativo.** Confirmado: a norma analisa a *matriz de correlações*
  com atenção a resultados > 0,80 e não define corte de VIF. Qualquer limiar de VIF é
  convenção de mercado.

## 4. Fronteira interpretada — item 4 (a), o "100%"

O texto diz que as medidas das características do avaliando "não sejam superiores a
**100 % do limite amostral superior**, nem inferiores à **metade do limite amostral
inferior**".

O piso é literal: `0,5 ×` o mínimo amostral. O teto é ambíguo e foi **decidido
explicitamente**, com a leitura concorrente registrada em código
(`THRESHOLD_PROVENANCE['MEASURE_UPPER_FACTOR']`):

- **Leitura adotada:** até 100% *acima* do limite superior → fator `2,0`.
- **Leitura alternativa:** até 100% *do* limite superior → fator `1,0`.

Justificativa da escolha: (i) com fator `1,0` nenhuma extrapolação seria admissível e os
campos Grau II e Grau I do item 4 ficariam vazios, contra a própria estrutura da
Tabela 1, que enuncia condições para admiti-la; (ii) a condição inferior é expressa como
"metade do limite inferior" (`0,5×`), de modo que a leitura simétrica do par é `0,5×` no
piso e `2,0×` no teto.

Isto é uma interpretação, está marcada como tal (`literal: false`) e é testável. Não é
apresentada como texto da norma.

## 5. Referências cruzadas entre edições

A Parte 2:2011 remete à Parte **1:2001**, edição superada pela Parte 1:2019 que temos em
mãos. Registrado em `normative_rules.CROSS_EDITION_NOTES`:

- **Campo de arbítrio.** 8.2.1.5.1 da Parte 2 quantifica ±15% e cita "3.8 da ABNT NBR
  14653-1:2001". Na Parte 1:2019 a definição foi renumerada para 3.1.9 e **não repete a
  amplitude de 15%**. A quantificação aplicada pelo produto é a da Parte 2:2011 — não uma
  leitura da Parte 1:2019.
- **Conteúdo do laudo.** 10.1 da Parte 2 remete a 7.2/7.3/7.7.2 e à Seção 8 da Parte
  1:2001. A Parte 1:2019 reorganizou essa numeração; a correspondência item a item exige
  conferência e **não** é presumida aqui.

## 6. Dependência externa — vigência das edições

**Estado: `BLOCKED_EXTERNAL_EVIDENCE`** (id da regra: `abnt.vigencia_das_edicoes`).

Tentativas de acesso regular realizadas em 2026-09-11:

| via | resultado |
|---|---|
| `https://www.abntcatalogo.com.br/` | aplicação JavaScript; a home não entrega registro de norma por requisição estática |
| `https://www.abntcatalogo.com.br/norma.aspx?ID=…` | responde "LINK EXPIRADO"; sem dados da norma |
| busca web por revisão de 14653-2 | apenas fontes secundárias, que **não** servem como autoridade de vigência |

Consequência delimitada, e apenas ela:

- **Permanece válido:** os limiares aplicados conferem com as edições
  **efetivamente consultadas** (14653-2:2011 e 14653-1:2019), com SHA-256 registrado.
- **Fica bloqueado:** afirmar conformidade com a edição **vigente**, ou que não há
  emenda/errata posterior.

Material exato necessário para desbloquear: o **registro do catálogo ABNT** para
`ABNT NBR 14653-1` e `ABNT NBR 14653-2` — edição em vigor, status (vigente/cancelada/em
revisão) e atos modificadores — obtido por acesso legítimo ao catálogo (assinatura
ABNT Coleção, consulta ao Sistema Confea/Crea/Mútua, ou aquisição pontual). Responsável:
o titular do projeto, por via autorizada. **Não** foi realizada compra nem contato
institucional nesta campanha.

## 7. Limites de uso desta matriz

1. Conferir limiares contra a norma qualifica o **software**, não qualifica nenhuma
   avaliação específica, não substitui revisão profissional e não constitui aceitação por
   instituição alguma.
2. Nenhuma destas fontes é programa de homologação de software. A ABNT publica normas
   técnicas; não homologa este produto.
3. Ter lido a norma não autoriza redistribuí-la. Esta campanha publica âncoras e
   critérios parafraseados na medida necessária para tornar a regra auditável.
