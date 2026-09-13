# C02 — handoff retomável

**Frente:** MP-COM-20260912-V2 / C02 — Fluxo profissional, responsabilidades e destinatários  
**Branch:** `mp-com-20260912/c02-fluxo-profissional`  
**Base:** `8d66c7973c659174e06d7223c9a9a8181e8eeabf` (`mp-pro-20260911/p04-referencia-consolidacao`, PR #20)  
**Alvo da PR incremental:** `mp-pro-20260911/p04-referencia-consolidacao`  
**SHA do produto:** publicado no comentário da PR após o commit (não gravado dentro dele).

## Objetivo executivo

Permitir que o avaliador que comprou o produto execute o trabalho completo, compreenda o método e libere somente a revisão correta para assinatura/entrega, inclusive com perfis de banco e seguradora visíveis como **não homologados**, sem operar como inseridor de dados numa caixa-preta.

## O que foi implementado neste HEAD

- Percurso profissional na UI existente (não reescrita): encomenda e perfil → amostra e evidências → avaliando e vistoria → modelagem e revisão → emissão e arquivo.
- `build_request_spec` emite campos aditivos MP/1: `qualification_profile`, `rights`, `recipient_id`, `value_basis`, `asset_scope`.
- Catálogo conhecido de perfis (C02 escolhe ids; **não** escreve regras C05). Banco/seguradora nunca recebem selo «aceito pelo…» a partir de compatibilidade.
- Vistoria/documentos/identidade com procedência; defaults não atestam ART/inspeção/regularidade.
- Invalidação de resultado, revisão e assinatura em mudança de arquivo, amostra, avaliando, perfil ou documento, sem apagar histórico.
- Checklist de revisão ligado ao fingerprint; exportação para assinador externo; importação de comprovante (HTTP 200 local ≠ aceite).
- Rotina vendida: backup, pesquisa local, histórico, redacção de PII, bloqueio de duplo POST.

## Reconciliação MP-HOM

Nenhuma branch `mp-hom` / H01–H06 observada em `origin` no início desta frente. Nada a reaproveitar nem a apagar.

## Estado honesto do produto

Ver `aceites.md`. Resumo: núcleo urbano comparativo/regressão no fluxo profissional **IMPLEMENTED_VERIFIED** na interface e no contrato aditivo. Perfis banco/seguradora **visíveis e recusados como homologados**. Rota de custo C01 e catálogo C05 **WAITING_FOR_COMPONENTS**. Aceite institucional **BLOCKED_EXTERNAL_EVIDENCE**. Não `COMMERCIAL_RELEASE_READY`.

## Comandos de verificação

```text
PYTHONPATH= python3 -m pytest tests/comercial/c02 tests/c09_frontend tests/pro_workflow/p02 tests/test_forms_heuristics.py -q --tb=short
```

Duas passagens, `PYTHONPATH` vazio, no tree a commitar.

## Retomada

1. Fetch `origin`; rebase/merge só se a base P04 avançar (sem force-push).
2. Se C01/C05 publicarem catálogo/`qualification_context`, passar a consumir `source_set_sha256` real e reavaliar A01/A04 (sem escrever regras aqui).
3. Se Playwright/Chromium estiver no ambiente, completar A08 no browser real (importação → revisão → cálculo → evidências → emissão → download → reabertura) e gravar screenshot.
4. C06 incorpora este HEAD na #20 depois de SEALED; C02 não publica na #20.

## Escrita

Somente `frontend/`, `tests/c09_frontend/`, `tests/pro_workflow/p02/`, `tests/test_forms_heuristics.py`, `tests/comercial/c02/`, `docs/comercial/c02/`. `third_party/vendor/c02/` vazio (sem fragmento copiado).
