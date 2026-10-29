import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Building2, Info, Loader2, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  agentivePillClass,
  agentivePanelClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import { empresaApi, mensagemDeErro, type ModalidadeClinica } from '../services/clinicApi.ts';

interface ModalidadePanelProps {
  /** Versão de uma linha, para telas onde o limite só precisa estar visível. */
  compact?: boolean;
  /** Notifica quem renderiza (a tela de Profissionais usa pode_adicionar). */
  onDados?: (modalidade: ModalidadeClinica) => void;
}

/**
 * Modalidade da clínica — SOMENTE LEITURA.
 *
 * A modalidade é a faixa comercial vendida: quem altera é o administrador da
 * plataforma (PUT /api/company/flag responde 403 para o cliente). A tela mostra
 * rótulo, limite, quantos profissionais ativos existem e a orientação de uso;
 * nunca oferece edição, mesmo quando `pode_editar` vem true — nesse caso apenas
 * informa onde a alteração acontece.
 */
const ModalidadePanel: React.FC<ModalidadePanelProps> = ({ compact = false, onDados }) => {
  const { isDark } = useTheme();
  const [modalidade, setModalidade] = useState<ModalidadeClinica | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

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
                somente leitura
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

      <p className={`mt-4 text-xs leading-relaxed ${mutedClass}`}>
        A modalidade é definida pelo administrador da plataforma e não pode ser alterada por aqui.
        {pode_editar
          ? ' Esta conta tem permissão administrativa: a troca é feita no painel da plataforma.'
          : ' Para mudar de modalidade, fale com o suporte da plataforma.'}
      </p>
    </div>
  );
};

export default ModalidadePanel;
