# Conformidade da saída contra os padrões estabelecidos

## Estado após C06

O perfil resolvido `bb-meci-avaliacao-imovel-pf` versão `0.3.0` contém 40 requisitos de saída. O produto tem capacidade para atender a todos: 29 representações são produzidas pelo software e 11 dependem de conteúdo ou evidência fornecidos pelo profissional. Não há requisito `partial` ou `missing` na linha de base do produto.

| estado | itens | significado |
|---|---:|---|
| emitido pelo produto | 29 | existe produtor, representação e verificação controlada |
| insumo humano | 11 | existe porta, persistência e representação; o caso permanece pendente enquanto o profissional não fornecer conteúdo válido |
| parcial | 0 | nenhuma lacuna de capacidade conhecida |
| ausente | 0 | nenhuma lacuna de capacidade conhecida |

A linha de base é reexecutável:

```python
from modules.qualification_profile import resolve_profile
from modules.qualification_profile.output_conformance import product_conformance_baseline

profile = resolve_profile({"id": "bb-meci-avaliacao-imovel-pf", "version": "0.3.0"})
product_conformance_baseline(profile)
# counts = {"emitted": 29, "partial": 0, "missing": 0, "human_input": 11}
# product_can_meet_standard = True
```

`product_can_meet_standard=True` declara capacidade documental. Não declara que um caso vazio está conforme, que o padrão é vigente, nem que o Banco do Brasil aceitou um laudo. `assess_output_conformance(profile, manifest)` continua fechado por ausência: cada requisito aplicável precisa de evidência derivada do conteúdo e dos bytes reais.

## Cadeia requisito → representação → bytes

A emissão usa dois manifestos porque incluir o hash do próprio PDF dentro do PDF criaria uma referência circular:

1. `output_manifest.json` descreve o conteúdo determinístico antes da renderização. Ele participa do `result_fingerprint` e do `report_content_fingerprint`.
2. `output_representation_manifest.json` é criado após PDF, DOCX e XLSX. Ele registra SHA-256, tamanho, tipo e resultado do verificador de cada representação e os vincula aos mesmos fingerprints.
3. A solicitação de assinatura identifica os bytes PDF revisados e só é criada se PDF, DOCX, XLSX, dossiê e manifesto ainda coincidirem.
4. O pacote final inclui `requirements/output-representations.json`; adulteração de qualquer representação, troca de manifesto ou vínculo com outro resultado é recusada.

`report_context.output_evidence`, booleanos e rótulos fornecidos pelo cliente ficam em `unverified_declarations` e nunca criam itens conformes. Anexos podem comprovar somente seu conteúdo documental; um `requirement_id` arbitrário em anexo não substitui métricas ou diagnósticos do produtor.

## Representações profissionais

PDF e DOCX apresentam campos distintos para finalidade e objetivo, diagnóstico de mercado, critérios/codificação/categorias/escalas das variáveis, justificativa de Grau I, observações, identificação profissional e geolocalização. A equação traz a escala do ajuste, a forma na unidade original, o método de retransformação e o estimando. Sem método suficiente, a forma original permanece pendente e `exp(E[ln Y|X])` não é rotulado como média condicional.

O XLSX `sample.xlsx` contém a amostra efetiva integral e usa os mesmos `used_row_ids` do snapshot. A aba `dados_excluidos` preserva também todos os `excluded_row_ids`, sem inventar coordenadas ausentes. Cada linha transporta endereço completo, latitude e longitude decimais WGS84, fonte, justificativa e variáveis disponíveis. O verificador compara cabeçalhos, ordem e conjunto exato de identificadores. O arquivo OOXML é determinístico para que emissões idênticas tenham o mesmo hash.

O XLSX não aceita fórmulas em campos fornecidos pelo usuário: cabeçalhos, fontes, endereços, justificativas, critérios e metadados passam pela mesma neutralização. A verificação compara todas as células das cinco planilhas com a projeção canônica, preserva a distinção entre booleanos e números, valida a faixa WGS84 e exige planilhas, linhas, colunas e formatos visíveis. Alterar, ocultar, duplicar ou omitir uma célula reprova a representação.

Os diagnósticos estatísticos só entram no manifesto quando o produtor declara `available=True`, não informa `reason` impeditiva e fornece conteúdo completo. Matriz de correlação exige `status=complete`, nenhuma célula ou variável faltante; elasticidades e outliers exigem `coverage.complete=True`. Lista vazia, `Infinity`, campo parcial ou simples presença da chave não satisfaz requisito. Matrizes largas são divididas em painéis de até seis colunas, com todas as linhas e valores repetidamente identificados; isso preserva a matriz N×N sem comprimir números até ficarem ilegíveis. P-valores finitos positivos abaixo de quatro casas decimais são impressos em notação científica, sem arredondamento enganoso para zero.

Na representação PDF, marcadores controlados ligam cada métrica, p-valor e célula diagnóstica à sua seção. A planilha amostral do PDF usa painéis de até cinco variáveis; cada cabeçalho, `row_id` e valor é ligado ao painel correspondente. O verificador recusa troca entre linhas ou painéis, cabeçalho deslocado, valor omitido ou duplicado e mutação de métricas, frequências normais, matriz, outliers ou elasticidades.

## Assinatura externa e ICP-Brasil

A etapa de assinatura é obrigatória para o perfil BB e permanece `awaiting_signature` depois da revisão. Essa pendência permite exportar os bytes signáveis, mas impede o estado final assinado. A assinatura recebida deve preservar incrementalmente o PDF revisado, coincidir com snapshot, revisão e fingerprints e passar pela verificação local do pyHanko.

Para a alegação ICP-Brasil, a verificação também exige cadeia confiável, evidência de revogação por LCR ou OCSP, política PAdES ICP-Brasil admitida e âncora pública oficial pinada. Nome de certificado, CN/OID parecido, texto `ICP-Brasil`, allowlist do operador ou raiz sintética não ampliam o conjunto oficial. `synthetic_test_only=True` nunca satisfaz o requisito ICP, mesmo que a assinatura de teste seja criptograficamente válida.

A política implementada se baseia no [DOC-ICP-15.03 v9.1 do ITI](https://www.gov.br/iti/pt-br/assuntos/legislacao/documentos-principais/v9.1_IN2021_03_DOCICP15.03_compilada.pdf), listado como versão corrente na página oficial de Documentos Principais consultada em 2026-09-12. O PDF consultado tem SHA-256 `2cc3859adb5af9531ff8d4498151560a689b0742820cc0db766278b1d588a0d9`. As páginas 102–129 identificam as políticas PAdES, períodos de assinatura, âncoras aplicáveis e LCR ou OCSP obrigatório para certificados finais e ACs.

O verificador admite somente as versões PAdES com período de assinatura vigente em 2026-09-12: AD-RB `2.16.76.1.7.1.11.1.2` e `.1.3`; AD-RT `2.16.76.1.7.1.12.1.2` e `.1.3`; AD-RC `2.16.76.1.7.1.13.1.3` e `.1.4`; AD-RA `2.16.76.1.7.1.14.1.3` e `.1.4`. Isso não presume que todo OID ICP-Brasil ou toda política histórica seja adequada.

A referência de política assinada é analisada pela estrutura ASN.1, com cardinalidade exata, e exige simultaneamente OID, algoritmo SHA-256 e resumo da política. Os resumos são conferidos contra a `LPA_PAdES.der` publicada pelo ITI, SHA-256 `4ef7a4e725deb1f785ddc822a999def912592126930eeab88c0cf45db1cf8d51`, e sua assinatura destacada `LPA_PAdES.p7s`, SHA-256 `615fee5bc30fafa10e2f548d5d3feba2e54e43ef55590163972457472834e513`, consultadas em 2026-09-12. A LPA informa próxima atualização em 2026-10-03T00:00:00Z; depois desse instante o registro falha fechado até uma atualização conferida. Um OID aprovado escondido em qualificador, política implícita, atributo duplicado, algoritmo diferente ou resumo arbitrário é recusado.

Os certificados públicos apontados pelo documento foram conferidos em 2026-09-12 e pinados pelo SHA-256 do DER: AC Raiz v5 `caa53fc6091c6951887c976e378f6ef89aa6377c55d97b6475422b71ed7e9b17` e AC Raiz v12 `d8478e37ce19c690cf657381e68fe600e4e1a042536830f06847e03e554c4b01`. Chave privada e ato de assinatura nunca são gerados ou solicitados pelo MODELA PRO.

O serviço valida a cadeia sem consulta de rede durante a importação. O operador fornece material público atualizado em `MODELA_REPORT_SIGNATURE_TRUST_ROOTS`, `MODELA_REPORT_SIGNATURE_CRLS` e `MODELA_REPORT_SIGNATURE_OCSPS`; cada variável recebe uma lista de caminhos DER ou PEM separada por `os.pathsep`. A configuração precisa conter uma raiz admitida e LCR/OCSP capaz de cobrir o certificado final e as ACs intermediárias. Ausência, expiração ou revogação deixa a assinatura pendente ou inválida. Essas variáveis recebem somente certificados e respostas públicas: o fluxo não lê nem solicita chave privada.

## Compatibilidade histórica do perfil

A versão `0.3.0` e o `source_set_sha256` foram preservados conscientemente. O conjunto de fontes e sua interpretação não mudaram; C06 corrigiu a capacidade da implementação e substituiu evidências históricas de lacuna por provas de produção. Alterar a versão quebraria a reabertura fail-closed de snapshots existentes, pois o resolver não trata versões como aliases intercambiáveis. Projetos históricos continuam sendo lidos pelos campos congelados e não são recomputados nem reclassificados como se já contivessem os novos insumos.

## Matriz dos 40 requisitos

| requisito | capacidade | representação exigida | prova de implementação |
|---|---|---|---|
| `meci.3.3.1.a` | emitido pelo produto | Equação utilizada com a variável dependente apresentada no laudo na forma NÃO TRANSFORMADA | Equação na escala de ajuste e forma na unidade original são emitidas com método e estimando de retransformação explícitos. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.b` | emitido pelo produto | Coeficientes atingidos: correlação (R), determinação (R²) e determinação ajustado (R² ajustado) | Renderer consome e apresenta R assinado, R² e R² ajustado do snapshot, sem derivar R de R². Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.c` | emitido pelo produto | Significâncias do modelo e das variáveis independentes | Tabela apresenta p-valores por regressor e significância F somente quando o produtor fornece números finitos. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.d` | emitido pelo produto | Número de dados utilizados | Snapshot, PDF, DOCX e XLSX apresentam a contagem e a identidade da amostra efetiva. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `meci.3.3.1.e` | emitido pelo produto | Atributos do imóvel avaliando (valores) | Atributos do avaliando persistidos no contexto e apresentados em PDF, DOCX e XLSX. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.f` | emitido pelo produto | Resultado da avaliação e intervalos atingidos (IC 80% E campo de arbítrio) | Estimativa, IC 80% e campo de arbítrio distintos são transportados do snapshot e apresentados. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.g` | emitido pelo produto | Gráfico de resíduos | Gráfico de resíduos é gerado a partir das séries alinhadas da amostra efetiva e verificado no PDF. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `meci.3.3.1.h` | emitido pelo produto | Gráfico de aderência (observados versus estimados) | Gráfico observado versus estimado com bissetriz é gerado a partir das séries alinhadas e verificado no PDF. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `meci.3.3.1.i` | emitido pelo produto | Demonstrativo da pontuação atingida (tabela de fundamentação e precisão) | Tabela apresenta grau, pontos e evidência por item e é repetida como anexo integral. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `meci.3.3.1.j` | emitido pelo produto | Histograma dos resíduos amostrais PADRONIZADOS | Histograma usa resíduos padronizados apenas com diagnóstico disponível, completo e alinhado à amostra efetiva. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.k` | emitido pelo produto | Probabilidades da distribuição normal padrão nos intervalos [-1;+1], [-1,64;+1,64] e [-1,96;+1,96] (68%, 90%, 95%) cotejadas com as frequências observadas | Tabela coteja frequências observadas e probabilidades nominais em ±1, ±1,64 e ±1,96. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.l` | emitido pelo produto | Matriz de correlações das variáveis independentes e dependente | Matriz integral na escala original é emitida; matriz de design adicional aparece quando fornecida. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.m1` | emitido pelo produto | Valor do teste F de Snedecor (F calculado) | F calculado é transportado de model.metrics e impresso. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.m2` | emitido pelo produto | Quantidade de outliers do modelo | Contagens de detectados, excluídos e influentes são emitidas apenas com cobertura diagnóstica completa. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.3.1.n` | insumo humano | Intervalos de valores admissíveis, quando for o caso, informados no campo "Observações" do laudo | Campo Observações profissional transportado ao PDF/DOCX e vinculado ao intervalo admissível calculado; ausência continua pendente. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.2.3.3.2.pdf` | emitido pelo produto | Relatório completo da inferência estatística em formato PDF, com gráficos (não só texto) | Pipeline renderiza PDF real com WeasyPrint, incorpora gráficos e verifica conteúdo contra snapshot/contexto. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `meci.2.3.3.2.excel` | emitido pelo produto | A amostra exportada em arquivo formato Excel (.xlsx/.xls) | sample.xlsx contém exatamente row_ids efetivos, variáveis, fontes e coordenadas e é verificado contra o snapshot. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.2.3.3.2.projecoes` | emitido pelo produto | O PDF contém "projeções" e "informações auxiliares" exigidas pela norma de avaliações | PDF/DOCX apresentam ponto, IC da média, intervalo preditivo e informações auxiliares sem confundir seus papéis. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.1.7.2.anexo` | emitido pelo produto | Memória de cálculo entregue como anexo do laudo — arquivo separado ou seção identificada, entregável em conjunto | Anexos integrais de amostra e pontuação fazem parte dos bytes; dossiê inclui artefatos documentais integrais por hash. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `bb.guiar.assinatura_icp` | emitido pelo produto | Via de assinatura digital do PDF por certificado ICP-Brasil | Fluxo importa PDF assinado, verifica integridade, cadeia, revogação, política PAdES e âncora oficial ITI pinada; certificado/assinatura reais continuam insumos externos e TESTE nunca satisfaz ICP. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.a` | insumo humano | identificação do solicitante | Solicitante tem porta persistida e representação em PDF/DOCX. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `10.1.b` | insumo humano | finalidade do laudo, quando informada pelo solicitante | Finalidade tem porta persistida e representação distinta do objetivo em PDF/DOCX. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `10.1.c` | insumo humano | objetivo da avaliação | Porta objetiva distinta da finalidade, persistida em report_context e emitida em PDF/DOCX; conteúdo permanece insumo humano. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.d` | insumo humano | pressupostos, ressalvas e fatores limitantes (7.2 da Parte 1) | Pressupostos, ressalvas e limitações persistidos e emitidos; lista vazia não satisfaz o caso. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.e` | emitido pelo produto | identificação e caracterização do imóvel avaliando (7.3 da Parte 1, no que couber) | Identificação e características do avaliando entram no contexto persistido e em todas as representações documentais. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.f` | insumo humano | diagnóstico do mercado (7.7.2 da Parte 1) | Diagnóstico do mercado persistido e emitido como campo próprio; conteúdo permanece insumo profissional. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.g` | emitido pelo produto | indicação do(s) método(s) e procedimento(s) utilizado(s) (Seção 8 da Parte 1) | Método, procedimento, equação, transformações e limitações são apresentados sem recalcular o snapshot. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `10.1.h` | emitido pelo produto | especificação da avaliação: grau de fundamentação e de precisão atingidos; demonstrativo da pontuação quando solicitado pelo contratante | Graus, status de precisão, pontuação total e demonstrativo por item são apresentados. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `10.1.i` | emitido pelo produto | planilha dos dados utilizados | PDF/DOCX e sample.xlsx apresentam todos os row_ids efetivos, valores, fontes e justificativas sem truncamento. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.j` | insumo humano | método comparativo: descrição das variáveis do modelo, com o critério de enquadramento de cada característica dos elementos amostrais e a escala das diferenças qualitativas | Critério, codificação, categorias e escalas por variável têm estrutura validada e tabela própria; definição é insumo profissional. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.k` | insumo humano | tratamento dos dados e identificação do resultado: cálculos efetuados, campo de arbítrio se for o caso, justificativas do resultado adotado e o gráfico de preços observados versus valores estimados | Cálculos, gráfico e campo de arbítrio são emitidos; a justificativa do valor adotado é insumo profissional obrigatório. Prova: tests/comercial/test_c06_output_conformance.py. |
| `10.1.l` | emitido pelo produto | resultado da avaliação e sua data de referência | Resultado e data de referência são campos distintos e verificados contra o snapshot. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `10.1.m` | insumo humano | qualificação legal completa e assinatura do(s) profissional(is) responsável(is) | Identidade, conselho, registro e ART/RRT são campos persistidos e emitidos; assinatura externa é tratada em etapa própria. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.4.1.grau_ii` | emitido pelo produto | Permitir DEFINIR o Grau de Fundamentação II como alvo e REPORTAR o grau atingido no laudo (MECI 3.4.1). | Alvo de fundamentação é consumido pela avaliação e o grau atingido é apresentado. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `meci.3.4.1.justificativa_grau_i` | insumo humano | Havendo Grau I, existir campo para a JUSTIFICATIVA exigida pelo MECI 3.4.1 ('Grau I admitido somente com justificativa'). | Porta e seção próprias para justificativa profissional, condicional a Grau I. Prova: tests/comercial/test_c06_output_conformance.py. |
| `meci.3.2.2.mcddm` | emitido pelo produto | O método padrão do produto é o comparativo direto de dados de mercado com tratamento por regressão linear (MECI 3.2.2). | Perfil, método comparativo direto e tratamento por regressão são identificados no documento. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `normas.12.1.16.tabela_anexa` | emitido pelo produto | Apresentar em TABELA ANEXA o demonstrativo da pontuação atingida para enquadramento nos graus de fundamentação e precisão (Normas para elaboração de laudos, 12.1.16.1). | Anexo próprio preserva item, grau, pontos e evidência; a tabela do corpo mantém a leitura operacional. Prova: tests/comercial/test_c06_output_conformance.py. |
| `normas.12.1.15.graficos` | emitido pelo produto | Gráfico de resíduos E gráfico de preços observados versus estimados chegarem ao laudo (Normas para elaboração de laudos, 12.1.15). | PDF incorpora e verifica gráficos de resíduos e observado versus estimado. Prova: tests/comercial/test_c06_output_conformance.py e testes C03 existentes. |
| `normas.12.1.8.geolocalizacao` | insumo humano | Registrar geolocalização do avaliando e de TODOS os elementos amostrais em graus decimais, com endereço completo e fonte por dado (itens 12.1.8/12.1.9). | Portas WGS84 para avaliando e todos os row_ids, com endereço e fonte, validação de completude e planilha integral; dados são insumo humano/documental. Prova: tests/comercial/test_c06_output_conformance.py. |
| `abnt.9.2.1.1.elasticidades` | emitido pelo produto | Para o Grau III, analisar as ELASTICIDADES em torno do ponto de estimação (NBR 14653-2, 9.2.1.1). | Para Grau III, tabela consome elasticidades na unidade original somente com cobertura quantitativa completa e método declarado. Prova: tests/comercial/test_c06_output_conformance.py. |

## Provas executáveis

`tests/comercial/test_c06_output_conformance.py` cobre o contrato produção → contexto → PDF/DOCX/XLSX → manifesto, incluindo campos profissionais, equação retransformada, diagnósticos completos, amostra efetiva com fonte/coordenadas e os 40 requisitos resolvidos. Os negativos recusam declaração do cliente, diagnóstico indisponível, bytes adulterados e certificado de TESTE promovido a ICP.

A matriz continua limitada ao material identificado no perfil: MECI-202400940-VER01 e as fontes registradas. Ela não estabelece vigência atual do MECI, não substitui revisão profissional e não registra aceitação institucional.
