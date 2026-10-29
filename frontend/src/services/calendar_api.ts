import api from './api.ts';

/** Turno de um dia da semana. `day_of_week`: 0 = segunda ... 6 = domingo. */
export interface Schedule {
    id?: number;
    agenda_id?: number;
    day_of_week: number;
    morning_start?: string | null; // HH:MM:SS
    morning_end?: string | null;
    afternoon_start?: string | null;
    afternoon_end?: string | null;
    night_start?: string | null;
    night_end?: string | null;
}

export interface Agenda {
    id: number;
    company_id: number;
    name: string;
    slot_duration: number;
    active: boolean;
    timezone?: string;
    safety_margin_minutes?: number;
    /** Dono da agenda (F1-10). Sempre presente na resposta; nulo só em agenda legada. */
    professional_id?: number | null;
    google_calendar_id?: string | null;
    google_calendar_summary?: string | null;
    google_calendar_time_zone?: string | null;
    created_at: string;
    schedules: Schedule[];
}

/**
 * Corpo do POST /api/calendar/.
 * `professional_id` é OBRIGATÓRIO no backend (F1-10): agenda sem dono não é criada.
 */
export interface AgendaCreate {
    name: string;
    slot_duration: number;
    professional_id: number;
    active?: boolean;
    timezone?: string;
    safety_margin_minutes?: number;
    schedules: Schedule[];
}

/**
 * Corpo do PUT /api/calendar/{id} — o backend exige o objeto completo
 * (`name` e `slot_duration` são campos obrigatórios do schema AgendaBase).
 * `schedules`, quando enviado, SUBSTITUI todos os turnos da agenda.
 */
export interface AgendaUpdate {
    name: string;
    slot_duration: number;
    active: boolean;
    timezone?: string;
    safety_margin_minutes?: number;
    /** Troca o dono da agenda. Profissional de outra empresa = 404; inativo = 409. */
    professional_id?: number;
    schedules?: Schedule[];
}

export interface Slot {
    start_time: string;
    end_time: string;
}

export interface ListarAgendasParams {
    /** Filtra a agenda de um profissional. Sem filtro: todas as agendas da empresa. */
    professional_id?: number;
    /** Traz também as agendas desativadas. */
    incluir_inativas?: boolean;
}

export const calendarApi = {
    createAgenda: async (data: AgendaCreate): Promise<Agenda> => {
        const response = await api.post<Agenda>('/api/calendar/', data);
        return response.data;
    },

    listAgendas: async (params?: ListarAgendasParams): Promise<Agenda[]> => {
        const response = await api.get<Agenda[]>('/api/calendar/', { params });
        return response.data;
    },

    getAgenda: async (id: number): Promise<Agenda> => {
        const response = await api.get<Agenda>(`/api/calendar/${id}`);
        return response.data;
    },

    updateAgenda: async (id: number, data: AgendaUpdate): Promise<Agenda> => {
        const response = await api.put<Agenda>(`/api/calendar/${id}`, data);
        return response.data;
    },

    getSlots: async (agendaId: number, startDate: string, endDate: string): Promise<Slot[]> => {
        const response = await api.get<Slot[]>(`/api/calendar/${agendaId}/slots`, {
            params: { start_date: startDate, end_date: endDate }
        });
        return response.data;
    }
};
