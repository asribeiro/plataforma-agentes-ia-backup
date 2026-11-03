import { api } from './api.ts';

export type LifecycleStatus = 'lead' | 'active' | 'in_treatment' | 'at_risk' | 'inactive' | string;

export interface PatientListItem {
  id: string;
  name: string;
  cpf?: string | null;
  birth_date?: string | null;
  phone?: string | null;
  email?: string | null;
  insurance?: string | null;
  lifecycle_status: LifecycleStatus;
  last_appointment_at?: string | null;
  next_appointment_at?: string | null;
  no_show_count: number;
  total_appointments: number;
}

export interface PatientAppointment {
  id: string;
  starts_at: string;
  duration_minutes: number;
  source: string;
  status: string;
  professional_id: number;
  note_text?: string | null;
}

export interface PatientTimelineItem {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface PatientDetail extends PatientListItem {
  source?: string | null;
  lgpd_consent_at?: string | null;
  lgpd_consent_version?: string | null;
  appointments: PatientAppointment[];
  timeline: PatientTimelineItem[];
}

export interface PatientCreatePayload {
  name: string;
  cpf?: string;
  birth_date?: string;
  phone?: string;
  email?: string;
  insurance?: string;
  source?: string;
  lgpd_consent_at?: string;
  lgpd_consent_version?: string;
}

export interface ClinicalNote {
  id: string;
  patient_id: string;
  appointment_id?: string | null;
  author_id?: number | null;
  note_text: string;
  procedures: Record<string, unknown>[];
  guidance: Record<string, unknown>[];
  signed_at?: string | null;
  signature_hash?: string | null;
}

export interface Addendum {
  id: string;
  note_id: string;
  author_id?: number | null;
  version: number;
  reason: string;
  content: string;
  created_at: string;
}

export interface TreatmentProcedure {
  id: string;
  name: string;
  status: string;
  recurrence_frequency?: string | null;
  recurrence_sessions?: number | null;
  recurrence_end_date?: string | null;
  sessions_completed: number;
  sessions_planned?: number | null;
}

export interface Treatment {
  id: string;
  patient_id: string;
  professional_id: number;
  title: string;
  description?: string | null;
  status: string;
  total_value: number | string;
  start_date?: string | null;
  expected_end_date?: string | null;
  procedures: TreatmentProcedure[];
}

export interface SatisfactionDashboard {
  total_surveys: number;
  answered_surveys: number;
  nps?: number | null;
  average_procedure_score?: number | null;
  no_show_rate: number;
  inactive_patients: number;
  pending_treatment_sessions: number;
  recent_negative_comments: { survey_id: string; comment: string; nps_score: number }[];
}

export interface SatisfactionSurvey {
  id: string;
  status: string;
  sent_at?: string | null;
  responded_at?: string | null;
  nps_score?: number | null;
  procedure_score?: number | null;
  comment?: string | null;
  patient_id?: string | null;
  appointment_id?: string | null;
}

export interface RecurrenceConflictTask {
  id: number;
  patient_id: string;
  appointment_id: string;
  status: string;
  title: string;
  created_at: string;
}

export interface ReactivationPatient {
  patient_id: string;
  name: string;
  last_attended_at?: string | null;
  lifecycle_status: string;
}

export interface ClinicalAttachment {
  id: string;
  patient_id: string;
  note_id?: string | null;
  mime_type: string;
  size_bytes: number;
}

const apiPath = (path: string) => `/api${path.startsWith('/') ? path : `/${path}`}`;

export const patientRecordApi = {
  async listPatients(params?: Record<string, string | boolean | number | undefined>) {
    const response = await api.get<PatientListItem[]>(apiPath('/patients'), { params });
    return response.data;
  },
  async createPatient(payload: PatientCreatePayload) {
    const response = await api.post<PatientListItem>(apiPath('/patients'), payload);
    return response.data;
  },
  async getPatient(patientId: string) {
    const response = await api.get<PatientDetail>(apiPath(`/patients/${patientId}`));
    return response.data;
  },
  async createClinicalNote(patientId: string, appointmentId: string, payload: {
    note_text: string;
    procedures?: Record<string, unknown>[];
    guidance?: Record<string, unknown>[];
  }) {
    const response = await api.post<ClinicalNote>(
      apiPath(`/clinical-records/patients/${patientId}/appointments/${appointmentId}/notes`),
      payload,
    );
    return response.data;
  },
  async signClinicalNote(noteId: string) {
    const response = await api.post<ClinicalNote>(apiPath(`/clinical-records/notes/${noteId}/sign`));
    return response.data;
  },
  async createAddendum(noteId: string, payload: { reason: string; content: string }) {
    const response = await api.post<Addendum>(apiPath(`/clinical-records/notes/${noteId}/addenda`), payload);
    return response.data;
  },
  async exportPatientHistory(patientId: string) {
    const response = await api.get<Blob>(apiPath(`/clinical-records/patients/${patientId}/export`), {
      responseType: 'blob',
    });
    return response.data;
  },
  async listTreatments(patientId: string) {
    const response = await api.get<Treatment[]>(apiPath(`/treatments/patients/${patientId}`));
    return response.data;
  },
  async createTreatment(patientId: string, payload: {
    title: string;
    description?: string;
    professional_id: number;
    total_value?: number;
    start_date?: string;
    expected_end_date?: string;
  }) {
    const response = await api.post<Treatment>(apiPath(`/treatments/patients/${patientId}`), payload);
    return response.data;
  },
  async createTreatmentProcedure(treatmentId: string, payload: {
    name: string;
    tooth_region?: string;
    value?: number;
    recurrence_frequency?: string;
    recurrence_sessions?: number;
    recurrence_end_date?: string;
  }) {
    const response = await api.post<Treatment>(apiPath(`/treatments/${treatmentId}/procedures`), payload);
    return response.data;
  },
  async generateRecurrence(procedureId: string, payload: {
    start_at: string;
    duration_minutes?: number;
    window_days?: number;
  }) {
    const response = await api.post(apiPath(`/recurrence/procedures/${procedureId}/generate`), payload);
    return response.data;
  },
  async processNoShows() {
    const response = await api.post<{ marked_no_shows: number; patients_updated: number }>(apiPath('/journey/process-no-shows'));
    return response.data;
  },
  async listReactivation() {
    const response = await api.get<ReactivationPatient[]>(apiPath('/journey/reactivation'));
    return response.data;
  },
  async getSatisfactionDashboard() {
    const response = await api.get<SatisfactionDashboard>(apiPath('/satisfaction/dashboard'));
    return response.data;
  },
  async listSatisfactionSurveys(status?: string) {
    const response = await api.get<SatisfactionSurvey[]>(apiPath('/satisfaction'), {
      params: status ? { status_filter: status } : undefined,
    });
    return response.data;
  },
  async respondSatisfaction(surveyId: string, payload: {
    nps_score: number;
    procedure_score: number;
    comment?: string;
  }) {
    const response = await api.post<SatisfactionSurvey>(apiPath(`/satisfaction/${surveyId}/respond`), payload);
    return response.data;
  },
  async listRecurrenceTasks(status?: string) {
    const response = await api.get<RecurrenceConflictTask[]>(apiPath('/recurrence/tasks'), {
      params: status ? { status_filter: status } : undefined,
    });
    return response.data;
  },
  async updateRecurrenceTask(taskId: number, status: 'pending' | 'resolved' | 'dismissed') {
    const response = await api.patch<RecurrenceConflictTask>(apiPath(`/recurrence/tasks/${taskId}`), { status });
    return response.data;
  },
  async sendSatisfaction(appointmentId: string) {
    const response = await api.post(apiPath(`/satisfaction/appointments/${appointmentId}/send`));
    return response.data;
  },
  async listClinicalAttachments(patientId: string) {
    const response = await api.get<ClinicalAttachment[]>(apiPath(`/clinical-attachments/patients/${patientId}`));
    return response.data;
  },
  async uploadClinicalAttachment(patientId: string, file: File, noteId?: string) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<ClinicalAttachment>(
      apiPath(`/clinical-attachments/patients/${patientId}${noteId ? `?note_id=${noteId}` : ''}`),
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },
  async downloadClinicalAttachment(attachmentId: string) {
    const response = await api.get<Blob>(apiPath(`/clinical-attachments/${attachmentId}/download`), { responseType: 'blob' });
    return response.data;
  },
};
