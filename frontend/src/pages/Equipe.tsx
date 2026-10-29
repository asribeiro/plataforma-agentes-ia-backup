/**
 * Equipe da clínica: quem entra no sistema e com qual papel (card tela do F1-12).
 *
 * A regra que a tela precisa deixar visível, porque é a que mais confunde:
 *   - Admin Clínica administra e vê o prontuário de toda a clínica;
 *   - Profissional Clínico vê o prontuário dos próprios pacientes;
 *   - Profissional de Atendimento agenda e fala com o paciente, e NÃO vê
 *     prontuário.
 * Por isso o papel tem descrição na tela e o seletor de profissional só aparece
 * quando o papel exige vínculo — quem escolhe é o backend, aqui só refletimos.
 *
 * O que o backend recusa, a tela não repete a regra: mostra a mensagem que veio.
 * Duplicar validação no frontend é como as duas versões divergem.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BadgeCheck,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  UserPlus,
  UserRound,
  Users,
  UserX,
} from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import ClinicaModal from '../components/ClinicaModal.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  AgentivePageHeader,
  AgentiveStatCard,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import { profissionaisApi, type Profissional } from '../services/clinicApi.ts';
import {
  equipeApi,
  mensagemDeErro,
  papeisQueVeemProntuario,
  type ClinicaUsuario,
  type PapelOpcao,
} from '../services/clinicUsersApi.ts';
import { usePapelClinico } from '../hooks/usePapelClinico.ts';

interface Formulario {
  name: string;
  email: string;
  password: string;
  role: string;
  professional_id: string; // string no form: <select> devolve texto
}

const FORM_VAZIO: Formulario = {
  name: '',
  email: '',
  password: '',
  role: 'service_professional',
  professional_id: '',
};

const Equipe: React.FC = () => {
  const { isDark } = useTheme();
  const { eu, carregando: carregandoPapel, erro: erroPapel } = usePapelClinico();

  const [usuarios, setUsuarios] = useState<ClinicaUsuario[]>([]);
  const [papeis, setPapeis] = useState<PapelOpcao[]>([]);
  const [profissionais, setProfissionais] = useState<Profissional[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [modalAberto, setModalAberto] = useState(false);
  const [editando, setEditando] = useState<ClinicaUsuario | null>(null);
  const [form, setForm] = useState<Formulario>(FORM_VAZIO);
  const [salvando, setSalvando] = useState(false);
  const [desativando, setDesativando] = useState<ClinicaUsuario | null>(null);

  const podeAdministrar = eu?.pode_administrar_usuarios ?? false;

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const [lista, opcoes, equipe] = await Promise.all([
        equipeApi.listar(true),
        equipeApi.papeis(),
        profissionaisApi.listar(true).catch(() => [] as Profissional[]),
      ]);
      setUsuarios(lista);
      setPapeis(opcoes);
      setProfissionais(equipe.filter((p) => p.active));
      setErro(null);
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível carregar a equipe da clínica'));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    if (!carregandoPapel && podeAdministrar) void carregar();
    if (!carregandoPapel && !podeAdministrar) setCarregando(false);
  }, [carregandoPapel, podeAdministrar, carregar]);

  const papelSelecionado = useMemo(
    () => papeis.find((p) => p.role === form.role) ?? null,
    [papeis, form.role],
  );

  const totais = useMemo(() => {
    const ativos = usuarios.filter((u) => u.is_active).length;
    const clinicos = usuarios.filter((u) => u.role === 'clinical_professional').length;
    const atendimento = usuarios.filter((u) => u.role === 'service_professional').length;
    return { total: usuarios.length, ativos, clinicos, atendimento };
  }, [usuarios]);

  const abrirNovo = () => {
    setEditando(null);
    setForm({ ...FORM_VAZIO, role: papeis[0]?.role ?? 'service_professional' });
    setModalAberto(true);
  };

  const abrirEdicao = (usuario: ClinicaUsuario) => {
    setEditando(usuario);
    setForm({
      name: usuario.name,
      email: usuario.email,
      password: '',
      role: usuario.role,
      professional_id: usuario.professional_id ? String(usuario.professional_id) : '',
    });
    setModalAberto(true);
  };

  const fecharModal = () => {
    if (salvando) return;
    setModalAberto(false);
    setEditando(null);
  };

  const salvar = async () => {
    const nome = form.name.trim();
    const email = form.email.trim();
    if (nome.length < 2) {
      toast.error('Informe o nome do usuário.');
      return;
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      toast.error('Informe um e-mail válido — é com ele que a pessoa entra.');
      return;
    }
    if (!editando && form.password.trim().length < 8) {
      toast.error('A senha inicial precisa ter pelo menos 8 caracteres.');
      return;
    }
    const exigeProfissional = papelSelecionado?.exige_profissional ?? false;
    if (exigeProfissional && !form.professional_id) {
      toast.error('Este papel precisa estar vinculado a um profissional.');
      return;
    }

    setSalvando(true);
    try {
      const vinculo = exigeProfissional ? Number(form.professional_id) : null;
      if (editando) {
        await equipeApi.atualizar(editando.id, {
          name: nome,
          role: form.role,
          professional_id: vinculo,
        });
        toast.success('Usuário atualizado.');
      } else {
        await equipeApi.criar({
          name: nome,
          email,
          password: form.password,
          role: form.role,
          professional_id: vinculo,
        });
        toast.success('Usuário criado. Ele já pode entrar com este e-mail.');
      }
      setModalAberto(false);
      setEditando(null);
      await carregar();
    } catch (e) {
      // Mensagem do backend: último admin, e-mail repetido, profissional
      // inativo... o texto já explica o que fazer.
      toast.error(mensagemDeErro(e, 'Não foi possível salvar o usuário'));
    } finally {
      setSalvando(false);
    }
  };

  const alternarAtivo = async (usuario: ClinicaUsuario) => {
    try {
      await equipeApi.atualizar(usuario.id, { is_active: !usuario.is_active });
      toast.success(usuario.is_active ? 'Usuário desativado.' : 'Usuário reativado.');
      await carregar();
    } catch (e) {
      toast.error(mensagemDeErro(e, 'Não foi possível alterar o acesso'));
    } finally {
      setDesativando(null);
    }
  };

  // -------------------------------------------------------------- sem permissão
  if (!carregandoPapel && (erroPapel || !podeAdministrar)) {
    return (
      <div className={agentivePageClass(isDark)}>
        <AgentivePageHeader
          icon={Users}
          title="Equipe da clínica"
          description="Quem entra no sistema e com qual papel."
        />
        <AgentiveAlert
          variant="warning"
          title={erroPapel ? 'Não foi possível identificar seu papel' : 'Sua conta não administra usuários'}
        >
          {erroPapel ? (
            erroPapel
          ) : (
            <>
              Você está logado como <strong>{eu?.role_rotulo}</strong>
              {eu?.professional_nome ? ` (${eu.professional_nome})` : ''} e este papel não
              administra a equipe. Quem cuida disso é o Admin Clínica
              {eu?.ve_prontuario ? '' : ' — e o seu acesso ao prontuário é restrito ao que o seu papel permite'}.
            </>
          )}
        </AgentiveAlert>
      </div>
    );
  }

  return (
    <div className={agentivePageClass(isDark)}>
      <AgentivePageHeader
        icon={Users}
        title="Equipe da clínica"
        description="Quem entra no sistema, com qual papel e vinculado a qual profissional."
        badges={
          <span className={agentivePillClass(isDark, true, 'text-xs')}>
            <ShieldCheck className="h-3.5 w-3.5" /> {eu?.role_rotulo ?? 'papel'}
          </span>
        }
        actions={
          <>
            <button
              type="button"
              onClick={() => void carregar()}
              className={agentiveSecondaryButtonClass(isDark)}
              disabled={carregando}
            >
              <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} /> Atualizar
            </button>
            <button type="button" onClick={abrirNovo} className={agentivePrimaryButtonClass()}>
              <UserPlus className="h-4 w-4" /> Novo usuário
            </button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <AgentiveStatCard icon={Users} label="Usuários" value={totais.total} helper={`${totais.ativos} ativos`} />
        <AgentiveStatCard
          icon={UserRound}
          label="Profissionais clínicos"
          value={totais.clinicos}
          helper="Veem o prontuário dos próprios pacientes"
        />
        <AgentiveStatCard
          icon={UserX}
          label="Atendimento"
          value={totais.atendimento}
          helper="Agenda e contato, sem prontuário"
        />
        <AgentiveStatCard
          icon={ShieldCheck}
          label="Administradores"
          value={usuarios.filter((u) => u.role === 'clinic_admin' || u.role === 'admin').length}
          helper="Veem todo o prontuário da clínica"
        />
      </div>

      {erro && (
        <AgentiveAlert variant="error" title="Não foi possível carregar" onClose={() => setErro(null)}>
          {erro}
        </AgentiveAlert>
      )}

      <div className={agentivePanelClass(isDark)}>
        {carregando ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm opacity-70">
            <Loader2 className="h-4 w-4 animate-spin" /> Carregando equipe…
          </div>
        ) : usuarios.length === 0 ? (
          <AgentiveEmptyState
            icon={Users}
            title="Ninguém na equipe ainda"
            description="Cadastre o primeiro usuário com o papel que ele exerce na clínica."
            action={
              <button type="button" onClick={abrirNovo} className={agentivePrimaryButtonClass()}>
                <Plus className="h-4 w-4" /> Cadastrar usuário
              </button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide opacity-60">
                  <th className="px-3 py-2">Usuário</th>
                  <th className="px-3 py-2">Papel</th>
                  <th className="px-3 py-2">Profissional</th>
                  <th className="px-3 py-2">Prontuário</th>
                  <th className="px-3 py-2">Situação</th>
                  <th className="px-3 py-2 text-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map((usuario) => {
                  const veProntuario = papeisQueVeemProntuario.includes(usuario.role);
                  return (
                    <tr key={usuario.id} className="border-t border-black/5 dark:border-white/10">
                      <td className="px-3 py-3">
                        <div className="font-medium flex items-center gap-2">
                          {usuario.name}
                          {usuario.id === eu?.id && (
                            <span className={agentivePillClass(isDark, false, 'text-[10px]')}>você</span>
                          )}
                        </div>
                        <div className="text-xs opacity-60">{usuario.email}</div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-col gap-1">
                          <span className={agentivePillClass(isDark, true, 'text-[11px] w-fit')}>
                            {usuario.role_rotulo.split('—')[0].trim()}
                          </span>
                          <span className="text-xs opacity-60 max-w-[220px]">
                            {usuario.role_rotulo.includes('—')
                              ? usuario.role_rotulo.split('—').slice(1).join('—').trim()
                              : ''}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        {usuario.professional_nome ? (
                          <span className="flex items-center gap-1.5">
                            <BadgeCheck className="h-4 w-4 text-emerald-500" />
                            {usuario.professional_nome}
                          </span>
                        ) : (
                          <span className="opacity-50">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        {veProntuario ? (
                          <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                            <ShieldCheck className="h-4 w-4" /> vê
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 opacity-60">
                            <ShieldOff className="h-4 w-4" /> não vê
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <span className={agentivePillClass(isDark, usuario.is_active, 'text-[11px]')}>
                          {usuario.is_active ? 'ativo' : 'inativo'}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => abrirEdicao(usuario)}
                            className={agentiveIconButtonClass(isDark)}
                            title="Editar papel e vínculo"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setDesativando(usuario)}
                            className={agentiveIconButtonClass(isDark, usuario.is_active ? 'danger' : 'success')}
                            title={usuario.is_active ? 'Desativar acesso' : 'Reativar acesso'}
                          >
                            {usuario.is_active ? <UserX className="h-4 w-4" /> : <BadgeCheck className="h-4 w-4" />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <AgentiveAlert variant="info" title="O que cada papel alcança">
        <ul className="list-disc pl-5 space-y-1">
          <li>
            <strong>Admin Clínica</strong> — administra a equipe e vê o prontuário de toda a clínica.
            Todo acesso a prontuário fica registrado.
          </li>
          <li>
            <strong>Profissional Clínico</strong> — vê o prontuário dos próprios pacientes. Precisa de
            vínculo com o cadastro do profissional.
          </li>
          <li>
            <strong>Profissional de Atendimento</strong> — agenda, confirma e fala com o paciente. Não
            acessa prontuário, anamnese nem anexo de exame.
          </li>
        </ul>
      </AgentiveAlert>

      <ClinicaModal
        open={modalAberto}
        onClose={fecharModal}
        icon={editando ? Pencil : UserPlus}
        title={editando ? 'Editar usuário' : 'Novo usuário da clínica'}
        description={
          editando
            ? 'Mudar o papel muda o que a pessoa enxerga. O vínculo com o profissional é o que permite separar "meus pacientes" dos demais.'
            : 'A pessoa entra no sistema com este e-mail e a senha inicial definida aqui.'
        }
        footer={
          <>
            <button
              type="button"
              onClick={fecharModal}
              disabled={salvando}
              className={agentiveSecondaryButtonClass(isDark)}
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={() => void salvar()}
              disabled={salvando}
              className={agentivePrimaryButtonClass()}
            >
              {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <BadgeCheck className="h-4 w-4" />}
              {editando ? 'Salvar alterações' : 'Criar usuário'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className={agentiveLabelClass(isDark)} htmlFor="nome-usuario">Nome</label>
            <input
              id="nome-usuario"
              className={agentiveInputClass(isDark)}
              value={form.name}
              onChange={(ev) => setForm((f) => ({ ...f, name: ev.target.value }))}
              placeholder="Ex.: Ana Souza"
            />
          </div>

          {!editando && (
            <>
              <div>
                <label className={agentiveLabelClass(isDark)} htmlFor="email-usuario">E-mail de acesso</label>
                <input
                  id="email-usuario"
                  type="email"
                  className={agentiveInputClass(isDark)}
                  value={form.email}
                  onChange={(ev) => setForm((f) => ({ ...f, email: ev.target.value }))}
                  placeholder="ana@clinica.com.br"
                />
              </div>
              <div>
                <label className={agentiveLabelClass(isDark)} htmlFor="senha-usuario">Senha inicial</label>
                <input
                  id="senha-usuario"
                  type="password"
                  className={agentiveInputClass(isDark)}
                  value={form.password}
                  onChange={(ev) => setForm((f) => ({ ...f, password: ev.target.value }))}
                  placeholder="mínimo de 8 caracteres"
                />
                <p className="mt-1 text-xs opacity-60">
                  A pessoa pode trocar depois em Minha conta. Evite mandar senha por WhatsApp.
                </p>
              </div>
            </>
          )}

          <div>
            <label className={agentiveLabelClass(isDark)} htmlFor="papel-usuario">Papel na clínica</label>
            <select
              id="papel-usuario"
              className={agentiveInputClass(isDark)}
              value={form.role}
              onChange={(ev) =>
                setForm((f) => ({
                  ...f,
                  role: ev.target.value,
                  professional_id: '',
                }))
              }
            >
              {papeis.map((opcao) => (
                <option key={opcao.role} value={opcao.role}>
                  {opcao.rotulo.split('—')[0].trim()}
                </option>
              ))}
            </select>
            {papelSelecionado && (
              <p className="mt-1 text-xs opacity-70">
                {papelSelecionado.rotulo.includes('—')
                  ? papelSelecionado.rotulo.split('—').slice(1).join('—').trim()
                  : papelSelecionado.rotulo}
                {papelSelecionado.exige_profissional
                  ? ' Exige vínculo com um profissional.'
                  : ' Não usa vínculo com profissional.'}
              </p>
            )}
          </div>

          {papelSelecionado?.exige_profissional && (
            <div>
              <label className={agentiveLabelClass(isDark)} htmlFor="profissional-usuario">
                Profissional vinculado
              </label>
              <select
                id="profissional-usuario"
                className={agentiveInputClass(isDark)}
                value={form.professional_id}
                onChange={(ev) => setForm((f) => ({ ...f, professional_id: ev.target.value }))}
              >
                <option value="">Selecione o profissional…</option>
                {profissionais.map((prof) => (
                  <option key={prof.id} value={String(prof.id)}>
                    {prof.name}
                  </option>
                ))}
              </select>
              {profissionais.length === 0 && (
                <p className="mt-1 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Nenhum profissional ativo cadastrado. Cadastre em Profissionais antes de criar este usuário.
                </p>
              )}
            </div>
          )}
        </div>
      </ClinicaModal>

      <AgentiveConfirmModal
        isOpen={desativando !== null}
        title={desativando?.is_active ? 'Desativar acesso' : 'Reativar acesso'}
        message={
          desativando?.is_active
            ? `Desativar ${desativando?.name}? A pessoa deixa de entrar no sistema, mas o histórico dela continua.`
            : `Reativar o acesso de ${desativando?.name}?`
        }
        confirmText={desativando?.is_active ? 'Desativar' : 'Reativar'}
        variant={desativando?.is_active ? 'danger' : 'info'}
        onConfirm={() => desativando && void alternarAtivo(desativando)}
        onClose={() => setDesativando(null)}
        isLoading={false}
      />
    </div>
  );
};

export default Equipe;
