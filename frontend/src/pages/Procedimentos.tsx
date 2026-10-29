import { useCallback, useEffect, useMemo, useState } from 'react';
import { ClipboardList, Loader2, Pencil, Plus, Power, RefreshCw, X } from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  agentiveIconButtonClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import {
  Procedimento,
  ProcedimentoEntrada,
  formatarDuracao,
  formatarPreco,
  mensagemDeErro,
  procedimentosApi,
} from '../services/clinicApi.ts';

const VAZIO: ProcedimentoEntrada = {
  name: '',
  duration_minutes: 30,
  price_cents: null,
  is_evaluation: false,
};

/**
 * Tela de procedimentos da clínica.
 *
 * Sempre disponível, nas duas configurações de clínica: a flag de múltiplos
 * profissionais controla QUEM executa, nunca O QUE a clínica oferece. Uma
 * clínica de um dentista só precisa do catálogo para o agente conseguir
 * responder "vocês fazem clareamento?".
 */
export default function Procedimentos() {
  const { isDark } = useTheme();
  const [itens, setItens] = useState<Procedimento[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [editando, setEditando] = useState<Procedimento | null>(null);
  const [form, setForm] = useState<ProcedimentoEntrada>(VAZIO);
  const [mostrarInativos, setMostrarInativos] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setItens(await procedimentosApi.listar(mostrarInativos));
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setCarregando(false);
    }
  }, [mostrarInativos]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const emEdicao = editando !== null;
  const podeSalvar = useMemo(
    () => form.name.trim().length >= 2 && form.duration_minutes >= 5 && !salvando,
    [form, salvando],
  );

  function abrirNovo() {
    setEditando(null);
    setForm(VAZIO);
  }

  function abrirEdicao(p: Procedimento) {
    setEditando(p);
    setForm({
      name: p.name,
      duration_minutes: p.duration_minutes,
      price_cents: p.price_cents,
      is_evaluation: p.is_evaluation,
    });
  }

  async function salvar() {
    if (!podeSalvar) return;
    setSalvando(true);
    try {
      const preco =
        form.price_cents === null || Number.isNaN(form.price_cents)
          ? null
          : Math.round(form.price_cents);

      if (emEdicao && editando) {
        const atualizado = await procedimentosApi.atualizar(editando.id, {
          name: form.name.trim(),
          duration_minutes: form.duration_minutes,
          price_cents: preco,
          is_evaluation: form.is_evaluation,
        });
        setItens((antes) => antes.map((i) => (i.id === atualizado.id ? atualizado : i)));
        toast.success('Procedimento atualizado');
      } else {
        const criado = await procedimentosApi.criar({
          name: form.name.trim(),
          duration_minutes: form.duration_minutes,
          price_cents: preco,
          is_evaluation: form.is_evaluation,
        });
        setItens((antes) => [...antes, criado]);
        toast.success('Procedimento cadastrado');
      }
      setEditando(null);
      setForm(VAZIO);
    } catch (e) {
      toast.error(mensagemDeErro(e));
    } finally {
      setSalvando(false);
    }
  }

  async function alternarAtivo(p: Procedimento) {
    if (p.active) {
      const confirmar = window.confirm(
        `Desativar "${p.name}"?\n\nO histórico é preservado: ele deixa de aparecer ` +
          'nas opções novas, mas agendamentos antigos continuam válidos.',
      );
      if (!confirmar) return;
    }
    try {
      if (p.active) {
        await procedimentosApi.desativar(p.id);
        setItens((antes) =>
          mostrarInativos
            ? antes.map((i) => (i.id === p.id ? { ...i, active: false } : i))
            : antes.filter((i) => i.id !== p.id),
        );
        toast.success('Procedimento desativado');
      } else {
        const reativado = await procedimentosApi.atualizar(p.id, { active: true });
        setItens((antes) => antes.map((i) => (i.id === p.id ? reativado : i)));
        toast.success('Procedimento reativado');
      }
    } catch (e) {
      toast.error(mensagemDeErro(e));
    }
  }

  return (
    <div className={agentivePageClass(isDark)}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
            <ClipboardList className="h-6 w-6" style={{ color: '#E63946' }} />
            Procedimentos
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            O que a clínica oferece. O agente usa esta lista para identificar o que o
            paciente procura. A duração define quanto tempo reservar na agenda.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={agentiveSecondaryButtonClass(isDark)}
            onClick={() => setMostrarInativos((v) => !v)}
          >
            {mostrarInativos ? 'Ocultar inativos' : 'Mostrar inativos'}
          </button>
          <button
            type="button"
            className={agentiveSecondaryButtonClass(isDark)}
            onClick={() => void carregar()}
            disabled={carregando}
          >
            <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
          </button>
          <button type="button" className={agentivePrimaryButtonClass()} onClick={abrirNovo}>
            <Plus className="h-4 w-4" /> Novo procedimento
          </button>
        </div>
      </div>

      {erro && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {erro}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <section className={agentivePanelClass(isDark)}>
          {carregando ? (
            <div className="flex items-center gap-2 px-4 py-10 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Carregando procedimentos…
            </div>
          ) : itens.length === 0 ? (
            <div className="px-4 py-12 text-center">
              <ClipboardList className="mx-auto h-10 w-10 text-slate-300" />
              <p className="mt-3 text-sm font-medium text-slate-700">
                Nenhum procedimento cadastrado
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Cadastre ao menos a avaliação inicial. Sem catálogo, o agente não tem como
                identificar o que o paciente precisa.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {itens.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`truncate font-medium ${
                          p.active ? 'text-slate-900' : 'text-slate-400 line-through'
                        }`}
                      >
                        {p.name}
                      </span>
                      {p.is_evaluation && (
                        <span className={`${agentivePillClass(isDark)} bg-amber-50 text-amber-800`}>
                          avaliação
                        </span>
                      )}
                      {!p.active && (
                        <span className={`${agentivePillClass(isDark)} bg-slate-100 text-slate-600`}>
                          inativo
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                      <span>{formatarDuracao(p.duration_minutes)}</span>
                      <span>{formatarPreco(p.price_cents)}</span>
                      <span>
                        {p.professionals === 0
                          ? 'nenhum profissional vinculado'
                          : `${p.professionals} profissional(is)`}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className={agentiveIconButtonClass(isDark)}
                    title="Editar"
                    onClick={() => abrirEdicao(p)}
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className={agentiveIconButtonClass(isDark)}
                    title={p.active ? 'Desativar' : 'Reativar'}
                    onClick={() => void alternarAtivo(p)}
                  >
                    <Power className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className={agentivePanelClass(isDark)}>
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-900">
              {emEdicao ? 'Editar procedimento' : 'Novo procedimento'}
            </h2>
            {emEdicao && (
              <button
                type="button"
                className={agentiveIconButtonClass(isDark)}
                title="Cancelar"
                onClick={abrirNovo}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          <div className="space-y-4 px-4 py-4">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-700">Nome</span>
              <input
                type="text"
                value={form.name}
                maxLength={160}
                placeholder="Ex.: Limpeza, Restauração, Clareamento"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-700">
                Duração (minutos)
              </span>
              <input
                type="number"
                min={5}
                max={600}
                step={5}
                value={form.duration_minutes}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                onChange={(e) =>
                  setForm((f) => ({ ...f, duration_minutes: Number(e.target.value) }))
                }
              />
              <span className="mt-1 block text-xs text-slate-500">
                É o tempo reservado na agenda, não o tempo de conversa.
              </span>
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-700">
                Preço em centavos (opcional)
              </span>
              <input
                type="number"
                min={0}
                step={100}
                value={form.price_cents ?? ''}
                placeholder="Deixe vazio para não informar"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    price_cents: e.target.value === '' ? null : Number(e.target.value),
                  }))
                }
              />
              <span className="mt-1 block text-xs text-slate-500">
                {form.price_cents ? formatarPreco(form.price_cents) : 'Sem preço: o agente não cita valor'}
              </span>
            </label>

            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={Boolean(form.is_evaluation)}
                className="mt-0.5"
                onChange={(e) => setForm((f) => ({ ...f, is_evaluation: e.target.checked }))}
              />
              <span className="text-xs text-slate-700">
                É a avaliação inicial
                <span className="mt-0.5 block text-slate-500">
                  A primeira consulta é sempre diagnóstico. Marcar aqui faz o agente
                  oferecê-la antes do procedimento.
                </span>
              </span>
            </label>

            <button
              type="button"
              className={`${agentivePrimaryButtonClass()} w-full justify-center`}
              disabled={!podeSalvar}
              onClick={() => void salvar()}
            >
              {salvando ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : emEdicao ? (
                'Salvar alterações'
              ) : (
                'Cadastrar'
              )}
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}
