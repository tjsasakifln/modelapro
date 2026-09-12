# C06 — Procedência das fontes persistidas

**Campanha:** MP-COM-20260912 / C06
**Aceites servidos:** C06-A04 (`real_case_matrix.md`) e C06-A05
(`institution_profiles.md`), ambos `BLOCKED_EXTERNAL_EVIDENCE`.

Este diretório existe porque a conferência de citações do C06-A05 antes repousava
sobre arquivos que viviam **fora do worktree**, num *scratchpad* de sessão. O
documento dizia ao revisor que a conferência "é reproduzível por qualquer
revisor", mas nada no repositório permitia reexecutá-la. Agora permite:

```
python3 scripts/comercial/aceite/verify_c06.py
```

## O que pode e o que não pode ser persistido aqui

Os três arquivos abaixo são **texto de ato normativo oficial brasileiro e de
página institucional pública** (BCB, SUSEP, CAIXA). São publicados pelo próprio
Estado para consulta e podem ser guardados aqui.

**Não** é persistido neste diretório, e não deve vir a ser: texto de norma ABNT
ou NBR, modelo/template licenciado, base de dados privada, arquivo de fonte
tipográfica. Verificação executada antes de persistir: `grep -c -i -E "ABNT|NBR"`
sobre os três arquivos retornou `0` em todos.

Nenhum dado pessoal foi persistido: as três fontes são páginas e normas públicas
sem identificação de pessoa natural.

## Fonte 1 — Resolução CMN nº 4.676/2018, texto consolidado v17 (BCB)

| campo | valor |
|---|---|
| Arquivo persistido | `res4676_v17.txt` |
| URL | `https://normativos.bcb.gov.br/Lists/Normativos/Attachments/50628/Res_4676_v17_P.pdf` |
| Recuperação original | 2026-09-12T01:5xZ (sessão C06) |
| Reobtenção para este manifesto | 2026-09-11 (data local da sessão de correção) |
| Ferramenta de recuperação | `curl -sSL` |
| Bytes do PDF recuperado | 455.366 |
| sha256 dos **bytes do PDF** | `18bbb843360c1adb217df495898172f7f104a999ae2f5ddffd2cdabd8370be43` |
| Ferramenta de extração | `pypdf` 6.16.1 |
| sha256 do **texto extraído** (o arquivo aqui persistido) | `38d6bae55d988079ec3461c660a88a49f273942b38d714dfc303553f502b621b` |

Comando de extração, verbatim:

```python
import pypdf
r = pypdf.PdfReader('Res_4676_v17_P.pdf')
open('res4676_v17.txt', 'w', encoding='utf-8').write(
    '\n'.join(p.extract_text() or '' for p in r.pages))
```

**Reprodutibilidade verificada, e não apenas alegada.** O PDF foi rebaixado nesta
sessão de correção e reextraído com o comando acima: o texto resultante tem
sha256 **idêntico** ao do arquivo aqui persistido (`38d6bae5…`). Ou seja, um
revisor que baixe o mesmo PDF e rode o mesmo comando obtém byte a byte este
arquivo. O PDF em si não é versionado aqui (455 KB de binário sem ganho de
auditoria sobre o texto, cujo hash já está registrado).

**Prova de que v17 é a consolidação mais recente publicada nesse caminho:** as
versões `v13`–`v17` retornam HTTP 200 e `v18`, `v19` e `v20` retornam HTTP 404 no
mesmo padrão de URL (verificado em 2026-09-12T01:5xZ).

## Fonte 2 — SUSEP, página "Seguro Habitacional"

| campo | valor |
|---|---|
| Arquivo persistido | `susep.txt` |
| URL | `https://www.gov.br/susep/pt-br/assuntos/meu-futuro-seguro/seguros-previdencia-e-capitalizacao/seguros/seguro-habitacional` |
| Recuperação original | 2026-09-12T01:55Z / 02:0xZ (WebFetch e, para conferência literal, `curl`) |
| sha256 do texto persistido | `f35735291f4e48811ef93f50c25aa1593746d7831b08dfa899c4e93fc3c957c4` |
| Carimbos da própria página | "Publicado em 14/09/2022 16:34" / "Modificado em 03/11/2022 16:08" |

## Fonte 3 — CAIXA, Licitações/Transparência

| campo | valor |
|---|---|
| Arquivo persistido | `caixa.txt` |
| URL | `https://www.caixa.gov.br/licitacoes/transparencia/Paginas/default.aspx` |
| Recuperação original | 2026-09-12T01:56Z |
| Ferramenta de recuperação | `curl` com *cookie jar* e *user-agent* de navegador (WebFetch falhou com `Too many redirects (exceeded 10)`) |
| HTTP / bytes na recuperação original | 200 / 317.977 |
| sha256 do texto persistido | `7961b25792ba75f0028396f0b84f0ad95638ae54b9d4a15252417b9027c73e7b` |

## Limitações desta procedência — declaradas, não contornadas

1. **O HTML de gov.br e caixa.gov.br não é estável byte a byte.** Não há hash de
   bytes registrado para as fontes 2 e 3, porque um hash que não reproduz é pior
   do que nenhum. Medida concreta: a página da CAIXA rebaixada na sessão de
   correção devolveu 317.975 bytes contra 317.977 na recuperação original —
   páginas dinâmicas variam a cada requisição. O artefato estável é o **texto
   persistido**, cujo hash está registrado, somado à conferência passagem a
   passagem contra uma recuperação nova.
2. **Conferência passagem a passagem contra recuperação nova (fontes 2 e 3),
   executada nesta sessão de correção:** as quatro passagens da SUSEP e as três
   passagens da CAIXA citadas no documento foram reencontradas, cada uma com
   contagem 1, no HTML rebaixado. Isto não é um hash, e não é apresentado como
   tal; é evidência de que o conteúdo citado continua na página.
3. **O comando exato de extração HTML→texto das fontes 2 e 3 não foi registrado
   pela sessão que as recuperou, e não é reconstruído aqui.** Reconstruir um
   comando que não foi rodado seria inventar procedência. O que se afirma é: o
   texto persistido é o que foi efetivamente usado na conferência, seu hash está
   registrado, e as passagens citadas foram reconfirmadas contra o HTML ao vivo
   conforme o item 2.
4. **Nenhuma dessas fontes constitui homologação, certificação, credenciamento ou
   aprovação deste software por instituição alguma.** Nenhuma ocorreu.
