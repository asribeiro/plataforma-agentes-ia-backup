# Fase 3 — Modelo entidade-relacionamento

`clinic_id` em todas as entidades abaixo referencia `companies.id` e é
obrigatório. Entidades legadas (agenda, CRM e financeiro) serão referenciadas
por FK opcional somente quando o contrato existente for confirmado.

```mermaid
erDiagram
  COMPANIES ||--o{ PATIENTS : possui
  PATIENTS ||--o{ TREATMENTS : recebe
  PROFESSIONALS ||--o{ TREATMENTS : responsavel
  TREATMENTS ||--o{ TREATMENT_PROCEDURES : contem
  PATIENTS ||--o{ APPOINTMENTS : agenda
  PROFESSIONALS ||--o{ APPOINTMENTS : atende
  TREATMENT_PROCEDURES ||--o{ APPOINTMENTS : gera
  APPOINTMENTS ||--o{ CLINICAL_NOTES : registra
  CLINICAL_NOTES ||--o{ CLINICAL_NOTE_ADDENDA : corrige
  CLINICAL_NOTES ||--o{ CLINICAL_ATTACHMENTS : anexa
  APPOINTMENTS ||--o| SATISFACTION_SURVEYS : pesquisa
  PATIENTS ||--o{ TIMELINE_EVENTS : possui
  PATIENTS ||--o{ CLINICAL_ACCESS_LOG : acessado
  COMPANIES ||--o{ MODULE_SETTINGS : configura
  COMPANIES ||--o{ PATIENTS : tenant
  COMPANIES ||--o{ TREATMENTS : tenant
  COMPANIES ||--o{ APPOINTMENTS : tenant

  COMPANIES { bigint id PK }
  PROFESSIONALS { bigint id PK bigint company_id FK }
  PATIENTS { uuid id PK bigint clinic_id FK string name string cpf date birth_date string phone string email string lifecycle_status boolean lgpd_consent }
  TREATMENTS { uuid id PK bigint clinic_id FK uuid patient_id FK bigint professional_id FK string title string status numeric total_value date start_date date expected_end_date }
  TREATMENT_PROCEDURES { uuid id PK bigint clinic_id FK uuid treatment_id FK string name string tooth_region numeric value string recurrence_frequency int sessions date end_date string status }
  APPOINTMENTS { uuid id PK bigint clinic_id FK uuid patient_id FK bigint professional_id FK uuid treatment_procedure_id FK timestamptz starts_at int duration_minutes string source string status string cancel_reason }
  CLINICAL_NOTES { uuid id PK bigint clinic_id FK uuid appointment_id FK uuid patient_id FK bigint author_id FK text note_text jsonb procedures jsonb guidance timestamptz signed_at string signature_hash }
  CLINICAL_NOTE_ADDENDA { uuid id PK bigint clinic_id FK uuid note_id FK bigint author_id FK int version text reason text content timestamptz created_at }
  CLINICAL_ATTACHMENTS { uuid id PK bigint clinic_id FK uuid note_id FK uuid patient_id FK string object_key string mime_type bigint size_bytes }
  SATISFACTION_SURVEYS { uuid id PK bigint clinic_id FK uuid appointment_id FK uuid patient_id FK bigint professional_id FK int nps_score int procedure_score text comment string channel string status timestamptz sent_at timestamptz responded_at }
  TIMELINE_EVENTS { uuid id PK bigint clinic_id FK uuid patient_id FK string event_type jsonb payload timestamptz occurred_at }
  CLINICAL_ACCESS_LOG { bigint id PK bigint clinic_id FK bigint user_id FK bigint professional_id FK uuid patient_id FK string resource string action jsonb metadata timestamptz created_at }
  MODULE_SETTINGS { bigint id PK bigint clinic_id FK int noshow_minutes int recurrence_window_days int survey_delay_hours int survey_expiration_hours int inactive_months boolean google_review_enabled }
  TASKS { bigint id PK bigint company_id FK string source }
```

## Entidades, índices e integridade

- **patients:** nome/data de nascimento obrigatórios; CPF opcional, mas único por
  clínica quando informado. Índices por `(clinic_id, name)`, telefone, CPF e
  lifecycle. Consentimento LGPD exige versão e data quando marcado.
- **treatments:** paciente, profissional, título e status obrigatórios; valor
  não negativo. Índices por clínica/paciente/status.
- **treatment_procedures:** tratamento e frequência obrigatórios; frequência
  personalizada exige parâmetro validado. Sessões ou data final são obrigatórias
  para recorrência. Índice por tratamento/status.
- **appointments:** paciente, profissional, início, duração e status
  obrigatórios. `clinic_id` deve coincidir com paciente, profissional e
  procedimento; índice por clínica/início/status e prevenção de duplicata.
- **clinical_notes:** somente atendimento concluído/compareceu; texto e autor
  obrigatórios. Trigger/política impede update/delete após `signed_at`.
- **clinical_note_addenda:** versão única por nota, autor e motivo obrigatórios;
  nunca altera o conteúdo original.
- **clinical_attachments:** `object_key` não contém PII fora do bucket privado;
  tamanho/MIME limitados e nota/paciente pertencem à mesma clínica.
- **satisfaction_surveys:** scores com CHECK (NPS 0–10; procedimento 1–5);
  uma pesquisa por atendimento; janela de expiração aplicada pelo job.
- **timeline_events:** somente append para eventos de domínio; payload não pode
  incluir conteúdo clínico em eventos consumidos pela IA.
- **clinical_access_log:** append-only, sem endpoint de edição/exclusão; índice
  `(clinic_id, patient_id, created_at)`.
- **module_settings:** uma linha por clínica, defaults 30/90/2/72/6; valores
  positivos e timezone válido.

## RLS e acesso

Cada tabela aplica `USING (clinic_id = current_setting('app.clinic_id')::bigint)`
e `WITH CHECK` equivalente. O serviço define o contexto transacional após
validar o usuário; ausência de contexto nega a operação. Views administrativas
removem campos clínicos para Atendimento e Master. Jobs abrem uma transação por
clínica e nunca reutilizam contexto entre tenants.
