# Fase 2 — Backlog e testes

## Convenções transversais

Todas as histórias incluem `clinic_id`, RLS PostgreSQL, filtro no serviço/API,
auditoria de acesso/alteração e teste com as clínicas A e B. O Profissional
Atendimento nunca recebe campos clínicos. Os IDs RN citados são a fonte da
regra de negócio.

## ÉPICO E-01 — Fundação, dados e isolamento

### H-01.1 — Criar modelo de dados e migração
**RNs:** RN-02 a RN-11, RN-28 a RN-31, RN-32.1.

**Critérios de aceite**
- [ ] Tabelas do MER existem com FK, timestamps, índices e `clinic_id NOT NULL`.
- [ ] Evolução assinada não pode ser alterada/removida; adendo mantém versão.
- [ ] Anexos ficam privados e segregados por clínica.
- [ ] CA-Tenant — usuário A não lê/escreve/exporta dados de B.

**Testes unitários**
| ID | Cenário | Entrada | Resultado |
|---|---|---|---|
| UT-01.1.1 | Integridade | registro sem clínica | rejeição por NOT NULL/FK |
| UT-01.1.2 | Assinatura | update/delete em nota assinada | erro de domínio |
| UT-01.1.3 | Adendo | nota assinada + adendo | nova versão vinculada, original intacta |
| UT-01.1.4 | Tenant | usuário A consulta ID de B | 404/403 sem dados |

### H-01.2 — Implementar perfis, RLS e auditoria
**RNs:** RN-11, RN-28, RN-29, RN-30.

**Critérios de aceite**
- [ ] Admin Clínica vê todo o prontuário da própria clínica.
- [ ] Profissional Clínico vê histórico permitido e altera apenas seus atendimentos.
- [ ] Profissional Atendimento recebe apenas dados administrativos.
- [ ] Master não vê conteúdo clínico.
- [ ] Cada acesso e mutação gera `clinical_access_log`.
- [ ] CA-Tenant — políticas bloqueiam acesso cruzado mesmo sem filtro de UI.

**Testes unitários:** UT-01.2.1 matriz dos quatro perfis; UT-01.2.2 RLS sem
contexto; UT-01.2.3 log de leitura; UT-01.2.4 log de alteração e tenant.

### Testes integrados — E-01
| ID | Fluxo | Pré-condições | Resultado |
|---|---|---|---|
| IT-01.1 | Seed | Clínicas A/B e perfis criados | dados fictícios isolados |
| IT-01.2 | Isolamento | token de A + ID de B | nenhuma rota retorna B |
| IT-01.3 | Permissões | quatro perfis | Atendimento sem conteúdo clínico; Master sem conteúdo clínico |

## ÉPICO E-02 — Pacientes e ficha

### H-02.1 — Lista e cadastro de pacientes
**RNs:** RN-03, RN-12 a RN-14.

**Critérios de aceite**
- [ ] Busca nome/telefone/CPF e filtros de ciclo de vida, profissional,
  convênio, sem retorno, risco e NPS baixo.
- [ ] Cadastro registra consentimento LGPD com versão e data.
- [ ] Lista mostra última/próxima consulta, no-shows e status.
- [ ] CA-Tenant — resultados são limitados à clínica autenticada.

**Testes unitários:** UT-02.1.1 busca; UT-02.1.2 filtros combinados; UT-02.1.3
CPF opcional/consentimento; UT-02.1.4 perfil e tenant.

### H-02.2 — Resumo, linha do tempo e atendimentos
**RNs:** RN-10, RN-13, RN-15.

**Critérios de aceite**
- [ ] Ficha exibe alertas, métricas e botão de agendar.
- [ ] Linha do tempo ordena eventos e não expõe nota ao Atendimento.
- [ ] Atendimentos exibem status/profissional/procedimento conforme permissão.
- [ ] CA-Tenant — ficha de B não aparece em A.

**Testes unitários:** UT-02.2.1 cálculo de métricas; UT-02.2.2 ordenação de
eventos; UT-02.2.3 mascaramento clínico; UT-02.2.4 acesso por perfil/tenant.

### Testes integrados — E-02
| ID | Fluxo | Resultado |
|---|---|---|
| IT-02.1 | buscar paciente e abrir ficha | resumo, timeline e atendimentos coerentes |
| IT-02.2 | Atendimento abre a ficha | dados administrativos sem notas |
| IT-02.3 | isolamento | paciente e timeline de B invisíveis para A |

## ÉPICO E-03 — Atendimento e prontuário clínico

### H-03.1 — Registrar e assinar evolução
**RNs:** RN-07, RN-08, RN-16, RN-27, RN-30.

**Critérios de aceite**
- [ ] Profissional que atendeu ou Admin Clínica registra procedimentos,
  orientação, anexos e assina.
- [ ] Apenas autor/Admin pode criar anotação no atendimento permitido.
- [ ] Assinatura gera hash, autor, data/hora e evento.
- [ ] Após assinatura, alteração/remoção é bloqueada.
- [ ] CA-Tenant e perfil são aplicados na API e banco.

**Testes unitários:** UT-03.1.1 criação; UT-03.1.2 assinatura/hash; UT-03.1.3
imutabilidade; UT-03.1.4 autorização e isolamento.

### H-03.2 — Corrigir por adendo e exportar histórico
**RNs:** RN-08, RN-30, RN-31.

**Critérios de aceite**
- [ ] Adendo exige nota original, autor, versão e motivo.
- [ ] Exportação respeita permissão e gera PDF preparado para guarda longa.
- [ ] Atendimento/Master não obtêm conteúdo clínico por exportação.
- [ ] CA-Tenant — exportação não mistura clínicas.

**Testes unitários:** UT-03.2.1 versão; UT-03.2.2 bloqueio de nota original;
UT-03.2.3 conteúdo por perfil; UT-03.2.4 tenant.

### Testes integrados — E-03
| ID | Fluxo | Resultado |
|---|---|---|
| IT-03.1 | agenda → atendimento → assinatura | nota assinada e evento criado |
| IT-03.2 | correção | somente adendo aparece no histórico |
| IT-03.3 | privacidade | Atendimento e IA não veem conteúdo clínico |

## ÉPICO E-04 — Tratamentos e recorrência

### H-04.1 — Planos e progresso
**RNs:** RN-04, RN-05, RN-15, RN-32.4.

**Critérios de aceite**
- [ ] CRUD de tratamento e procedimentos com estados e progresso.
- [ ] Aprovação de recorrência valida frequência, sessões/data final e janela.
- [ ] CA-Tenant e permissões mantidos.

**Testes unitários:** UT-04.1.1 transições de status; UT-04.1.2 recorrência
mensal de 12 sessões; UT-04.1.3 entradas inválidas; UT-04.1.4 tenant.

### H-04.2 — Gerar, remarcar e tratar conflitos
**RNs:** RN-06, RN-18 a RN-20.

**Critérios de aceite**
- [ ] Gera ocorrências em 90 dias respeitando disponibilidade/fuso.
- [ ] Remarcação recalcula sessões seguintes sem duplicatas.
- [ ] Conflito vira pendência e tarefa para Profissional Atendimento.
- [ ] CA-Tenant — jobs processam somente o tenant do contexto.

**Testes unitários:** UT-04.2.1 frequências; UT-04.2.2 janela; UT-04.2.3
remarcação; UT-04.2.4 conflito/tenant.

### Testes integrados — E-04
| ID | Fluxo | Resultado |
|---|---|---|
| IT-04.1 | aprovar 12 sessões mensais | agenda futura correta |
| IT-04.2 | remarcar sessão 3 | sessões seguintes recalculadas |
| IT-04.3 | conflito | pendência e tarefa criadas |

## ÉPICO E-05 — Jornada, no-show e satisfação

### H-05.1 — Ciclo de vida e no-show
**RNs:** RN-12, RN-13, RN-21 a RN-23, RN-26.

**Critérios de aceite**
- [ ] Job marca no-show após 30 minutos e cria evento.
- [ ] Dois no-shows seguidos criam alerta e oferta de remarcação.
- [ ] Status calculado pela prioridade aprovada e configuração por clínica.
- [ ] Lista reativação após seis meses.
- [ ] CA-Tenant — job não cruza clínicas/fusos.

**Testes unitários:** UT-05.1.1 limiar de 30 minutos; UT-05.1.2 sequência de
no-shows; UT-05.1.3 prioridade de status; UT-05.1.4 configuração/tenant.

### H-05.2 — NPS via WhatsApp e painel
**RNs:** RN-09, RN-17, RN-24 a RN-27, RN-33.

**Critérios de aceite**
- [ ] Pesquisa é enviada 2h após conclusão e expira em 72h.
- [ ] Resposta salva NPS, satisfação, comentário e canal.
- [ ] NPS ≤6 cria tarefa; NPS ≥9 usa configuração para convite Google.
- [ ] Painel apresenta NPS, no-show, inativos, pendências e comentários.
- [ ] IA recebe somente dados administrativos.
- [ ] CA-Tenant — métricas e campanhas são por clínica.

**Testes unitários:** UT-05.2.1 janela de envio/expiração; UT-05.2.2 validação
0–10 e 1–5; UT-05.2.3 tarefas por nota; UT-05.2.4 payload sem clínica.

### Testes integrados — E-05
| ID | Fluxo | Resultado |
|---|---|---|
| IT-05.1 | concluir atendimento | pesquisa enviada no prazo |
| IT-05.2 | responder NPS baixo | tarefa e painel atualizados |
| IT-05.3 | painel A/B | métricas não misturam clínicas |

## Suposições e definição de pronto

As suposições são as de [01-resumo-e-duvidas.md](./01-resumo-e-duvidas.md).
Cada história só será concluída com seus testes unitários/integrados, RLS,
perfis, auditoria, seed fictício e suíte existente passando.
