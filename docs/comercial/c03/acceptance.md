# Oito aceites C03

Estado da frente: `IMPLEMENTED_PARTIAL`. Estado comercial do produto: não liberado; depende da
composição C01/C02/C04/C05/C06 e de evidências externas indicadas abaixo.

| Aceite | Estado da frente | Evidência | Limite do produto |
|---|---|---|---|
| C03-A01 | IMPLEMENTED_VERIFIED | Gate MP-QUAL/1 exige decisão técnica aprovadora, profissional/motivo/versão e fingerprints do resultado e do conteúdo; `signed` não substitui revisão | Casos/revisores reais: `BLOCKED_EXTERNAL_EVIDENCE` |
| C03-A02 | IMPLEMENTED_VERIFIED | PDF congela ponto, valor adotado, quatro intervalos, datas, contagens, coeficientes, perfil, regra, grau e revisão; verifier acusa mutação específica | Autoridade das regras depende de C05 |
| C03-A03 | IMPLEMENTED_VERIFIED | Fixture sintética 200+, mapa exato de IDs, fontes/valores, imagem autorizada e hash do conjunto no PDF | Fotos/documentos reais: `BLOCKED_EXTERNAL_EVIDENCE` |
| C03-A04 | IMPLEMENTED_VERIFIED | Dossiê com mapa de representações, qualificação/revisão e estados separados; reprodução de ponto/IC/predição/arbítrio/admissível; snapshots, IDs, coeficientes, assinatura e PDF são reconciliados | Completude depende dos bytes recebidos em cada caso |
| C03-A05 | IMPLEMENTED_PARTIAL | PDF e DOCX determinístico do mesmo view; DOCX incorpora imagens autorizadas e edição externa é detectada | PDF/A fica `unsupported` sem validador concreto; integração aguarda C01/C04/C06 |
| C03-A06 | IMPLEMENTED_PARTIAL | pyHanko 0.37.0 assinou/verificou revisão incremental com certificado temporário; o gate reexecuta a criptografia sobre os bytes e vincula snapshot, conteúdo e revisão | Dependência global aguarda C04; ICP-Brasil/revogação/carimbo/perfil real: `BLOCKED_EXTERNAL_EVIDENCE` |
| C03-A07 | WAITING_FOR_COMPONENTS | Pacote neutro valida PDF, equivalência DOCX, snapshot, IDs/coeficientes do dossiê e mapa substantivo de requisitos antes de empacotar | Perfis comprometidos e fontes legítimas aguardam C05; aceite institucional é evento externo |
| C03-A08 | IMPLEMENTED_VERIFIED | Mutações específicas de valor, intervalo, coeficiente, data, linha, perfil, revisão, base do PDF assinado e manifestos falham | Prova externa de assinatura depende do caminho qualificado acima |

`IMPLEMENTED_VERIFIED` descreve o comportamento testado da frente. Não equivale a
`COMMERCIAL_RELEASE_READY`, homologação institucional ou conformidade de uma avaliação concreta.
