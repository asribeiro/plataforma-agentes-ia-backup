/**
 * Cliente das rotas de feriado (`/api/feriados`).
 *
 * Regra do produto: feriado fecha a agenda de TODOS os profissionais de TODAS as clínicas.
 * A clínica não decide se o dia existe — ela decide QUEM trabalha nele, profissional por
 * profissional, e só o admin da clínica pode fazer isso (`pode_configurar`).
 *
 * Feriado não cancela agendamento: por isso a listagem traz `agendamentos_no_dia`. A tela mostra
 * o número e o admin decide o que fazer com o paciente — o sistema não decide por ele.
 *
 * Usa a instância `api` do api.ts (baseURL, cookie de sessão, CSRF e refresh de token já vêm de
 * lá); um axios novo aqui duplicaria a autenticação.
 *
 * Contrato (backend/routes/feriados_routes.py):
 *   GET    /feriados?ano=AAAA                 -> FeriadosDoAno
 *   PUT    /feriados/{id}/liberacoes          -> { ok, liberados[] }   (admin da clínica)
 *   POST   /feriados                          -> { ok, feriado_id }    (admin da plataforma)
 *   POST   /feriados/importar?ano=AAAA        -> { ok, importados }    (admin da plataforma)
 *   DELETE /feriados/{id}                     -> { ok }                (admin da plataforma)
 */
import { api } from './api.ts';

export type TipoFeriado = 'nacional' | 'estadual' | 'municipal' | 'pontual';

export interface Feriado {
    id: number;
    data: string; // AAAA-MM-DD
    nome: string;
    tipo: TipoFeriado;
    uf: string | null;
    cidade: string | null;
    recorrente: boolean;
    origem: 'importado' | 'manual';
    liberados: number[];
    agendamentos_no_dia: number;
}

export interface ProfissionalDaClinica {
    id: number;
    name: string;
}

export interface FeriadosDoAno {
    ano: number;
    company_id: number | null;
    admin_plataforma: boolean;
    pode_configurar: boolean;
    profissionais: ProfissionalDaClinica[];
    feriados: Feriado[];
}

export const feriadosApi = {
    async listar(ano: number): Promise<FeriadosDoAno> {
        const { data } = await api.get<FeriadosDoAno>('/feriados', { params: { ano } });
        return data;
    },

    async definirLiberacoes(feriadoId: number, professionalIds: number[]) {
        const { data } = await api.put(`/feriados/${feriadoId}/liberacoes`, {
            professional_ids: professionalIds,
        });
        return data as { ok: boolean; liberados: number[] };
    },

    async criar(payload: {
        data: string;
        nome: string;
        tipo: TipoFeriado;
        uf?: string | null;
        cidade?: string | null;
        recorrente?: boolean;
    }) {
        const { data } = await api.post('/feriados', payload);
        return data as { ok: boolean; feriado_id: number; ja_existia?: boolean };
    },

    async importar(ano: number) {
        const { data } = await api.post('/feriados/importar', null, { params: { ano } });
        return data as { ok: boolean; ano: number; importados: number; ja_existiam: number };
    },

    async apagar(feriadoId: number) {
        const { data } = await api.delete(`/feriados/${feriadoId}`);
        return data as { ok: boolean };
    },
};

export default feriadosApi;
