# Privacidade e confidencialidade operacional

Esta minuta descreve comportamento do produto; não declara “LGPD compliant” e
não define, sozinha, controlador, operador, base legal ou retenção de cada
cliente. Essas decisões pertencem ao contrato/caso e exigem revisão do titular.

## Comportamento padrão verificável

- cálculo, projetos, logs, backups e diagnósticos permanecem no equipamento;
- nenhuma telemetria de dados pessoais ou consulta à nuvem é necessária;
- o produto coleta apenas dados enviados pelo operador para a avaliação e
  metadados técnicos mínimos;
- logs e diagnósticos removem tokens, e-mail, CPF e campos de payload conhecidos;
- exportação/backup é ação local explícita e não transmissão automática;
- expiração de licença não remove nem bloqueia a portabilidade das evidências.

## Retenção e eliminação

O controlador deve configurar e documentar prazo por categoria: fonte de
mercado, projeto, evidência, backup, log e registro de incidente. Exclusão deve
ser explícita, auditável e não apagar material sujeito a obrigação legal,
contraditório ou preservação contratual. Backups têm ciclo próprio; apagar o
store ativo não apaga cópias externas.

O release inicial não oferece eliminação remota, telemetria de uso ou upload
automático. Um administrador local pode copiar/ler arquivos do perfil; o modelo
não promete proteção contra esse administrador.

## Diagnóstico e suporte

O operador vê o conteúdo do bundle antes de compartilhá-lo. Ele deve conter
versão, plataforma, hashes/estado, códigos de erro e métricas de recurso, nunca
planilha, endereço, nome de cliente, laudo, foto, certificado, token ou chave.
Suporte deve solicitar o mínimo necessário e fornecer canal privado antes da
liberação comercial.

## Pendências externas

Antes da oferta, identificar por perfil de cliente: papéis de tratamento, base
legal, finalidade, titulares, categorias, retenção, operadores/suboperadores,
transferência, resposta a direitos e processo de incidente. Referências oficiais
consultadas estão em `primary_sources.md`.
