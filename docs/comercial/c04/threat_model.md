# Modelo de ameaças — estação local profissional

## Escopo e fronteiras

O produto-alvo executa API e UI em loopback, com projetos sob diretório privado
do usuário do sistema operacional. Navegador, arquivos importados, arquivos de
licença, backups e diagnósticos cruzam a fronteira de confiança. Uma página web
maliciosa pode tentar alcançar `localhost`; loopback não é autorização.

Fora do escopo declarado: servidor compartilhado, acesso remoto, RBAC
multiusuário, proteção contra administrador/root comprometido e sincronização em
nuvem. Configuração não-loopback deve falhar até outro modelo ser qualificado.

## Ativos

- dados de imóveis, fontes, anexos e identificadores;
- snapshots, revisões, laudos e dossiês que sustentam decisões profissionais;
- tokens de acesso local e licenças do comprador;
- executáveis, locks, SBOM, hashes e histórico de migração;
- logs e diagnósticos, que não devem virar uma cópia silenciosa do projeto.

## Ameaças e controles

| ameaça | controle C04 | estado de composição |
| --- | --- | --- |
| página maliciosa chama localhost | allow-list exata de `Origin`, token bearer e CSRF em mutações | componente implementado; conexão em `backend/api.py` é handoff C01/C06 |
| leitura cruzada de job/projeto | escopo de workspace/projeto e comparação constante de segredo | componente/teste; rotas reais aguardam conexão |
| travessia/symlink | componentes de caminho seguro e restore sem links/`..` | implementado/testado |
| arquivo malformado ou bomba ZIP | limite comprimido/descomprimido, razão, quantidade e extensão/magic | implementado/testado no componente; parsers reais aguardam conexão |
| CSV formula injection | exportação deve prefixar células iniciadas por `= + - @`; dossiê MP/1 já tem teste próprio | preservar na composição |
| parsing/executável perigoso | JSON declarativo; pickle/model object recusado; nenhuma fórmula de planilha executada | implementado na persistência; integrar importadores |
| vazamento por log/diagnóstico | mensagens e campos sensíveis redigidos; bundle mínimo revisado pelo operador | implementado/testado |
| corrupção/queda | SQLite FULL/WAL, sidecars atômicos, backup com hashes, restauração em raiz limpa | implementado/testado; energia real não simulada |
| exaustão de disco/memória/CPU | limites pré-definidos e cancelamento cooperativo | componente/teste; benchmark do hardware-alvo pendente |
| licença expirada sequestra evidência | leitura/exportação permanecem autorizadas; apenas novo cálculo é negado | implementado/testado |
| dependência/instalador adulterado | lock, SBOM, scanner, hashes; assinatura real pendente | parcial; composição/release C06 |

## Dados em repouso

Permissões por usuário e diretório privado reduzem exposição casual. Esta frente
não promete criptografia que resista a administrador comprometido. Se o contrato
exigir criptografia em repouso, o titular deve escolher gestão de chaves ligada
ao sistema operacional e validar backup/recuperação; não se embute chave no
produto.
