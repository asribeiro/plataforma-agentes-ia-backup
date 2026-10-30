import api from './api.ts';

export interface CompanyRegistrationPayload {
  customer_id?: number;
  person_type: 'PF' | 'PJ';
  document: string;
  legal_name: string;
  trade_name: string;
  municipal_registration?: string;
  postal_code?: string;
  address?: string;
  address_number?: string;
  address_complement?: string;
  province?: string;
  city?: string;
  state?: string;
  fixed_phone?: string;
  website?: string;
  instagram?: string;
  administrative_responsible_name: string;
  administrative_responsible_email: string;
  administrative_responsible_phone: string;
  technical_responsible_professional_id?: number;
  technical_responsible_cro?: string;
  technical_responsible_cro_uf?: string;
  business_hours: Record<string, unknown>;
  ai_whatsapp?: string;
  accepts_insurance: boolean;
  accepted_insurance: string[];
  plan: 'consultorio' | 'clinica' | 'clinica_plus' | 'redes_clinicas';
  billing_interval: 'monthly' | 'yearly';
  is_founder_customer: boolean;
  trial_days: number;
  start_date?: string;
  billing_email?: string;
  preferred_payment_method?: string;
}

export interface CompanyRegistrationDraft {
  id: number;
  payload: CompanyRegistrationPayload;
  logo_url: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  completed_company_id: number | null;
}

const base = '/api/admin/company-registration';

export const companyRegistrationApi = {
  async getCurrent(): Promise<CompanyRegistrationPayload> {
    const response = await api.get(`${base}/current`);
    return response.data;
  },
  async updateCurrent(payload: CompanyRegistrationPayload): Promise<CompanyRegistrationPayload> {
    const response = await api.put(`${base}/current`, payload);
    return response.data;
  },
  async listDrafts(): Promise<CompanyRegistrationDraft[]> {
    const response = await api.get(`${base}/drafts`);
    return response.data;
  },
  async createDraft(payload: CompanyRegistrationPayload): Promise<CompanyRegistrationDraft> {
    const response = await api.post(`${base}/drafts`, payload);
    return response.data;
  },
  async getDraft(id: number): Promise<CompanyRegistrationDraft> {
    const response = await api.get(`${base}/drafts/${id}`);
    return response.data;
  },
  async updateDraft(id: number, payload: CompanyRegistrationPayload): Promise<CompanyRegistrationDraft> {
    const response = await api.put(`${base}/drafts/${id}`, payload);
    return response.data;
  },
  async uploadDraftLogo(id: number, file: File): Promise<CompanyRegistrationDraft> {
    const formData = new FormData();
    formData.append('logo', file);
    const response = await api.post(`${base}/drafts/${id}/logo`, formData);
    return response.data;
  },
  async createCompany(id: number): Promise<{ company_id: number; message: string }> {
    const response = await api.post(`${base}/drafts/${id}/create`);
    return response.data;
  },
  async deleteDraft(id: number): Promise<void> {
    await api.delete(`${base}/drafts/${id}`);
  },
};
