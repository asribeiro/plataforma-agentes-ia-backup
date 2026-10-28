---
name: plataforma-agentes-ia-workflow
description: Fluxo padrão para trabalhar neste repositório, priorizando leitura da documentação pública, execução segura e validação mínima antes de alterações.
metadata:
  short-description: Workflow padrão do projeto plataforma-agentes-ia
---

# Workflow padrão — plataforma-agentes-ia

## Objetivo

Padronizar o trabalho neste projeto com foco em segurança, previsibilidade e mudanças mínimas.

## Sequência recomendada

1. Ler `README.md` e o índice de docs em `docs/public/README.md`.
2. Quando o pedido envolver setup/deploy, seguir a ordem dos guias em `docs/public/`.
3. Antes de editar, mapear impacto e manter mudanças cirúrgicas.
4. Após editar, validar o escopo alterado (teste/comando específico primeiro).
5. Para segurança, executar `python tools/security_check.py` antes de concluir mudanças relevantes.

## Regras de execução

- Não alterar infraestrutura/segredos sem pedido explícito.
- Não criar commits/branches sem solicitação.
- Evitar mexer em arquivos não relacionados ao pedido.
- Priorizar PostgreSQL (SQLite não suportado para instalação completa).
