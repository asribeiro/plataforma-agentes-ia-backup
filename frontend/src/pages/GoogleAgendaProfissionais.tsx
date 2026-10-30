import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarDays, Loader2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentivePageHeader,
  agentiveInputClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import { AgendaGoogleCalendarCard } from '../components/AgendaGoogleCalendarCard.tsx';
import {
  listarProfissionaisGoogleAgenda,
  obterGoogleOAuthApp,
  removerGoogleOAuthApp,
  salvarGoogleOAuthApp,
  type GoogleAgendaProfissional,
  type GoogleOAuthAppStatus,
} from '../services/googleAgendaApi.ts';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

/**
 * Google Agenda por profissional.
 *
 * O backend decide o escopo da lista: admin da plataforma vê todos os
 * profissionais de todas as empresas, Admin Clínica vê os da própria empresa e
 * o profissional vê só o próprio.
 */
interface Props {
  embedded?: boolean;
}

const GoogleAgendaProfissionais: React.FC<Props> = ({ embedded = false }) => {
  const { isDark } = useTheme();
  const [searchParams, setSearchParams] = useSearchParams();
  const [itens, setItens] = useState<GoogleAgendaProfissional[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState('');
  const [selecionado, setSelecionado] = useState<number | null>(null);
  const [recemConectadoAgenda, setRecemConectadoAgenda] = useState<number | null>(null);
  const [app, setApp] = useState<GoogleOAuthAppStatus | null>(null);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [salvandoApp, setSalvandoApp] = useState(false);
  const [chaveCartao, setChaveCartao] = useState(0);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setItens(await listarProfissionaisGoogleAgenda());
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Erro ao listar os profissionais.');
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
    obterGoogleOAuthApp().then(setApp).catch(() => setApp(null));
  }, [carregar]);

  const salvarApp = async () => {
    setSalvandoApp(true);
    try {
      setApp(await salvarGoogleOAuthApp(clientId, clientSecret));
      setClientId('');
      setClientSecret('');
      setChaveCartao((n) => n + 1);
      toast.success('Credenciais do Google salvas.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Erro ao salvar as credenciais.');
    } finally {
      setSalvandoApp(false);
    }
  };

  const removerApp = async () => {
    setSalvandoApp(true);
    try {
      setApp(await removerGoogleOAuthApp());
      setChaveCartao((n) => n + 1);
      toast.success('Credenciais removidas da plataforma.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Erro ao remover as credenciais.');
    } finally {
      setSalvandoApp(false);
    }
  };

  // Retorno do OAuth (?google_oauth=success&agenda_id=N)
  useEffect(() => {
    const resultado = searchParams.get('google_oauth');
    if (!resultado) return;
    const agendaId = Number(searchParams.get('agenda_id')) || null;
    if (resultado === 'success') {
      toast.success('Conta Google autorizada. Escolha o calendário do profissional.');
      setRecemConectadoAgenda(agendaId);
    } else {
      const motivo = searchParams.get('reason');
      toast.error(
        motivo === 'api_disabled'
          ? 'A Google Calendar API está desativada no projeto do Google Cloud. Ative-a em APIs e serviços e tente novamente.'
          : motivo === 'access_denied'
            ? 'A autorização foi negada no Google.'
            : 'Não foi possível conectar com o Google Agenda. Tente novamente.',
        { autoClose: 12000 },
      );
    }
    const restantes = new URLSearchParams(searchParams);
    restantes.delete('google_oauth');
    restantes.delete('reason');
    restantes.delete('agenda_id');
    setSearchParams(restantes, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (recemConectadoAgenda && itens.length) {
      const alvo = itens.find((i) => i.agenda_id === recemConectadoAgenda);
      if (alvo) setSelecionado(alvo.professional_id);
    }
  }, [recemConectadoAgenda, itens]);

  const filtrados = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    if (!termo) return itens;
    return itens.filter((i) => `${i.professional_name} ${i.company_name}`.toLowerCase().includes(termo));
  }, [itens, busca]);

  const atual = itens.find((i) => i.professional_id === selecionado) ?? null;
  const varias = new Set(itens.map((i) => i.company_id)).size > 1;

  const Wrapper: React.ElementType = embedded ? 'div' : 'main';
  return (
    <Wrapper className={embedded ? undefined : agentivePageClass(isDark, 'p-4 sm:p-6')}>
      <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-4">
        {!embedded && <AgentivePageHeader
          icon={CalendarDays}
          title="Google Agenda"
          description="Conecte a agenda Google de cada profissional. Cada conexão pertence ao profissional, não à clínica."
        />}

        {app?.can_configure && (
          <div className={agentivePanelClass(isDark, 'flex flex-col gap-3 p-4')}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">Credenciais do aplicativo Google</h2>
              <span className={agentivePillClass(isDark, app.configured)}>
                {app.configured
                  ? app.source === 'plataforma' ? 'Configurado na plataforma' : 'Configurado no servidor (variáveis de ambiente)'
                  : 'Não configurado'}
              </span>
            </div>
            <p className={cx('text-xs leading-relaxed', mutedClass)}>
              No Google Cloud, ative a Google Calendar API e crie um OAuth Client ID do tipo <strong>Aplicativo da Web</strong>,
              cadastrando este URI de redirecionamento autorizado: <code className="break-all">{app.redirect_uri}</code>.
              O Client Secret é guardado criptografado e nunca é exibido novamente.
            </p>
            {app.client_id && <p className={cx('break-all text-xs', mutedClass)}>Client ID atual: {app.client_id}</p>}
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="Client ID"
                autoComplete="off"
                className={agentiveInputClass(isDark)}
              />
              <input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder="Client Secret"
                autoComplete="new-password"
                className={agentiveInputClass(isDark)}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={salvandoApp || !clientId.trim() || !clientSecret.trim()}
                onClick={() => void salvarApp()}
                className={agentivePrimaryButtonClass('px-3 py-2 disabled:opacity-50')}
              >
                {salvandoApp ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Salvar credenciais
              </button>
              {app.source === 'plataforma' && (
                <button
                  type="button"
                  disabled={salvandoApp}
                  onClick={() => void removerApp()}
                  className={agentiveSecondaryButtonClass(isDark, 'px-3 py-2')}
                >
                  Remover
                </button>
              )}
            </div>
          </div>
        )}

        {carregando ? (
          <div className="flex items-center gap-2 p-6 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Carregando profissionais...
          </div>
        ) : erro ? (
          <div className={agentivePanelClass(isDark, 'p-4 text-sm')}>{erro}</div>
        ) : itens.length === 0 ? (
          <div className={agentivePanelClass(isDark, 'p-4 text-sm')}>
            Nenhum profissional ativo cadastrado. Cadastre profissionais para conectar o Google Agenda.
          </div>
        ) : (
          <section className="grid gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
            <div className={agentivePanelClass(isDark, 'flex max-h-[70vh] flex-col gap-3 overflow-hidden p-3')}>
              <input
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                placeholder={varias ? 'Buscar profissional ou empresa' : 'Buscar profissional'}
                className={agentiveInputClass(isDark)}
              />
              <ul className="flex flex-col gap-2 overflow-y-auto">
                {filtrados.map((item) => (
                  <li key={item.professional_id}>
                    <button
                      type="button"
                      onClick={() => setSelecionado(item.professional_id)}
                      className={cx(
                        'flex w-full items-start justify-between gap-2 rounded-xl border p-3 text-left transition',
                        isDark ? 'border-white/10 hover:bg-white/[0.06]' : 'border-brand/10 hover:bg-brand-canvas',
                        selecionado === item.professional_id && (isDark ? 'bg-white/[0.08]' : 'bg-brand-canvas'),
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold">{item.professional_name}</span>
                        {varias && <span className={cx('block truncate text-xs', mutedClass)}>{item.company_name}</span>}
                        {item.google_account_email && (
                          <span className={cx('block truncate text-xs', mutedClass)}>{item.google_account_email}</span>
                        )}
                      </span>
                      <span className={agentivePillClass(isDark, item.google_connected, 'shrink-0')}>
                        {item.agenda_id ? (item.google_connected ? 'Conectado' : 'Não conectado') : 'Sem agenda'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <div className={agentivePanelClass(isDark, 'p-4')}>
              {!atual ? (
                <p className={cx('text-sm', mutedClass)}>Selecione um profissional para conectar o Google Agenda.</p>
              ) : !atual.agenda_id ? (
                <p className={cx('text-sm', mutedClass)}>
                  {atual.professional_name} ainda não tem agenda. Crie a agenda em Agenda → Agendas por profissional e
                  volte aqui para conectar o Google.
                </p>
              ) : (
                <>
                  <h2 className="mb-2 text-base font-semibold">
                    {atual.professional_name}
                    {varias && <span className={cx('ml-2 text-xs font-normal', mutedClass)}>{atual.company_name}</span>}
                  </h2>
                  <AgendaGoogleCalendarCard
                    key={chaveCartao}
                    agendaId={atual.agenda_id}
                    agendaNome={atual.agenda_name}
                    companyId={atual.company_id}
                    returnTo="integrations"
                    podeGerenciar
                    recemConectado={recemConectadoAgenda === atual.agenda_id}
                    onAlterado={() => void carregar()}
                  />
                </>
              )}
            </div>
          </section>
        )}
      </div>
    </Wrapper>
  );
};

export default GoogleAgendaProfissionais;
