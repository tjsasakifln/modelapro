# Manual operacional do candidato C04

## Requisitos e instalação

Produto-alvo: Windows 11 x64 em estação local. O pipeline gera bundle
`onedir` com runtime Python e um instalador Inno Setup; o comprador não deve
clonar o repositório, instalar Python, usar terminal ou WSL. Esse percurso só
pode ser anunciado após build e instalação reais em máquina Windows limpa,
incluindo geração de PDF e desinstalação. O estado de cada candidato vem da
execução Windows identificada, não da presença dos arquivos de build.

Linux x86_64 é uma referência separada. Wheel/venv de desenvolvimento não é o
produto Windows e o pacote Linux não valida DLLs, instalador ou assinatura do
Windows.

Antes de instalar, confira versão, sistema/arquitetura, SHA-256, SBOM e status de
assinatura publicados juntos. Um instalador `UNSIGNED` deve ser apresentado
como tal; assinatura de código só é requisito se a oferta aprovada a exigir.
Não ignore divergência de hash ou alerta de assinatura quando aplicável. A
versão e os limites do produto ficam em **Ajuda/Sobre**.

## Dados e início/parada

Por padrão, dados e estado ficam no perfil do usuário, fora do checkout.
Diretórios podem ser redirecionados apenas para caminho local controlado. O modo
compartilhado e bind em todas as interfaces não são suportados.

O lançador inicia API e UI como processos filhos e encerra ambos em saída normal
ou sinal. Uma interrupção durante cálculo marca o trabalho como interrompido;
snapshot já congelado não é apagado. Não mate o processo durante restore ou
atualização. Se isso ocorrer, use o último backup íntegro.

## Backup e restauração

1. Aguarde os trabalhos ativos e, na interface, abra **Licença, cópia de
   segurança e restauração**.
2. Use **Preparar cópia de segurança** e depois **Baixar cópia de segurança**.
   A UI autentica a rota local `/operations/backup`; o ZIP contém manifest,
   versão de schema e SHA-256 de cada membro e não contém symlinks.
3. Copie o ZIP para mídia aprovada pelo controlador. O produto não o envia à
   nuvem automaticamente.
4. Para restaurar, use **Cópia para restaurar em espaço vazio** e **Restaurar
   cópia verificada**. A UI envia o ZIP à rota local `/operations/restore`; o
   produto valida conteúdo, hashes e caminhos antes de criar um store privado
   separado. O store atual não é sobrescrito.
5. Reinicie quando solicitado e confira projetos, snapshots, anexos,
   PDF/dossiê e reprodução. Preserve o backup e o store anterior até terminar
   a conferência.

Rollback de código não abre automaticamente schema de dados mais novo. Restaure
o backup pré-atualização com a versão compatível. Nunca misture executável antigo
e store já migrado.

## Atualização

Cada atualização exige backup verificado, manifest de migração, release notes,
SBOM/scan e teste `A → trabalhos → B → reabrir/reproduzir → restore A`. Ausência
de migração conhecida deve falhar sem mutar o store. Atualizador automático e
download em nuvem não são ativados por padrão.

## Licença expirada

Expiração pode impedir novo cálculo conforme o contrato do comprador. Ela não
impede abrir, verificar, exportar ou fazer backup de trabalhos/evidências já
produzidos. Arquivo de licença não é assinatura do laudo nem prova de habilitação
do profissional.

## Falhas

- Disco insuficiente: o novo trabalho deve ser recusado antes de gravar; libere
  espaço sem apagar o único backup.
- Biblioteca PDF ausente: o cálculo pode permanecer íntegro, mas o artefato fica
  falho/pending; instale o build correto, não fabrique PDF vazio.
- Corrupção: preserve o original, registre hash/versão e restaure o backup
  verificado em raiz separada; não tente editar o ZIP ou apontar o produto para
  um diretório parcialmente restaurado.
- Diagnóstico: gere localmente, revise a redação e compartilhe somente pelo canal
  autorizado. Nunca envie base, laudo, token, chave ou licença por issue pública.
