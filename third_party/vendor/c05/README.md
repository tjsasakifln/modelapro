# third_party/vendor/c05/ — vazio por decisão

Esta frente (MP-COM-20260912/C05) **não incorporou nenhum fragmento de código de
terceiros**. O diretório existe porque o contrato da campanha atribui a cada frente um
espaço próprio de vendoring, e porque um diretório ausente é ambíguo: não distingue "nada
foi incorporado" de "ninguém verificou".

A decisão e sua justificativa estão em [`../../../docs/comercial/c05/reuse.json`](../../../docs/comercial/c05/reuse.json):

- O trabalho desta frente é regra normativa e contrato de qualificação — não há solver,
  criptografia ou formato complexo a reimplementar nem a copiar.
- `pypdf` (BSD-3-Clause) foi usada **apenas em ambiente de desenvolvimento local**, para
  ler os exemplares licenciados das normas e conferir limiares contra o texto. Nenhum
  código de produto a importa, e ela não é dependência de runtime.
- Nenhuma dependência foi instalada, atualizada ou proposta ao produto por esta frente.
  C04 é o único editor das dependências e constraints globais.

Se uma incorporação futura ocorrer aqui, o manifesto exige registrar: `origin_url`,
commit/tag, arquivos e funções, hashes, SPDX/licença, notices, dependências transitivas,
vulnerabilidades, razão de dependência versus cópia, adaptações, responsável por
atualizações e testes de equivalência contra o upstream.
