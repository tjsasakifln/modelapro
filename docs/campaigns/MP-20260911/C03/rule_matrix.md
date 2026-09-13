# C03 rule matrix (ABNT NBR 14653-2:2011)

Protected table wording is not reproduced. Each row is a calculable condition
verified against the authorized local PDF
`docs/normas/NBR 14653-2 2011  Avaliação de bens Imóveis urbanos.pdf`.

| id | edition / item / fonte | dados necessários | cálculo | teste |
| --- | --- | --- | --- | --- |
| tabela1.item1 | 14653-2:2011 Tabela 1 item 1 | grau declarado + proveniência | documental; declared ≠ verified | C03-A05 |
| tabela1.item2 | 14653-2:2011 Tabela 1 item 2 | n efetivo, k efetivo (intercepto declarado) | n vs 3(k+1) / 4(k+1) / 6(k+1) | C03-A04, TestItem2QuantidadeDados |
| tabela1.item3 | 14653-2:2011 Tabela 1 item 3 | grau declarado + proveniência | documental; declared ≠ verified | C03-A05 |
| tabela1.item4.measure | 14653-2:2011 Tabela 1 item 4 (a) | min/max amostrais e valor do avaliando (eixo quantitativo, razão positiva) | [min,max] in-sample; extensão ≤2·max e ≥0,5·min | C03-A01, C03-A02 |
| tabela1.item4.value | 14653-2:2011 Tabela 1 item 4 (b) | `predict_original` na unidade original | \|ŷ_av−ŷ_front\|/\|ŷ_front\|; II ≤15% uma variável; I ≤20% de per si e simultaneamente | C03-A01, C03-A02, C03-A03 |
| anexoA.5_7.qualitative | 14653-2:2011 Anexo A.5, A.6, A.7 | kind + conjunto amostral discreto | sem faixa numérica inventada | C03-A02 |
| tabela1.item5 | 14653-2:2011 Tabela 1 item 5 | p-valores dos regressores (exceto intercepto) | pior p ≤10%/20%/30% | C03-A04, TestItem5 |
| tabela1.item6 | 14653-2:2011 Tabela 1 item 6 | p-valor do teste F | p ≤1%/2%/5% | C03-A04, TestItem6 |
| tabela2.enquadramento | 14653-2:2011 Tabela 2 / 9.2.1.6 | graus dos itens 1–6 | pontos mínimos e obrigatórios; pendência não aprova | C03-A04, TestClassifyFundamentacao |
| tabela5.precisao | 14653-2:2011 Tabela 5 / 9.2.3 | amplitude % do IC 80% | ≤30/40/50 → 3/2/1; >50 unclassified; ausente not_computed; não finito error | C03-A04, C03-A05 |
| campo_arbitrio | 14653-2:2011 8.2.1.5.1 e 8.2.1.5.4; 14653-1:2001 3.8 | estimativa de tendência central | ±15%; distinto do IC 80% | C03-A05 |
| admissiveis.central | 14653-2:2011 Anexo A.10.1.1 notas 9–10 | estimand, adopted_estimator, IC e/ou PI | interseção só com condição de uso declarada | C03-A05 |

Item 4 Grau III = extrapolação não admitida. Grau II/I exigem (a) **e** (b).
Faixa ampliada sozinha não aprova. `predict_original` ausente com eixo fora de
[min,max] → pending (assess_normative) / 0 no adapter legado.
