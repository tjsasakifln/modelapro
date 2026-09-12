# C06-A05 — Perfis institucionais de destinatário (bancário e securitário)

**Campanha:** MP-COM-20260912 / C06
**Status do aceite:** `BLOCKED_EXTERNAL_EVIDENCE`
**Data de elaboração:** 2026-09-11 (data local da sessão; as recuperações de fonte
estão registradas em UTC, 2026-09-12T01:5xZ — não há contradição, apenas fuso)

> Este documento registra **o que as fontes primárias consultadas efetivamente
> dizem**, com URL e data-hora de recuperação. Onde a fonte é silente, está
> escrito que ela é silente — não foi preenchido por memória, por inferência de
> domínio nem por expectativa de mercado. Nenhuma homologação, certificação,
> credenciamento ou aprovação institucional é afirmada neste documento, porque
> nenhuma ocorreu.

---

## 0. Procedência das fontes (três desfechos diferentes)

| Fonte | URL atribuída | Desfecho da recuperação | Recuperado em (UTC) |
|---|---|---|---|
| SUSEP — Seguro Habitacional | `https://www.gov.br/susep/pt-br/assuntos/meu-futuro-seguro/seguros-previdencia-e-capitalizacao/seguros/seguro-habitacional` | **OK.** Recuperada por WebFetch e, para conferência literal das citações, recuperada de novo por `curl` e convertida em texto. Todas as citações abaixo foram conferidas caractere a caractere contra o HTML bruto. | 2026-09-12T01:55Z / 02:0xZ |
| BCB — Resolução CMN 4.676 | `https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=4676&tipo=Resolução` | **PARCIAL — a URL atribuída não entregou texto normativo.** Retornou apenas o cabeçalho "Banco Central do Brasil" (casca JS), sem ementa, sem status e sem articulado. O texto em vigor foi recuperado de **outra URL do próprio BCB** (ver §1.1). A URL atribuída **não** deve ser citada como se tivesse entregue o texto. | 2026-09-12T01:55Z |
| CAIXA — Licitações/Transparência | `https://www.caixa.gov.br/licitacoes/transparencia/Paginas/default.aspx` | **OK, com ressalva de método.** WebFetch falhou (`Too many redirects (exceeded 10)`). A mesma URL foi recuperada com sucesso por `curl` com *cookie jar* e *user-agent* de navegador (HTTP 200, 317.977 bytes). Não está bloqueada; está registrada a forma de obtenção. | 2026-09-12T01:56Z |

Nenhuma fonte foi substituída por memória. Onde uma URL falhou, a recuperação
alternativa está nomeada.

---

## 1. Perfil BANCÁRIO — o que a norma em vigor diz

### 1.1 Texto efetivamente consultado

A URL atribuída do BCB é uma casca JavaScript. O texto consolidado foi obtido em:

`https://normativos.bcb.gov.br/Lists/Normativos/Attachments/50628/Res_4676_v17_P.pdf`

**Snapshot consolidado v17 consultado.** A consulta histórica obteve HTTP 200
para `v13`–`v17` e 404 para nomes hipotéticos `v18`–`v20`; isso **não prova** que
v17 seja a consolidação mais recente. A vigência deve ser conferida pela ficha
oficial e seus atos alteradores. Ver a [conferência C06 de processos e fontes](profile-process-verification-20260912.md).
A primeira extração desta sessão foi feita sobre a **v12** e foi **descartada**:
o PDF consolidado empilha a redação revogada imediatamente acima da redação
vigente, e citar a v12 publicaria como atual um texto já superado.

**Ementa EM VIGOR desde 1º/7/2025 (verbatim, v17, redação dada pela Resolução
CMN nº 5.197, de 19/12/2024):** "Dispõe sobre os integrantes do Sistema
Brasileiro de Poupança e Empréstimo – SBPE, do Sistema Financeiro da Habitação –
SFH e do Sistema de Financiamento Imobiliário – SFI, as condições gerais e os
critérios para contratação de operação de crédito imobiliário pelas instituições
financeiras e demais instituições autorizadas a funcionar pelo Banco Central do
Brasil e disciplina o direcionamento dos recursos captados em depósitos de
poupança."

**Ementa SUPERADA (verbatim, redação original de 31/7/2018, vigente até
30/6/2025 — reproduzida aqui apenas para identificar a armadilha, NÃO é o texto
em vigor):** "Dispõe sobre os integrantes do Sistema Brasileiro de Poupança e
Empréstimo (SBPE), do Sistema Financeiro da Habitação (SFH) e do Sistema de
Financiamento Imobiliário (SFI), as condições gerais e os critérios para
contratação de financiamento imobiliário pelas instituições financeiras e demais
instituições autorizadas a funcionar pelo Banco Central do Brasil e disciplina o
direcionamento dos recursos captados em depósitos de poupança."

As duas redações estão **empilhadas** no PDF consolidado v17 (a superada
imediatamente acima da vigente), e só a segunda é seguida do marcador de
vigência. A diferença operativa é "contratação de **financiamento imobiliário**"
(superada) contra "contratação de **operação de crédito imobiliário**" (em
vigor). Ver §1.6 — este documento já publicou a redação errada e o registro da
correção está lá.

**Atos alteradores citados no próprio texto consolidado v17** (conjunto obtido por
`grep -oE "Resolução( CMN)? nº [0-9]\.[0-9]{3}" | sort -u` sobre o texto extraído,
subtraindo a lista de revogações do art. 27 e a referência cruzada à Resolução
nº 3.811/2009, que não é ato alterador): Resoluções nº **4.691**/2018,
**4.739**/2019, **4.754**/2019, **4.763**/2019, **4.774**/2020, **4.819**/2020,
**4.837**/2020, e Resoluções CMN nº **4.909**/2021, **4.925**/2021, **5.048**/2022,
**5.055**/2022, **5.119**/2024, **5.197**/2024, **5.208**/2025 e **5.255**/2025.
Nenhum ato alterador foi presumido de memória.

**Método de conferência das citações — o que ele faz e o que ele NÃO faz.**

A conferência é executada por `scripts/comercial/aceite/verify_c06.py`, que
**extrai as passagens deste próprio documento** (todo trecho entre aspas retas,
depois de removidos os trechos entre crases) e as confronta com os textos-fonte
persistidos em `docs/comercial/c06/sources/` (procedência, URL, hash e comando de
extração em `sources/MANIFEST.md`). O vínculo documento→fonte é **testado**, não
afirmado: alterar uma citação neste arquivo faz o script falhar.

*Correção de uma afirmação anterior deste documento.* Uma versão anterior desta
seção dizia que "contagem igual a 1 demonstra que não existe, para aquela
passagem, redação empilhada superada". **Isso é logicamente falso e foi
removido.** Uma redação superada empilhada é uma *cadeia de caracteres
diferente*, logo ela também ocorre exatamente uma vez. Contraprova no próprio
v17: o caput do art. 6º em vigor ("A cota de crédito não pode ser superior a")
tem contagem 1, e o seu gêmeo superado ("garantia, na data da contratação, não
pode ser superior a") **também** tem contagem 1. Ocorrência única demonstra
apenas que a passagem não foi duplicada na extração — nada sobre vigência.

*O que efetivamente detecta redação empilhada (regra de adjacência de marcador).*
No PDF consolidado do BCB a redação em vigor é **imediatamente seguida** do seu
marcador de vigência — `(Redação dada ... pela Resolução CMN nº ...)`,
`(Incluído, a partir de ... pela Resolução CMN nº ...)`, `(Parágrafo ... incluído
pela Resolução nº ...)` — enquanto a redação superada fica separada desse
marcador por **toda a redação substituta empilhada entre as duas**. O script
mede, para cada passagem citada da Res. 4.676, a distância em caracteres entre o
fim da passagem e o primeiro marcador seguinte, e exige:

- passagem declarada **EM VIGOR**: distância ≤ 40 caracteres (adjacente ao
  marcador), e o marcador encontrado tem de bater com o ato alterador que este
  documento atribui à passagem;
- passagem declarada **SUPERADA**: distância > 40 caracteres (separada do
  marcador pela redação substituta);
- passagem declarada **SEM MARCADOR DE VIGÊNCIA EM V17**: nenhum marcador dentro
  da janela de 900 caracteres seguintes.

As distâncias medidas são **impressas** pelo script, para que a margem fique
visível ao revisor e não escondida numa constante. Nas medições atuais o vale é
largo: as passagens em vigor ficam entre 2 e 4 caracteres do marcador e as duas
superadas ficam a 56 e 457 caracteres — o limiar de 40 não está perto de
nenhuma borda. A regra de adjacência é **exclusiva da fonte BCB**: as fontes
SUSEP e CAIXA são páginas HTML sem empilhamento de redações, e para elas o script
faz apenas a conferência literal.

**Cobertura exata — o que é e o que não é conferido.** Não se afirma mais que
"cada passagem" está conferida por um comando genérico. O que o script garante é:
toda cadeia entre aspas retas deste documento ou (a) é encontrada literalmente
(módulo espaços em branco, que a extração de PDF quebra de forma arbitrária) em
um dos três textos-fonte persistidos, ou (b) consta da **lista de exclusões** do
script — que o script **imprime**, entrada por entrada, com o motivo. As
exclusões são apenas trechos que não são citação de fonte (rótulos nossos,
expressões buscadas e não encontradas, formulações comerciais proibidas). Se uma
passagem nova aparecer no documento sem estar em fonte nem na lista, o script
falha. As citações da CAIXA, que antes não eram conferidas por comando nenhum,
passaram a ser conferidas contra `sources/caixa.txt`.

A conferência é reproduzível por qualquer revisor **sobre este repositório**:
`python3 scripts/comercial/aceite/verify_c06.py`. Estado atual: `PASS=89
FAIL=0`.

**Prova de que a conferência morde (mutantes).** Um script que passa não prova
nada se não puder falhar. A versão anterior desta conferência (`verify_c06.sh`,
em *scratchpad* de sessão) lia apenas os arquivos-fonte, procurando cadeias
redigitadas dentro do próprio script; substituir **todos** os blocos citados
deste documento por `TEXTO TOTALMENTE INVENTADO QUE NAO EXISTE EM FONTE NENHUMA`
ainda assim imprimia `PASS=21 FAIL=0` e saía com código 0. O vínculo
documento→fonte era afirmado, não testado. Três mutantes foram executados sobre
cópias deste documento fora do repositório, com o script novo:

| Mutante | O que foi alterado | Resultado |
|---|---|---|
| M1 — o ataque exato do verificador | os 73 blocos entre aspas substituídos por texto inventado | `PASS=24 FAIL=75`, saída 1 |
| M2 — uma palavra numa única citação | art. 13, I: `R$2.250.000,00` → `R$2.500.000,00` | `PASS=86 FAIL=2`, saída 1 |
| M3 — a armadilha original | a ementa em vigor trocada pela redação superada de 2018 | `PASS=88 FAIL=1`, saída 1 |

M3 é o que importa mais: é exatamente o defeito que este documento cometeu
(§1.6), e a regra de adjacência de marcador somada à exigência de que **toda
regra de vigência declarada seja acionada por alguma passagem** faz o script
reprovar em vez de aprovar em silêncio.

Entre as passagens citadas neste documento não há redação com vigência futura:
todas as datas escalonadas associadas a elas (1º/6/2022, 1º/7/2025, 10/10/2025)
são anteriores à data deste documento.

### 1.2 Base de valor efetivamente exigida

A norma **não usa a expressão "valor de mercado"**. Busca insensível a
maiúsculas por `valor de mercado` no texto consolidado v17 retorna **0
ocorrências**. O termo operativo é **"valor de avaliação"**.

- **Art. 6º (redação dada, a partir de 1º/7/2025, pela Res. CMN nº 5.197/2024):**
  "A cota de crédito não pode ser superior a:" — I, 80% para financiamento a
  pessoa natural para aquisição ou construção de imóvel residencial; II, 60% em
  *home equity*; com até 90% no caso de SAC ou Sacre.
- **Art. 1º-A, XI (incluído, a partir de 1º/7/2025, pela Res. CMN nº 5.197/2024):**
  "cota de crédito: o percentual resultante da razão entre o valor nominal da
  operação de crédito imobiliário, compreendendo principal e despesas
  acessórias, e **o valor de avaliação do imóvel dado em garantia**, apurado na
  data da contratação." — isto é: a reescrita de 2024 trocou a redação do art. 6º,
  mas a dependência do **valor de avaliação** permanece, agora pela definição.
- **Art. 13, I (redação dada pela Res. CMN nº 5.255, de 10/10/2025):** "limite
  máximo do valor de avaliação do imóvel financiado de R$2.250.000,00 (dois
  milhões duzentos e cinquenta mil reais)" — substituiu o limite anterior de
  R$1.500.000,00.
- **Art. 11-A (incluído, a partir de 1º/6/2022, pela Res. CMN nº 4.925/2021):**
  "Para fins desta Resolução, a avaliação de imóvel compreende: I - a análise
  técnica efetuada para a estimação do valor de um bem imóvel, com base em suas
  especificações, características, custos, frutos, direitos e finalidade; e II -
  a análise jurídica efetuada para determinar riscos que possam repercutir sobre
  a viabilidade da utilização do bem imóvel como garantia, incluindo a
  confirmação da titularidade, da livre disposição do imóvel e da inexistência de
  ônus ou impedimentos."

**Leitura honesta:** a base é *valor de avaliação*, definida por uma análise
técnica que considera especificações, características, **custos**, frutos,
direitos e **finalidade** — conceito mais amplo do que "valor de mercado", e que
não é sinônimo dele. Traduzir "valor de avaliação" por "market value" em material
comercial seria uma afirmação que a norma não faz. A norma também acopla à
avaliação uma **análise jurídica** (titularidade, ônus) que este software **não**
produz — e isso é limitação a declarar, não a omitir.

### 1.3 O que a norma diz sobre quem faz a avaliação, e sobre modelos

- **Art. 11, I, "b":** "a avaliação do imóvel deve ser efetuada por profissional
  **sem qualquer vínculo com a área de crédito da instituição proponente** ou com
  outras áreas que possam implicar conflito de interesses ou configurar
  deficiência na segregação de funções".
- **Art. 11, § 4º (incluído pela Res. nº 4.754, de 26/9/2019)** — o dispositivo
  mais próximo de "requisitos para software de avaliação" em toda a norma:
  "Para fins de apuração do valor do imóvel [...] a instituição proponente pode,
  alternativamente, empregar **modelo de precificação próprio ou de terceiros**,
  desde que:
  I - o modelo seja baseado em critérios, premissas e procedimentos consistentes,
  documentados e passíveis de verificação;
  II - o modelo e os sistemas internos de gerenciamento de risco e de
  monitoramento de garantias da instituição sejam capazes de demonstrar que a
  análise do risco da operação justifica eventual dispensa de visita de inspeção
  ao imóvel;
  III - os profissionais responsáveis pelos modelos não possuam qualquer vínculo
  com a área de crédito da instituição ou com outras áreas que possam implicar
  conflito de interesses ou configurar deficiência na segregação de funções; e
  IV - o modelo propicie a geração de **relatório individualizado da precificação
  do imóvel**, incluindo o exame dos aspectos relevantes e dos riscos inerentes à
  estimação do valor do imóvel."
- **Art. 8º-A, § 2º, III:** condiciona a cobrança de tarifa de avaliação à
  "entrega ao mutuário ou pretendente ao crédito de extrato do laudo de avaliação
  ou documento equivalente, contendo a análise técnica de que trata o art. 11-A,
  inciso I".
- **Art. 11, § 2º:** "As informações utilizadas na avaliação e concessão do
  crédito devem permanecer à disposição do Banco Central do Brasil durante a
  vigência da operação, preferencialmente em formato eletrônico."

### 1.4 Existe programa formal de HOMOLOGAÇÃO DE SOFTWARE? **Não, segundo esta fonte.**

Busca insensível a maiúsculas por `homolog` e por `software` sobre o texto
consolidado v17 da Resolução CMN 4.676 retorna **0 ocorrências** (busca
reproduzível: `grep -ci -E "homolog|software"` sobre o texto extraído do PDF v17).

A norma **não cria** registro, cadastro, lista, selo, certificado ou órgão
aprovador de software de avaliação. Ela impõe condições **à instituição
financeira** sobre o modelo que ela usa — próprio ou de terceiros — e não
qualifica o fornecedor do modelo.

**O que é efetivamente exigido, em vez de homologação:** que o modelo seja
documentado, verificável e auditável; que gere relatório individualizado por
imóvel com exame de riscos; que os responsáveis técnicos não tenham vínculo com a
área de crédito; e que as informações fiquem à disposição do BCB. Em outras
palavras, **o caminho comercial real é ser aprovável na diligência interna da
instituição** (documentação, rastreabilidade, reprodutibilidade), não obter um
carimbo.

> **Proibição explícita neste projeto:** é vedado emitir, exibir ou sugerir
> qualquer "certificado interno" que carregue o nome de banco, seguradora ou
> regulador. Nenhuma instituição aprovou este software. Qualquer peça comercial
> que insinue o contrário é falsa.

### 1.5 CAIXA — o que a página de Licitações/Transparência efetivamente mostra

Recuperada em 2026-09-12T01:56Z (método em §0). A página contém:

- Título e chamada, em linhas distintas da página: "Transparência Licitações
  CAIXA" e "Acompanhe os contratos, fornecedores e pagamentos da CAIXA."
- "Transparência é fundamental para que a população acompanhe, participe e
  fiscalize todos os processos licitatórios. Desde os já concluídos aos **em
  credenciamento**, em andamento ou em disputa."
- "Além de ético e moral, a transparência em licitações é assegurada pela Lei
  13.202/2016 em seus artigos 48 e 88." *(citação reproduzida exatamente como
  impressa na página na data de recuperação; não foi corrigida por nós.)*

  **Nota ao revisor — isto aparenta ser erro da própria página, e não deve ser
  carregado adiante.** O bloco "Legislação" **da mesma página** cita "Lei n°
  13.303/2016 – Dispõe sobre o estatuto jurídico da empresa pública, da sociedade
  de economia mista e de suas subsidiárias, no âmbito da União, dos Estados, do
  Distrito Federal e dos Municípios." É esse o diploma que a página trata como
  base das compras da CAIXA, e é ele que tem arts. 48 e 88 sobre transparência e
  sanções. A atribuição dos mesmos artigos à "Lei 13.202/2016" na frase acima é,
  portanto, internamente inconsistente com a própria página. **Não lemos o texto
  da Lei 13.202/2016 nesta sessão** e não afirmamos aqui qual é o objeto dela; o
  que se afirma é apenas a inconsistência interna da fonte. Nenhum material
  comercial deste projeto deve repetir a citação "Lei 13.202/2016" como se fosse
  a base de transparência das licitações da CAIXA.
- Ferramenta de consulta eletrônica a "Licitações instauradas" e "Contratos
  Assinados", com filtros (modalidade, número do certame, ano, contrato,
  vigência, valor, objeto, fornecedor, CNPJ/CPF, situação).
- "Código de Conduta do Fornecedor Caixa."  *(assim impresso, minúsculas e
  maiúsculas incluídas)*
- Bloco "Legislação" citando: Lei 8.666/1993, Lei 10.520/2002, Lei n° 13.303/2016,
  Lei Complementar 123/2006, Lei 12.349/2010, Decreto 5.504/2005, Decreto
  7.546/2011.
- "Regulamento de licitações e contratos da Caixa", com link para download
  *(a página imprime em caixa baixa; transcrito como impresso)*.

**Interpretação correta e armadilha a evitar:** a palavra "credenciamento" nessa
página designa **uma fase/modalidade de processo de compra (credenciamento de
fornecedores)**, dentro do canal de licitações. **Não** é credenciamento de
software de avaliação nem selo técnico. Inflar isso em "a CAIXA credencia
software de avaliação" seria falsificação.

**O que esta página NÃO responde** (e que, portanto, fica em aberto): se e como a
CAIXA credencia **profissionais ou empresas** de avaliação de imóveis. A fonte
atribuída é silente e nenhuma outra fonte foi consultada para isso. Pergunta
**não resolvida** — não preenchida por memória.

---

### 1.6 Registro de correção — seleção de versão errada na ementa (v17 empilhada)

Este registro existe porque a correção é substantiva e não pode ser feita em
silêncio.

**O que estava errado.** A versão anterior deste documento apresentava, sob o
título "Texto efetivamente consultado", a ementa terminada em "...e os critérios
para contratação de **financiamento imobiliário** pelas instituições
financeiras...", sem qualquer qualificador de versão. Essa é a **redação
originária de 31/7/2018, superada desde 1º/7/2025** pela Resolução CMN nº 5.197,
de 19/12/2024 — isto é, superada havia catorze meses na data deste documento.

**O que isto é, com precisão.** Não é citação fabricada: a cadeia de caracteres
existe literalmente no PDF consolidado v17. É **seleção de versão errada** dentro
de um texto consolidado empilhado — exatamente o erro que o método declarado na
§1.1 dizia prevenir e não prevenia, porque a regra usada (ocorrência única) não
discrimina vigência. O erro e a insuficiência do método são da mesma raiz.

**Como foi corrigido.** A ementa em vigor passou a ser citada primeiro e
identificada como tal com a data e o ato alterador; a redação superada
permanece no documento, mas rotulada como superada e com o período de vigência.
O método foi substituído pela regra de adjacência de marcador (§1.1), que é
executada pelo script e cuja saída imprime a distância medida em cada passagem.

**Rechecagem exaustiva das demais passagens da Res. CMN 4.676 citadas aqui.**
Todas foram reexaminadas quanto à mesma armadilha. O resultado abaixo é
reproduzido pelo script a cada execução:

| Passagem citada | Situação em v17 | Distância medida até o marcador |
|---|---|---|
| Ementa — redação em vigor | **EM VIGOR**, marcador Res. CMN 5.197/2024, a partir de 1º/7/2025 | adjacente |
| Ementa — redação originária | **SUPERADA**, separada do marcador pela redação substituta | 457 caracteres |
| Art. 6º, caput — redação em vigor | **EM VIGOR**, marcador Res. CMN 5.197/2024, a partir de 1º/7/2025 | adjacente (2–3) |
| Art. 6º, caput — gêmeo superado | **SUPERADA**, separada do marcador pela redação substituta | 56 caracteres |
| Art. 1º-A, XI | **EM VIGOR**, marcador "(Incluído, a partir de 1º/7/2025, pela Resolução CMN nº 5.197, de 19/12/2024.)" | adjacente |
| Art. 13, I | **EM VIGOR**, marcador Res. CMN 5.255, de 10/10/2025 | adjacente |
| Art. 11-A, I e II | **EM VIGOR**, marcador "(Artigo 11 -A incluído, a partir de 1º/6/2022, pela Resolução CMN nº 4.925, de 24/6/2021.)" | adjacente (2) |
| Art. 11, § 4º, I a IV | **EM VIGOR**, marcador "(Parágrafo 4º incluído pela Resolução nº 4.754, de 26/9/2019.)" | adjacente |
| Art. 8º-A, § 2º, III | **sem marcador de vigência na janela seguinte, em v17** | — |
| Art. 11, § 2º | **sem marcador de vigência na janela seguinte, em v17** | — |
| Art. 11, I, "b" | **sem marcador de vigência na janela seguinte, em v17** | — |

A coluna "sem marcador de vigência na janela seguinte" é uma afirmação **sobre o
que a fonte mostra**, não uma inferência de que o dispositivo nunca foi alterado:
significa apenas que, no v17, nenhum marcador de redação/inclusão/revogação
aparece nos 900 caracteres seguintes à passagem transcrita. Não se afirma aqui
que o art. 11, I, "b", o art. 8º-A, § 2º, III e o art. 11, § 2º jamais foram
alterados — apenas que a fonte consultada não lhes apõe marcador nessa janela
posterior.

*Segunda correção, produzida pelo próprio script.* Uma redação intermediária
deste registro classificava o art. 11-A como estando sem marcador de vigência,
e datava o ato de inclusão de forma errada. O script mediu marcador adjacente a 2 caracteres e reprovou a classificação: o
art. 11-A é **EM VIGOR** com marcador "(Artigo 11 -A incluído, a partir de
1º/6/2022, pela Resolução CMN nº 4.925, de 24/6/2021.)" — coerente, aliás, com
o que a §1.2 já atribuía ao dispositivo. A afirmação foi corrigida antes da
publicação. Registra-se porque é a demonstração de que a conferência agora
morde o documento, e não apenas a fonte.

**Outro empilhamento presente no v17 e NÃO citado neste documento.** O art. 1º
traz o mesmo par empilhado da ementa (redação originária com "financiamento
imobiliário" seguida da redação de 1º/7/2025 com "operação de crédito
imobiliário"). Ele é registrado aqui para mostrar que a rechecagem foi
exaustiva, e continua **não** sendo citado — não porque seja irrelevante, mas
porque nada neste documento depende dele.

---

## 2. Perfil SECURITÁRIO — o que a SUSEP efetivamente publica

Fonte: página SUSEP "Seguro Habitacional", recuperada em 2026-09-12 (§0). A
página se refere ao **Seguro Habitacional em Apólices de Mercado – SH/AM**. A
página **exibe referência** à Resolução CNSP nº 447, de 10 de outubro de 2022, mas
**não** a apresenta como base geral do SH/AM: a menção aparece restrita a
consórcios — "Também se enquadram no rol dos imóveis do seguro habitacional
aqueles que correspondem às operações de consórcios, devendo ser consideradas, no
que couber, as disposições constantes da Resolução CNSP nº 447, de 10 de outubro
de 2022." A base normativa geral do SH/AM **não está declarada nesta página** (ver
§2.4). A página registra "Publicado em 14/09/2022" e "Modificado em 03/11/2022".

### 2.1 Coberturas

"O Seguro Habitacional em Apólices de Mercado – SH/AM deverá garantir
obrigatoriamente coberturas securitárias que prevejam, no mínimo, os riscos de
morte e invalidez permanente (MIP) do segurado e/ou de danos físicos ao imóvel
(DFI), de acordo com a operação de financiamento de imóvel contratada."

Riscos de DFI listados na página: "Incêndio, queda de raio ou explosão",
"Vendaval", "Desmoronamento total", "Desmoronamento parcial", "Ameaça de
desmoronamento, devidamente comprovada", "Destelhamento", "Inundação ou
alagamento, ainda que decorrente de chuva". A página registra ainda que "Poderão
ser oferecidas nas apólices de SH/AM, em caráter facultativo, outras coberturas
além das descritas acima."

### 2.2 Base de valor — duas grandezas distintas, não sinônimas

Este é o ponto central para o perfil securitário. A página distingue:

1. **Limite máximo de garantia (DFI)** — ancorado no valor de avaliação:
   "O limite máximo de garantia correspondente à cobertura dos riscos de DFI
   consistirá, **em qualquer tempo, do valor da avaliação inicial do imóvel**, que
   serviu de base para a operação de financiamento, devidamente atualizado com
   base no índice convencionado no contrato de seguro."
   E: "No caso de contratos de financiamento sem previsão de cláusula de
   atualização, o valor de avaliação inicial do imóvel será atualizado com base no
   índice e periodicidade definidos no respectivo contrato de seguro."
2. **Indenização (DFI)** — lógica de reposição/reconstrução:
   "Para a cobertura dos riscos de DFI, a indenização, respeitado o limite máximo
   de garantia vigente na data do sinistro, corresponderá ao **valor necessário à
   reposição do imóvel ao estado equivalente ao que se encontrava imediatamente
   antes do sinistro**."
3. **Limite máximo de garantia (MIP)** — dívida, não imóvel: "consistirá, a cada
   mês, do valor do saldo devedor do financiamento do imóvel, consideradas pagas
   todas as prestações vencidas e as eventuais amortizações já pagas."

**Consequência prática:** *valor de mercado*, *custo de reedificação/reposição* e
*valor atual depreciado* **não são sinônimos**, e o SH/AM usa grandezas
diferentes em pontos diferentes do contrato: o **teto** vem do valor de avaliação
inicial atualizado por índice; a **indenização** é medida por custo de reposição
ao estado anterior. Um produto que entrega apenas valor de mercado por inferência
de mercado **não** entrega, por si, a grandeza de reposição. Isso deve constar
como limitação declarada em qualquer laudo destinado a fim securitário (ver caso
RC-08 em `real_case_matrix.md`).

A expressão "valor de mercado" **não ocorre** na página SUSEP consultada
(0 ocorrências no texto extraído).

### 2.3 Existe programa formal de HOMOLOGAÇÃO DE SOFTWARE? **Não, segundo esta fonte.**

Buscas insensíveis a maiúsculas sobre o texto extraído da página SUSEP retornam
**0 ocorrências** para `homolog`, `software`, `laudo` e `vistoria`.

A página **não** institui programa de homologação de sistemas de avaliação, não
menciona software aprovado, e sequer descreve, nesta página, o processo de
vistoria ou de aceitação de laudo. O que ela estabelece é a **grandeza
contratual** que o seguro usa (§2.2). O processo de aceitação documental do lado
da seguradora **não está descrito nesta fonte** — pergunta em aberto, não
preenchida por memória.

### 2.4 Aberto e não respondido pela fonte

- Tratamento do **terreno** sob a cobertura DFI (a página não trata do ponto).
- Requisitos documentais concretos que a seguradora exige de um laudo.
- Se existe qualquer cadastro de prestadores de avaliação no âmbito SH/AM.
- Qual é a base normativa geral do SH/AM: a página não a declara; a única
  resolução citada (CNSP nº 447/2022) aparece referida a consórcios.

Estes itens ficam registrados como **não respondidos pela fonte primária
consultada** e não devem ser preenchidos por conhecimento geral.

---

## 3. Os quatro escopos que não podem ser confundidos

Esta seção existe porque a confusão entre eles é a principal fonte de afirmação
comercial falsa neste domínio. São **quatro coisas diferentes**, com titulares
diferentes, objetos diferentes e provas diferentes.

| # | Escopo | Objeto qualificado | Quem confere | Prova típica | Temos evidência recuperada? |
|---|---|---|---|---|---|
| 1 | **Qualificação do SOFTWARE** | O sistema/modelo em si | — **Nenhum programa formal identificado** nas fontes consultadas | — | **Sim, evidência negativa.** `homolog`/`software` = 0 ocorrências na Res. CMN 4.676 v17 e na página SUSEP. O que existe é o art. 11, §4º: condições de documentação, verificabilidade, independência e relatório individualizado, exigidas **da instituição** sobre o modelo que ela usa |
| 2 | **Conformidade de uma AVALIAÇÃO específica** | Um trabalho técnico concreto, com data-base, método e amostra | O responsável técnico e, em revisão, o destinatário | O próprio laudo, com memória de cálculo e diagnósticos | Parcial: art. 11-A define o que a avaliação compreende (análise técnica **e** jurídica); a análise jurídica está **fora** do escopo deste software |
| 3 | **Revisão/assinatura do PROFISSIONAL responsável** | A pessoa habilitada que responde tecnicamente | Conselho profissional / regime de assinatura aplicável | Registro profissional, responsabilidade técnica, assinatura | **Não fetchado.** Nenhuma fonte sobre credenciamento profissional (conselhos, responsabilidade técnica) ou sobre regimes de assinatura digital foi recuperada nesta sessão. O escopo é nomeado aqui; seu conteúdo **não** é afirmado |
| 4 | **Aceitação pelo DESTINATÁRIO** | A decisão do banco/seguradora de acolher aquele laudo | A própria instituição, na sua diligência interna | Aprovação interna do processo de crédito/sinistro | Sim, indiretamente: Res. CMN 4.676 art. 11, I, "b" (avaliador sem vínculo com a área de crédito), art. 11, §4º (condições do modelo), art. 11, §2º (informações à disposição do BCB); SUSEP (grandeza contratual do SH/AM) |

**Regras que decorrem disso:**

- Passar em (2) não produz (1). Um laudo conforme não qualifica o software.
- Ter (3) não produz (4). Um profissional habilitado assinando não obriga a
  instituição a aceitar.
- Obter (4) uma vez não produz (1). Um laudo aceito por um banco não é
  homologação do sistema, e não pode ser anunciado como tal.
- **Credenciamento profissional, assinatura digital, aceitação de laudo e
  aprovação de software são quatro escopos distintos.** Nenhum implica outro.
- **Vedado:** emitir "certificado" com nome de instituição; dizer "homologado
  pelo/para o Banco X"; dizer "aprovado pela SUSEP/BCB/CAIXA"; usar logotipo
  institucional como se indicasse aprovação. Nada disso ocorreu.

---

## 4. Status do aceite e atos externos ainda necessários

`C06-A05 = BLOCKED_EXTERNAL_EVIDENCE`.

O que este documento **entrega**: o levantamento das fontes primárias
efetivamente recuperadas, com citações conferidas, e o registro fundamentado de
que **não foi identificado programa formal de homologação de software de
avaliação** nem no lado bancário (Res. CMN 4.676, texto em vigor) nem no lado
securitário (página SUSEP do SH/AM).

O que **falta**, e que só um ato externo pode produzir:

| # | Ato externo necessário | Quem pratica |
|---|---|---|
| E1 | Confirmação formal, por instituição destinatária concreta, dos requisitos documentais que ela exige de um laudo (não há substituto público para isso) | Área técnica/credito da instituição destinatária |
| E2 | Autorização do responsável pelo projeto para abrir contato institucional — **não concedida nesta sessão** | Direção do projeto |
| E3 | Levantamento das exigências de credenciamento profissional e de regime de assinatura aplicáveis (escopo 3 da §3), a partir de fontes primárias ainda não consultadas | Responsável técnico, com consulta às fontes dos conselhos |
| E4 | Esclarecimento, junto à CAIXA, sobre credenciamento de profissionais/empresas de avaliação — questão não respondida pela página atribuída | Canal institucional da CAIXA |
| E5 | Revisão da redação comercial e condições concretas de destinatário; as fontes examinadas não comprovam programa geral nem sua inexistência universal | Responsável pela oferta / assessoria designada |

Até que E1–E5 existam, o material comercial deve afirmar apenas o que é
verificável: que o produto **produz documentação, memória de cálculo e
rastreabilidade compatíveis com as condições do art. 11, §4º, da Resolução CMN
4.676** — e nada além disso. Não há homologação, não há certificação e não há
aprovação institucional.
