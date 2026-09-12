# C06 — fechamento dos requisitos de saída na composição

## Implementação e confirmação local

Os produtores numérico, documental e de arbitramento estão compostos. Em
`33314fa1016b1fbecad4a82cdafe58b1ca6f6ca0`, a coorte de interface profissional,
superfícies comerciais, conformidade de saída e arbitramento passou **52 testes**.
O worker real alcança PDF, DOCX, XLSX e manifesto: os 28 requisitos `emitted`
anteriores à assinatura têm representação; os 11 requisitos humanos são
contabilizados como presentes, pendentes ou não aplicáveis; a assinatura
ICP-Brasil permanece explicitamente pendente. A capacidade de verificar assinatura
não constitui assinatura real nem aceite institucional.

A reabertura preserva IDs canônicos, precedência por campo e coordenadas zero.
Uma falha de determinismo do XLSX foi corrigida normalizando também a data interna
OOXML, com teste sob dois relógios diferentes. O navegador identificou depois
coordenadas pt-BR mapeadas que não eram convertidas fora das oito linhas da prévia;
`test_decimal_comma_mapping_covers_rows_beyond_preview_and_stays_strict` cobre
12 linhas, zero, precedência e entradas inválidas. A coorte posterior de produtor
e contratos Windows passou 87 testes; a confirmação do navegador está em curso.

Os hashes dos seis arquivos do worker e os JUnits locais estão registrados em
[evidence-local-documentary-20260912.json](evidence-local-documentary-20260912.json).
São provas intermediárias locais. O CI e o executável instalado da candidata
final continuam obrigatórios. O detalhamento de representação e assinatura está
em [defeitos_abertos_nos_documentos.md](defeitos_abertos_nos_documentos.md).

## Baseline histórico e obrigações preservadas

Na retomada, a execução real de `resolve_profile` + `product_conformance_baseline`
para BB 0.3.0 ainda contou 12 emitted, 15 partial, 11 missing e 2 human_input.
Esses 26 gaps são obrigações internas de capacidade, distintas dos dados e atos
profissionais reais. A lista abaixo congela a cobertura do fechamento; só testes
do produtor até os bytes PDF/DOCX/XLSX, manifesto e catálogo podem fechá-los.
Não basta alterar o baseline nem injetar um contexto diretamente no renderer.

| Requisito | Baseline observado | Obrigação de fechamento |
|---|---|---|
| meci.3.3.1.a | partial | Equação utilizada com a variável dependente apresentada no laudo na forma NÃO TRANSFORMADA |
| meci.3.3.1.b | partial | Coeficientes atingidos: correlação (R), determinação (R²) e determinação ajustado (R² ajustado) |
| meci.3.3.1.c | partial | Significâncias do modelo e das variáveis independentes |
| meci.3.3.1.e | missing | Atributos do imóvel avaliando (valores) |
| meci.3.3.1.f | partial | Resultado da avaliação e intervalos atingidos (IC 80% E campo de arbítrio) |
| meci.3.3.1.j | partial | Histograma dos resíduos amostrais PADRONIZADOS |
| meci.3.3.1.k | missing | Probabilidades da distribuição normal padrão nos intervalos [-1;+1], [-1,64;+1,64] e [-1,96;+1,96] (68%, 90%, 95%) cotejadas com as frequências observadas |
| meci.3.3.1.l | missing | Matriz de correlações das variáveis independentes e dependente |
| meci.3.3.1.m1 | partial | Valor do teste F de Snedecor (F calculado) |
| meci.3.3.1.m2 | missing | Quantidade de outliers do modelo |
| meci.3.3.1.n | missing | Intervalos de valores admissíveis, quando for o caso, informados no campo "Observações" do laudo |
| meci.2.3.3.2.excel | partial | A amostra exportada em arquivo formato Excel (.xlsx/.xls) |
| meci.2.3.3.2.projecoes | partial | O PDF contém "projeções" e "informações auxiliares" exigidas pela norma de avaliações |
| bb.guiar.assinatura_icp | missing | Via de assinatura digital do PDF por certificado ICP-Brasil |
| 10.1.c | partial | objetivo da avaliação |
| 10.1.d | partial | pressupostos, ressalvas e fatores limitantes (7.2 da Parte 1) |
| 10.1.e | partial | identificação e caracterização do imóvel avaliando (7.3 da Parte 1, no que couber) |
| 10.1.f | missing | diagnóstico do mercado (7.7.2 da Parte 1) |
| 10.1.i | partial | planilha dos dados utilizados |
| 10.1.j | partial | método comparativo: descrição das variáveis do modelo, com o critério de enquadramento de cada característica dos elementos amostrais e a escala das diferenças qualitativas |
| 10.1.k | partial | tratamento dos dados e identificação do resultado: cálculos efetuados, campo de arbítrio se for o caso, justificativas do resultado adotado e o gráfico de preços observados versus valores estimados |
| 10.1.m | missing | qualificação legal completa e assinatura do(s) profissional(is) responsável(is) |
| meci.3.4.1.justificativa_grau_i | missing | Havendo Grau I, existir campo para a JUSTIFICATIVA exigida pelo MECI 3.4.1 ('Grau I admitido somente com justificativa'). |
| normas.12.1.16.tabela_anexa | partial | Apresentar em TABELA ANEXA o demonstrativo da pontuação atingida para enquadramento nos graus de fundamentação e precisão (Normas para elaboração de laudos, 12.1.16.1). |
| normas.12.1.8.geolocalizacao | missing | Registrar geolocalização do avaliando e de TODOS os elementos amostrais em graus decimais, com endereço completo e fonte por dado (itens 12.1.8/12.1.9). |
| abnt.9.2.1.1.elasticidades | missing | Para o Grau III, analisar as ELASTICIDADES em torno do ponto de estimação (NBR 14653-2, 9.2.1.1). |

Os itens emitted/human_input também precisam de manifesto por trabalho e bytes
identificados. Ausência de dados, amostra adequada, assinatura válida ou revisão
profissional mantém o trabalho específico pendente; capacidade do programa não
preenche essas entradas. A matriz corrente continua em `integration-matrix.md`.

Frentes de implementação isoladas nesta retomada:
- Produtor numérico: métricas, resíduos, correlações e elasticidades do fit congelado.
- Interface: entradas profissionais, geolocalização e invalidação do estado.
- Documentos: apresentação, Excel, manifestação requisito→representação e catálogo.
- Distribuição: Windows instalado, lock/SBOM/DLLs, atualização e rollback.

Todos são integrados e testados na mesma #20 por C06; nenhum branch produtor
C01–C05 será reescrito. Revisão/aceite externos permanecem NOT_RUN.
