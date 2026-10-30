import axios from 'axios';
import { api } from './api';

/**
 * Google Calendar POR AGENDA (F1-06).
 *
 * Diferença que este arquivo carrega: a credencial OAuth pode pertencer à AGENDA
 * (o profissional autorizou a conta dele) ou pode ser herdada da EMPRESA. As
 * rotas abaixo separam as duas coisas de propósito — `fonte_credencial` é o
 * campo que a tela usa para não mentir para o dono.
 *
 * Todas as rotas vivem sob `/api/integrations/calendar` e usam a instância
 * `api` de `services/api` (cookie, CSRF e refresh de sessão já resolvidos lá).
 */

const BASE = '/api/integrations/calendar';

export type GoogleAgendaFonteCredencial = 'agenda' | 'empresa' | null;

export interface GoogleAgendaStatus {
  agenda_id: number;
  agenda_nome: string;
  /** 'agenda' = credencial própria do profissional; 'empresa' = herdada; null = nenhuma. */
  fonte_credencial: GoogleAgendaFonteCredencial;
  credencial_propria: boolean;
  /** true quando existe credencial efetiva (da agenda OU da empresa). */
  google_connected: boolean;
  google_account_email: string | null;
  google_calendar_id: string | null;
  google_calendar_summary: string | null;
  /** false = o servidor não tem GOOGLE_OAUTH_CLIENT_ID/SECRET: conectar é impossível. */
  oauth_configured: boolean;
}

export interface GoogleAgendaCalendario {
  id: string;
  summary?: string | null;
  description?: string | null;
  primary?: boolean;
  access_role?: string | null;
  background_color?: string | null;
  time_zone?: string | null;
}

export interface GoogleAgendaCalendarios {
  fonte_credencial: GoogleAgendaFonteCredencial;
  calendars: GoogleAgendaCalendario[];
}

export interface GoogleAgendaCalendarioSelecionado {
  id?: string | null;
  summary?: string | null;
  description?: string | null;
  primary?: boolean;
  access_role?: string | null;
  background_color?: string | null;
  time_zone?: string | null;
}

export interface GoogleAgendaCredencialRemovida {
  status: string;
  removed: boolean;
  message: string;
}

/**
 * O backend escreve a mensagem de negócio em `detail`. Preferimos sempre ela;
 * o fallback só existe para rede/servidor fora do ar.
 */
export function mensagemDeErroGoogleAgenda(erro: unknown, fallback: string): string {
  if (axios.isAxiosError(erro)) {
    const detalhe = (erro.response?.data as { detail?: unknown } | undefined)?.detail;

    if (typeof detalhe === 'string' && detalhe.trim()) return detalhe.trim();

    if (Array.isArray(detalhe) && detalhe.length > 0) {
      const primeiro = detalhe[0] as { msg?: string } | string | undefined;
      const texto = typeof primeiro === 'string' ? primeiro : primeiro?.msg;
      if (texto) return texto;
    }

    if (!erro.response) return 'Falha de rede ao falar com a API. Tente novamente.';
    return fallback;
  }

  if (erro instanceof Error && erro.message) return erro.message;
  return fallback;
}

function obterCompanyId(): string {
  const companyId = localStorage.getItem('company_id') || localStorage.getItem('clinic_id');
  if (!companyId) throw new Error('company_id não encontrado na sessão.');
  return companyId;
}

function urlAgenda(agendaId: number, sufixo: string): string {
  return `${BASE}/google/${obterCompanyId()}/agendas/${agendaId}${sufixo}`;
}

/** GET /google/{company_id}/agendas/{agenda_id}/status */
export async function obterStatusGoogleDaAgenda(agendaId: number): Promise<GoogleAgendaStatus> {
  try {
    const resp = await api.get<GoogleAgendaStatus>(urlAgenda(agendaId, '/status'));
    return resp.data;
  } catch (erro) {
    throw new Error(mensagemDeErroGoogleAgenda(erro, 'Erro ao consultar o Google desta agenda.'));
  }
}

/**
 * GET /google/{company_id}/oauth/start?agenda_id={id}
 * Devolve a URL de autorização do Google DA AGENDA. Quem chama redireciona.
 */
export async function iniciarOAuthGoogleDaAgenda(agendaId: number): Promise<string> {
  try {
    const resp = await api.get<{ authorization_url: string }>(
      `${BASE}/google/${obterCompanyId()}/oauth/start`,
      { params: { agenda_id: agendaId } },
    );
    if (!resp.data?.authorization_url) {
      throw new Error('O servidor não devolveu a URL de autorização do Google.');
    }
    return resp.data.authorization_url;
  } catch (erro) {
    throw new Error(mensagemDeErroGoogleAgenda(erro, 'Erro ao iniciar a conexão com o Google.'));
  }
}

/** GET /google/{company_id}/agendas/{agenda_id}/calendars */
export async function listarCalendariosGoogleDaAgenda(agendaId: number): Promise<GoogleAgendaCalendarios> {
  try {
    const resp = await api.get<GoogleAgendaCalendarios>(urlAgenda(agendaId, '/calendars'));
    return { fonte_credencial: resp.data?.fonte_credencial ?? null, calendars: resp.data?.calendars ?? [] };
  } catch (erro) {
    throw new Error(mensagemDeErroGoogleAgenda(erro, 'Erro ao listar os calendários Google desta agenda.'));
  }
}

/** POST /google/{company_id}/agendas/{agenda_id}/calendar */
export async function definirCalendarioGoogleDaAgenda(
  agendaId: number,
  googleCalendarId: string,
): Promise<GoogleAgendaCalendarioSelecionado> {
  try {
    const resp = await api.post<{ status: string; calendar: GoogleAgendaCalendarioSelecionado }>(
      urlAgenda(agendaId, '/calendar'),
      { google_calendar_id: googleCalendarId },
    );
    return resp.data?.calendar ?? {};
  } catch (erro) {
    throw new Error(mensagemDeErroGoogleAgenda(erro, 'Erro ao definir o calendário Google desta agenda.'));
  }
}

/**
 * DELETE /google/{company_id}/agendas/{agenda_id}/credential
 * Remove a credencial PRÓPRIA da agenda: ela volta a usar a da empresa, se houver.
 */
export async function removerCredencialGoogleDaAgenda(agendaId: number): Promise<GoogleAgendaCredencialRemovida> {
  try {
    const resp = await api.delete<GoogleAgendaCredencialRemovida>(urlAgenda(agendaId, '/credential'));
    return resp.data;
  } catch (erro) {
    throw new Error(mensagemDeErroGoogleAgenda(erro, 'Erro ao desconectar o Google desta agenda.'));
  }
}
