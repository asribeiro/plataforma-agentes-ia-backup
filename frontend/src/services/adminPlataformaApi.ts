/**
 * Cliente das rotas `/api/admin` — painel do admin master da plataforma.
 *
 * O que resolve: até aqui o admin master só conseguia trocar a modalidade da
 * empresa em que ele ESTAVA (`PUT /api/company/flag`). Não havia lista de
 * clientes da plataforma — `/customers` é a carteira de pacientes/faturas do
 * workspace, não a lista de empresas.
 *
 * Usa a instância `api` do api.ts, que já carrega baseURL, cookie de sessão,
 * interceptor de CSRF e refresh de token. Criar um axios novo aqui duplicaria a
 * autenticação — e na primeira mudança de CSRF só uma das cópias acompanharia.
 *
 * Contrato (backend/routes/admin_platform_routes.py):
 *   GET  /api/admin/eu                     -> SouAdminPlataforma (NUNCA 403)
 *   GET  /api/admin/companies              -> PainelPlataforma   (403 se não for admin master)
 *   POST /api/admin/companies/{id}/entrar  -> EntradaNaEmpresa
 *   PUT  /api/admin/companies/{id}/modalidade -> ModalidadeEmpresa
 */
import { api } from './api.ts';

// --------------------------------------------------------------------------
// Tipos — espelham os schemas do backend
// --------------------------------------------------------------------------
export type ModalidadeTier = 'mono' | 'up_to_4' | 'up_to_10' | 'network';

export interface SouAdminPlataforma {
  admin_plataforma: boolean;
  email: string;
  company_id: number | null;
}

export interface EmpresaDaPlataforma {
  id: number;
  /** `Company.name` (razão social). A tela prefere `nome_exibido`. */
  nome: string;
  nome_exibido: string | null;
  cnpj: string | null;
  logo_url: string | null;
  /** `mono` | `up_to_4` | `up_to_10`; tipado frouxo porque o banco é a fonte. */
  professional_tier: string;
  max_professionals: number;
  profissionais_ativos: number;
  profissionais_total: number;
  usuarios_ativos: number;
  usuarios_total: number;
  agendas_ativas: number;
  agendamentos_total: number;
  /** O admin master já tem vínculo (`client_companies`) com esta empresa. */
  vinculada_ao_meu_login: boolean;
  /** É a empresa em que a sessão está agora. */
  empresa_atual: boolean;
  network_unit_limit?: number | null;
  network_units_used?: number;
}

export interface PainelPlataforma {
  total_empresas: number;
  empresa_atual_id: number | null;
  empresas: EmpresaDaPlataforma[];
}

export interface EntradaNaEmpresa {
  status: string;
  company_id: number;
  nome: string;
  company_logo_url: string;
  vinculo_criado: boolean;
  message: string;
}

export interface ModalidadeEmpresa {
  professional_tier: string;
  max_professionals: number;
  rotulo: string;
  profissionais_ativos: number;
  pode_adicionar: boolean;
  pode_editar: boolean;
  orientacao: string;
}

export interface LimiteUnidadesRede {
  company_id: number;
  limite: number;
  unidades_utilizadas: number;
  unidades_disponiveis: number;
}

/** As três faixas comerciais. O limite é a regra de negócio de cada uma. */
export const MODALIDADES: { tier: ModalidadeTier; rotulo: string; limite: number }[] = [
  { tier: 'mono', rotulo: 'Monoprofissional — 1 profissional', limite: 1 },
  { tier: 'up_to_4', rotulo: 'Até 4 profissionais', limite: 4 },
  { tier: 'up_to_10', rotulo: 'Até 10 profissionais', limite: 10 },
  { tier: 'network', rotulo: 'Redes de Clínicas — até 30 unidades', limite: 30 },
];

/** Tier vindo do banco como string: devolve o tipo só quando é um dos três. */
export function tierValido(valor: string | null | undefined): ModalidadeTier | null {
  const normalizado = (valor || '').trim().toLowerCase();
  if (normalizado === 'mono' || normalizado === 'up_to_4' || normalizado === 'up_to_10' || normalizado === 'network') {
    return normalizado;
  }
  return null;
}

/** Rótulo legível de uma modalidade; cai para o valor cru se for desconhecida. */
export function rotuloDaModalidade(valor: string | null | undefined): string {
  const tier = tierValido(valor);
  if (!tier) return valor ? String(valor) : 'não definida';
  return MODALIDADES.find((m) => m.tier === tier)?.rotulo || tier;
}

// --------------------------------------------------------------------------
// Erros
// --------------------------------------------------------------------------
/** Status HTTP do erro do axios, quando existe. */
export function statusDeErro(erro: unknown): number | null {
  const e = erro as { response?: { status?: number } };
  const status = e?.response?.status;
  return typeof status === 'number' ? status : null;
}

/**
 * Mensagem legível a partir do que a API devolve.
 *
 * O backend escreve o texto pronto em `detail` (string). Erro de validação do
 * Pydantic vem como lista de `{loc, msg}` — a primeira mensagem já é a que
 * explica o problema. Sem nada disso, `error.message`; por último, um fallback.
 */
export function mensagemDeErro(erro: unknown): string {
  const e = erro as { response?: { data?: { detail?: unknown } }; message?: string };
  const detalhe = e?.response?.data?.detail;

  if (typeof detalhe === 'string' && detalhe.trim()) {
    return detalhe.trim();
  }

  if (Array.isArray(detalhe) && detalhe.length > 0) {
    const partes = detalhe
      .map((item) => {
        if (typeof item === 'string') return item;
        const msg = (item as { msg?: string } | null)?.msg;
        const loc = (item as { loc?: unknown[] } | null)?.loc;
        if (!msg) return '';
        return Array.isArray(loc) && loc.length > 0
          ? `${msg} (campo: ${loc.filter((p) => p !== 'body').join('.')})`
          : msg;
      })
      .filter((parte) => Boolean(parte));
    if (partes.length > 0) return partes.join(' ');
  }

  if (e?.message && e.message.trim()) return e.message;
  return 'Erro ao comunicar com o servidor';
}

/**
 * O 409 cuja saída é reenviar com `confirmar: true` (redução de limite).
 *
 * Existem DOIS 409 nesta rota e eles pedem coisas opostas:
 *   - redução que exige confirmação -> o `detail` termina pedindo `confirmar=true`;
 *   - rebaixamento impossível (mais ativos que o novo limite) -> o `detail` diz
 *     para desativar profissionais; NÃO há como confirmar.
 * O texto é a única coisa que separa os dois, então a decisão lê o texto.
 */
export function exigeConfirmacao(erro: unknown): boolean {
  if (statusDeErro(erro) !== 409) return false;
  return /confirmar\s*=\s*true/i.test(mensagemDeErro(erro));
}

// --------------------------------------------------------------------------
// As quatro chamadas
// --------------------------------------------------------------------------
export const adminPlataformaApi = {
  /** Quem está logado é admin master? Responde `false` para os demais, nunca 403. */
  async eu(): Promise<SouAdminPlataforma> {
    const r = await api.get('/api/admin/eu');
    return r.data;
  },

  /** Todas as empresas da plataforma, com os números que decidem a modalidade. */
  async listarEmpresas(): Promise<PainelPlataforma> {
    const r = await api.get('/api/admin/companies');
    return r.data;
  },

  /**
   * Troca o contexto da sessão para a empresa escolhida (cria o vínculo se faltar).
   * Depois disto TODO o painel lê a empresa antiga até recarregar: a tela chama
   * `window.location.reload()`.
   */
  async entrar(companyId: number): Promise<EntradaNaEmpresa> {
    const r = await api.post(`/api/admin/companies/${companyId}/entrar`);
    return r.data;
  },

  /**
   * Modalidade de QUALQUER empresa, sem trocar de contexto.
   *
   * Erros que a tela precisa distinguir:
   *   409 excedente de profissionais ativos -> mostrar e NÃO oferecer reenvio;
   *   409 redução de limite               -> confirmar com `confirmar: true`;
   *   422 tier inválido                   -> mensagem pronta em `detail`.
   */
  async definirModalidade(
    companyId: number,
    tier: ModalidadeTier,
    confirmar = false,
  ): Promise<ModalidadeEmpresa> {
    const r = await api.put(`/api/admin/companies/${companyId}/modalidade`, {
      professional_tier: tier,
      confirmar,
    });
    return r.data;
  },

  async lerLimiteUnidadesRede(companyId: number): Promise<LimiteUnidadesRede> {
    const r = await api.get(`/api/admin/companies/${companyId}/network-limit`);
    return r.data;
  },

  async atualizarLimiteUnidadesRede(companyId: number, limite: number): Promise<LimiteUnidadesRede> {
    const r = await api.put(`/api/admin/companies/${companyId}/network-limit`, { limite });
    return r.data;
  },
};
