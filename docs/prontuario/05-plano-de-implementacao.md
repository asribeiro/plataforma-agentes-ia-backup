# Fase 3 — Plano de implementação

## Ordem aprovada para execução

1. E-01: H-01.1, H-01.2 e testes integrados.
2. E-02: H-02.1, H-02.2 e testes integrados.
3. E-03: H-03.1, H-03.2 e testes integrados.
4. E-04: H-04.1, H-04.2 e testes integrados.
5. E-05: H-05.1, H-05.2 e testes integrados.

Cada história começa por testes unitários que falham, implementa apenas o
contrato aprovado, executa testes focados e depois a suíte completa. Nenhuma
migração, rota ou tela será criada antes da aprovação explícita.

## Status após a aprovação

- **H-01.1 implementada:** modelos SQLAlchemy, migration Alembic e testes de
  integridade foram criados; a execução dos testes depende da instalação das
  dependências Python do projeto.
- **H-01.2 implementada:** o contexto transacional `app.clinic_id` foi
  centralizado e o fluxo de auditoria passou a aplicá-lo antes de ler/gravar
  acessos clínicos; a matriz de papéis já existente foi reutilizada.
- **H-02.1 implementada:** a API inicial de pacientes foi adicionada com
  cadastro, busca, filtros administrativos e recorte por clínica.
- **H-02.2 implementada:** a ficha do paciente foi adicionada com resumo,
  métricas, linha do tempo e atendimentos; anotações ficam ocultas para o
  Profissional de Atendimento.
- **H-03.1 implementada:** o fluxo de evolução clínica permite registrar uma
  nota, restringe o profissional ao próprio atendimento, assina com hash
  determinístico e registra evento na linha do tempo.
- **H-03.2 implementada:** adendos versionados para notas assinadas e
  exportação do histórico clínico em PDF foram adicionados.
- **H-04.1 implementada:** tratamentos, procedimentos, estados, validação de
  recorrência e progresso por sessões foram adicionados.
- **H-04.2 implementada:** geração de sessões dentro da janela configurada,
  prevenção de duplicidade, detecção de conflito, status pendente e tarefa
  específica para confirmação foram adicionados.
- **H-05.1 implementada:** cálculo de ciclo de vida, marcação de no-show por
  prazo configurável, eventos de timeline e lista de reativação foram
  adicionados.
- **H-05.2 implementada:** envio de pesquisa pelo provider WhatsApp, resposta
  NPS, expiração, eventos de follow-up e painel de jornada foram adicionados.

## Prompts por história

Para cada item, usar o prompt-base abaixo substituindo `[HISTÓRIA]` pelo ID e
título e mantendo os testes listados em [02-backlog.md](./02-backlog.md):

```text
Implemente [HISTÓRIA] do módulo Prontuário e Jornada do Paciente, conforme
docs/prontuario/02-backlog.md e docs/prontuario/03-mer.md.
1. Escreva primeiro os UT da história e confirme que falham.
2. Implemente o mínimo para todos passarem, seguindo os RN citados.
3. Garanta clinic_id + RLS, perfis, auditoria e ausência de conteúdo clínico
   para Atendimento/Master.
4. Não altere comportamento fora do escopo; pare e pergunte se o contrato
   existente de agenda/CRM estiver incompatível.
5. Rode testes focados e a suíte completa.
6. Liste arquivos, critérios atendidos e suposições.
```

Histórias, na ordem:

- H-01.1 — Criar modelo de dados e migração
- H-01.2 — Implementar perfis, RLS e auditoria
- H-02.1 — Criar lista e cadastro de pacientes
- H-02.2 — Criar resumo, linha do tempo e atendimentos
- H-03.1 — Registrar e assinar evolução
- H-03.2 — Corrigir por adendo e exportar histórico
- H-04.1 — Criar planos e progresso
- H-04.2 — Gerar, remarcar e tratar conflitos
- H-05.1 — Calcular ciclo de vida e no-show
- H-05.2 — Integrar NPS via WhatsApp e painel

## Prompts de fechamento dos épicos

```text
Todas as histórias de [ÉPICO] estão implementadas.
1. Implemente os testes integrados IT do épico usando seed fictício das clínicas
   A e B.
2. Rode testes integrados e suíte completa; corrija falhas sem mudar regras.
3. Verifique explicitamente isolamento, perfis, logs e ausência de conteúdo
   clínico nos payloads da IA.
4. Atualize docs/prontuario/04-diagramas.md se a implementação divergir e
   explique o motivo.
5. Entregue histórias, cobertura, pendências e riscos.
```

## Checklist de cada história

- [ ] Testes unitários escritos antes da implementação.
- [ ] Critérios de aceite e CA-Tenant atendidos.
- [ ] RLS/API/UI aplicam menor privilégio.
- [ ] Auditoria e anexos privados verificados.
- [ ] Seed apenas fictício.
- [ ] Testes focados e suíte completa passando.
- [ ] Documentação atualizada.
