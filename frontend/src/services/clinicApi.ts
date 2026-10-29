/**
 * Cliente das rotas da clínica: procedimentos, profissionais, vínculos e a
 * flag de múltiplos profissionais (F1-08).
 *
 * Usa a instância `api` do api.ts, que já carrega:
 *   - baseURL configurada
 *   - withCredentials: true (autenticação por cookie)
 *   - interceptor de CSRF
 *   - tratamento de erro e refresh de token
 *
 * Reimplementar axios aqui seria duplicar autenticação — e a primeira vez que
 * o CSRF mudasse, só uma das cópias acompanharia.
 */
import { api } from './api.ts';

// --------------------------------------------------------------------------
// Tipos — espelham os schemas do backend
// --------------------------------------------------------------------------
export interface Procedimento {
  id: number;
  name: string;
  duration_minutes: number;
  price_cents: number | null;
  is_evaluation: boolean;
  active: boolean;
  professionals: number;
}

export interface ProcedimentoEntrada {
  name: string;
  duration_minutes: number;
  price_cents?: number | null;
  is_evaluation?: boolean;
}

export interface Profissional {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  cro: string | null;
  active: boolean;
  services: number;
}

export interface ProfissionalEntrada {
  name: string;
  email: string;
  phone?: string | null;
  cro?: string | null;
}

export interface Vinculo {
  professional_id: number;
  service_ids: number[];
  total: number;
}

export interface FlagMulti {
  multi_professional_enabled: boolean;
  profissionais_ativos: number;
  orientacao: string;
}

/** Mensagem de erro legível a partir do que a API devolve. */
export function mensagemDeErro(erro: unknown): string {
  const e = erro as { response?: { data?: { detail?: unknown } }; message?: string };
  const detalhe = e?.response?.data?.detail;
  if (typeof detalhe === 'string') return detalhe;
  if (Array.isArray(detalhe) && detalhe.length > 0) {
    // erro de validação do Pydantic: lista de {loc, msg}
    const primeiro = detalhe[0] as { msg?: string };
    if (primeiro?.msg) return primeiro.msg;
  }
  return e?.message || 'Erro ao comunicar com o servidor';
}

// --------------------------------------------------------------------------
// Procedimentos
// --------------------------------------------------------------------------
export const procedimentosApi = {
  async listar(incluirInativos = false): Promise<Procedimento[]> {
    const r = await api.get('/api/services', { params: { incluir_inativos: incluirInativos } });
    return r.data;
  },

  async criar(dados: ProcedimentoEntrada): Promise<Procedimento> {
    const r = await api.post('/api/services', dados);
    return r.data;
  },

  async atualizar(id: number, dados: Partial<ProcedimentoEntrada> & { active?: boolean }): Promise<Procedimento> {
    const r = await api.put(`/api/services/${id}`, dados);
    return r.data;
  },

  async desativar(id: number): Promise<void> {
    await api.delete(`/api/services/${id}`);
  },
};

// --------------------------------------------------------------------------
// Profissionais
// --------------------------------------------------------------------------
export const profissionaisApi = {
  async listar(incluirInativos = false): Promise<Profissional[]> {
    const r = await api.get('/api/professionals', { params: { incluir_inativos: incluirInativos } });
    return r.data;
  },

  async criar(dados: ProfissionalEntrada): Promise<Profissional> {
    const r = await api.post('/api/professionals', dados);
    return r.data;
  },

  async atualizar(id: number, dados: Partial<ProfissionalEntrada> & { active?: boolean }): Promise<Profissional> {
    const r = await api.put(`/api/professionals/${id}`, dados);
    return r.data;
  },

  async desativar(id: number): Promise<void> {
    await api.delete(`/api/professionals/${id}`);
  },

  /** Procedimentos que este profissional atende. */
  async procedimentos(id: number): Promise<Vinculo> {
    const r = await api.get(`/api/professionals/${id}/services`);
    return r.data;
  },

  /** Substitui o conjunto inteiro. Lista vazia é válida. */
  async definirProcedimentos(id: number, serviceIds: number[]): Promise<Vinculo> {
    const r = await api.put(`/api/professionals/${id}/services`, { service_ids: serviceIds });
    return r.data;
  },
};

// --------------------------------------------------------------------------
// Flag de múltiplos profissionais
// --------------------------------------------------------------------------
export const empresaApi = {
  async lerFlag(): Promise<FlagMulti> {
    const r = await api.get('/api/company/flag');
    return r.data;
  },

  /**
   * Define a flag. Quando houver mais de um profissional ativo e a intenção
   * for desligar, a API responde 409 pedindo confirmação — reenvie com
   * `confirmar: true` depois de mostrar a mensagem ao usuário.
   */
  async definirFlag(habilitado: boolean, confirmar = false): Promise<FlagMulti> {
    const r = await api.put('/api/company/flag', {
      multi_professional_enabled: habilitado,
      confirmar,
    });
    return r.data;
  },
};

// --------------------------------------------------------------------------
// Formatação
// --------------------------------------------------------------------------
export function formatarPreco(centavos: number | null): string {
  if (centavos === null || centavos === undefined) return 'sem preço';
  return (centavos / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export function formatarDuracao(minutos: number): string {
  if (minutos < 60) return `${minutos} min`;
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, '0')}`;
}
