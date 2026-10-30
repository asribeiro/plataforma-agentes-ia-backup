/**
 * Painel da plataforma — todos os clientes do admin master.
 *
 * O produto tinha uma tela só para a empresa do login (`/company`). O dono da
 * plataforma não tinha onde ver os OUTROS clientes, nem como trocar o plano de
 * quem não é ele. `/customers` não serve: ali é a carteira de pacientes/faturas
 * do workspace, não a lista de empresas.
 *
 * Três naturezas de ação na mesma tela:
 *   - "Entrar nesta empresa" muda o CONTEXTO DA SESSÃO no servidor. Depois disso
 *     todo o painel continua lendo a empresa antiga até recarregar — por isso o
 *     `window.location.reload()`. Sem o reload a tela mente.
 *   - "Salvar modalidade" mexe no limite de profissionais de OUTRA empresa sem
 *     sair desta. Os erros vêm prontos do backend (409/422) e são mostrados como
 *     vieram: reescrever a regra aqui é como as duas versões divergem.
 *   - "Configurar empresa" / "Usuários & acessos" / "Perfis de permissão" são
 *     atalhos para as telas de configuração DAQUELE cliente. Elas leem a empresa
 *     da sessão, então só fazem sentido no contexto dele: se a empresa já é a
 *     atual, navega direto; se não é, troca o contexto (`entrar`) e só depois de
 *     o servidor confirmar faz navegação DURA (`window.location.href`). Navegar
 *     pelo router deixaria dados da empresa anterior em caches de várias telas
 *     (empresa no topo, permissões, listas já carregadas).
 *
 * Dois 409 pedem coisas opostas e a tela os separa pelo texto:
 *   - excedente de profissionais ativos -> não há confirmação possível; a ação é
 *     desativar profissionais antes;
 *   - redução de limite -> confirmação explícita em modal e reenvio com
 *     `confirmar: true`.
 *
 * Cobrança (área "Plano & cobrança", fechada por padrão em cada cartão): o
 * painel dizia quem era o cliente e qual o limite, mas não quanto ele paga. A
 * área por empresa define plano e dia de vencimento, emite a fatura do mês e
 * marca paga/reabre. O bloco "Planos e preços" no topo existe porque o preço
 * nasce nulo no catálogo: sem definir preço, nenhuma fatura pode ser emitida, e
 * o botão de emitir fica desabilitado com o motivo escrito ao lado.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  BadgeDollarSign,
  Building2,
  Calendar,
  CalendarCheck,
  KeyRound,
  Layers,
  Loader2,
  LogIn,
  Plus,
  RefreshCw,
  Settings,
  ShieldAlert,
  ShieldCheck,
  UserRound,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  AgentivePageHeader,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import {
  CobrancaEmpresaPanel,
  PlanosPanel,
} from '../components/CobrancaPlataforma.tsx';
import {
  adminPlataformaApi,
  exigeConfirmacao,
  mensagemDeErro,
  MODALIDADES,
  rotuloDaModalidade,
  statusDeErro,
  tierValido,
  type EmpresaDaPlataforma,
  type ModalidadeTier,
  type PainelPlataforma,
} from '../services/adminPlataformaApi.ts';
import {
  cobrancaApi,
  competenciaAtual,
  rotuloCompetencia,
  type CobrancaEmpresa,
  type Fatura,
  type Plano,
  type PlanoAtualizacao,
  type StatusFatura,
} from '../services/cobrancaApi.ts';
import { formatarPreco } from '../services/clinicApi.ts';
import { companyRegistrationApi, type CompanyRegistrationDraft } from '../services/companyRegistrationApi.ts';

// --------------------------------------------------------------------------
// Formatação
// --------------------------------------------------------------------------
const numeroFormatado = (valor: number | null | undefined): string =>
  typeof valor === 'number' && Number.isFinite(valor) ? valor.toLocaleString('pt-BR') : '0';

/** `nome_exibido` é o nome comercial; `nome` é a razão social. */
const nomeDaEmpresa = (empresa: EmpresaDaPlataforma): string => {
  const exibido = (empresa.nome_exibido || '').trim();
  const razao = (empresa.nome || '').trim();
  if (exibido) return exibido;
  if (razao) return razao;
  return `Empresa #${empresa.id}`;
};

const formatarCnpj = (cnpj: string | null): string | null => {
  if (!cnpj) return null;
  const digitos = cnpj.replace(/\D/g, '');
  if (digitos.length !== 14) return cnpj;
  return `${digitos.slice(0, 2)}.${digitos.slice(2, 5)}.${digitos.slice(5, 8)}/${digitos.slice(8, 12)}-${digitos.slice(12)}`;
};

// --------------------------------------------------------------------------
// Ações de configuração do cliente
// --------------------------------------------------------------------------
/**
 * Atalhos para as telas de configuração DAQUELE cliente.
 *
 * `destino` é a rota que a tela alvo já sabe abrir: `/company` mostra os dados
 * cadastrais (logo, nome de exibição), `/equipe` é onde se define papel, perfil
 * de permissão e vínculo, e `/company?tab=teams` abre a aba de perfis —
 * `CompanyConfig` lê `?tab=` na query string.
 *
 * Todas essas telas leem a empresa da SESSÃO, não um id na URL: por isso a ação
 * só é honesta se o contexto estiver na empresa certa antes de navegar.
 */
interface AcaoDaEmpresa {
  /** Rota a abrir no contexto da empresa. */
  destino: string;
  icone: LucideIcon;
  rotulo: string;
  /** O que o usuário encontra lá — o rótulo sozinho não diz. */
  detalhe: string;
}

const ACOES_DA_EMPRESA: AcaoDaEmpresa[] = [
  {
    destino: '/company',
    icone: Settings,
    rotulo: 'Configurar empresa',
    detalhe: 'Dados cadastrais, logo e nome de exibição',
  },
  {
    destino: '/equipe',
    icone: Users,
    rotulo: 'Usuários & acessos',
    detalhe: 'Papel, perfil de permissão e vínculo',
  },
  {
    destino: '/company?tab=teams',
    icone: KeyRound,
    rotulo: 'Perfis de permissão',
    // A aba se chama "Equipes" dentro de /company; dizer isso aqui evita o
    // usuário achar que caiu na tela errada.
    detalhe: 'Aba Equipes de /company: perfis e o que cada um pode fazer',
  },
];

// --------------------------------------------------------------------------
// Pedaços da tela
// --------------------------------------------------------------------------
interface ContagemProps {
  icon: LucideIcon;
  rotulo: string;
  valor: string;
  detalhe: string;
  mutedClass: string;
}

const Contagem: React.FC<ContagemProps> = ({ icon: Icon, rotulo, valor, detalhe, mutedClass }) => (
  <div className="min-w-0">
    <p className={`flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.08em] ${mutedClass}`}>
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{rotulo}</span>
    </p>
    <p className="mt-1 text-sm font-semibold leading-none">{valor}</p>
    <p className={`mt-1 text-xs ${mutedClass}`}>{detalhe}</p>
  </div>
);

interface EmpresaCardProps {
  /** Área "Plano & cobrança" do cartão, montada pela tela (fechada por padrão). */
  areaCobranca: React.ReactNode;
  bloqueado: boolean;
  empresa: EmpresaDaPlataforma;
  isDark: boolean;
  onAbrirConfiguracao: (acao: AcaoDaEmpresa) => void;
  onEntrar: () => void;
  onEscolher: (tier: ModalidadeTier | '') => void;
  onSalvar: () => void;
  onSalvarLimiteRede: (limite: number) => void;
  salvando: boolean;
  salvandoLimiteRede: boolean;
  selecao: ModalidadeTier | '';
}

const EmpresaCard: React.FC<EmpresaCardProps> = ({
  areaCobranca,
  bloqueado,
  empresa,
  isDark,
  onAbrirConfiguracao,
  onEntrar,
  onEscolher,
  onSalvar,
  onSalvarLimiteRede,
  salvando,
  salvandoLimiteRede,
  selecao,
}) => {
  const nome = nomeDaEmpresa(empresa);
  const cnpj = formatarCnpj(empresa.cnpj);
  const tierAtual = tierValido(empresa.professional_tier);
  const mudou = selecao !== '' && selecao !== tierAtual;
  const [limiteRede, setLimiteRede] = useState(String(empresa.network_unit_limit || 30));
  const selectId = `modalidade-empresa-${empresa.id}`;
  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const faintClass = isDark ? 'text-white/40' : 'text-brand/45';
  const borderClass = isDark ? 'border-white/10' : 'border-brand/10';
  const softClass = isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas';

  return (
    <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
      {/* Identificação */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={`grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-xl ${
              isDark ? 'bg-white/10 text-white' : 'bg-brand-canvas text-brand'
            }`}
          >
            {empresa.logo_url ? (
              <img src={empresa.logo_url} alt={`Logo de ${nome}`} className="h-full w-full object-cover" />
            ) : (
              <Building2 className="h-5 w-5" />
            )}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-semibold leading-tight">{nome}</h2>
              {empresa.empresa_atual && (
                <span className={agentivePillClass(isDark, true)}>
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Empresa atual
                </span>
              )}
              <span className={agentivePillClass(isDark, false)}>
                {rotuloDaModalidade(empresa.professional_tier)}
              </span>
            </div>
            <p className={`mt-1 text-xs ${mutedClass}`}>
              {cnpj ? `CNPJ ${cnpj}` : 'CNPJ não informado'}
              {' · '}
              {empresa.professional_tier === 'network'
                ? `${numeroFormatado(empresa.network_units_used)} de ${numeroFormatado(empresa.network_unit_limit || 30)} unidades`
                : `limite de ${numeroFormatado(empresa.max_professionals)} ${
                  empresa.max_professionals === 1 ? 'profissional' : 'profissionais'
                }`}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onEntrar}
          disabled={empresa.empresa_atual || bloqueado}
          className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
          title={
            empresa.empresa_atual
              ? 'A sessão já está nesta empresa'
              : 'Troca o contexto da sessão para esta empresa e recarrega o painel'
          }
        >
          <LogIn className="h-4 w-4" />
          Entrar nesta empresa
        </button>
      </div>

      {/* Números: é o que decide a modalidade */}
      <div className={`mt-4 grid grid-cols-2 gap-3 rounded-2xl border p-3 sm:grid-cols-4 ${borderClass} ${softClass}`}>
        <Contagem
          icon={UserRound}
          rotulo="Profissionais"
          valor={`${numeroFormatado(empresa.profissionais_ativos)} ativos`}
          detalhe={`${numeroFormatado(empresa.profissionais_total)} no total`}
          mutedClass={mutedClass}
        />
        <Contagem
          icon={Users}
          rotulo="Usuários"
          valor={`${numeroFormatado(empresa.usuarios_ativos)} ativos`}
          detalhe={`${numeroFormatado(empresa.usuarios_total)} no total`}
          mutedClass={mutedClass}
        />
        <Contagem
          icon={Calendar}
          rotulo="Agendas ativas"
          valor={numeroFormatado(empresa.agendas_ativas)}
          detalhe="agendas em uso"
          mutedClass={mutedClass}
        />
        <Contagem
          icon={CalendarCheck}
          rotulo="Agendamentos"
          valor={numeroFormatado(empresa.agendamentos_total)}
          detalhe="histórico completo"
          mutedClass={mutedClass}
        />
      </div>

      {/* Configuração do cliente: entra na tela certa já no contexto dele */}
      <div className={`mt-4 rounded-2xl border p-3 ${borderClass} ${softClass}`}>
        <p className={`flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.08em] ${mutedClass}`}>
          <Settings className="h-3.5 w-3.5 shrink-0" />
          Configuração do cliente
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          {ACOES_DA_EMPRESA.map((acao) => {
            const Icon = acao.icone;
            return (
              <button
                key={acao.destino}
                type="button"
                onClick={() => onAbrirConfiguracao(acao)}
                disabled={bloqueado}
                className={agentiveSecondaryButtonClass(isDark, 'min-w-0 sm:flex-1')}
                title={`${acao.detalhe} — abre ${acao.destino} nesta empresa`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{acao.rotulo}</span>
              </button>
            );
          })}
        </div>
        <p className={`mt-2 text-xs ${faintClass}`}>
          {empresa.empresa_atual
            ? 'Estas telas abrem na empresa atual da sessão — nenhuma troca de contexto.'
            : `Estas telas abrem em ${nome}: a sessão passa a apontar para ela antes de o painel trocar de tela.`}
        </p>
      </div>

      {/* Modalidade */}
      <div className={`mt-4 rounded-2xl border p-3 ${borderClass} ${softClass}`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1">
            <label htmlFor={selectId} className={agentiveLabelClass(isDark)}>
              Modalidade / limite de profissionais
            </label>
            <select
              id={selectId}
              value={selecao}
              onChange={(event) => onEscolher(event.target.value as ModalidadeTier | '')}
              disabled={salvando}
              className={agentiveInputClass(isDark)}
            >
              {!tierAtual && <option value="">Selecione a modalidade</option>}
              {MODALIDADES.map((modalidade) => (
                <option key={modalidade.tier} value={modalidade.tier}>
                  {modalidade.rotulo}
                </option>
              ))}
            </select>
            <p className={`mt-1.5 text-xs ${faintClass}`}>
              Hoje: {rotuloDaModalidade(empresa.professional_tier)} ·{' '}
              {numeroFormatado(empresa.profissionais_ativos)} profissional(is) ativo(s) de{' '}
              {numeroFormatado(empresa.max_professionals)} permitido(s).
            </p>
          </div>

          {empresa.professional_tier === 'network' && (
            <div className={`mt-4 rounded-2xl border p-3 ${borderClass} ${softClass}`}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <div className="min-w-0 flex-1">
                  <label className={agentiveLabelClass(isDark)}>Limite de unidades da rede</label>
                  <input
                    type="number"
                    min={empresa.network_units_used || 1}
                    value={limiteRede}
                    onChange={(event) => setLimiteRede(event.target.value)}
                    className={agentiveInputClass(isDark)}
                  />
                  <p className={`mt-1.5 text-xs ${faintClass}`}>
                    {numeroFormatado(empresa.network_units_used)} unidade(s) usada(s). Somente admins da plataforma podem alterar.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onSalvarLimiteRede(Number(limiteRede))}
                  disabled={salvandoLimiteRede || Number(limiteRede) === Number(empresa.network_unit_limit || 30)}
                  className={agentivePrimaryButtonClass('shrink-0')}
                >
                  {salvandoLimiteRede ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Salvar limite
                </button>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={onSalvar}
            disabled={!mudou || salvando || bloqueado}
            className={agentivePrimaryButtonClass('shrink-0')}
          >
            {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {salvando ? 'Salvando...' : 'Salvar modalidade'}
          </button>
        </div>
      </div>

      {/* Cobrança: plano, vencimento, emissão e faturas desta empresa */}
      {areaCobranca}
    </section>
  );
};

// --------------------------------------------------------------------------
// Tela
// --------------------------------------------------------------------------
const Plataforma: React.FC = () => {
  const { isDark } = useTheme();
  const navigate = useNavigate();

  const [painel, setPainel] = useState<PainelPlataforma | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [semPermissao, setSemPermissao] = useState(false);
  const [motivoSemPermissao, setMotivoSemPermissao] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [rascunhos, setRascunhos] = useState<CompanyRegistrationDraft[]>([]);

  /** Seleção de modalidade por empresa (ainda não salva). */
  const [selecoes, setSelecoes] = useState<Record<number, ModalidadeTier | ''>>({});
  const [salvandoId, setSalvandoId] = useState<number | null>(null);
  const [salvandoLimiteRedeId, setSalvandoLimiteRedeId] = useState<number | null>(null);

  const [empresaParaEntrar, setEmpresaParaEntrar] = useState<EmpresaDaPlataforma | null>(null);
  const [entrando, setEntrando] = useState(false);

  /**
   * Ação de configuração aguardando confirmação. Só existe quando a empresa NÃO
   * é a atual: sem troca de contexto não há o que confirmar.
   */
  const [acaoPendente, setAcaoPendente] = useState<{
    acao: AcaoDaEmpresa;
    empresa: EmpresaDaPlataforma;
  } | null>(null);
  const [abrindoConfiguracao, setAbrindoConfiguracao] = useState(false);

  const [confirmacaoReducao, setConfirmacaoReducao] = useState<{
    empresa: EmpresaDaPlataforma;
    mensagem: string;
    tier: ModalidadeTier;
  } | null>(null);

  // --- Cobrança -----------------------------------------------------------
  /**
   * Catálogo de planos é GLOBAL: o preço de "Plano Clinica" é o mesmo para todos
   * os clientes. Por isso vive na tela e é passado aos cartões — cada cartão
   * buscar o próprio catálogo daria três respostas que podem divergir.
   */
  const [planos, setPlanos] = useState<Plano[]>([]);
  const [planosAbertos, setPlanosAbertos] = useState(false);
  const [carregandoPlanos, setCarregandoPlanos] = useState(true);
  const [erroPlanos, setErroPlanos] = useState<string | null>(null);
  const [salvandoPlanoId, setSalvandoPlanoId] = useState<number | null>(null);

  /** Cobrança por empresa. Ausente = ainda não buscada (busca na 1ª abertura). */
  const [cobrancas, setCobrancas] = useState<Record<number, CobrancaEmpresa>>({});
  const [cobrancaAberta, setCobrancaAberta] = useState<Record<number, boolean>>({});
  const [carregandoCobranca, setCarregandoCobranca] = useState<Record<number, boolean>>({});
  const [erroCobranca, setErroCobranca] = useState<Record<number, string | null>>({});
  const [salvandoAssinaturaId, setSalvandoAssinaturaId] = useState<number | null>(null);
  const [emitindoId, setEmitindoId] = useState<number | null>(null);
  const [faturaEmAndamentoId, setFaturaEmAndamentoId] = useState<number | null>(null);

  const carregarPlanos = useCallback(async () => {
    setCarregandoPlanos(true);
    setErroPlanos(null);
    try {
      const dados = await cobrancaApi.listarPlanos();
      setPlanos(dados);
    } catch (e) {
      // Erro de planos NÃO derruba a lista de clientes: são dados diferentes, e
      // o cartão de cada empresa continua servindo. O aviso fica no bloco.
      setErroPlanos(mensagemDeErro(e));
    } finally {
      setCarregandoPlanos(false);
    }
  }, []);

  const carregarCobranca = useCallback(async (empresaId: number) => {
    setCarregandoCobranca((prev) => ({ ...prev, [empresaId]: true }));
    setErroCobranca((prev) => ({ ...prev, [empresaId]: null }));
    try {
      const dados = await cobrancaApi.lerCobranca(empresaId);
      setCobrancas((prev) => ({ ...prev, [empresaId]: dados }));
    } catch (e) {
      setErroCobranca((prev) => ({ ...prev, [empresaId]: mensagemDeErro(e) }));
    } finally {
      setCarregandoCobranca((prev) => ({ ...prev, [empresaId]: false }));
    }
  }, []);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    setSemPermissao(false);
    setMotivoSemPermissao(null);
    // Planos em paralelo: a lista de clientes não espera o catálogo (e vice-versa).
    void carregarPlanos();
    try {
      const dados = await adminPlataformaApi.listarEmpresas();
      setPainel(dados);
      try {
        setRascunhos(await companyRegistrationApi.listDrafts());
      } catch {
        // A lista principal continua disponível se a migration de rascunhos
        // ainda não estiver aplicada neste ambiente.
        setRascunhos([]);
      }
      const inicial: Record<number, ModalidadeTier | ''> = {};
      dados.empresas.forEach((empresa) => {
        inicial[empresa.id] = tierValido(empresa.professional_tier) ?? '';
      });
      setSelecoes(inicial);
    } catch (e) {
      // 403 aqui é acesso por URL de quem não é admin master — estado próprio,
      // não tela vazia nem toast de erro genérico.
      if (statusDeErro(e) === 403) {
        setSemPermissao(true);
        setMotivoSemPermissao(mensagemDeErro(e));
        setPainel(null);
      } else {
        setErro(mensagemDeErro(e));
      }
    } finally {
      setCarregando(false);
    }
  }, [carregarPlanos]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const salvarModalidade = useCallback(
    async (empresa: EmpresaDaPlataforma, tier: ModalidadeTier, confirmar = false) => {
      setSalvandoId(empresa.id);
      try {
        const atualizada = await adminPlataformaApi.definirModalidade(empresa.id, tier, confirmar);
        setConfirmacaoReducao(null);
        setSelecoes((prev) => ({
          ...prev,
          [empresa.id]: tierValido(atualizada.professional_tier) ?? '',
        }));
        setPainel((prev) =>
          prev
            ? {
                ...prev,
                empresas: prev.empresas.map((item) =>
                  item.id === empresa.id
                    ? {
                        ...item,
                        professional_tier: atualizada.professional_tier,
                        max_professionals: atualizada.max_professionals,
                        profissionais_ativos: atualizada.profissionais_ativos,
                      }
                    : item,
                ),
              }
            : prev,
        );

        toast.success(
          `${nomeDaEmpresa(empresa)}: modalidade agora é ${atualizada.rotulo} (limite de ${numeroFormatado(
            atualizada.max_professionals,
          )}).`,
        );
      } catch (e) {
        if (exigeConfirmacao(e)) {
          // Redução de limite: NÃO é erro a mostrar em toast — é uma decisão
          // comercial que precisa de confirmação explícita.
          setConfirmacaoReducao({ empresa, mensagem: mensagemDeErro(e), tier });
          return;
        }
        if (statusDeErro(e) === 403) {
          setSemPermissao(true);
        }
        // 409 de excedente cai aqui: o backend já diz quantos profissionais
        // precisam sair e que nada foi alterado. Não há reenvio para oferecer.
        // O modal de redução, se estava aberto, fecha: o erro novo manda outra
        // ação e manter a confirmação na tela convidaria a repetir o fracasso.
        setConfirmacaoReducao(null);
        toast.error(mensagemDeErro(e));
      } finally {
        setSalvandoId(null);
      }
    },
    [],
  );

  const salvarLimiteRede = useCallback(async (empresa: EmpresaDaPlataforma, limite: number) => {
    setSalvandoLimiteRedeId(empresa.id);
    try {
      const atualizado = await adminPlataformaApi.atualizarLimiteUnidadesRede(empresa.id, limite);
      setPainel((prev) => prev ? {
        ...prev,
        empresas: prev.empresas.map((item) => item.id === empresa.id
          ? { ...item, network_unit_limit: atualizado.limite, network_units_used: atualizado.unidades_utilizadas }
          : item),
      } : prev);
      toast.success('Limite de unidades atualizado.');
    } catch (e) {
      toast.error(mensagemDeErro(e));
    } finally {
      setSalvandoLimiteRedeId(null);
    }
  }, []);

  const entrarNaEmpresa = useCallback(async (empresa: EmpresaDaPlataforma) => {
    setEntrando(true);
    try {
      const resposta = await adminPlataformaApi.entrar(empresa.id);
      setEmpresaParaEntrar(null);
      toast.success(resposta.message || `Contexto alterado para ${resposta.nome}.`);
      // O contexto mudou no servidor: até recarregar, todo o painel (menu,
      // empresa no topo, telas) continua mostrando a empresa anterior. O reload
      // é parte da operação, não enfeite.
      window.setTimeout(() => window.location.reload(), 600);
    } catch (e) {
      setEntrando(false);
      toast.error(mensagemDeErro(e));
    }
  }, []);

  /**
   * Clique na ação de configuração.
   *
   * O destino (`/company`, `/equipe`, `/company?tab=teams`) lê a empresa da
   * SESSÃO e não tem id na URL. Então:
   *   - empresa já é a atual: nada a trocar, navega direto pelo router (o
   *     contexto no cliente e no servidor já bate);
   *   - outra empresa: NÃO navega daqui. Abre a confirmação e só o `confirmar`
   *     troca o contexto e navega.
   * Trocar de contexto porque o usuário clicou em "Perfis de permissão" seria
   * efeito colateral silencioso: daqui em diante o painel inteiro é outro.
   */
  const pedirConfiguracao = useCallback(
    (empresa: EmpresaDaPlataforma, acao: AcaoDaEmpresa) => {
      if (empresa.empresa_atual) {
        navigate(acao.destino);
        return;
      }
      setAcaoPendente({ empresa, acao });
    },
    [navigate],
  );

  const abrirConfiguracao = useCallback(
    async (empresa: EmpresaDaPlataforma, acao: AcaoDaEmpresa) => {
      setAbrindoConfiguracao(true);
      try {
        await adminPlataformaApi.entrar(empresa.id);
        setAcaoPendente(null);
        // Navegação DURA, de propósito: empresa atual, permissões e dados de
        // várias telas vivem em localStorage e em estados já carregados. Pelo
        // router a tela de destino abriria no contexto antigo — com o título da
        // nova empresa e os dados da anterior, que é o erro que mente.
        window.location.href = acao.destino;
      } catch (e) {
        // A troca falhou: nada de navegar. O `detail` do backend é a mensagem,
        // e o modal fica aberto para o usuário tentar de novo.
        setAbrindoConfiguracao(false);
        toast.error(mensagemDeErro(e));
      }
    },
    [],
  );

  // ---------------------------------------------------------------------
  // Cobrança: ações
  // ---------------------------------------------------------------------
  /**
   * Abre/fecha a área do cartão. O GET da cobrança acontece na PRIMEIRA
   * abertura: uma chamada por empresa em toda visita seria carga sem uso, já
   * que a maioria dos cartões fica fechada.
   */
  const alternarCobranca = useCallback(
    (empresaId: number) => {
      setCobrancaAberta((prev) => ({ ...prev, [empresaId]: !prev[empresaId] }));
      if (!cobrancas[empresaId] && !carregandoCobranca[empresaId]) {
        void carregarCobranca(empresaId);
      }
    },
    [cobrancas, carregandoCobranca, carregarCobranca],
  );

  const salvarAssinatura = useCallback(
    async (empresaId: number, planoId: number, diaVencimento: number) => {
      setSalvandoAssinaturaId(empresaId);
      try {
        const dados = await cobrancaApi.definirAssinatura(empresaId, {
          plano_id: planoId,
          dia_vencimento: diaVencimento,
        });
        setCobrancas((prev) => ({ ...prev, [empresaId]: dados }));
        setErroCobranca((prev) => ({ ...prev, [empresaId]: null }));
        toast.success(
          dados.assinatura
            ? `${dados.company_nome}: ${dados.assinatura.plano_nome}, vencimento todo dia ${dados.assinatura.dia_vencimento}.`
            : `${dados.company_nome}: cobrança atualizada.`,
        );
      } catch (e) {
        // 409 de plano inativo vem com o motivo em `detail`: mostrar como veio.
        toast.error(mensagemDeErro(e));
      } finally {
        setSalvandoAssinaturaId(null);
      }
    },
    [],
  );

  const emitirFatura = useCallback(
    async (empresa: EmpresaDaPlataforma) => {
      setEmitindoId(empresa.id);
      // Competência explícita: o backend usaria o mês do servidor, que pode ser
      // outro na virada do mês (fuso). O rótulo do botão diz "do mês" — o que
      // foi criado tem que ser o que está escrito.
      const competencia = competenciaAtual();
      try {
        const fatura = await cobrancaApi.emitirFatura(empresa.id, { competencia });
        toast.success(
          `Fatura de ${rotuloCompetencia(fatura.competencia)} emitida para ${nomeDaEmpresa(empresa)} (${formatarPreco(
            fatura.valor_centavos,
          )}).`,
        );
        // O POST devolve só a fatura; os totais em aberto/pago vêm do GET.
        await carregarCobranca(empresa.id);
      } catch (e) {
        toast.error(mensagemDeErro(e));
      } finally {
        setEmitindoId(null);
      }
    },
    [carregarCobranca],
  );

  const atualizarFatura = useCallback(
    async (empresa: EmpresaDaPlataforma, fatura: Fatura, status: StatusFatura) => {
      setFaturaEmAndamentoId(fatura.id);
      try {
        const atualizada = await cobrancaApi.atualizarFatura(fatura.id, { status });
        toast.success(
          atualizada.status === 'paga'
            ? `Fatura de ${rotuloCompetencia(atualizada.competencia)} de ${nomeDaEmpresa(empresa)} marcada como paga.`
            : `Fatura de ${rotuloCompetencia(atualizada.competencia)} de ${nomeDaEmpresa(empresa)} reaberta.`,
        );
        await carregarCobranca(empresa.id);
      } catch (e) {
        toast.error(mensagemDeErro(e));
      } finally {
        setFaturaEmAndamentoId(null);
      }
    },
    [carregarCobranca],
  );

  const salvarPlano = useCallback(async (planoId: number, dados: PlanoAtualizacao) => {
    setSalvandoPlanoId(planoId);
    try {
      const atualizado = await cobrancaApi.atualizarPlano(planoId, dados);
      // Os cartões leem o preço desta lista: atualizar aqui já corrige o
      // "sem preço" do botão de emitir, sem um GET extra por empresa.
      setPlanos((prev) => prev.map((item) => (item.id === atualizado.id ? atualizado : item)));
      setErroPlanos(null);
      toast.success(
        `${atualizado.nome}: ${
          atualizado.preco_centavos === null ? 'preço removido' : formatarPreco(atualizado.preco_centavos)
        }${atualizado.ativo ? '' : ' · inativo'}.`,
      );
    } catch (e) {
      toast.error(mensagemDeErro(e));
    } finally {
      setSalvandoPlanoId(null);
    }
  }, []);

  const bloqueado = entrando || abrindoConfiguracao || salvandoId !== null;
  const empresas = painel?.empresas ?? [];

  return (
    <div className={agentivePageClass(isDark, 'px-4 py-6 sm:px-6')}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
        <AgentivePageHeader
          icon={Layers}
          title="Clientes da plataforma"
          description="Todos os clientes, com os números que decidem a modalidade. As ações de configuração abrem a tela do cliente no contexto dele; salvar a modalidade vale para a empresa da linha. Cada cartão abre a área de plano e cobrança, e os preços de cada plano ficam em Planos e preços."
          badges={
            painel ? (
              <span className={agentivePillClass(isDark, false)}>
                {numeroFormatado(painel.total_empresas)}{' '}
                {painel.total_empresas === 1 ? 'empresa' : 'empresas'}
              </span>
            ) : undefined
          }
          actions={
            <>
              <button
                type="button"
                onClick={() => setPlanosAbertos((prev) => !prev)}
                aria-expanded={planosAbertos}
                className={agentiveSecondaryButtonClass(isDark)}
                title="Preço de cada plano — sem preço definido, nenhuma fatura pode ser emitida"
              >
                <BadgeDollarSign className="h-4 w-4" />
                Planos e preços
              </button>
              <Link to="/new-company-admin" className={agentivePrimaryButtonClass()}>
                <Plus className="h-4 w-4" />
                Nova empresa cliente
              </Link>
              <button
                type="button"
                onClick={carregar}
                disabled={carregando}
                className={agentiveSecondaryButtonClass(isDark)}
              >
                <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
                Atualizar
              </button>
            </>
          }
        />

        {!semPermissao && (
          <PlanosPanel
            aberto={planosAbertos}
            carregando={carregandoPlanos}
            erro={erroPlanos}
            isDark={isDark}
            onAlternar={() => setPlanosAbertos((prev) => !prev)}
            onRecarregar={carregarPlanos}
            onSalvar={salvarPlano}
            planos={planos}
            salvandoId={salvandoPlanoId}
          />
        )}

        {carregando && !painel && (
          <div className={agentivePanelClass(isDark, 'p-5')}>
            <div className="flex items-center gap-3">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm font-medium">Carregando os clientes da plataforma</span>
            </div>
          </div>
        )}

        {semPermissao && (
          <AgentiveEmptyState
            icon={ShieldAlert}
            title="Sem permissão para ver a plataforma"
            description={`Esta tela lista todos os clientes e só o administrador da plataforma pode abri-la. Se você chegou aqui pela URL, nada foi alterado — volte ao painel.${
              motivoSemPermissao ? ` Resposta do servidor: ${motivoSemPermissao}` : ''
            }`}
            action={
              <Link to="/dashboard" className={agentiveSecondaryButtonClass(isDark)}>
                Voltar ao painel
              </Link>
            }
          />
        )}

        {!semPermissao && erro && (
          <AgentiveAlert variant="error" title="Não foi possível carregar os clientes">
            <p>{erro}</p>
            <button type="button" onClick={carregar} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
              <RefreshCw className="h-4 w-4" />
              Tentar novamente
            </button>
          </AgentiveAlert>
        )}

        {!semPermissao && !erro && !carregando && painel && empresas.length === 0 && (
          <AgentiveEmptyState
            icon={Building2}
            title="Nenhuma empresa cadastrada"
            description="A plataforma ainda não tem clientes para listar. Cadastre a primeira empresa cliente: ela aparece aqui, com as ações de configuração."
            action={
              <Link to="/new-company-admin" className={agentivePrimaryButtonClass()}>
                <Plus className="h-4 w-4" />
                Nova empresa cliente
              </Link>
            }
          />
        )}

        {!semPermissao && rascunhos.length > 0 && (
          <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold">Rascunhos de empresas</h2>
                <p className="mt-1 text-xs text-brand/55 dark:text-white/55">
                  Visíveis somente para administradores da plataforma.
                </p>
              </div>
              <span className={agentivePillClass(isDark, false)}>{rascunhos.length}</span>
            </div>
            <div className="mt-3 grid gap-2">
              {rascunhos.map((draft) => (
                <button
                  key={draft.id}
                  type="button"
                  onClick={() => navigate(`/new-company-admin?draftId=${draft.id}`)}
                  className={`flex items-center justify-between rounded-xl border px-3 py-2 text-left text-sm ${
                    isDark ? 'border-white/10 hover:bg-white/5' : 'border-brand/10 hover:bg-brand-canvas'
                  }`}
                >
                  <span>{draft.payload.trade_name || draft.payload.legal_name || `Rascunho #${draft.id}`}</span>
                  <span className="text-xs opacity-60">Editar rascunho #{draft.id}</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {!semPermissao && !erro && empresas.length > 0 && (
          <div className="flex flex-col gap-4">
            {empresas.map((empresa) => (
              <EmpresaCard
                key={empresa.id}
                empresa={empresa}
                isDark={isDark}
                selecao={selecoes[empresa.id] ?? ''}
                salvando={salvandoId === empresa.id}
                bloqueado={bloqueado}
                areaCobranca={
                  <CobrancaEmpresaPanel
                    aberto={Boolean(cobrancaAberta[empresa.id])}
                    bloqueado={bloqueado}
                    carregando={Boolean(carregandoCobranca[empresa.id])}
                    cobranca={cobrancas[empresa.id] ?? null}
                    empresaNome={nomeDaEmpresa(empresa)}
                    emitindo={emitindoId === empresa.id}
                    erro={erroCobranca[empresa.id] ?? null}
                    faturaEmAndamento={faturaEmAndamentoId}
                    isDark={isDark}
                    onAlternar={() => alternarCobranca(empresa.id)}
                    onAtualizarFatura={(fatura, status) => atualizarFatura(empresa, fatura, status)}
                    onEmitir={() => emitirFatura(empresa)}
                    onRecarregar={() => carregarCobranca(empresa.id)}
                    onSalvarAssinatura={(planoId, diaVencimento) =>
                      salvarAssinatura(empresa.id, planoId, diaVencimento)
                    }
                    planos={planos}
                    salvando={salvandoAssinaturaId === empresa.id}
                  />
                }
                onEscolher={(tier) => setSelecoes((prev) => ({ ...prev, [empresa.id]: tier }))}
                onSalvar={() => {
                  const tier = selecoes[empresa.id];
                  if (tier) salvarModalidade(empresa, tier);
                }}
                onSalvarLimiteRede={(limite) => salvarLimiteRede(empresa, limite)}
                salvandoLimiteRede={salvandoLimiteRedeId === empresa.id}
                onEntrar={() => setEmpresaParaEntrar(empresa)}
                onAbrirConfiguracao={(acao) => pedirConfiguracao(empresa, acao)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Confirmação de troca de contexto */}
      <AgentiveConfirmModal
        isOpen={Boolean(empresaParaEntrar)}
        title="Trocar o contexto da sessão?"
        variant="warning"
        confirmText="Entrar nesta empresa"
        cancelText="Cancelar"
        isLoading={entrando}
        message={
          empresaParaEntrar ? (
            <>
              A sessão passa a apontar para <strong>{nomeDaEmpresa(empresaParaEntrar)}</strong>. O painel
              recarrega para mostrar os dados desta empresa e você deixa de ver os da empresa em que está
              agora. Nada é alterado em nenhuma das duas.
            </>
          ) : (
            ''
          )
        }
        onClose={() => {
          if (!entrando) setEmpresaParaEntrar(null);
        }}
        onConfirm={() => {
          if (empresaParaEntrar) entrarNaEmpresa(empresaParaEntrar);
        }}
      />

      {/* Confirmação de troca de contexto ao abrir a configuração do cliente */}
      <AgentiveConfirmModal
        isOpen={Boolean(acaoPendente)}
        title="Abrir a configuração desta empresa?"
        variant="warning"
        confirmText="Trocar contexto e abrir"
        cancelText="Cancelar"
        isLoading={abrindoConfiguracao}
        message={
          acaoPendente ? (
            <>
              Para abrir <strong>{acaoPendente.acao.rotulo}</strong> de{' '}
              <strong>{nomeDaEmpresa(acaoPendente.empresa)}</strong>, a sessão passa a apontar para esta
              empresa — a tela de destino lê a empresa da sessão, não um id na URL. O painel então carrega em{' '}
              <code className="text-xs">{acaoPendente.acao.destino}</code>. Nada é alterado em nenhuma das duas
              empresas, e você volta para a atual pelo próprio painel de Clientes da plataforma.
            </>
          ) : (
            ''
          )
        }
        onClose={() => {
          if (!abrindoConfiguracao) setAcaoPendente(null);
        }}
        onConfirm={() => {
          if (acaoPendente) abrirConfiguracao(acaoPendente.empresa, acaoPendente.acao);
        }}
      />

      {/* Confirmação de redução de limite (o 409 que pede confirmar=true) */}
      <AgentiveConfirmModal
        isOpen={Boolean(confirmacaoReducao)}
        title="Reduzir o limite de profissionais?"
        variant="warning"
        confirmText="Salvar mesmo assim"
        cancelText="Cancelar"
        isLoading={Boolean(confirmacaoReducao && salvandoId === confirmacaoReducao.empresa.id)}
        message={
          confirmacaoReducao ? (
            <>
              Reduzir a modalidade é uma decisão comercial: a partir de agora a empresa{' '}
              <strong>{nomeDaEmpresa(confirmacaoReducao.empresa)}</strong> não aceita novos profissionais
              acima do novo limite. Nada foi alterado ainda.
            </>
          ) : (
            ''
          )
        }
        onClose={() => {
          if (salvandoId === null) setConfirmacaoReducao(null);
        }}
        onConfirm={() => {
          if (confirmacaoReducao) {
            salvarModalidade(confirmacaoReducao.empresa, confirmacaoReducao.tier, true);
          }
        }}
      >
        {confirmacaoReducao ? <p>{confirmacaoReducao.mensagem}</p> : null}
      </AgentiveConfirmModal>
    </div>
  );
};

export default Plataforma;
