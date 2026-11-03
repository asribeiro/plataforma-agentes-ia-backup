# Fase 1 — Resumo e dúvidas

## Contexto técnico verificado

O repositório usa FastAPI, SQLAlchemy, Alembic e PostgreSQL no backend, React 18,
TypeScript, Vite e Tailwind no frontend, Redis/Celery para tarefas e WAHA/Z-API
para WhatsApp. A empresa cliente existente (`companies.id`) será o tenant lógico
do módulo; as tabelas novas usarão o nome explícito `clinic_id` apontando para
`companies.id`, sem substituir os módulos existentes de agenda, CRM ou cobrança.

## Resumo das regras de negócio

O módulo centraliza paciente, tratamentos, procedimentos, agendamentos,
evoluções clínicas, adendos, anexos, NPS, linha do tempo e auditoria. Todo dado
é multi-tenant, auditável e protegido por perfil. O ciclo de vida é calculado
pelos eventos clínicos/administrativos. A secretária IA pode consultar apenas
dados administrativos e nunca conteúdo clínico. Notas assinadas são imutáveis e
correções ocorrem por adendo.

As entregas serão feitas nesta ordem: fundação de dados e isolamento; pacientes
e ficha; atendimento e prontuário; tratamentos e recorrência; satisfação e
painel de jornada.

## Dúvidas que precisam de confirmação

| ID | Dúvida | Proposta para aprovação |
|---|---|---|
| D-01 | Um paciente pode satisfazer vários status de RN-12. | Prioridade: **Em risco > Em tratamento > Em manutenção > Novo paciente > Inativo > Lead**. |
| D-02 | O que remove “Em risco”? | Remover automaticamente quando não houver mais 2 no-shows consecutivos e o NPS mais recente for maior que 6; permitir ação explícita do Admin Clínica para casos excepcionais, sempre auditada. |
| D-03 | Master pode ver conteúdo clínico? | Não. Master acessa apenas dados administrativos via “Entrar nesta empresa”; qualquer acesso fica no log. |
| D-04 | Histórico compartilhado entre profissionais? | Admin Clínica vê todo o histórico da clínica. Profissional Clínico vê o histórico clínico do paciente dentro da clínica para continuidade assistencial, mas só edita/assina atendimentos próprios. |
| D-05 | Destinatário de tarefa por NPS baixo? | Admin Clínica e profissional responsável pelo atendimento, com uma única tarefa e ambos como participantes. |
| D-06 | Tipo de assinatura? | Nesta primeira implementação, confirmação forte no sistema (usuário autenticado, autor, timestamp e hash da nota). Assinatura ICP-Brasil fica como extensão após validação jurídica. |
| D-07 | `lead_id` aponta para qual tabela legada? | Usar referência opcional ao lead/contato existente após confirmar a tabela canônica no CRM; a migração deve falhar de forma explícita se a tabela não estiver disponível. |
| D-08 | “Procedimentos realizados” precisa de catálogo? | Proposta: texto estruturado em `JSONB` na nota nesta fase, preservando referência opcional ao procedimento do tratamento. Catálogo clínico separado pode ser criado depois. |
| D-09 | Fuso horário e disponibilidade na recorrência. | Usar o fuso configurado na agenda/clínica, validar cada ocorrência contra a disponibilidade já existente e nunca gerar sessão silenciosamente conflitante. |

## Suposições controladas

1. `companies` representa a clínica/tenant e `clinic_id` será o FK padronizado
   nas novas tabelas.
2. Usuários e profissionais existentes serão reutilizados; não haverá novo
   mecanismo de autenticação.
3. O storage de anexos terá bucket privado por clínica, URLs temporárias e
   criptografia gerenciada pelo provedor.
4. O seed será integralmente fictício, com clínicas A e B, e só será criado
   depois da aprovação do desenho.
5. Os prazos padrão são 30 minutos, 2 horas, 72 horas, 90 dias e 6 meses,
   todos sobrescrevíveis por configuração de clínica.

**A confirmação das dúvidas D-01 a D-09 é necessária antes de congelar o
contrato de API.**
