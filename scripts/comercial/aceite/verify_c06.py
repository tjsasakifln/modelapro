#!/usr/bin/env python3
"""Conferencia executavel dos aceites C06-A04 e C06-A05 (MP-COM-20260912).

O que este script faz, e que a versao anterior (verify_c06.sh, em scratchpad de
sessao) NAO fazia: ele EXTRAI as passagens citadas DE DENTRO do proprio
documento `docs/comercial/c06/institution_profiles.md` e as confronta com os
textos-fonte persistidos em `docs/comercial/c06/sources/`. O vinculo
documento -> fonte passa a ser testado, e nao apenas afirmado: alterar uma
citacao no documento faz este script falhar.

Regras aplicadas:

1. Integridade das fontes: sha256 de cada texto-fonte persistido tem de bater
   com o hash registrado em sources/MANIFEST.md (repetido aqui).
2. Extracao: removidos os trechos entre crases (comandos, caminhos), toda
   cadeia entre aspas retas do documento e uma "passagem candidata".
3. Cada passagem candidata ou (a) e encontrada literalmente, modulo espacos em
   branco, em um dos textos-fonte, ou (b) consta da lista de exclusoes abaixo,
   que o script imprime com o motivo de cada entrada. Nao ha terceira via.
4. Adjacencia de marcador (SOMENTE fonte BCB, que e PDF consolidado com
   redacoes empilhadas): para cada passagem da Res. CMN 4.676 o script mede a
   distancia entre o fim da passagem e o primeiro marcador de vigencia
   seguinte, e confronta com a classe declarada (EM VIGOR / SUPERADA / SEM
   MARCADOR). As distancias medidas sao impressas.
5. Matriz C06-A04: cada linha `| RC-xx |` tem de trazer STATUS NOT_RUN e a
   celula de resultado vazia; o numero de linhas tem de ser o declarado.
6. Ambos os documentos tem de manter o status BLOCKED_EXTERNAL_EVIDENCE.

Uso:
    python3 scripts/comercial/aceite/verify_c06.py
    C06_DOC=/tmp/copia.md python3 scripts/comercial/aceite/verify_c06.py

Saida: linhas OK/FAIL e um sumario. Codigo de saida 0 somente se FAIL == 0.
"""

import hashlib
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SRC_DIR = os.path.join(ROOT, 'docs', 'comercial', 'c06', 'sources')
DOC = os.environ.get(
    'C06_DOC', os.path.join(ROOT, 'docs', 'comercial', 'c06',
                            'institution_profiles.md'))
MATRIX = os.environ.get(
    'C06_MATRIX', os.path.join(ROOT, 'docs', 'comercial', 'c06',
                               'real_case_matrix.md'))

# sha256 dos textos-fonte persistidos (ver sources/MANIFEST.md).
SOURCE_HASHES = {
    'res4676_v17.txt':
        '38d6bae55d988079ec3461c660a88a49f273942b38d714dfc303553f502b621b',
    'susep.txt':
        'f35735291f4e48811ef93f50c25aa1593746d7831b08dfa899c4e93fc3c957c4',
    'caixa.txt':
        '7961b25792ba75f0028396f0b84f0ad95638ae54b9d4a15252417b9027c73e7b',
}

BCB = 'res4676_v17.txt'

# Janela de busca do marcador de vigencia, em caracteres do texto original.
MARKER_WINDOW = 900
# Limiar de adjacencia. Medicoes atuais: passagens em vigor entre 0 e 4
# caracteres do marcador; passagens superadas a 56 e 506. O vale e largo.
ADJACENCY_MAX = 40

MARKER_RE = re.compile(
    r'\([^)]{0,240}?(?:[Rr]edação dada|[Ii]nclu[ií]d[oa]|'
    r'[Rr]evogad[oa])[^)]{0,240}\)')

# Classe de vigencia por passagem da Res. CMN 4.676, indexada por uma ancora
# (substring sem espacos) que identifica a passagem sem ambiguidade.
# EM_VIGOR  -> distancia ate o marcador <= ADJACENCY_MAX, e o marcador tem de
#              conter o trecho esperado;
# SUPERADA  -> existe marcador na janela, mas a distancia e > ADJACENCY_MAX
#              (a redacao substituta esta empilhada entre os dois);
# SEM_MARCADOR -> nenhum marcador na janela seguinte.
# MARCADOR  -> a propria passagem citada e um marcador de vigencia; confere-se
#              apenas a literalidade.
VIGENCIA_RULES = [
    ('ementa em vigor (Res. CMN 5.197/2024, desde 1o/7/2025)',
     'critériosparacontrataçãodeoperaçãodecréd'
     'itoimobiliáriopelasinstituiçõesfinanceiras',
     'EM_VIGOR', 'pela Resolução CMN nº 5.197'),
    ('ementa superada (redacao originaria de 31/7/2018)',
     'critériosparacontrataçãodefinanciamentoimobiliário'
     'pelasinstituiçõesfinanceiras',
     'SUPERADA', None),
    ('art. 6o caput, redacao em vigor',
     'Acotadecréditonãopodesersuperiora',
     'EM_VIGOR', 'pela Resolução CMN nº 5.197'),
    ('art. 6o caput, gemeo superado',
     'garantia,nadatadacontratação,nãopodesersuperiora',
     'SUPERADA', None),
    ('art. 1o-A, XI',
     'ovalordeavaliaçãodoimóveldadoemgarantia',
     'EM_VIGOR', 'pela Resolução CMN nº 5.197'),
    ('art. 13, I',
     'limitemáximodovalordeavaliaçãodoimóvelfinanciado',
     'EM_VIGOR', 'pela Resolução CMN nº 5.255'),
    ('art. 11-A, I e II',
     'aavaliaçãodeimóvelcompreende',
     'EM_VIGOR', 'incluído, a partir de 1º/6/2022, pela Resolução CMN nº '
     '4.925'),
    ('art. 11, I, "b"',
     'aavaliaçãodoimóveldeveserefetuadaporprofissional',
     'SEM_MARCADOR', None),
    ('art. 11, par. 4o, I a IV',
     'modelodeprecificaçãoprópriooudeterceiros',
     'EM_VIGOR', 'Parágrafo 4º incluído pela Resoluç'
     'ão nº 4.754'),
    ('art. 8o-A, par. 2o, III',
     'entregaaomutuáriooupretendenteaocréditodeextratodolaudo',
     'SEM_MARCADOR', None),
    ('art. 11, par. 2o',
     'devempermaneceràdisposiçãodoBancoCentraldoBrasil',
     'SEM_MARCADOR', None),
    ('marcador de vigencia citado (Res. CMN 5.197/2024)',
     'Incluído,apartirde1º/7/2025,pelaResoluçãoCMN',
     'MARCADOR', None),
    ('marcador de vigencia citado (Res. CMN 4.925/2021)',
     'Artigo11-Aincluído,apartirde1º/6/2022,pelaResoluçãoCMN',
     'MARCADOR', None),
    ('marcador de vigencia citado (Res. 4.754/2019)',
     'Parágrafo4ºincluídopelaResoluçãonº4.754',
     'MARCADOR', None),
]

# Trechos entre aspas que NAO sao citacao de fonte. Cada entrada traz o motivo
# e e impressa na execucao. Esta lista e o ponto fraco natural deste script:
# ela e deliberadamente curta e so admite rotulo nosso, termo buscado, ou
# formulacao comercial proibida.
EXCLUSIONS = [
    ('Banco Central do Brasil',
     'cabecalho devolvido pela URL atribuida do BCB (casca JS); esse retorno '
     'nao foi persistido como fonte, justamente porque nao traz texto '
     'normativo'),
    ('contratação de **financiamento imobiliário**',
     'fragmento contrastivo nosso; a passagem integral esta conferida'),
    ('contratação de **operação de crédito '
     'imobiliário**',
     'fragmento contrastivo nosso; a passagem integral esta conferida'),
    ('financiamento imobiliário',
     'fragmento contrastivo nosso; a passagem integral esta conferida'),
    ('operação de crédito imobiliário',
     'fragmento contrastivo nosso; a passagem integral esta conferida'),
    ('...e os critérios para contratação de **financiamento '
     'imobiliário** pelas instituições financeiras...',
     'citacao elidida da redacao errada, no registro de correcao; a passagem '
     'integral esta conferida'),
    ('contagem igual a 1 demonstra que não existe, para aquela passagem, '
     'redação empilhada superada',
     'autocitacao da afirmacao FALSA que este documento removeu'),
    ('cada passagem', 'autocitacao de formulacao nossa retirada'),
    ('valor de mercado',
     'termo BUSCADO e NAO encontrado; coberto pelas checagens de ocorrencia '
     'zero'),
    ('valor de avaliação',
     'termo analitico nosso; as passagens que o contem estao conferidas'),
    ('market value', 'traducao comercial vedada, nao e texto de fonte'),
    ('b', 'rotulo de alinea do art. 11, I'),
    ('requisitos para software de avaliação',
     'parafrase nossa, explicitamente marcada como tal'),
    ('certificado interno', 'formulacao comercial vedada'),
    ('certificado', 'formulacao comercial vedada'),
    ('homologado pelo/para o Banco X', 'formulacao comercial vedada'),
    ('aprovado pela SUSEP/BCB/CAIXA', 'formulacao comercial vedada'),
    ('a CAIXA credencia software de avaliação',
     'falsificacao nomeada para ser proibida'),
    ('Texto efetivamente consultado', 'titulo de secao deste documento'),
    ('sem marcador de vigência na janela seguinte',
     'rotulo de coluna deste documento'),
]

ZERO_HIT = [
    (BCB, ['homolog', 'software', 'valor de mercado']),
    ('susep.txt',
     ['homolog', 'software', 'laudo', 'vistoria', 'valor de mercado']),
]

MATRIX_ROWS = 10

INVISIBLE = dict.fromkeys(
    [0x200b, 0x200c, 0x200d, 0xfeff, 0x00ad, 0x202a, 0x202b, 0x202c,
     0x202d, 0x202e, 0x2066, 0x2067, 0x2068, 0x2069], None)


def squeeze(text):
    """Remove espacos e caracteres invisiveis; normaliza para NFC.

    A extracao de PDF quebra palavras com espacos arbitrarios ('imobilia rio'),
    e as paginas HTML trazem marcas de direcionalidade. Comparar sem espacos e
    a unica normalizacao que torna a conferencia possivel; ela e declarada
    aqui e no documento.
    """
    text = unicodedata.normalize('NFC', text).translate(INVISIBLE)
    return re.sub(r'\s+', '', text)


def build_index(text):
    """Devolve (texto_sem_espacos, mapa indice_comprimido -> indice_original)."""
    keep = [(i, c) for i, c in enumerate(text)
            if not c.isspace() and ord(c) not in INVISIBLE]
    return ''.join(c for _, c in keep), [i for i, _ in keep]


class Report(object):
    def __init__(self):
        self.passes = 0
        self.fails = 0

    def ok(self, msg):
        self.passes += 1
        print('OK   %s' % msg)

    def fail(self, msg):
        self.fails += 1
        print('FAIL %s' % msg)


def load_sources(rep):
    sources = {}
    for name, expected in sorted(SOURCE_HASHES.items()):
        path = os.path.join(SRC_DIR, name)
        if not os.path.exists(path):
            rep.fail('fonte ausente: %s' % path)
            continue
        raw = open(path, 'rb').read()
        got = hashlib.sha256(raw).hexdigest()
        if got == expected:
            rep.ok('sha256 da fonte %s confere (%s...)' % (name, got[:16]))
        else:
            rep.fail('sha256 da fonte %s NAO confere: %s' % (name, got))
        text = raw.decode('utf-8')
        squeezed, index = build_index(text)
        sources[name] = (text, squeezed, index)
    return sources


def extract_quotes(doc_text):
    """Passagens candidatas: tudo entre aspas retas, fora de trechos em crase."""
    stripped = re.sub(r'`[^`]*`', ' ', doc_text)
    if stripped.count('"') % 2 != 0:
        return None
    return re.findall(r'"([^"]+)"', stripped)


def fragments(quote):
    """Tira enfase markdown e parte a citacao nas elisoes '[...]'."""
    clean = quote.replace('**', '').replace('*', '')
    parts = [squeeze(p) for p in clean.split('[...]')]
    return [p for p in parts if p]


def locate(source, frags):
    """Acha os fragmentos em ordem. Devolve (inicio, fim) comprimidos ou None."""
    squeezed = source[1]
    pos = squeezed.find(frags[0])
    if pos < 0:
        return None
    start = pos
    end = pos + len(frags[0])
    for frag in frags[1:]:
        nxt = squeezed.find(frag, end)
        if nxt < 0:
            return None
        end = nxt + len(frag)
    return start, end


def marker_after(source, end_compressed):
    """Primeiro marcador de vigencia apos a passagem: (distancia, texto)."""
    text, _, index = source
    end = index[end_compressed - 1] + 1
    tail = text[end:end + MARKER_WINDOW]
    match = MARKER_RE.search(tail)
    if match is None:
        return None, None
    return match.start(), re.sub(r'\s+', ' ', match.group())


RULES_HIT = set()


def check_vigencia(rep, source, quote, frags, span):
    matched = [r for r in VIGENCIA_RULES if r[1] in squeeze(
        quote.replace('**', '').replace('*', ''))]
    label = re.sub(r'\s+', ' ', quote)[:58]
    if len(matched) != 1:
        rep.fail('passagem BCB sem regra de vigencia unica declarada '
                 '(%d regras casaram): "%s..."' % (len(matched), label))
        return
    name, _, klass, expected_marker = matched[0]
    RULES_HIT.add(name)
    dist, marker = marker_after(source, span[1])
    shown = 'sem marcador na janela' if dist is None else '%d caracteres' % dist
    if klass == 'MARCADOR':
        rep.ok('%s: marcador citado literalmente' % name)
        return
    if klass == 'EM_VIGOR':
        if dist is None or dist > ADJACENCY_MAX:
            rep.fail('%s: declarada EM VIGOR mas a distancia ate o marcador e '
                     '%s (> %d) -- indicio de redacao empilhada superada'
                     % (name, shown, ADJACENCY_MAX))
        elif expected_marker and expected_marker not in marker:
            rep.fail('%s: marcador adjacente e "%s", nao contem "%s"'
                     % (name, marker[:90], expected_marker))
        else:
            rep.ok('%s: EM VIGOR, marcador adjacente a %s -- %s'
                   % (name, shown, marker[:70]))
        return
    if klass == 'SUPERADA':
        if dist is None:
            rep.fail('%s: declarada SUPERADA mas nao ha marcador na janela'
                     % name)
        elif dist <= ADJACENCY_MAX:
            rep.fail('%s: declarada SUPERADA mas esta adjacente ao marcador '
                     '(%s)' % (name, shown))
        else:
            rep.ok('%s: SUPERADA, separada do marcador por %s de redacao '
                   'substituta' % (name, shown))
        return
    if klass == 'SEM_MARCADOR':
        if dist is None:
            rep.ok('%s: nenhum marcador de vigencia nos %d caracteres '
                   'seguintes, em v17' % (name, MARKER_WINDOW))
        else:
            rep.fail('%s: declarada sem marcador, mas ha um a %s -- %s'
                     % (name, shown, marker[:70]))
        return
    rep.fail('%s: classe de vigencia desconhecida %r' % (name, klass))


def check_quotes(rep, sources, doc_text):
    quotes = extract_quotes(doc_text)
    if quotes is None:
        rep.fail('numero impar de aspas retas no documento: extracao das '
                 'passagens nao e confiavel')
        return
    excl = dict((squeeze(k), v) for k, v in EXCLUSIONS)
    print('\n-- exclusoes declaradas (nao sao citacao de fonte) --')
    for text, reason in EXCLUSIONS:
        print('   EXCLUIDO  "%s" -- %s' % (re.sub(r'\s+', ' ', text)[:60],
                                           reason))
    print('-- %d passagens candidatas extraidas de %s --\n'
          % (len(quotes), os.path.basename(DOC)))
    used = set()
    for quote in quotes:
        key = squeeze(quote)
        if key in excl:
            used.add(key)
            continue
        frags = fragments(quote)
        label = re.sub(r'\s+', ' ', quote)[:58]
        hits = [(n, s) for n, s in sorted(sources.items())
                if locate(s, frags)]
        if not hits:
            rep.fail('passagem nao encontrada em fonte nenhuma nem na lista '
                     'de exclusoes: "%s..."' % label)
            continue
        if len(hits) > 1 and BCB not in [n for n, _ in hits]:
            rep.fail('passagem ambigua, encontrada em %r: "%s..."'
                     % ([n for n, _ in hits], label))
            continue
        # A fonte BCB tem precedencia: e a unica com redacoes empilhadas, e
        # deixar uma passagem dela resolver para outra fonte puleria a regra
        # de adjacencia de marcador.
        name, source = next(((n, s) for n, s in hits if n == BCB), hits[0])
        span = locate(source, frags)
        rep.ok('passagem conferida contra %s: "%s..."' % (name, label))
        if name == BCB:
            check_vigencia(rep, source, quote, frags, span)
    unhit = [r[0] for r in VIGENCIA_RULES if r[0] not in RULES_HIT]
    if unhit:
        rep.fail('regras de vigencia declaradas que nenhuma passagem do '
                 'documento acionou (passagem removida ou alterada): %r'
                 % unhit)
    else:
        rep.ok('todas as %d regras de vigencia declaradas foram acionadas'
               % len(VIGENCIA_RULES))
    stale = [t for t, _ in EXCLUSIONS if squeeze(t) not in used]
    if stale:
        rep.fail('exclusoes declaradas que ja nao ocorrem no documento '
                 '(lista desatualizada): %r' % stale[:5])
    else:
        rep.ok('lista de exclusoes sem entradas mortas')


def check_zero_hits(rep, sources):
    for name, terms in ZERO_HIT:
        if name not in sources:
            continue
        text = sources[name][0].lower()
        for term in terms:
            count = text.count(term.lower())
            if count == 0:
                rep.ok('%s: "%s" ocorre 0 vezes, como afirmado' % (name, term))
            else:
                rep.fail('%s: "%s" ocorre %d vezes, contrariando a afirmacao '
                         'de ocorrencia zero' % (name, term, count))


def check_matrix(rep, matrix_text):
    rows = [ln for ln in matrix_text.splitlines()
            if re.match(r'^\|\s*RC-\d+\s*\|', ln)]
    if len(rows) == MATRIX_ROWS:
        rep.ok('matriz tem as %d linhas RC declaradas' % MATRIX_ROWS)
    else:
        rep.fail('matriz tem %d linhas RC, declaradas %d'
                 % (len(rows), MATRIX_ROWS))
    for line in rows:
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        case = cells[0] if cells else '?'
        if len(cells) < 10:
            rep.fail('%s: linha com %d colunas, esperadas 10'
                     % (case, len(cells)))
            continue
        resultado, status = cells[-2], cells[-1]
        if status != 'NOT_RUN':
            rep.fail('%s: STATUS e %r, nao NOT_RUN' % (case, status))
        elif resultado != '':
            rep.fail('%s: celula de resultado nao esta vazia: %r'
                     % (case, resultado))
        else:
            rep.ok('%s: STATUS=NOT_RUN e resultado vazio' % case)


def check_status(rep, doc_text, matrix_text):
    for label, text in (('institution_profiles.md', doc_text),
                        ('real_case_matrix.md', matrix_text)):
        if 'BLOCKED_EXTERNAL_EVIDENCE' in text:
            rep.ok('%s mantem BLOCKED_EXTERNAL_EVIDENCE' % label)
        else:
            rep.fail('%s perdeu o status BLOCKED_EXTERNAL_EVIDENCE' % label)


def main():
    rep = Report()
    print('documento : %s' % DOC)
    print('matriz    : %s' % MATRIX)
    print('fontes    : %s\n' % SRC_DIR)
    sources = load_sources(rep)
    doc_text = open(DOC, encoding='utf-8').read()
    matrix_text = open(MATRIX, encoding='utf-8').read()
    check_quotes(rep, sources, doc_text)
    print('')
    check_zero_hits(rep, sources)
    print('')
    check_matrix(rep, matrix_text)
    check_status(rep, doc_text, matrix_text)
    print('\nPASS=%d FAIL=%d' % (rep.passes, rep.fails))
    return 1 if rep.fails else 0


if __name__ == '__main__':
    sys.exit(main())
