# Matriz dos oito aceites C04

Data de corte: 2026-09-11. Os estados abaixo descrevem o candidato desta
branch, não o produto composto e não uma autorização de venda.

| aceite | estado da frente | evidência disponível | bloqueio/continuidade exata |
| --- | --- | --- | --- |
| C04-A01 — direito de distribuir | `IMPLEMENTED_PARTIAL` + `BLOCKED_EXTERNAL_EVIDENCE` | locks, SBOM, notices, `reuse.json`, manifesto e auditoria técnica de titularidade | o repositório não tem licença; direitos sobre contribuições, marca, três PDFs da raiz e notices do artefato final exigem decisão do titular |
| C04-A02 — instalador Windows/Linux | `IMPLEMENTED_PARTIAL` + `WAITING_FOR_COMPONENTS` | wheel, spec PyInstaller onedir, Inno Setup, launcher frozen e matriz documentada | instalador Windows x64 ainda não foi construído/instalado em Windows limpo; lock Windows ainda deve ser gerado no host-alvo; Linux é somente referência |
| C04-A03 — proteções da aplicação | `IMPLEMENTED_PARTIAL` + `WAITING_FOR_COMPONENTS` | componentes testados para bearer, Origin, CSRF, upload, ZIP, caminhos, workspace e redação | `backend/api.py`/websocket e bootstrap UI pertencem a consumidores; até a conexão e o teste das rotas reais, loopback não é considerado protegido |
| C04-A04 — backup/recuperação/migração | `IMPLEMENTED_PARTIAL` | backup com manifesto/hash, escrita serializada, corrupção/travessia recusadas, cancelamento e restauração em store vazio testados | migração A → B e rollback/restore em máquina limpa com paridade numérica/documental dependem da composição e do artefato Windows |
| C04-A05 — distribuição/licença do comprador | `IMPLEMENTED_PARTIAL` + `WAITING_FOR_COMPONENTS` | entitlement offline Ed25519, instalação atômica e regra que mantém leitura/exportação de evidência válida após expiração; minutas e suporte | pontos de entrada de cálculo/UI ainda não consomem a decisão; titular não aprovou termos; licença do comprador não é assinatura de laudo |
| C04-A06 — privacidade operacional | `IMPLEMENTED_PARTIAL` + `BLOCKED_EXTERNAL_EVIDENCE` | caminhos por usuário, permissões privadas, sem telemetria adicionada, redação de logs/diagnóstico, retenção/exportação documentadas | controlador/operador, base legal, retenção contratual e canal real devem ser definidos pelo responsável; integração das rotas/diagnóstico precisa ser verificada |
| C04-A07 — supply chain/atualização | `IMPLEMENTED_PARTIAL` + `WAITING_FOR_COMPONENTS` | pins, SBOM, auditoria de vulnerabilidades, build fail-closed em checkout/lock divergentes, manifesto/hashes | wheel/DLL/instalador Windows real e revisão das licenças `NOASSERTION` ainda precisam de execução; autoridade do titular e termos do comprador não estão registrados, sem inferir que a ausência de licença aberta proíba o titular legítimo |
| C04-A08 — carga/operação cotidiana | `IMPLEMENTED_PARTIAL` | orçamento prévio e checks de fila/cancelamento, backup, disco e PDF no Linux | corpus técnico agregado ficou vermelho e ensaio Windows não ocorreu; não há alegação universal de desempenho |

## Estados do produto

| decisão | estado em 2026-09-11 | motivo |
| --- | --- | --- |
| `TECHNICAL_QUALIFICATION` | `WAITING_FOR_COMPONENTS` | corpus agregado desta execução falhou; qualificação técnica final pertence à composição |
| `NORMATIVE_SCOPE_VERIFICATION` | `WAITING_FOR_COMPONENTS` | depende de C05/C01 e das fontes legítimas do perfil |
| `COMMERCIAL_PACKAGE_VERIFICATION` | `IMPLEMENTED_PARTIAL` | fontes de build e checks existem; instalador Windows real não |
| `INDEPENDENT_TECHNICAL_REVIEW` | `BLOCKED_EXTERNAL_EVIDENCE` | revisão adversarial interna não substitui revisor independente real |
| `REAL_CASE_VALIDATION` | `BLOCKED_EXTERNAL_EVIDENCE` | nenhum caso real autorizado foi fornecido |
| `INSTITUTION_PROFILE_VERIFICATION` | `BLOCKED_EXTERNAL_EVIDENCE` | nenhum manual/perfil concreto aplicável foi conferido integralmente |
| `INSTITUTION_ACCEPTANCE` | `BLOCKED_EXTERNAL_EVIDENCE` | nenhum ato real de destinatário foi fornecido/obtido |
| `COMMERCIAL_RELEASE_READY` | **falso** | direitos, composição, Windows, casos/revisão e perfis institucionais permanecem abertos |

Uma análise calculável pode continuar sendo salva e estudada com estado não
liberado. Nenhum teste de pacote, entitlement ou assinatura transfere aprovação
para o cálculo, o profissional ou o destinatário.
