import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  CheckCircle2,
  Clock,
  DollarSign,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  Users,
  Wallet,
} from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import ClinicaModal from '../components/ClinicaModal.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  AgentivePageHeader,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import {
  formatarDuracao,
  formatarPreco,
  mensagemDeErro,
  procedimentosApi,
  type Procedimento,
  type ProcedimentoEntrada,
} from '../services/clinicApi.ts';

// ---------------------------------------------------------------------------
// Preço: texto em reais <-> centavos inteiros (é o que a API guarda)
// ---------------------------------------------------------------------------
// União simples (não discriminada) porque o projeto usa `strict: false`:
// com strictNullChecks desligado o TypeScript não estreita união por booleano.
interface PrecoLido {
  ok: boolean;
  centavos: number | null;
  erro?: string;
}

const centavosParaTexto = (centavos: number | null): string =>
  centavos === null || centavos === undefined ? '' : (centavos / 100).toFixed(2).replace('.', ',');

/**
 * Aceita "250", "250,00", "250.00", "R$ 250,00" e "1.500,00".
 * Vazio significa "sem preço" — o agente então não cita valor nenhum.
 */
function lerPreco(texto: string): PrecoLido {
  const bruto = texto.replace(/R\$/gi, '').replace(/\s/g, '').trim();
  if (!bruto) return { ok: true, centavos: null };

  let normalizado: string;
  if (bruto.includes(',')) {
    normalizado = bruto.replace(/\./g, '').replace(',', '.');
  } else if (/^\d{1,3}(\.\d{3})+$/.test(bruto)) {
    normalizado = bruto.replace(/\./g, ''); // 1.500 = mil e quinhentos
  } else {
    normalizado = bruto;
  }

  if (!/^\d+(\.\d{1,2})?$/.test(normalizado)) {
    return { ok: false, centavos: null, erro: 'Preço inválido. Use apenas números, por exemplo 250,00.' };
  }

  const valor = Number(normalizado);
  if (!Number.isFinite(valor) || valor < 0) {
    return { ok: false, centavos: null, erro: 'Preço inválido: informe um valor maior ou igual a zero.' };
  }
  if (valor > 1_000_000) {
    return { ok: false, centavos: null, erro: 'Preço acima do limite aceito (R$ 1.000.000,00).' };
  }

  return { ok: true, centavos: Math.round(valor * 100) };
}

// ---------------------------------------------------------------------------
// Formulário
// ---------------------------------------------------------------------------
interface FormState {
  nome: string;
  duracao: string;
  preco: string;
  avaliacao: boolean;
}

const formVazio: FormState = { nome: '', duracao: '30', preco: '', avaliacao: false };

const Procedimentos: React.FC = () => {
  const { isDark } = useTheme();

  const [procedimentos, setProcedimentos] = useState<Procedimento[]>([]);
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState<Procedimento | null>(null);
  const [form, setForm] = useState<FormState>(formVazio);
  const [erroForm, setErroForm] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  const [alvoDesativar, setAlvoDesativar] = useState<Procedimento | null>(null);
  const [processando, setProcessando] = useState(false);
  const [reativandoId, setReativandoId] = useState<number | null>(null);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const borderClass = isDark ? 'border-white/10' : 'border-brand/10';

  // Sempre traz ativos E inativos e filtra no cliente: com o filtro no servidor,
  // uma clínica cujos procedimentos estão todos desativados via "Nenhum
  // procedimento cadastrado" e tende a recadastrar o que já existe.
  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      const lista = await procedimentosApi.listar(true);
      setProcedimentos(lista);
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const ativos = useMemo(() => procedimentos.filter((p) => p.active), [procedimentos]);
  const inativos = useMemo(() => procedimentos.filter((p) => !p.active), [procedimentos]);
  const visiveis = useMemo(() => (incluirInativos ? procedimentos : ativos), [incluirInativos, procedimentos, ativos]);
  const avaliacao = useMemo(() => ativos.find((p) => p.is_evaluation) ?? null, [ativos]);

  const abrirNovo = () => {
    setEditando(null);
    setForm(formVazio);
    setErroForm(null);
    setModalAberto(true);
  };

  const abrirEdicao = (procedimento: Procedimento) => {
    setEditando(procedimento);
    setForm({
      nome: procedimento.name,
      duracao: String(procedimento.duration_minutes),
      preco: centavosParaTexto(procedimento.price_cents),
      avaliacao: procedimento.is_evaluation,
    });
    setErroForm(null);
    setModalAberto(true);
  };

  const fecharModal = () => {
    if (salvando) return;
    setModalAberto(false);
    setErroForm(null);
  };

  const salvar = async (evento: React.FormEvent) => {
    evento.preventDefault();
    setErroForm(null);

    const nome = form.nome.trim();
    if (nome.length < 2) {
      setErroForm('Informe o nome do procedimento (mínimo 2 caracteres).');
      return;
    }

    const duracao = Number(form.duracao.replace(',', '.').trim());
    if (!Number.isInteger(duracao) || duracao < 5 || duracao > 600) {
      setErroForm('A duração deve ser um número inteiro de minutos entre 5 e 600.');
      return;
    }

    const preco = lerPreco(form.preco);
    if (!preco.ok) {
      setErroForm(preco.erro ?? 'Preço inválido.');
      return;
    }

    // Campo vazio -> price_cents null -> o preço é APAGADO. O backend aplica
    // isso de verdade desde backend/utils/patch_utils.py, que distingue "campo
    // não enviado" de "campo enviado como null". Antes o null era ignorado e
    // esta tela precisava bloquear a remoção para não mentir ao usuário.

    const dados: ProcedimentoEntrada = {
      name: nome,
      duration_minutes: duracao,
      price_cents: preco.centavos,
      is_evaluation: form.avaliacao,
    };

    setSalvando(true);
    try {
      if (editando) {
        const atualizado = await procedimentosApi.atualizar(editando.id, dados);
        const mensagem = `Procedimento "${atualizado.name}" atualizado.`;
        setAviso(mensagem);
        toast.success(mensagem);
      } else {
        const criado = await procedimentosApi.criar(dados);
        const mensagem = `Procedimento "${criado.name}" cadastrado.`;
        setAviso(mensagem);
        toast.success(mensagem);
      }
      setModalAberto(false);
      await carregar();
    } catch (e) {
      // 409/422 vêm com texto escrito para o usuário final — mostrar como veio.
      setErroForm(mensagemDeErro(e));
    } finally {
      setSalvando(false);
    }
  };

  const desativar = async () => {
    if (!alvoDesativar) return;
    setProcessando(true);
    try {
      await procedimentosApi.desativar(alvoDesativar.id);
      const mensagem = `Procedimento "${alvoDesativar.name}" desativado. O histórico é preservado.`;
      setAviso(mensagem);
      toast.success(mensagem);
      setAlvoDesativar(null);
      await carregar();
    } catch (e) {
      setErro(mensagemDeErro(e));
      toast.error(mensagemDeErro(e));
    } finally {
      setProcessando(false);
    }
  };

  const reativar = async (procedimento: Procedimento) => {
    setReativandoId(procedimento.id);
    try {
      await procedimentosApi.atualizar(procedimento.id, { active: true });
      const mensagem = `Procedimento "${procedimento.name}" reativado.`;
      setAviso(mensagem);
      toast.success(mensagem);
      await carregar();
    } catch (e) {
      const mensagem = mensagemDeErro(e);
      setErro(mensagem);
      toast.error(mensagem);
    } finally {
      setReativandoId(null);
    }
  };

  // -------------------------------------------------------------------------
  // Estados de carregamento e erro (visíveis no corpo da tela)
  // -------------------------------------------------------------------------
  if (carregando && procedimentos.length === 0) {
    return (
      <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
        <div className="mx-auto max-w-screen-2xl space-y-5">
          <div className={agentivePanelClass(isDark, 'p-8')}>
            <div className="flex items-center justify-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm font-medium">Carregando procedimentos</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const listaVazia = procedimentos.length === 0;
  const filtroEscondeTudo = !listaVazia && visiveis.length === 0;

  return (
    <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
      <div className="mx-auto max-w-screen-2xl space-y-5">
        <AgentivePageHeader
          icon={Wallet}
          title="Procedimentos"
          description="O que a clínica oferece, quanto dura e quanto custa. É a partir daqui que o agente entende o que pode oferecer ao paciente."
          badges={
            <>
              <span className={agentivePillClass(isDark, true)}>{ativos.length} ativos</span>
              {incluirInativos && (
                <span className={agentivePillClass(isDark, false)}>{inativos.length} inativos</span>
              )}
            </>
          }
          actions={
            <button type="button" onClick={abrirNovo} className={agentivePrimaryButtonClass('px-4')}>
              <Plus className="h-4 w-4" />
              Novo procedimento
            </button>
          }
        />

        {erro && (
          <AgentiveAlert variant="error" title="Não foi possível carregar os procedimentos" onClose={() => setErro(null)}>
            <p>{erro}</p>
            <button type="button" onClick={carregar} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
              <RefreshCw className="h-4 w-4" />
              Tentar novamente
            </button>
          </AgentiveAlert>
        )}

        {aviso && (
          <AgentiveAlert variant="success" title="Tudo certo" onClose={() => setAviso(null)}>
            {aviso}
          </AgentiveAlert>
        )}

        {!listaVazia && !avaliacao && (
          <AgentiveAlert variant="warning" title="Falta o procedimento de avaliação de diagnóstico">
            Toda clínica precisa de um procedimento marcado como avaliação — é a primeira consulta do paciente
            e o que o agente usa para abrir a agenda. Edite um procedimento e marque{' '}
            <strong>"É avaliação de diagnóstico"</strong>.
          </AgentiveAlert>
        )}

        <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
          <div className={`flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between ${borderClass}`}>
            <div>
              <h2 className="text-base font-semibold">Catálogo da clínica</h2>
              <p className={`text-sm ${mutedClass}`}>
                Procedimento de avaliação aparece primeiro; os demais em ordem alfabética.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setIncluirInativos(false)}
                className={agentivePillClass(isDark, !incluirInativos)}
              >
                Só ativos
              </button>
              <button
                type="button"
                onClick={() => setIncluirInativos(true)}
                className={agentivePillClass(isDark, incluirInativos)}
              >
                Ativos e inativos
              </button>
              <button
                type="button"
                onClick={carregar}
                className={agentiveIconButtonClass(isDark)}
                aria-label="Recarregar lista"
                title="Recarregar lista"
              >
                <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {listaVazia ? (
            <div className="p-4">
              <AgentiveEmptyState
                icon={BadgeCheck}
                title="Nenhum procedimento cadastrado"
                description="Comece pela avaliação de diagnóstico: é o primeiro contato do paciente e a base da agenda. Depois cadastre limpeza, restauração, clareamento e o que mais a clínica realiza."
                action={
                  <button type="button" onClick={abrirNovo} className={agentivePrimaryButtonClass('px-4')}>
                    <Plus className="h-4 w-4" />
                    Cadastrar avaliação inicial
                  </button>
                }
              />
            </div>
          ) : filtroEscondeTudo ? (
            <div className="p-4">
              <AgentiveEmptyState
                icon={AlertTriangle}
                title="Nenhum procedimento ativo"
                description="Todos os procedimentos cadastrados estão desativados. Reative um deles ou mostre a lista completa."
                action={
                  <button
                    type="button"
                    onClick={() => setIncluirInativos(true)}
                    className={agentiveSecondaryButtonClass(isDark)}
                  >
                    Mostrar ativos e inativos
                  </button>
                }
              />
            </div>
          ) : (
            <ul className={isDark ? 'divide-y divide-white/10' : 'divide-y divide-brand/10'}>
              {visiveis.map((procedimento) => {
                const semProfissionais = procedimento.professionals === 0;
                return (
                  <li
                    key={procedimento.id}
                    className={`flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between ${borderClass} ${
                      procedimento.active ? '' : isDark ? 'bg-white/[0.02]' : 'bg-brand-canvas/60'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className={`truncate text-sm font-semibold ${procedimento.active ? '' : 'line-through decoration-1'}`}>
                          {procedimento.name}
                        </p>
                        {procedimento.is_evaluation && (
                          <span
                            className={agentivePillClass(
                              isDark,
                              false,
                              isDark
                                ? 'border-amber-400/30 bg-amber-400/10 text-amber-200'
                                : 'border-amber-200 bg-amber-50 text-amber-800'
                            )}
                          >
                            <BadgeCheck className="h-3.5 w-3.5" />
                            avaliação de diagnóstico
                          </span>
                        )}
                        {!procedimento.active && (
                          <span className={agentivePillClass(isDark, false)}>inativo</span>
                        )}
                      </div>

                      <div className={`mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs ${mutedClass}`}>
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5" />
                          {formatarDuracao(procedimento.duration_minutes)} ({procedimento.duration_minutes} min)
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <DollarSign className="h-3.5 w-3.5" />
                          {procedimento.price_cents === null
                            ? 'sem preço — o agente não cita valor'
                            : formatarPreco(procedimento.price_cents)}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Users className="h-3.5 w-3.5" />
                          {semProfissionais
                            ? 'nenhum profissional atende ainda'
                            : `${procedimento.professionals} profissional(is) atende(m)`}
                        </span>
                      </div>

                      {procedimento.active && semProfissionais && (
                        <p className={`mt-1.5 text-xs font-medium ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>
                          Nenhum profissional vinculado: o agente não vai oferecer este procedimento.{' '}
                          <Link to="/profissionais" className="underline decoration-1 underline-offset-2">
                            Vincular em Profissionais
                          </Link>
                        </p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => abrirEdicao(procedimento)}
                        className={agentiveSecondaryButtonClass(isDark)}
                      >
                        <Pencil className="h-4 w-4" />
                        Editar
                      </button>
                      {procedimento.active ? (
                        <button
                          type="button"
                          onClick={() => setAlvoDesativar(procedimento)}
                          className={agentiveSecondaryButtonClass(
                            isDark,
                            isDark
                              ? 'text-red-300 hover:bg-red-400/10'
                              : 'text-red-600 hover:bg-red-50'
                          )}
                        >
                          <Trash2 className="h-4 w-4" />
                          Desativar
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => reativar(procedimento)}
                          disabled={reativandoId === procedimento.id}
                          className={agentiveSecondaryButtonClass(isDark)}
                        >
                          {reativandoId === procedimento.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <RotateCcw className="h-4 w-4" />
                          )}
                          Reativar
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <div className={`flex items-start gap-2 rounded-2xl border p-4 text-xs leading-relaxed ${borderClass} ${mutedClass}`}>
          <ArrowRight className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Profissionais só aparecem na conversa com o paciente depois de vinculados a um procedimento.{' '}
            <Link to="/profissionais" className="font-semibold underline decoration-1 underline-offset-2">
              Cadastrar profissionais e vínculos
            </Link>
          </p>
        </div>
      </div>

      <ClinicaModal
        open={modalAberto}
        onClose={fecharModal}
        icon={editando ? Pencil : Plus}
        title={editando ? 'Editar procedimento' : 'Novo procedimento'}
        description={
          editando
            ? 'Alterações valem para os próximos agendamentos; o histórico continua como está.'
            : 'Cadastre o que a clínica realiza. Duração e preço são opcionais para o agente — a duração não: ela define o tamanho da vaga.'
        }
        footer={
          <>
            <button
              type="button"
              onClick={fecharModal}
              disabled={salvando}
              className={agentiveSecondaryButtonClass(isDark, 'px-4')}
            >
              Cancelar
            </button>
            <button
              type="submit"
              form="form-procedimento"
              disabled={salvando}
              className={agentivePrimaryButtonClass('px-4')}
            >
              {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {editando ? 'Salvar alterações' : 'Cadastrar procedimento'}
            </button>
          </>
        }
      >
        <form id="form-procedimento" onSubmit={salvar} className="space-y-4">
          {erroForm && (
            <AgentiveAlert variant="error" title="Não foi possível salvar">
              {erroForm}
            </AgentiveAlert>
          )}

          <div>
            <label className={agentiveLabelClass(isDark)} htmlFor="proc-nome">
              Nome do procedimento *
            </label>
            <input
              id="proc-nome"
              value={form.nome}
              onChange={(e) => setForm((atual) => ({ ...atual, nome: e.target.value }))}
              placeholder="Ex.: Limpeza / profilaxia"
              maxLength={160}
              className={agentiveInputClass(isDark)}
              autoFocus
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={agentiveLabelClass(isDark)} htmlFor="proc-duracao">
                Duração (minutos) *
              </label>
              <input
                id="proc-duracao"
                type="number"
                min={5}
                max={600}
                step={5}
                value={form.duracao}
                onChange={(e) => setForm((atual) => ({ ...atual, duracao: e.target.value }))}
                className={agentiveInputClass(isDark)}
              />
              <p className={`mt-1 text-xs ${mutedClass}`}>Entre 5 e 600 minutos. Define o tamanho da vaga na agenda.</p>
            </div>

            <div>
              <label className={agentiveLabelClass(isDark)} htmlFor="proc-preco">
                Preço (opcional)
              </label>
              <input
                id="proc-preco"
                inputMode="decimal"
                value={form.preco}
                onChange={(e) => setForm((atual) => ({ ...atual, preco: e.target.value }))}
                placeholder="Deixe vazio para não citar valor"
                className={agentiveInputClass(isDark)}
              />
              <p className={`mt-1 text-xs ${mutedClass}`}>
                Vazio = <strong>sem preço</strong>: o agente não cita valor nenhum ao paciente.
              </p>
            </div>
          </div>

          <label
            className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${borderClass} ${
              isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'
            }`}
          >
            <input
              type="checkbox"
              checked={form.avaliacao}
              onChange={(e) => setForm((atual) => ({ ...atual, avaliacao: e.target.checked }))}
              className="mt-0.5 h-4 w-4 accent-current"
            />
            <span className="text-sm">
              <span className="font-semibold">É avaliação de diagnóstico</span>
              <span className={`mt-0.5 block text-xs ${mutedClass}`}>
                Primeira consulta, em que o dentista examina e monta o plano de tratamento. Toda clínica precisa de um.
              </span>
            </span>
          </label>

          {editando && editando.is_evaluation && !form.avaliacao && (
            <AgentiveAlert variant="warning">
              Desmarcar a avaliação deixa a clínica sem procedimento de diagnóstico — o agente perde a porta de entrada
              do paciente novo.
            </AgentiveAlert>
          )}
        </form>
      </ClinicaModal>

      <AgentiveConfirmModal
        isOpen={alvoDesativar !== null}
        isLoading={processando}
        title={`Desativar "${alvoDesativar?.name ?? ''}"?`}
        variant="warning"
        confirmText="Desativar procedimento"
        cancelText="Manter ativo"
        onClose={() => {
          if (!processando) setAlvoDesativar(null);
        }}
        onConfirm={desativar}
        message={
          <div className="space-y-2">
            <p>
              Ele deixa de ser oferecido pelo agente e sai das opções de novos agendamentos
              {alvoDesativar && alvoDesativar.professionals > 0
                ? ` (${alvoDesativar.professionals} profissional(is) ficam sem este item).`
                : '.'}
            </p>
            <p className="font-semibold">
              O histórico é preservado: agendamentos antigos, prontuários e valores já registrados continuam válidos.
            </p>
            <p>Você pode reativar a qualquer momento, sem recadastrar.</p>
          </div>
        }
      />
    </div>
  );
};

export default Procedimentos;
