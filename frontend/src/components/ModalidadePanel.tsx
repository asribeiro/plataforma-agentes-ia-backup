import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Building2, Info, Loader2, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  agentivePillClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import { empresaApi, mensagemDeErro, type Modalidade, type ModalidadeClinica } from '../services/clinicApi.ts';

interface ModalidadePanelProps {
  /** Versão de uma linha, para telas onde o limite só precisa estar visível. */
  compact?: boolean;
  /** Notifica quem renderiza (a tela de Profissionais usa pode_adicionar). */
  onDados?: (modalidade: ModalidadeClinica) => void;
}

/**
 * Modalidade da clínica.
 *
 * A modalidade é a faixa comercial vendida. Quem altera é o administrador da
 * plataforma: `PUT /api/company/flag` responde 403 para o cliente. A tela NÃO
 * decide isso sozinha — lê `pode_editar` da resposta e só mostra o seletor quando
 * o servidor autoriza. Antes ela ignorava esse campo e negava na tela uma
 * permissão que o backend concedia.
 *
 * Reduzir o limite tem dois 409 diferentes, e a tela não tenta adivinhar: pedido
 * de confirmação (reenvia com confirmar=true depois do modal) e rebaixamento
 * barrado por profissionais ativos (mostra o texto do backend).
 */
const ModalidadePanel: React.FC<ModalidadePanelProps> = ({ compact = false, onDados }) => {
  const { isDark } = useTheme();
  const [modalidade, setModalidade] = useState<ModalidadeClinica | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [tierEscolhido, setTierEscolhido] = useState<Modalidade | ''>('');
  const [salvando, setSalvando] = useState(false);
  const [erroSalvar, setErroSalvar] = useState<string | null>(null);
  const [confirmacao, setConfirmacao] = useState<string | null>(null);

  const dadosRef = useRef(onDados);
  useEffect(() => {
    dadosRef.current = onDados;
  }, [onDados]);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      const dados = await empresaApi.lerModalidade();
      setModalidade(dados);
      dadosRef.current?.(dados);
    } catch (e) {
      setModalidade(null);
      setErro(mensagemDeErro(e));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  // O seletor acompanha a modalidade real: se a leitura mudar (outra aba, refresh),
  // o campo não fica mostrando a faixa antiga.
  useEffect(() => {
    setTierEscolhido(modalidade ? (modalidade.professional_tier as Modalidade) : '');
  }, [modalidade]);

  const aplicar = useCallback(async (tier: Modalidade, confirmar: boolean) => {
    setSalvando(true);
    setErroSalvar(null);
    try {
      const dados = await empresaApi.definirModalidade(tier, confirmar);
      setModalidade(dados);
      dadosRef.current?.(dados);
      setConfirmacao(null);
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      const texto = mensagemDeErro(e);
      // 409 de confirmação: mostramos o texto do backend e deixamos ele decidir.
      if (status === 409 && /confirmar/i.test(texto)) {
        setConfirmacao(texto);
      } else {
        setConfirmacao(null);
        setErroSalvar(texto);
      }
    } finally {
      setSalvando(false);
    }
  }, []);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const borderClass = isDark ? 'border-white/10' : 'border-brand/10';

  if (carregando) {
    return (
      <div className={agentivePanelClass(isDark, 'p-5')}>
        <div className="flex items-center gap-3">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-sm font-medium">Carregando modalidade da clínica</span>
        </div>
      </div>
    );
  }

  if (erro) {
    return (
      <AgentiveAlert variant="error" title="Não foi possível ler a modalidade da clínica">
        <p>{erro}</p>
        <button type="button" onClick={carregar} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
          <RefreshCw className="h-4 w-4" />
          Tentar novamente
        </button>
      </AgentiveAlert>
    );
  }

  if (!modalidade) return null;

  const { rotulo, max_professionals, profissionais_ativos, pode_adicionar, pode_editar, orientacao } = modalidade;
  const ocupacao = max_professionals > 0 ? Math.min(100, Math.round((profissionais_ativos / max_professionals) * 100)) : 0;

  if (compact) {
    return (
      <div className={agentivePanelClass(isDark, 'p-4')}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10' : 'bg-brand-canvas'}`}>
              <Building2 className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold">Modalidade: {rotulo}</p>
                <span className={agentivePillClass(isDark, false)}>somente leitura</span>
              </div>
              <p className={`mt-1 text-xs ${mutedClass}`}>
                {profissionais_ativos} de {max_professionals} profissionais ativos ·{' '}
                {pode_adicionar ? 'há vaga disponível' : 'limite da modalidade atingido'}
              </p>
            </div>
          </div>
          <p className={`max-w-sm text-xs leading-relaxed ${mutedClass}`}>
            A modalidade é definida pelo administrador da plataforma.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={agentivePanelClass(isDark, 'p-5')}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
            <Building2 className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">Modalidade da clínica</h2>
              <span className={agentivePillClass(isDark, false)}>
                <ShieldCheck className="h-3.5 w-3.5" />
                {pode_editar ? 'você pode alterar' : 'somente leitura'}
              </span>
            </div>
            <p className={`mt-1 text-sm ${mutedClass}`}>{rotulo}</p>
          </div>
        </div>
      </div>

      <div className={`mt-5 grid gap-4 rounded-2xl border p-4 sm:grid-cols-3 ${borderClass} ${isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}`}>
        <div>
          <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Limite</p>
          <p className="mt-1 text-sm font-semibold">
            {max_professionals} {max_professionals === 1 ? 'profissional' : 'profissionais'}
          </p>
        </div>
        <div>
          <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Profissionais ativos</p>
          <p className="mt-1 flex items-center gap-1.5 text-sm font-semibold">
            <Users className="h-4 w-4" />
            {profissionais_ativos} de {max_professionals}
          </p>
        </div>
        <div>
          <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Situação</p>
          <p className="mt-1 text-sm font-semibold">
            {pode_adicionar ? 'Há vaga para novo profissional' : 'Limite atingido'}
          </p>
        </div>
      </div>

      <div className="mt-4">
        <div className={`mb-2 flex justify-between text-xs ${mutedClass}`}>
          <span>Ocupação da modalidade</span>
          <span className="font-semibold">{ocupacao}%</span>
        </div>
        <div className={`h-2 overflow-hidden rounded-full ${isDark ? 'bg-white/10' : 'bg-brand/10'}`}>
          <div
            className={`h-full rounded-full ${pode_adicionar ? 'bg-emerald-500' : 'bg-amber-500'}`}
            style={{ width: `${ocupacao}%` }}
          />
        </div>
      </div>

      <div className={`mt-4 flex items-start gap-2 rounded-xl border p-3 text-sm ${borderClass} ${isDark ? 'bg-white/[0.04] text-white/70' : 'bg-brand-canvas text-brand/70'}`}>
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="leading-relaxed">{orientacao}</p>
      </div>

      {pode_editar ? (
        <div className={`mt-5 rounded-2xl border p-4 ${borderClass} ${isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}`}>
          <p className="text-sm font-semibold">Definir modalidade</p>
          <p className={`mt-1 text-xs leading-relaxed ${mutedClass}`}>
            Vale para esta empresa e muda o teto de profissionais ativos. Reduzir o limite pode
            pedir confirmação — o sistema avisa antes de aplicar.
          </p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1">
              <span className={`block text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
                Modalidade
              </span>
              <select
                value={tierEscolhido}
                onChange={(e) => setTierEscolhido(e.target.value as Modalidade)}
                disabled={salvando}
                className={`mt-1 w-full rounded-xl border px-3 py-2 text-sm ${borderClass} ${isDark ? 'bg-transparent text-white' : 'bg-white text-brand'}`}
              >
                <option value="mono">Monoprofissional — 1 profissional</option>
                <option value="up_to_4">Até 4 profissionais</option>
                <option value="up_to_10">Até 10 profissionais</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => tierEscolhido && aplicar(tierEscolhido, false)}
              disabled={salvando || !tierEscolhido}
              className={agentivePrimaryButtonClass()}
            >
              {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Salvar modalidade
            </button>
          </div>
          {erroSalvar ? (
            <p className="mt-2 text-xs font-medium text-red-600 dark:text-red-400">{erroSalvar}</p>
          ) : null}
        </div>
      ) : (
        <p className={`mt-4 text-xs leading-relaxed ${mutedClass}`}>
          A modalidade é definida pelo administrador da plataforma. Para mudar de modalidade, fale
          com o suporte da plataforma.
        </p>
      )}

      <AgentiveConfirmModal
        isOpen={confirmacao !== null}
        title="Confirmar mudança de modalidade"
        message={confirmacao ?? ''}
        confirmText="Aplicar"
        cancelText="Cancelar"
        variant="warning"
        isLoading={salvando}
        onClose={() => setConfirmacao(null)}
        onConfirm={() => tierEscolhido && aplicar(tierEscolhido, true)}
      />
    </div>
  );
};

export default ModalidadePanel;
