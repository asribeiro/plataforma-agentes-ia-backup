/**
 * Cliente das rotas de cobrança da plataforma (`/api/admin/planos` e
 * `/api/admin/companies/{id}/cobranca`).
 *
 * O que resolve: o painel `/plataforma` já trocava modalidade, mas não dizia
 * quanto cada cliente paga nem registrava o que foi cobrado. Aqui ficam o
 * catálogo de planos (com preço), a assinatura de cada empresa e as faturas
 * mensais.
 *
 * O backend NÃO cobra: o registro é manual, a cobrança real vai por parceiro.
 * Nada aqui fala com adquirente — só se lê e grava o combinado e o quitado.
 *
 * Duas regras do contrato que a tela herda e NÃO reimplementa:
 *   - plano com `preco_centavos = null` não emite fatura (400): null é "ainda
 *     não combinado", não é zero. Zero geraria fatura de valor nenhum, que
 *     parece paga e não é;
 *   - a fatura guarda o preço da emissão (snapshot), então reajustar o plano
 *     não reescreve o passado. Por isso a tela nunca recalcula fatura antiga a
 *     partir do catálogo de hoje.
 *
 * Usa a instância `api` do api.ts, que já carrega baseURL, cookie de sessão,
 * interceptor de CSRF e refresh de token. Um axios novo aqui duplicaria a
 * autenticação — e na primeira mudança de CSRF só uma das cópias acompanharia.
 *
 * Contrato (backend/routes/admin_billing_routes.py, prefixo `/api/admin`):
 *   GET   /planos                          -> Plano[]
 *   PUT   /planos/{id}                     -> Plano
 *   GET   /companies/{id}/cobranca         -> CobrancaEmpresa
 *   PUT   /companies/{id}/cobranca         -> CobrancaEmpresa
 *   POST  /companies/{id}/faturas   (201)  -> Fatura
 *   PATCH /faturas/{id}                    -> Fatura
 */
import { api } from './api.ts';

// --------------------------------------------------------------------------
// Tipos — espelham os schemas do backend
// --------------------------------------------------------------------------
/** `mono` | `up_to_4` | `up_to_10`; tipado frouxo porque o banco é a fonte. */
export type StatusAssinatura = 'ativa' | 'suspensa' | 'encerrada';
export type StatusFatura = 'aberta' | 'paga' | 'cancelada';

export interface Plano {
  id: number;
  nome: string;
  tier: string;
  /** `null` = preço ainda não combinado. É o estado inicial dos três planos. */
  preco_centavos: number | null;
  ciclo: string;
  ativo: boolean;
}

/**
 * Campos ausentes não são enviados.
 *
 * A distinção importa: `preco_centavos: null` é informação ("preço retirado do
 * catálogo") e o backend grava; ausência é "não mexer neste campo". Mandar
 * `undefined` para o JSON o faria desaparecer de qualquer jeito, mas a tela
 * monta o corpo campo a campo para deixar isso explícito.
 */
export interface PlanoAtualizacao {
  nome?: string;
  preco_centavos?: number | null;
  ativo?: boolean;
}

/**
 * Assinatura ATIVA da empresa. O backend só devolve a ativa (índice parcial no
 * banco garante uma por empresa), então assinatura suspensa ou encerrada não
 * aparece no GET — e não há caminho de volta pela API. É por isso que a tela
 * não oferece mudar o status: quem suspender some da tela e não consegue
 * reativar.
 */
export interface Assinatura {
  id: number;
  plano_id: number;
  plano_nome: string;
  status: string;
  dia_vencimento: number;
  /** `AAAA-MM-DD`. */
  inicio: string;
  observacao: string | null;
}

export interface Fatura {
  id: number;
  /** `AAAA-MM`. */
  competencia: string;
  /** Valor no momento da emissão, não o preço de hoje. */
  valor_centavos: number;
  /** `AAAA-MM-DD`. */
  vencimento: string;
  status: StatusFatura;
  /** ISO completo, ou null quando não está paga. */
  pago_em: string | null;
  observacao: string | null;
}

export interface CobrancaEmpresa {
  company_id: number;
  company_nome: string;
  assinatura: Assinatura | null;
  /** Ordenadas por competência, da mais recente para a mais antiga. */
  faturas: Fatura[];
  total_aberto_centavos: number;
  total_pago_centavos: number;
}

export interface AssinaturaEntrada {
  plano_id: number;
  /** 1..28 — o CHECK do banco não aceita 29, 30 nem 31. */
  dia_vencimento: number;
  status?: StatusAssinatura;
  observacao?: string;
}

export interface EmissaoEntrada {
  /** `AAAA-MM`. Omitido, o backend usa o mês corrente do servidor. */
  competencia?: string;
  /** `AAAA-MM-DD`. Omitido, o backend calcula pelo dia de vencimento. */
  vencimento?: string;
  observacao?: string;
}

// --------------------------------------------------------------------------
// As chamadas
// --------------------------------------------------------------------------
export const cobrancaApi = {
  /** Catálogo de planos, com preço e se está ativo. */
  async listarPlanos(): Promise<Plano[]> {
    const r = await api.get('/api/admin/planos');
    return r.data;
  },

  /**
   * Define preço, nome ou ativação do plano.
   *
   * `preco_centavos` em CENTAVOS e inteiro ≥ 0 (o backend responde 422 fora
   * disso). Enviar `null` apaga o preço e, com ele, a possibilidade de emitir
   * fatura deste plano — o corpo só inclui o campo quando a tela quis mudá-lo.
   */
  async atualizarPlano(planoId: number, dados: PlanoAtualizacao): Promise<Plano> {
    const corpo: Record<string, unknown> = {};
    if (dados.nome !== undefined) corpo.nome = dados.nome;
    if (dados.preco_centavos !== undefined) corpo.preco_centavos = dados.preco_centavos;
    if (dados.ativo !== undefined) corpo.ativo = dados.ativo;
    const r = await api.put(`/api/admin/planos/${planoId}`, corpo);
    return r.data;
  },

  /** Assinatura ativa + faturas + totais de UMA empresa, sem trocar contexto. */
  async lerCobranca(companyId: number): Promise<CobrancaEmpresa> {
    const r = await api.get(`/api/admin/companies/${companyId}/cobranca`);
    return r.data;
  },

  /**
   * Define plano e dia de vencimento.
   *
   * Trocar de plano ENCERRA a assinatura anterior e cria outra (o banco aceita
   * uma ativa por empresa); repetir o mesmo plano só atualiza o dia. Devolve o
   * estado completo, então a tela não precisa de um GET extra.
   *
   * 409 quando o plano está inativo — o `detail` explica e nada é alterado.
   */
  async definirAssinatura(companyId: number, dados: AssinaturaEntrada): Promise<CobrancaEmpresa> {
    const r = await api.put(`/api/admin/companies/${companyId}/cobranca`, dados);
    return r.data;
  },

  /**
   * Emite a fatura da competência com o preço vigente do plano.
   *
   * Erros que a tela precisa mostrar pelo `detail`:
   *   400 plano sem preço        -> mandar o usuário definir o preço;
   *   409 sem assinatura ativa   -> definir plano antes;
   *   409 competência repetida   -> já existe fatura daquele mês.
   * Por isso o botão da tela fica desabilitado nos dois primeiros casos: não se
   * convida o usuário a clicar para receber erro previsível.
   */
  async emitirFatura(companyId: number, dados: EmissaoEntrada = {}): Promise<Fatura> {
    const r = await api.post(`/api/admin/companies/${companyId}/faturas`, dados);
    return r.data;
  },

  /** Marca paga, reabre ou cancela. `pago_em` é do backend, não da tela. */
  async atualizarFatura(
    faturaId: number,
    dados: { status: StatusFatura; observacao?: string },
  ): Promise<Fatura> {
    const r = await api.patch(`/api/admin/faturas/${faturaId}`, dados);
    return r.data;
  },
};

// --------------------------------------------------------------------------
// Competência, datas e dinheiro
// --------------------------------------------------------------------------
const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/**
 * Competência do mês corrente no fuso do navegador.
 *
 * O backend usaria o mês do SERVIDOR se o campo fosse omitido, e os dois podem
 * divergir na virada do mês (servidor em UTC, usuário em UTC-3 emitindo às 22h
 * do dia 31). Mandar a competência explícita deixa o rótulo do botão — "fatura
 * de out/2026" — igual ao que foi criado.
 */
export function competenciaAtual(agora: Date = new Date()): string {
  return `${agora.getFullYear()}-${String(agora.getMonth() + 1).padStart(2, '0')}`;
}

/** `2026-10` -> `out/2026`. */
export function rotuloCompetencia(competencia: string): string {
  const [ano, mes] = (competencia || '').split('-');
  const indice = Number(mes) - 1;
  if (!ano || !Number.isInteger(indice) || indice < 0 || indice > 11) return competencia || '—';
  return `${MESES_CURTOS[indice]}/${ano}`;
}

/**
 * `2026-10-05` -> `05/10/2026`, sem passar por `Date`.
 *
 * `new Date('2026-10-05')` é meia-noite UTC: em UTC-3 o dia renderiza 04/10.
 * Para data de vencimento, o dia é o dado — não se converte fuso.
 */
export function formatarVencimento(data: string | null | undefined): string {
  const partes = String(data || '').split('T')[0].split('-');
  if (partes.length !== 3 || partes[2] === '') return data ? String(data) : '—';
  return `${partes[2]}/${partes[1]}/${partes[0]}`;
}

/** Centavos -> texto de input em reais (`123456` -> `1234,56`). */
export function centavosParaReais(centavos: number | null | undefined): string {
  if (typeof centavos !== 'number' || !Number.isFinite(centavos)) return '';
  return (centavos / 100).toFixed(2).replace('.', ',');
}

/**
 * Texto de input em reais -> centavos inteiros; `null` quando não é um valor.
 *
 * Aceita o que o usuário digita de fato: `1.234,56`, `1234,56`, `1234.56`,
 * `R$ 1.234,56`. Ponto sozinho é ambíguo — `1.234` é milhar em pt-BR — então a
 * regra é: vírgula presente => ponto é milhar; sem vírgula, ponto seguido de
 * exatamente 1 ou 2 dígitos é decimal, senão é milhar.
 */
export function reaisParaCentavos(texto: string): number | null {
  const limpo = (texto || '').replace(/[^\d.,-]/g, '').trim();
  if (!limpo) return null;

  let normalizado = limpo;
  if (normalizado.includes(',')) {
    normalizado = normalizado.replace(/\./g, '').replace(',', '.');
  } else if (!/^-?\d+(\.\d{1,2})?$/.test(normalizado)) {
    normalizado = normalizado.replace(/\./g, '');
  }

  const valor = Number(normalizado);
  if (!Number.isFinite(valor) || valor < 0) return null;
  return Math.round(valor * 100);
}
