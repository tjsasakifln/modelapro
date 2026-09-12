# Suporte, atualização e vulnerabilidades

## Política proposta para revisão do titular

Uma versão só é suportada se constar numa tabela de release publicada com data
de início, fim, plataformas e hash. Este candidato não cria compromisso de SLA.
O canal privado, responsável, horário e prazos precisam ser definidos pelo
titular antes de venda.

Classificação proposta: crítica (exploração alcançável com perda de
confidencialidade/integridade/disponibilidade essencial), alta, moderada e baixa.
Crítica alcançável bloqueia release. Alertas de dependência recebem análise de
alcance, versão afetada, mitigação e decisão identificada; ausência de alerta não
é prova de segurança.

## Processo de release

1. fixar commit, versão e ambiente de build;
2. executar testes, corpus operacional e instalação limpa por plataforma;
3. gerar artefato, hashes, lock, SBOM, notices e relatório de vulnerabilidades;
4. comparar conteúdo do artefato com allow-list (sem PDFs/fontes/testes/dados);
5. assinar com chave legítima quando exigido;
6. revisar migração/backup/restore/rollback e release notes;
7. publicar somente após as decisões técnicas, normativas, profissionais e
   comerciais aplicáveis.

Atualizações são manuais/offline por padrão. O software não baixa código nem
envia inventário sem ação explícita. Uma correção de segurança deve preservar
acesso a evidências históricas e registrar versões afetadas.

## Canal pendente

`BLOCKED_EXTERNAL_EVIDENCE`: o titular ainda deve designar e publicar contato
privado de suporte/segurança. `SECURITY.md` define o conteúdo mínimo e proíbe
issues públicas com dados reais.
