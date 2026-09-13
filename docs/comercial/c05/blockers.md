# C05 — Dependências externas objetivas (BLOCKED_EXTERNAL_EVIDENCE)

Cada item traz o **material exato**, o **emissor**, as **rotas tentadas** e o
**responsável**. Nenhum contato institucional foi disparado, nenhuma compra foi feita e
nenhum dado foi enviado a instituição alguma nesta campanha.

Os blocos estão em ordem de impacto sobre os critérios de aceite.

## 1. Condições contratuais de um produto securitário comercializado — bloqueia C05-A06

| campo | conteúdo |
|---|---|
| material exato | Condições gerais, nota técnica ou apólice de um seguro habitacional **efetivamente comercializado**, que declare a base de valor, componentes incluídos e excluídos, índice e periodicidade de atualização, documentação exigida e forma de conclusão do trabalho |
| emissor | seguradora do ramo habitacional, ou o agente financeiro que intermedia a apólice |
| Circular 677/2022 | Recuperada na retomada C06; disciplina CESH e não resolve método/base de avaliação. Não é dependência ausente; ver [conferência e hash](../c06/profile-process-verification-20260912.md) |
| rotas tentadas | Atos recuperados do próprio emissor. A lacuna restante é o contrato/produto concreto, não um requisito de software presumido |
| por que bloqueia | A Res. CNSP 447/2022 foi **conferida em texto integral** e é **expressamente silente quanto à base de valor**. Há um teto procedimental (Art. 19, LMG = valor da avaliação inicial indexado) e uma medida indenizatória de sabor reconstrutivo (Art. 30, reposição ao estado imediatamente anterior ao sinistro), **sem a ponte entre as duas**. Essa ponte está no contrato, não no ato |
| responsável | titular do projeto, por via autorizada |

**Efeito delimitado:** A06 fica `NOT_MET`. A alegação de perfil securitário está
bloqueada. Permanece válido o que foi conferido: a regra do LMG do DFI e do MIP, em fonte
primária, tensada "conforme publicado no DOU de 14/10/2022".

## 2. Edital de Credenciamento BB nº 2024/00940(7421) — limita a força de C05-A05

| campo | conteúdo |
|---|---|
| material exato | Edital 2024/00940, GUIAR e MECI aplicáveis à ordem concreta, com revisão e hashes. A retomada recuperou GUIAR VER02, mas não confirmou VER04 nem demonstrou qual revisão é corrente; ver [conferência C06](../c06/profile-process-verification-20260912.md) |
| emissor | Banco do Brasil S.A., DISEC / Cesup Compras e Contratações (SP) |
| rotas tentadas | `bb.com.br` responde **HTTP 403 a todo cliente não-navegador**. Os PDFs do MECI e das Normas para elaboração de laudos foram obtidos em sessão de navegador real na própria origem; o anexo do edital não foi localizado como URL pública |
| rota que deve ser tentada primeiro | ler o `href` da âncora "Edital 2024/00940" na página oficial de downloads do BB e buscá-lo na mesma origem, exatamente como os PDFs do MECI foram obtidos |
| responsável | titular do projeto, por navegador na página oficial de downloads do BB |

**Efeito delimitado:** A05 está **atendido em força moderada** com o que foi obtido — o
MECI e as Normas para elaboração de laudos são fonte primária do emissor e trazem método,
formato e regras. O que fica bloqueado é: (i) asserir qualquer item **GUIAR** como
requisito vinculante atual, pois a vigência das citações disponíveis não foi estabelecida; (ii) afirmar
que `MECI-202400940-VER01` é a revisão **corrente**. Redação obrigatória: "conforme
publicado em MECI-202400940-VER01, cuja vigência não foi estabelecida". Vedado: "o MECI
vigente", "o BB exige hoje".

## 3. Requisitos de LAUDO da CAIXA — lacuna real de escopo

| campo | conteúdo |
|---|---|
| material exato | Documento vigente da CAIXA que estabeleça requisitos de **laudo de avaliação** (manual, caderno de encargos ou modelo de laudo) |
| emissor | Caixa Econômica Federal |
| rotas tentadas | Portal Licitações CAIXA (SICVE, `licitacoes.caixa.gov.br`) — bloqueado por interstício anti-bot. Obtido, em contrapartida, o **Edital CR 012/2026** autopublicado pela CAIXA no PNCP |
| por que ainda bloqueia | O edital obtido governa **relatórios de precificação por AVM**, não laudos: no texto lido, "laudo" ocorre **zero** vezes e "ABNT" **zero** vezes. Provenance forte não amplia escopo |
| responsável | titular do projeto, por navegador no portal da CAIXA |

**Efeito delimitado:** a CAIXA entra como **segundo perfil bancário**, em estado
`discovery`, com escopo AVM colado a toda citação. Nada nele estabelece como a CAIXA
especifica, verifica ou aceita um laudo.

## 4. Vigência das edições ABNT NBR 14653-1 e -2 — limita a redação de C05-A01

Detalhado em [`sources.md` §6](sources.md). Material exato: o **registro do catálogo
ABNT** para cada parte (edição em vigor, status, atos modificadores). O catálogo é
aplicação JavaScript e não entrega o registro por requisição estática; a URL de norma
responde "LINK EXPIRADO".

**Efeito delimitado:** permanece válido que os limiares conferem com as edições
**efetivamente consultadas**, com SHA-256 registrado e reconferível. Fica bloqueado
afirmar conformidade com "a edição vigente" ou ausência de emenda posterior.

## 5. Fonte de custo por caso — não bloqueia mais a implementação

A rota `MP-COST/1` e seu consumidor estão integrados. O material exato continua sendo
uma fonte de custo autorizada para o **caso** — orçamento sintético identificado ou série
CUB aplicável por região/padrão, conforme a modalidade declarada — além das memórias de
BDI e depreciação. Esses insumos não são incorporados ao produto e não são inferidos de
preço de mercado. Ausência ou invalidade reprova o cálculo daquele caso; não justifica um
bloqueio global de software. Ver [`handoff.md` §2.4](handoff.md).

## 6. Blocos que NÃO devem consumir orçamento de recuperação

Registrados por completude, com o efeito real de cada um:

| item | por que é decorativo aqui |
|---|---|
| Ficha oficial do normativo BCB da Res. 4.676/2018 (campo "Situação" e lista de alterações) | o texto consolidado **v17** está conferido byte a byte (md5 `e6da5788…f092fd3`); nenhum critério depende do flag, desde que a redação permaneça "conforme consolidado na v17" |
| Texto consolidado da Res. CNSP 447/2022 | afeta apenas o **tempo verbal** da redação de A06, e A06 já está bloqueado por outro fundamento (item 1) |
| Texto integral da LGPL-2.1 (libquadmath nos wheels de numpy/scipy) | é obrigação de **empacotamento**, de titularidade da C04; registrado em [`reuse.json`](reuse.json). Não afeta critério algum desta frente |
| Lei nº 6.496/1977, arts. 1º a 3º (institui a ART) | a Resolução CONFEA nº 1.137/2023 foi lida e já estabelece o que a ART atesta; a lei reforça, não altera a conclusão de que nada ali certifica software |

## 7. O que as fontes obtidas negam, e isso é resultado

Registrado porque é a conclusão mais importante desta frente sobre perfis institucionais:

- **As fontes examinadas não estabelecem um programa geral de homologação deste software.**
  Isso não demonstra inexistência universal de programas ou processos. A Res.
  CNSP 447/2022 não contém "homolog\*", "software", "ABNT", "NBR", "engenheiro", "CREA"
  nem "credenciamento"; a Res. CMN 4.676/2018 consolidada não contém "homolog\*",
  "credenci\*", "ABNT", "NBR", "14653", "engenheir\*", "CREA" nem "CAU".
- Onde a palavra "homologação" aparece, ela significa **outra coisa**, e confundi-las
  seria o erro mais fácil de cometer:
  - no ANS do Edital BB 2023/01269, "Homologação da Plataforma de Laudos" é a aprovação
    de **cada laudo submetido** — instrumento de medição de indicador de qualidade;
  - no Anexo I 19.10 do Edital CAIXA CR 012/2026, a "homologação" do **modelo AVM** por
    cidade após 30 dias de fluxo pareado é porta de aceitação do modelo de um fornecedor
    **contratado**;
  - no inciso LIV do contrato CAIXA, a vedação a "sistemas não homologados pela CAIXA"
    como **intermediários no envio de dados** é controle de segurança da informação
    imposto à contratada.
- Conforme o contrato da campanha: sem evidência de um programa aplicável, **não se inventa
  tal certificado**. Documenta-se a regra de aceitação de trabalho da instituição e o
  protocolo de evidência correspondente — que é o que os perfis em
  `profiles/institutions/` fazem.

**Consequência para a oferta:** `INSTITUTION_ACCEPTANCE` não existe para nenhum
destinatário, e `INSTITUTION_PROFILE_VERIFICATION` existe apenas para o perfil bancário do
BB. A alegação `institution_accepted` está bloqueada no registro de alegações, por
construção e com teste que o prova.
