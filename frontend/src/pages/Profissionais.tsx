import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  Clock,
  Loader2,
  Mail,
  Pencil,
  Phone,
  Plus,
  RefreshCw,
  RotateCcw,
  Stethoscope,
  Trash2,
  UserCheck,
  UserRound,
} from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import ClinicaModal from '../components/ClinicaModal.tsx';
import ModalidadePanel from '../components/ModalidadePanel.tsx';
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
  profissionaisApi,
  type ModalidadeClinica,
  type Procedimento,
  type Profissional,
  type ProfissionalEntrada,
} from '../services/clinicApi.ts';

interface FormState {
  nome: string;
  email: string;
  telefone: string;
  cro: string;
}

const formVazio: FormState = { nome: '', email: '', telefone: '', cro: '' };

const emailValido = (valor: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(valor.trim());

const Profissionais: React.FC = () => {
  const { isDark } = useTheme();

  const [profissionais, setProfissionais] = useState<Profissional[]>([]);
  const [procedimentos, setProcedimentos] = useState<Procedimento[]>([]);
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [modalidade, setModalidade] = useState<ModalidadeClinica | null>(null);

  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState<Profissional | null>(null);
  const [form, setForm] = useState<FormState>(formVazio);
  const [selecionados, setSelecionados] = useState<number[]>([]);
  const [carregandoVinculo, setCarregandoVinculo] = useState(false);
  const [erroVinculo, setErroVinculo] = useState<string | null>(null);
  const [erroForm, setErroForm] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  const [alvoDesativar, setAlvoDesativar] = useState<Profissional | null>(null);
  const [processando, setProcessando] = useState(false);
  const [reativandoId, setReativandoId] = useState<number | null>(null);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const borderClass = isDark ? 'border-white/10' : 'border-brand/10';

  // Sempre traz ativos E inativos (filtro no cliente): com o filtro no servidor,
  // uma equipe toda desativada apareceria como "nenhum profissional cadastrado".
  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      const [listaProfissionais, listaProcedimentos] = await Promise.all([
        profissionaisApi.listar(true),
        // incluir_inativos=true: um vínculo pode apontar para procedimento já
        // desativado — precisamos do nome dele para não sumir do checklist.
        procedimentosApi.listar(true),
      ]);
      setProfissionais(listaProfissionais);
      setProcedimentos(listaProcedimentos);
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const procedimentosAtivos = useMemo(() => procedimentos.filter((p) => p.active), [procedimentos]);

  const visiveis = useMemo(
    () => (incluirInativos ? profissionais : profissionais.filter((p) => p.active)),
    [incluirInativos, profissionais]
  );

  const semProcedimentos = procedimentosAtivos.length === 0;
  const limiteAtingido = modalidade ? !modalidade.pode_adicionar : false;

  const abrirNovo = () => {
    setEditando(null);
    setForm(formVazio);
    setSelecionados([]);
    setErroVinculo(null);
    setErroForm(null);
    setModalAberto(true);
  };

  const abrirEdicao = async (profissional: Profissional) => {
    setEditando(profissional);
    setForm({
      nome: profissional.name ?? '',
      email: profissional.email ?? '',
      telefone: profissional.phone ?? '',
      cro: profissional.cro ?? '',
    });
    setSelecionados([]);
    setErroForm(null);
    setErroVinculo(null);
    setModalAberto(true);

    setCarregandoVinculo(true);
    try {
      const vinculo = await profissionaisApi.procedimentos(profissional.id);
      setSelecionados(Array.isArray(vinculo?.service_ids) ? vinculo.service_ids : []);
    } catch (e) {
      setErroVinculo(mensagemDeErro(e));
    } finally {
      setCarregandoVinculo(false);
    }
  };

  const fecharModal = () => {
    if (salvando) return;
    setModalAberto(false);
    setErroForm(null);
  };

  const alternarProcedimento = (id: number) => {
    setSelecionados((atual) =>
      atual.includes(id) ? atual.filter((item) => item !== id) : [...atual, id]
    );
  };

  const salvar = async (evento: React.FormEvent) => {
    evento.preventDefault();
    setErroForm(null);

    const nome = form.nome.trim();
    if (nome.length < 2) {
      setErroForm('Informe o nome do profissional (mínimo 2 caracteres).');
      return;
    }
    if (!emailValido(form.email)) {
      setErroForm('Informe um e-mail válido — é o identificador do profissional na clínica.');
      return;
    }

    // Campo vazio -> null EXPLÍCITO, que o backend aplica como limpeza
    // (`phone` e `cro` são anuláveis; ver backend/utils/patch_utils.py). Antes
    // o null era ignorado e a tela mandava "" como contorno, o que gravava
    // string vazia em vez de NULL na coluna.
    const telefone = form.telefone.trim();
    const cro = form.cro.trim();
    const dados: ProfissionalEntrada = {
      name: nome,
      email: form.email.trim().toLowerCase(),
      phone: telefone === '' ? null : telefone,
      cro: cro === '' ? null : cro,
    };

    setSalvando(true);
    try {
      if (editando) {
        const atualizado = await profissionaisApi.atualizar(editando.id, dados);
        try {
          await profissionaisApi.definirProcedimentos(atualizado.id, selecionados);
        } catch (eVinculo) {
          // Os dados cadastrais já foram salvos: não fechar o modal como se
          // tudo tivesse dado certo.
          setErroForm(
            `Dados do profissional salvos, mas o vínculo com procedimentos não foi gravado: ${mensagemDeErro(eVinculo)} ` +
              'Corrija e salve de novo.'
          );
          await carregar();
          return;
        }
        const mensagem = `Profissional "${atualizado.name}" atualizado.`;
        setAviso(mensagem);
        toast.success(mensagem);
      } else {
        const criado = await profissionaisApi.criar(dados);
        if (selecionados.length > 0) {
          try {
            await profissionaisApi.definirProcedimentos(criado.id, selecionados);
          } catch (eVinculo) {
            setEditando(criado);
            setErroForm(
              `Profissional "${criado.name}" cadastrado, mas o vínculo com procedimentos não foi gravado: ` +
                `${mensagemDeErro(eVinculo)} Corrija a seleção e salve de novo.`
            );
            await carregar();
            return;
          }
        }
        const mensagem = `Profissional "${criado.name}" cadastrado.`;
        setAviso(mensagem);
        toast.success(mensagem);
      }

      setModalAberto(false);
      await carregar();
    } catch (e) {
      // 409 do limite da modalidade e duplicidade de e-mail vêm com texto
      // escrito para o usuário final: mostrar exatamente como veio.
      setErroForm(mensagemDeErro(e));
    } finally {
      setSalvando(false);
    }
  };

  const desativar = async () => {
    if (!alvoDesativar) return;
    setProcessando(true);
    try {
      await profissionaisApi.desativar(alvoDesativar.id);
      const mensagem = `Profissional "${alvoDesativar.name}" desativado. O histórico é preservado.`;
      setAviso(mensagem);
      toast.success(mensagem);
      setAlvoDesativar(null);
      await carregar();
    } catch (e) {
      const mensagem = mensagemDeErro(e);
      setErro(mensagem);
      toast.error(mensagem);
    } finally {
      setProcessando(false);
    }
  };

  const reativar = async (profissional: Profissional) => {
    setReativandoId(profissional.id);
    try {
      await profissionaisApi.atualizar(profissional.id, { active: true });
      const mensagem = `Profissional "${profissional.name}" reativado.`;
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

  if (carregando && profissionais.length === 0 && procedimentos.length === 0) {
    return (
      <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
        <div className="mx-auto max-w-screen-2xl space-y-5">
          <div className={agentivePanelClass(isDark, 'p-8')}>
            <div className="flex items-center justify-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm font-medium">Carregando profissionais</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const listaVazia = profissionais.length === 0;
  const filtroEscondeTudo = !listaVazia && visiveis.length === 0;

  return (
    <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
      <div className="mx-auto max-w-screen-2xl space-y-5">
        <AgentivePageHeader
          icon={Stethoscope}
          title="Profissionais"
          description="Quem atende na clínica e quais procedimentos cada um realiza. É esse vínculo que o agente usa para oferecer horário."
          badges={
            <>
              <span className={agentivePillClass(isDark, true)}>
                {profissionais.filter((p) => p.active).length} ativos
              </span>
              {incluirInativos && (
                <span className={agentivePillClass(isDark, false)}>
                  {profissionais.filter((p) => !p.active).length} inativos
                </span>
              )}
            </>
          }
          actions={
            <div className="flex flex-col items-end gap-1">
              <button
                type="button"
                onClick={abrirNovo}
                disabled={limiteAtingido}
                title={
                  limiteAtingido
                    ? 'Limite da modalidade atingido. A mudança de modalidade é feita pelo administrador da plataforma.'
                    : undefined
                }
                className={agentivePrimaryButtonClass('px-4')}
              >
                <Plus className="h-4 w-4" />
                Novo profissional
              </button>
              {limiteAtingido && (
                <span className={`text-[11px] ${mutedClass}`}>limite da modalidade atingido</span>
              )}
            </div>
          }
        />

        <ModalidadePanel compact onDados={setModalidade} />

        {erro && (
          <AgentiveAlert variant="error" title="Não foi possível carregar os dados" onClose={() => setErro(null)}>
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

        {semProcedimentos && (
          <AgentiveAlert variant="warning" title="Cadastre um procedimento antes de vincular o profissional">
            <p>
              Um profissional sem procedimento não aparece na conversa com o paciente: o agente não tem o que
              oferecer. Cadastre ao menos a avaliação de diagnóstico e volte aqui para marcar quem a realiza.
            </p>
            <Link to="/procedimentos" className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
              <Plus className="h-4 w-4" />
              Ir para Procedimentos
            </Link>
          </AgentiveAlert>
        )}

        <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
          <div className={`flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between ${borderClass}`}>
            <div>
              <h2 className="text-base font-semibold">Equipe da clínica</h2>
              <p className={`text-sm ${mutedClass}`}>
                Ordem alfabética. Desativar um profissional libera vaga na modalidade.
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
                icon={UserRound}
                title="Nenhum profissional cadastrado"
                description={
                  semProcedimentos
                    ? 'Comece pelos procedimentos: cadastre a avaliação de diagnóstico e o que a clínica realiza. Depois volte para cadastrar quem atende.'
                    : 'Cadastre o primeiro profissional e marque quais procedimentos ele realiza.'
                }
                action={
                  semProcedimentos ? (
                    <Link to="/procedimentos" className={agentivePrimaryButtonClass('px-4')}>
                      <Plus className="h-4 w-4" />
                      Cadastrar procedimento
                    </Link>
                  ) : (
                    <button type="button" onClick={abrirNovo} className={agentivePrimaryButtonClass('px-4')}>
                      <Plus className="h-4 w-4" />
                      Cadastrar profissional
                    </button>
                  )
                }
              />
            </div>
          ) : filtroEscondeTudo ? (
            <div className="p-4">
              <AgentiveEmptyState
                icon={AlertTriangle}
                title="Nenhum profissional ativo"
                description="Todos os profissionais cadastrados estão desativados. Reative um deles ou veja a lista completa."
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
              {visiveis.map((profissional) => {
                const semVinculo = (profissional.services ?? 0) === 0;
                return (
                  <li
                    key={profissional.id}
                    className={`flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between ${borderClass} ${
                      profissional.active ? '' : isDark ? 'bg-white/[0.02]' : 'bg-brand-canvas/60'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className={`truncate text-sm font-semibold ${profissional.active ? '' : 'line-through decoration-1'}`}>
                          {profissional.name}
                        </p>
                        {profissional.cro && (
                          <span className={agentivePillClass(isDark, false)}>CRO {profissional.cro}</span>
                        )}
                        {!profissional.active && (
                          <span className={agentivePillClass(isDark, false)}>inativo</span>
                        )}
                      </div>

                      <div className={`mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs ${mutedClass}`}>
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3.5 w-3.5" />
                          {profissional.email}
                        </span>
                        {profissional.phone && (
                          <span className="inline-flex items-center gap-1">
                            <Phone className="h-3.5 w-3.5" />
                            {profissional.phone}
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1">
                          <BadgeCheck className="h-3.5 w-3.5" />
                          {semVinculo
                            ? 'nenhum procedimento vinculado'
                            : `${profissional.services} procedimento(s) vinculado(s)`}
                        </span>
                      </div>

                      {profissional.active && semVinculo && (
                        <p className={`mt-1.5 text-xs font-medium ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>
                          Sem procedimento, o agente não oferece este profissional.{' '}
                          <button
                            type="button"
                            onClick={() => abrirEdicao(profissional)}
                            className="underline decoration-1 underline-offset-2"
                          >
                            Vincular agora
                          </button>
                        </p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => abrirEdicao(profissional)}
                        className={agentiveSecondaryButtonClass(isDark)}
                      >
                        <Pencil className="h-4 w-4" />
                        Editar
                      </button>
                      {profissional.active ? (
                        <button
                          type="button"
                          onClick={() => setAlvoDesativar(profissional)}
                          className={agentiveSecondaryButtonClass(
                            isDark,
                            isDark ? 'text-red-300 hover:bg-red-400/10' : 'text-red-600 hover:bg-red-50'
                          )}
                        >
                          <Trash2 className="h-4 w-4" />
                          Desativar
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => reativar(profissional)}
                          disabled={reativandoId === profissional.id}
                          className={agentiveSecondaryButtonClass(isDark)}
                        >
                          {reativandoId === profissional.id ? (
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
      </div>

      <ClinicaModal
        open={modalAberto}
        onClose={fecharModal}
        icon={editando ? Pencil : UserCheck}
        wide
        title={editando ? 'Editar profissional' : 'Novo profissional'}
        description="Dados de contato e quais procedimentos este profissional atende. O vínculo é o que permite o agente oferecer horário para ele."
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
              form="form-profissional"
              disabled={salvando || carregandoVinculo}
              className={agentivePrimaryButtonClass('px-4')}
            >
              {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {editando ? 'Salvar alterações' : 'Cadastrar profissional'}
            </button>
          </>
        }
      >
        <form id="form-profissional" onSubmit={salvar} className="space-y-4">
          {erroForm && (
            <AgentiveAlert variant="error" title="Não foi possível salvar">
              {erroForm}
            </AgentiveAlert>
          )}

          <div>
            <label className={agentiveLabelClass(isDark)} htmlFor="prof-nome">
              Nome completo *
            </label>
            <input
              id="prof-nome"
              value={form.nome}
              onChange={(e) => setForm((atual) => ({ ...atual, nome: e.target.value }))}
              placeholder="Ex.: Dra. Ana Souza"
              maxLength={160}
              className={agentiveInputClass(isDark)}
              autoFocus
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={agentiveLabelClass(isDark)} htmlFor="prof-email">
                E-mail *
              </label>
              <input
                id="prof-email"
                type="email"
                value={form.email}
                onChange={(e) => setForm((atual) => ({ ...atual, email: e.target.value }))}
                placeholder="ana@clinica.com.br"
                maxLength={255}
                className={agentiveInputClass(isDark)}
              />
              <p className={`mt-1 text-xs ${mutedClass}`}>Único dentro da clínica — é o identificador do profissional.</p>
            </div>
            <div>
              <label className={agentiveLabelClass(isDark)} htmlFor="prof-telefone">
                Telefone (opcional)
              </label>
              <input
                id="prof-telefone"
                value={form.telefone}
                onChange={(e) => setForm((atual) => ({ ...atual, telefone: e.target.value }))}
                placeholder="(11) 99999-0000"
                maxLength={30}
                className={agentiveInputClass(isDark)}
              />
            </div>
          </div>

          <div>
            <label className={agentiveLabelClass(isDark)} htmlFor="prof-cro">
              CRO (opcional)
            </label>
            <input
              id="prof-cro"
              value={form.cro}
              onChange={(e) => setForm((atual) => ({ ...atual, cro: e.target.value }))}
              placeholder="CRO-SP 123456"
              maxLength={30}
              className={agentiveInputClass(isDark)}
            />
          </div>

          <div className={`rounded-2xl border p-4 ${borderClass}`}>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold">Procedimentos que este profissional atende *</p>
                <p className={`text-xs ${mutedClass}`}>
                  {selecionados.length === 0
                    ? 'Nenhum selecionado.'
                    : `${selecionados.length} selecionado(s).`}
                </p>
              </div>
              {selecionados.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelecionados([])}
                  className={agentiveSecondaryButtonClass(isDark, 'px-2 py-1 text-xs')}
                >
                  Limpar seleção
                </button>
              )}
            </div>

            {carregandoVinculo ? (
              <div className={`mt-4 flex items-center gap-2 text-sm ${mutedClass}`}>
                <Loader2 className="h-4 w-4 animate-spin" />
                Carregando procedimentos vinculados
              </div>
            ) : erroVinculo ? (
              <AgentiveAlert variant="error" className="mt-4" title="Não foi possível ler os vínculos atuais">
                <p>{erroVinculo}</p>
                <p className="mt-1 text-xs">
                  Sem essa leitura, salvar aqui substituiria os vínculos existentes. Feche o modal e abra de novo.
                </p>
              </AgentiveAlert>
            ) : semProcedimentos ? (
              <AgentiveAlert variant="warning" className="mt-4" title="Nenhum procedimento cadastrado ainda">
                <p>
                  Cadastre primeiro os procedimentos da clínica — a começar pela avaliação de diagnóstico. Sem isso não há
                  o que vincular, e o agente não tem como oferecer horário.
                </p>
                <Link to="/procedimentos" className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
                  <Plus className="h-4 w-4" />
                  Cadastrar procedimento
                </Link>
              </AgentiveAlert>
            ) : (
              <>
                <ul className="mt-4 grid gap-2 sm:grid-cols-2">
                  {procedimentos.map((procedimento) => {
                    const marcado = selecionados.includes(procedimento.id);
                    const desativado = !procedimento.active;
                    return (
                      <li key={procedimento.id}>
                        <label
                          className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm transition-colors ${
                            marcado
                              ? isDark
                                ? 'border-white/25 bg-white/10'
                                : 'border-brand/30 bg-brand-canvas'
                              : borderClass
                          } ${desativado ? 'opacity-70' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={marcado}
                            onChange={() => alternarProcedimento(procedimento.id)}
                            className="mt-0.5 h-4 w-4 accent-current"
                          />
                          <span className="min-w-0">
                            <span className="block truncate font-medium">{procedimento.name}</span>
                            <span className={`mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs ${mutedClass}`}>
                              <span className="inline-flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {formatarDuracao(procedimento.duration_minutes)}
                              </span>
                              <span>{procedimento.price_cents === null ? 'sem preço' : formatarPreco(procedimento.price_cents)}</span>
                              {desativado && <span className="font-medium text-amber-600">procedimento inativo</span>}
                              {procedimento.is_evaluation && <span className="font-medium">avaliação</span>}
                            </span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
                <p className={`mt-3 text-xs leading-relaxed ${mutedClass}`}>
                  A duração mostrada é a do procedimento. A API de vínculo devolve apenas os ids dos procedimentos,
                  sem duração própria por profissional.
                </p>
              </>
            )}
          </div>
        </form>
      </ClinicaModal>

      <AgentiveConfirmModal
        isOpen={alvoDesativar !== null}
        isLoading={processando}
        title={`Desativar "${alvoDesativar?.name ?? ''}"?`}
        variant="warning"
        confirmText="Desativar profissional"
        cancelText="Manter ativo"
        onClose={() => {
          if (!processando) setAlvoDesativar(null);
        }}
        onConfirm={desativar}
        message={
          <div className="space-y-2">
            <p>
              Ele deixa de ser oferecido pelo agente e sai da agenda de novos agendamentos. O vínculo com procedimentos
              é mantido e volta se você reativar.
            </p>
            <p className="font-semibold">
              O histórico é preservado: atendimentos e prontuários já registrados continuam válidos.
            </p>
            <p>Desativar libera uma vaga na modalidade da clínica.</p>
          </div>
        }
      />
    </div>
  );
};

export default Profissionais;
