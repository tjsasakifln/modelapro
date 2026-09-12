# Manual operacional do candidato C04

## Requisitos e instalação

Produto-alvo: Windows 11 x64 em estação local. O pipeline planejado gera bundle
`onedir` com runtime Python e um instalador Inno Setup; o comprador não deve
clonar o repositório, instalar Python, usar terminal ou WSL. Esse percurso só
pode ser anunciado após build e instalação reais em máquina Windows limpa,
incluindo geração de PDF e desinstalação. Nesta branch, o estado permanece
`WAITING_FOR_COMPONENTS`/`NOT_RUN` onde indicado em `acceptance.md`.

Linux x86_64 é uma referência separada. Wheel/venv de desenvolvimento não é o
produto Windows e o pacote Linux não valida DLLs, instalador ou assinatura do
Windows.

Antes de instalar, confira versão, sistema/arquitetura, SHA-256, SBOM e status de
assinatura publicados juntos. Não ignore divergência de hash ou alerta de
assinatura. A versão deve ficar visível em `--version`, manifest de release e
Ajuda/Sobre após o handoff da interface.

## Dados e início/parada

Por padrão, dados e estado ficam no perfil do usuário, fora do checkout.
Diretórios podem ser redirecionados apenas para caminho local controlado. O modo
compartilhado e bind em todas as interfaces não são suportados.

O lançador inicia API e UI como processos filhos e encerra ambos em saída normal
ou sinal. Uma interrupção durante cálculo marca o trabalho como interrompido;
snapshot já congelado não é apagado. Não mate o processo durante restore ou
atualização. Se isso ocorrer, use o último backup íntegro.

## Backup e restauração

1. Cancele/aguarde trabalhos ativos e feche a aplicação.
2. Crie um backup pela ferramenta operacional. O diretório contém manifest,
   versão de schema e SHA-256 de cada membro; não contém symlinks.
3. Copie o backup para mídia aprovada pelo controlador. O produto não o envia à
   nuvem automaticamente.
4. Restaure somente em diretório novo/vazio. A verificação acontece antes da
   troca de estado; hash inválido, membro extra ou caminho inseguro aborta.
5. Abra projetos e confira snapshot, anexos, PDF/dossiê e reprodução.

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
  verificado em raiz separada; seleção automatizada de projeto ainda não está
  implementada e permanece parcial no aceite A04.
- Diagnóstico: gere localmente, revise a redação e compartilhe somente pelo canal
  autorizado. Nunca envie base, laudo, token, chave ou licença por issue pública.
