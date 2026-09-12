# C04 — fontes primárias consultadas

Consultado em 2026-09-11. Este registro apoia decisões de produto e a
qualificação comercial; não é parecer jurídico, certificação, homologação
institucional ou autorização para tratar dados pessoais. As versões de
dependências referidas são as travadas no candidato (`constraints/linux-py3.txt`)
na data desta consulta. A SBOM/notices de um artefato distribuído continuam
devendo ser gerados a partir do ambiente/artefato efetivamente entregue.

## Privacidade, confidencialidade e incidentes

- A [LGPD, Lei nº 13.709/2018 consolidada (arts. 6º, 16, 18, 46, 48–50)](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm)
  estabelece princípios como necessidade, direitos do titular incluindo acesso
  e portabilidade nas hipóteses legais, medidas técnicas e administrativas de
  segurança, comunicação de incidente nos casos definidos em lei e requisitos
  de segurança/boas práticas para sistemas de tratamento. Para C04, isso dá
  base para minimização, exportação controlada, logs redigidos e processo de
  incidente; não demonstra, por si, conformidade LGPD de um caso concreto.
- A [página oficial da ANPD para comunicação de incidente](https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca-cis)
  orienta que o controlador avalie o risco e que a comunicação se aplica a
  incidente confirmado envolvendo dados pessoais que possa acarretar risco ou
  dano relevante. O procedimento não substitui avaliação jurídica nem autoriza
  enviar dados/diagnósticos do produto à ANPD sem o controlador competente.
- A [Resolução CD/ANPD nº 15/2024, divulgada pela própria ANPD](https://www.gov.br/anpd/pt-br/assuntos/noticias/anpd-aprova-o-regulamento-de-comunicacao-de-incidente-de-seguranca)
  regulamenta a comunicação de incidente e requer registro por ao menos cinco
  anos segundo a divulgação oficial. C04 deve manter trilha local de incidente
  quando aplicável, sem alegar que a retenção do software, isoladamente,
  cumpre todos os deveres do controlador.
- O [texto oficial do RCIS (Resolução CD/ANPD nº 15/2024)](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/documentos/rcis___anonimizado_final_ocultado_2_parte3.pdf)
  fixa, para a comunicação de incidente sujeito ao regulamento, prazo de três
  dias úteis; fluxos operacionais devem ser avaliados pelo controlador e não
  devem transmitir automaticamente informações de um projeto ao fornecedor.
- O [Guia orientativo de segurança da informação da ANPD](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/processo-guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte.pdf)
  reúne medidas administrativas e técnicas para agentes de pequeno porte. É
  orientação, não selo de conformidade, certificação ou substituto de análise
  de risco proporcional ao produto.

## Desenvolvimento seguro e cadeia de suprimentos

- O [NIST SP 800-218, SSDF v1.1 (final, fevereiro de 2022)](https://csrc.nist.gov/pubs/sp/800/218/final)
  recomenda práticas de desenvolvimento seguro que podem ser integradas ao
  SDLC para reduzir vulnerabilidades, mitigar impacto e prevenir recorrências.
  É uma referência de práticas e vocabulário para fornecedores/compradores,
  não uma certificação NIST nem prova de ausência de vulnerabilidades.
- A [documentação oficial do GitHub sobre licenciamento de repositórios](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
  esclarece que, sem licença, o titular retém direitos e terceiros não recebem
  permissão para reproduzir, distribuir ou criar derivados; a visibilidade
  pública por si só não concede licença de redistribuição. Assim, cada
  dependência, arquivo vendorizado, imagem e fonte do artefato requer licença,
  versão e notice verificáveis antes da distribuição.

## Dependências e empacotamento candidatos

- O repositório oficial do [SciPy](https://github.com/scipy/scipy) identifica
  a licença BSD-3-Clause, e o do [statsmodels](https://github.com/statsmodels/statsmodels)
  identifica a licença BSD-3-Clause. São referências de origem para as
  dependências numéricas travadas; o release/arquivo exato, suas licenças
  embutidas, notices e dependências transitivas ainda devem ser coletados no
  SBOM do artefato, não inferidos da página da branch principal.
- Os metadados upstream do [NumPy](https://github.com/numpy/numpy/blob/main/pyproject.toml)
  declaram uma expressão de licença que inclui BSD-3-Clause, 0BSD, MIT, Zlib e
  CC0-1.0 para arquivos identificados; a licença não pode ser resumida como
  somente BSD sem inspeção do wheel distribuído. O [arquivo de licença do
  pandas](https://github.com/pandas-dev/pandas/blob/main/LICENSE) identifica
  BSD-3-Clause. Para ambos, a verificação definitiva continua sendo do
  release/wheel travado e de suas transitivas no artefato final.
- A [documentação oficial do PyInstaller 6.22.2](https://pyinstaller.org/en/stable/)
  descreve que ele agrupa aplicação e dependências para execução sem Python
  instalado pelo usuário e que não é compilador cruzado: o binário Windows
  deve ser produzido no Windows e o Linux no Linux. Isso sustenta matrizes de
  build/teste separadas; não comprova que o produto foi instalado em máquina
  limpa nem que um instalador Windows está assinado.
- A documentação de [modo de operação do PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html)
  registra que artefatos são específicos do sistema operacional, versão de
  Python e arquitetura usados no build; por isso Windows x64 e Linux requerem
  builds e validações próprios. Ela também alerta para os riscos operacionais
  do modo `onefile` no Windows; a escolha não substitui teste de instalação
  limpa e hardening do diretório temporário.
- Os [termos de licença do PyInstaller](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt)
  registram GPL-2.0-or-later com exceção do bootloader para embutir/distribuir
  o bootloader com programas não livres, inclusive comerciais; modificações e
  demais componentes continuam sujeitos aos termos aplicáveis. Caso adotado,
  C04 deve fixar release/commit, registrar `pyinstaller`,
  `pyinstaller-hooks-contrib` e transitivas, preservar notices e revisar a
  licença no artefato real.

## Assinaturas eletrônicas: limite da evidência

- O [VALIDAR do ITI](https://validar.iti.gov.br/) informa que valida assinaturas
  ICP-Brasil, GOV.BR ou de acordos de reconhecimento e que o resultado se
  limita a identificar o titular do certificado e confirmar se o documento
  não foi adulterado após a assinatura. Portanto, uma validação de assinatura
  apoia integridade/autoria da assinatura, mas não valida cálculo, conteúdo
  técnico, qualificação profissional, aceitação por banco/seguradora ou
  licença do software.

## Limites e continuidade obrigatória

Estas fontes não cobrem termos comerciais do comprador, definição concreta de
controlador/operador, base legal de cada tratamento, obrigação contratual de
seguradora/banco, licença de ativos não-Python ou vulnerabilidades de um
release. Antes de declarar distribuição, o responsável C04 deve vincular os
hashes do lock, SBOM, scanner e notices ao artefato final e tratar cada
pendência material como bloqueio ou decisão identificada.
