/**
 * Painel da plataforma — todos os clientes do admin master.
 *
 * O produto tinha uma tela só para a empresa do login (`/company`). O dono da
 * plataforma não tinha onde ver os OUTROS clientes, nem como trocar o plano de
 * quem não é ele. `/customers` não serve: ali é a carteira de pacientes/faturas
 * do workspace, não a lista de empresas.
 *
 * Duas ações, de naturezas diferentes:
 *   - "Entrar nesta empresa" muda o CONTEXTO DA SESSÃO no servidor. Depois disso
 *     todo o painel continua lendo a empresa antiga até recarregar — por isso o
 *     `window.location.reload()`. Sem o reload a tela mente.
 *   - "Salvar modalidade" mexe no limite de profissionais de OUTRA empresa sem
 *     sair desta. Os erros vêm prontos do backend (409/422) e são mostrados como
 *     vieram: reescrever a regra aqui é como as duas versões divergem.
 *
 * Dois 409 pedem coisas opostas e a tela os separa pelo texto:
 *   - excedente de profissionais ativos -> não há confirmação possível; a ação é
 *     desativar profissionais antes;
 *   - redução de limite -> confirmação explícita em modal e reenvio com
 *     `confirmar: true`.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Building2,
  Calendar,
  CalendarCheck,
  Layers,
  Loader2,
  LogIn,
  RefreshCw,
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
  bloqueado: boolean;
  empresa: EmpresaDaPlataforma;
  isDark: boolean;
  onEntrar: () => void;
  onEscolher: (tier: ModalidadeTier | '') => void;
  onSalvar: () => void;
  salvando: boolean;
  selecao: ModalidadeTier | '';
}

const EmpresaCard: React.FC<EmpresaCardProps> = ({
  bloqueado,
  empresa,
  isDark,
  onEntrar,
  onEscolher,
  onSalvar,
  salvando,
  selecao,
}) => {
  const nome = nomeDaEmpresa(empresa);
  const cnpj = formatarCnpj(empresa.cnpj);
  const tierAtual = tierValido(empresa.professional_tier);
  const mudou = selecao !== '' && selecao !== tierAtual;
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
              limite de {numeroFormatado(empresa.max_professionals)}{' '}
              {empresa.max_professionals === 1 ? 'profissional' : 'profissionais'}
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
    </section>
  );
};

// --------------------------------------------------------------------------
// Tela
// --------------------------------------------------------------------------
const Plataforma: React.FC = () => {
  const { isDark } = useTheme();

  const [painel, setPainel] = useState<PainelPlataforma | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [semPermissao, setSemPermissao] = useState(false);
  const [motivoSemPermissao, setMotivoSemPermissao] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  /** Seleção de modalidade por empresa (ainda não salva). */
  const [selecoes, setSelecoes] = useState<Record<number, ModalidadeTier | ''>>({});
  const [salvandoId, setSalvandoId] = useState<number | null>(null);

  const [empresaParaEntrar, setEmpresaParaEntrar] = useState<EmpresaDaPlataforma | null>(null);
  const [entrando, setEntrando] = useState(false);

  const [confirmacaoReducao, setConfirmacaoReducao] = useState<{
    empresa: EmpresaDaPlataforma;
    mensagem: string;
    tier: ModalidadeTier;
  } | null>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    setSemPermissao(false);
    setMotivoSemPermissao(null);
    try {
      const dados = await adminPlataformaApi.listarEmpresas();
      setPainel(dados);
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
  }, []);

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

  const bloqueado = entrando || salvandoId !== null;
  const empresas = painel?.empresas ?? [];

  return (
    <div className={agentivePageClass(isDark, 'px-4 py-6 sm:px-6')}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
        <AgentivePageHeader
          icon={Layers}
          title="Clientes da plataforma"
          description="Todos os clientes, com os números que decidem a modalidade. Entrar em uma empresa troca o contexto da sua sessão; salvar a modalidade vale para a empresa da linha."
          badges={
            painel ? (
              <span className={agentivePillClass(isDark, false)}>
                {numeroFormatado(painel.total_empresas)}{' '}
                {painel.total_empresas === 1 ? 'empresa' : 'empresas'}
              </span>
            ) : undefined
          }
          actions={
            <button
              type="button"
              onClick={carregar}
              disabled={carregando}
              className={agentiveSecondaryButtonClass(isDark)}
            >
              <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
              Atualizar
            </button>
          }
        />

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
            description="A plataforma ainda não tem clientes para listar. Quando a primeira empresa existir, ela aparece aqui."
          />
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
                onEscolher={(tier) => setSelecoes((prev) => ({ ...prev, [empresa.id]: tier }))}
                onSalvar={() => {
                  const tier = selecoes[empresa.id];
                  if (tier) salvarModalidade(empresa, tier);
                }}
                onEntrar={() => setEmpresaParaEntrar(empresa)}
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
