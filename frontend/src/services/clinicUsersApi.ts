/**
 * Cliente da tela de Equipe da clínica (card F1-12 / tela).
 *
 * Espelha as rotas `/api/clinic/users`. Usa a instância `api` do api.ts, que já
 * carrega cookie de autenticação, CSRF e refresh — reimplementar axios aqui
 * duplicaria autenticação e a primeira mudança de CSRF quebraria só esta cópia.
 *
 * Erro de negócio (409 do último administrador, papel sem profissional etc.) vem
 * com mensagem pronta do backend em `detail`. A tela mostra ESSA mensagem: o
 * backend sabe por que recusou, o frontend só sabe que deu erro.
 */
import { api } from './api.ts';

export interface ClinicaUsuario {
  id: number;
  name: string;
  email: string;
  role: string;
  role_rotulo: string;
  professional_id: number | null;
  professional_nome: string | null;
  is_active: boolean;
}

export interface PapelOpcao {
  role: string;
  rotulo: string;
  exige_profissional: boolean;
}

export interface EuClinica {
  id: number;
  name: string;
  email: string;
  role: string;
  role_rotulo: string;
  professional_id: number | null;
  professional_nome: string | null;
  pode_administrar_usuarios: boolean;
  ve_prontuario: boolean;
}

export interface ClinicaUsuarioEntrada {
  name: string;
  email: string;
  password: string;
  role: string;
  professional_id?: number | null;
}

export interface ClinicaUsuarioPatch {
  name?: string;
  role?: string;
  professional_id?: number | null;
  is_active?: boolean;
}

/**
 * Mensagem legível de um erro de API.
 *
 * O backend devolve `detail` como string nas recusas de negócio. Quando o
 * FastAPI recusa por schema (422), `detail` é uma LISTA de objetos — mostrar
 * isso cru para o usuário é pior do que uma frase genérica.
 */
export function mensagemDeErro(erro: unknown, padrao = 'Não foi possível concluir a operação'): string {
  const e = erro as { response?: { data?: { detail?: unknown }; status?: number } };
  const status = e?.response?.status;
  const detalhe = e?.response?.data?.detail;

  if (typeof detalhe === 'string' && detalhe.trim()) return detalhe;

  if (Array.isArray(detalhe) && detalhe.length > 0) {
    const primeiro = detalhe[0] as { msg?: string; loc?: unknown[] };
    const campo = Array.isArray(primeiro?.loc) ? primeiro.loc[primeiro.loc.length - 1] : null;
    if (primeiro?.msg) {
      return campo
        ? `Campo "${String(campo)}": ${primeiro.msg}`
        : primeiro.msg;
    }
  }

  if (status === 403) return 'Seu papel nesta clínica não permite administrar usuários.';
  if (status === 401) return 'Sua sessão expirou. Entre novamente.';
  if (status === 404) return 'Usuário não encontrado nesta clínica.';
  if (status === 0 || status === undefined) return 'Não foi possível falar com o servidor.';
  return padrao;
}

export const equipeApi = {
  /** Retrato do usuário logado: papel, vínculo e o que o papel permite. */
  async eu(): Promise<EuClinica> {
    const { data } = await api.get<EuClinica>('/api/clinic/users/eu');
    return data;
  },

  async papeis(): Promise<PapelOpcao[]> {
    const { data } = await api.get<PapelOpcao[]>('/api/clinic/users/papeis');
    return data;
  },

  async listar(incluirInativos = true): Promise<ClinicaUsuario[]> {
    const { data } = await api.get<ClinicaUsuario[]>('/api/clinic/users', {
      params: { incluir_inativos: incluirInativos },
    });
    return data;
  },

  async criar(entrada: ClinicaUsuarioEntrada): Promise<ClinicaUsuario> {
    const { data } = await api.post<ClinicaUsuario>('/api/clinic/users', entrada);
    return data;
  },

  async atualizar(id: number, patch: ClinicaUsuarioPatch): Promise<ClinicaUsuario> {
    const { data } = await api.patch<ClinicaUsuario>(`/api/clinic/users/${id}`, patch);
    return data;
  },
};

/** Papel pode ver prontuário? Regra espelhada do backend, só para rotular a tela. */
export const papeisQueVeemProntuario = ['admin', 'clinic_admin', 'clinical_professional'];
