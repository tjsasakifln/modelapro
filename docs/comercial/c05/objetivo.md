# Objetivo reenquadrado: atender ao padrão, não ser homologado

**Correção de objetivo registrada em 2026-09-12, do titular do projeto.**

> "o objetivo não é ser homologado diretamente por instituições, mas produzir análises que
> seriam aceitas sem ressalvas por padrões por elas estabelecidos"

## O que isso muda

A campanha C05 foi executada com o alvo certo nos **fatos** e o alvo errado na
**conclusão**. Os padrões que essas instituições estabelecem foram levantados em fonte
primária e estão em `profiles/institutions/`. Mas a conclusão que eu destaquei —
"nenhuma instituição homologa software de avaliação" — responde a uma pergunta que não
era a contratada.

Reenquadramento, com efeito prático em três pontos:

| ponto | antes | agora |
|---|---|---|
| alegação que sustenta a oferta | `institution_accepted` (bloqueada, e permaneceria bloqueada para sempre) | `profile_compatible` — o trabalho atende ao padrão publicado pelo destinatário |
| pergunta de aceite de A05/A06 | "a instituição homologou o software?" | "a análise emitida satisfaz cada requisito do padrão que a instituição publicou?" |
| natureza da lacuna | dependência externa insolúvel por nós | **lacuna de produto, endereçável**, com dono e payload |

A distinção entre as quatro decisões do contrato comum **permanece** válida e não foi
relaxada: qualificação do software, conformidade da avaliação, revisão do profissional e
aceitação do destinatário continuam separadas. O que muda é qual delas é a meta. A meta é
a segunda — conformidade do trabalho com o padrão — e a quarta deixa de ser pré-requisito
da oferta.

## Por que "nenhuma homologa software" continua no dossiê

Rebaixado de resultado central a nota de rodapé necessária, por um motivo: é o que impede
que um documento obtido seja lido como aquilo que ele não concede. Três documentos
diferentes usam a palavra "homologação" para três coisas que não são certificação do
produto — aprovação de **cada laudo** no ANS do BB, aceitação do **modelo AVM** de
fornecedor contratado na CAIXA, e controle de **acesso a dados** no contrato da CAIXA.
Sem esse registro, qualquer um dos três viraria, por descuido ou por conveniência, uma
alegação de homologação.

O achado deixa de ser a resposta e passa a ser a cerca.

## O que a pergunta certa exige, e que eu não havia feito

Levantar o padrão **não é** verificar que o atendemos. Os perfis registravam os requisitos;
nenhum verificava, requisito por requisito, se a análise que o produto emite os satisfaz.
Essa é a lacuna real desta frente, e é o que `output_conformance` passa a responder.

### Como "sem ressalvas" fica computável

`modules/qualification_profile/output_conformance.py` responde duas perguntas distintas:

- **`product_conformance_baseline(profile)`** — sobre a VERSÃO DO SOFTWARE: o produto
  consegue, hoje, produzir um trabalho que atenda a este padrão? Independe de caso
  concreto. É o que sustenta ou bloqueia a alegação `profile_compatible`.
- **`assess_output_conformance(profile, output_manifest)`** — sobre UM TRABALHO: o laudo
  emitido contém tudo que o padrão exige? `would_be_accepted_without_reservations` só é
  verdadeiro quando nenhum requisito aplicável está pendente ou em falta.

Quatro decisões de projeto que tornam a barra difícil de satisfazer por acidente:

1. **Ausência no manifesto não é conformidade.** Um requisito que o produto emite, mas que
   este trabalho não registrou, fica pendente. O silêncio não conta a favor.
2. **Declarar não torna presente.** Se o produto está `missing` quanto a um requisito,
   evidência de caso não conserta: o item permanece `unsupported`. Não há caminho em que
   um clique supere uma lacuna do software.
3. **`partial` é falha, não quase-acerto.** CSV onde o padrão pede Excel, R² onde pede R,
   equação transformada onde pede a destransformada, teste de normalidade onde pede o
   cotejo de frequências — tudo isso é `failed`.
4. **Perfil vazio não passa por vacuidade.** Zero requisitos aplicáveis ⇒ veredito falso.
   Um catálogo incompleto não vira aprovação.

E duas de auditabilidade, verificadas na carga do catálogo: uma lacuna **sem descrição**
não é auditável e uma lacuna **sem dono** não é endereçável — ambas recusadas com erro
estruturado.

## O que o veredito continua a NÃO ser

`would_be_accepted_without_reservations = True` significa: *este trabalho satisfaz cada
requisito do padrão documental que esta instituição publicou, na versão do padrão que
conferimos*. Não significa, e nada aqui deve ser redigido como se significasse:

- que a instituição aceitou este trabalho — aceitação é ato dela, e continua registrada
  apenas quando ocorre de verdade;
- que a instituição aceitaria qualquer trabalho futuro;
- que o padrão conferido é o vigente, quando a vigência não foi estabelecida (é o caso do
  MECI: `MECI-202400940-VER01`, cuja atualidade não foi confirmada);
- que a revisão do profissional responsável foi dispensada — não foi, e um requisito de
  conteúdo humano sem registro mantém o caso em `review_required`.

Em uma frase: **atender ao padrão é o que podemos provar e é o que a oferta precisa;
aceitação é ato de terceiro e não é pré-requisito para vender uma ferramenta com alegação
honesta.**
