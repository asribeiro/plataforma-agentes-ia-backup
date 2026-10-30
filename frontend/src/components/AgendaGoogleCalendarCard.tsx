import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CalendarDays, Check, ExternalLink, Loader2, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
    agentiveInputClass,
    agentivePanelClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import {
    definirCalendarioGoogleDaAgenda,
    iniciarOAuthGoogleDaAgenda,
    listarCalendariosGoogleDaAgenda,
    obterStatusGoogleDaAgenda,
    removerCredencialGoogleDaAgenda,
    type GoogleAgendaCalendario,
    type GoogleAgendaStatus,
} from '../services/googleAgendaApi.ts';

/**
 * 'Google Calendar desta agenda'.
 *
 * Cada cartão representa uma credencial OAuth independente, armazenada na
 * agenda do profissional correspondente.
 */
interface AgendaGoogleCalendarCardProps {
    agendaId: number;
    agendaNome?: string | null;
    /** Chamado depois de trocar/remover a credencial, para a tela recarregar a agenda. */
    onAlterado?: () => void;
    /** Devolve a fonte da credencial para a tela ajustar o que mostra ao redor. */
    onStatusCarregado?: (status: GoogleAgendaStatus) => void;
    /** true quando a pessoa acabou de voltar do OAuth desta agenda. */
    recemConectado?: boolean;
    /** Apenas Admin Clínica ou o profissional dono da agenda pode alterar a conexão. */
    podeGerenciar?: boolean;
    /** Empresa da agenda; omitido = empresa da sessão. O admin da plataforma precisa informar. */
    companyId?: number | null;
    /** Para onde o OAuth devolve a pessoa. */
    returnTo?: 'integrations' | 'calendar';
}

export const AgendaGoogleCalendarCard: React.FC<AgendaGoogleCalendarCardProps> = ({
    agendaId,
    agendaNome,
    onAlterado,
    onStatusCarregado,
    recemConectado = false,
    podeGerenciar = false,
    companyId,
    returnTo,
}) => {
    const { isDark } = useTheme();

    const [status, setStatus] = useState<GoogleAgendaStatus | null>(null);
    const [carregando, setCarregando] = useState(true);
    const [erroStatus, setErroStatus] = useState<string | null>(null);

    const [calendarios, setCalendarios] = useState<GoogleAgendaCalendario[] | null>(null);
    const [carregandoCalendarios, setCarregandoCalendarios] = useState(false);
    const [mostrarSeletor, setMostrarSeletor] = useState(false);
    const [calendarioEscolhido, setCalendarioEscolhido] = useState('');

    const [salvando, setSalvando] = useState(false);
    const [confirmarDesconexao, setConfirmarDesconexao] = useState(false);

    const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
    const cardBorderClass = isDark ? 'border-white/10' : 'border-brand/10';
    const softBoxClass = isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas';

    // Callback em ref: `carregarStatus` precisa de identidade estável, senão o
    // efeito que recarrega ao trocar de agenda entra em laço.
    const statusCarregadoRef = useRef(onStatusCarregado);
    useEffect(() => {
        statusCarregadoRef.current = onStatusCarregado;
    }, [onStatusCarregado]);

    const carregarStatus = useCallback(async () => {
        setCarregando(true);
        setErroStatus(null);
        try {
            const dados = await obterStatusGoogleDaAgenda(agendaId, companyId);
            setStatus(dados);
            statusCarregadoRef.current?.(dados);
        } catch (erro) {
            setStatus(null);
            setErroStatus(erro instanceof Error ? erro.message : 'Erro ao consultar o Google desta agenda.');
        } finally {
            setCarregando(false);
        }
    }, [agendaId, companyId]);

    const carregarCalendarios = useCallback(async () => {
        setCarregandoCalendarios(true);
        try {
            const dados = await listarCalendariosGoogleDaAgenda(agendaId, companyId);
            const lista = dados.calendars ?? [];
            setCalendarios(lista);
            const atual = status?.google_calendar_id;
            const preferido = lista.find((item) => item.id === atual) ?? lista.find((item) => item.primary) ?? lista[0];
            setCalendarioEscolhido(preferido?.id ?? '');
            setMostrarSeletor(true);
        } catch (erro) {
            setCalendarios([]);
            toast.error(erro instanceof Error ? erro.message : 'Erro ao listar os calendários Google desta agenda.');
        } finally {
            setCarregandoCalendarios(false);
        }
    }, [agendaId, companyId, status?.google_calendar_id]);

    useEffect(() => {
        setStatus(null);
        setCalendarios(null);
        setMostrarSeletor(false);
        setCalendarioEscolhido('');
        carregarStatus();
    }, [carregarStatus]);

    // Voltou do OAuth desta agenda: o próximo passo obrigatório é escolher o
    // calendário (rotas 3 e 4). Já abre a lista em vez de esperar um clique —
    // uma vez só, para não reabrir depois que a pessoa fechar.
    const autoAbriuSeletor = useRef(false);
    useEffect(() => {
        if (autoAbriuSeletor.current) return;
        if (!recemConectado) return;
        if (!status) return;
        if (status.fonte_credencial !== 'agenda') return;
        autoAbriuSeletor.current = true;
        carregarCalendarios();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [recemConectado, status?.fonte_credencial, status?.google_calendar_id]);

    const conectar = async () => {
        setSalvando(true);
        try {
            const authorizationUrl = await iniciarOAuthGoogleDaAgenda(agendaId, companyId, returnTo);
            window.location.href = authorizationUrl;
        } catch (erro) {
            toast.error(erro instanceof Error ? erro.message : 'Erro ao iniciar a conexão com o Google desta agenda.');
            setSalvando(false);
        }
    };

    const aplicarCalendario = async () => {
        if (!calendarioEscolhido) {
            toast.error('Selecione um calendário Google.');
            return;
        }
        setSalvando(true);
        try {
            const calendario = await definirCalendarioGoogleDaAgenda(agendaId, calendarioEscolhido, companyId);
            toast.success(`Calendário “${calendario.summary || calendario.id || calendarioEscolhido}” vinculado a esta agenda.`);
            setMostrarSeletor(false);
            setCalendarios(null);
            await carregarStatus();
            onAlterado?.();
        } catch (erro) {
            toast.error(erro instanceof Error ? erro.message : 'Erro ao definir o calendário Google desta agenda.');
        } finally {
            setSalvando(false);
        }
    };

    const desconectar = async () => {
        setSalvando(true);
        try {
            const resposta = await removerCredencialGoogleDaAgenda(agendaId, companyId);
            toast.success(resposta?.message || 'Credencial do Google removida desta agenda.');
            setConfirmarDesconexao(false);
            setMostrarSeletor(false);
            setCalendarios(null);
            await carregarStatus();
            onAlterado?.();
        } catch (erro) {
            toast.error(erro instanceof Error ? erro.message : 'Erro ao desconectar o Google desta agenda.');
        } finally {
            setSalvando(false);
        }
    };

    const fonte = status?.fonte_credencial ?? null;
    const pillLabel = carregando && !status
        ? 'Consultando…'
        : fonte === 'agenda'
            ? 'Credencial da agenda'
            : 'Sem Google';

    const semOAuthNoServidor = Boolean(status && !status.oauth_configured);
    const podeConectar = Boolean(status && status.oauth_configured);
    const calendarioAtual = status?.google_calendar_summary || status?.google_calendar_id || null;

    return (
        <section className={agentivePanelClass(isDark, 'mt-6 min-w-0 overflow-hidden')}>
            <header className={`flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-start sm:justify-between ${cardBorderClass}`}>
                <div className="flex min-w-0 items-start gap-3">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl border ${softBoxClass}`}>
                        <CalendarDays className={`h-4 w-4 ${isDark ? 'text-white/70' : 'text-brand/70'}`} />
                    </span>
                    <div className="min-w-0">
                        <h3 className="text-sm font-semibold">Google Calendar desta agenda</h3>
                        <p className={`mt-1 text-xs leading-relaxed ${mutedClass}`}>
                            Esta agenda usa somente a conta Google autorizada para o profissional correspondente.
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                            <span className={agentivePillClass(isDark, fonte === 'agenda')}>
                                {fonte === 'agenda' && <ShieldCheck className="h-3.5 w-3.5" />}
                                {pillLabel}
                            </span>
                            {status?.google_account_email && (
                                <span className={agentivePillClass(isDark)} title="Conta Google em uso por esta agenda">
                                    {status.google_account_email}
                                </span>
                            )}
                        </div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={carregarStatus}
                    disabled={carregando || salvando}
                    className={agentiveSecondaryButtonClass(isDark, 'py-1.5 text-xs')}
                >
                    {carregando ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    Atualizar
                </button>
            </header>

            <div className="space-y-3 p-4">
                {carregando && !status ? (
                    <div className="flex items-center gap-3">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span className={`text-sm ${mutedClass}`}>Consultando o Google desta agenda…</span>
                    </div>
                ) : erroStatus ? (
                    <AgentiveAlert variant="error" title="Não foi possível consultar o Google desta agenda">
                        {erroStatus}
                    </AgentiveAlert>
                ) : status ? (
                    <>
                        {semOAuthNoServidor && (
                            <AgentiveAlert variant="warning" title="OAuth do Google ainda não foi configurado">
                                Enquanto o Client ID e o Client Secret do Google não forem informados, nenhuma agenda consegue autorizar
                                uma conta. O Admin da plataforma cadastra esses dados no painel &ldquo;Credenciais do aplicativo Google&rdquo; no topo desta tela.
                            </AgentiveAlert>
                        )}

                        {fonte === 'agenda' && (
                            <AgentiveAlert variant="success" title="Credencial própria desta agenda">
                                O profissional autorizou a conta Google dele para esta agenda
                                {status.google_account_email ? <> (<strong>{status.google_account_email}</strong>)</> : null}.
                                Os eventos desta agenda são criados nessa conta, não na conta da clínica.
                            </AgentiveAlert>
                        )}

                        {fonte === null && (
                            <AgentiveAlert variant="warning" title="Nenhum Google conectado para esta agenda">
                                Conecte a conta Google do profissional para criar eventos e consultar a disponibilidade desta agenda.
                            </AgentiveAlert>
                        )}

                        <dl className="grid gap-3 sm:grid-cols-2">
                            {[
                                { rotulo: 'Calendário Google em uso', valor: calendarioAtual },
                                { rotulo: 'Calendar ID', valor: status.google_calendar_id },
                            ].map((item) => (
                                <div key={item.rotulo} className={`rounded-xl border px-3 py-2 ${softBoxClass}`}>
                                    <dt className={`text-[10px] font-bold uppercase tracking-[0.14em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                                        {item.rotulo}
                                    </dt>
                                    <dd className="mt-1 break-all text-sm font-medium">
                                        {item.valor || <span className={mutedClass}>Nenhum calendário escolhido</span>}
                                    </dd>
                                </div>
                            ))}
                        </dl>

                        <div className="flex flex-wrap items-center gap-2">
                            {podeGerenciar && podeConectar && (
                                <button type="button" onClick={conectar} disabled={salvando} className={agentivePrimaryButtonClass('px-4')}>
                                    {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                                    {fonte === 'agenda' ? 'Autorizar outra conta Google desta agenda' : 'Conectar o Google desta agenda'}
                                </button>
                            )}

                            {podeGerenciar && status.google_connected && (
                                <button
                                    type="button"
                                    onClick={() => (mostrarSeletor ? setMostrarSeletor(false) : carregarCalendarios())}
                                    disabled={salvando || carregandoCalendarios}
                                    className={agentiveSecondaryButtonClass(isDark, 'text-xs')}
                                >
                                    {carregandoCalendarios ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                                    {mostrarSeletor ? 'Fechar lista de calendários' : status.google_calendar_id ? 'Trocar calendário' : 'Escolher calendário'}
                                </button>
                            )}

                            {podeGerenciar && fonte === 'agenda' && (
                                <button
                                    type="button"
                                    onClick={() => setConfirmarDesconexao(true)}
                                    disabled={salvando}
                                    className={agentiveSecondaryButtonClass(isDark, 'text-xs')}
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                    Desconectar esta agenda
                                </button>
                            )}

                            {podeGerenciar && fonte !== 'agenda' && semOAuthNoServidor && (
                                <span className={`text-xs ${mutedClass}`}>Conectar fica indisponível até o Admin da plataforma cadastrar as credenciais do Google.</span>
                            )}
                        </div>

                        {mostrarSeletor && (
                            <div className={`rounded-2xl border p-4 ${cardBorderClass}`}>
                                <div className="flex items-center gap-2">
                                    {fonte === 'agenda' ? (
                                        <ShieldCheck className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                    ) : (
                                        <AlertCircle className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                    )}
                                    <h4 className="text-sm font-semibold">Escolha o calendário desta agenda</h4>
                                </div>
                                <p className={`mt-1 text-xs leading-relaxed ${mutedClass}`}>
                                    A lista vem da conta Google autorizada por esta agenda. Só aparecem calendários em que a conta é dona.
                                </p>

                                {carregandoCalendarios ? (
                                    <div className="mt-3 flex items-center gap-3">
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        <span className={`text-sm ${mutedClass}`}>Listando calendários…</span>
                                    </div>
                                ) : (calendarios?.length ?? 0) === 0 ? (
                                    <AgentiveAlert variant="warning" className="mt-3" title="Nenhum calendário disponível">
                                        A conta conectada não tem nenhum calendário em que seja dona. Crie um calendário no Google ou
                                        autorize outra conta.
                                    </AgentiveAlert>
                                ) : (
                                    <div className="mt-3 space-y-2">
                                        <label className="sr-only" htmlFor="agenda-google-calendario">Calendário Google</label>
                                        <select
                                            id="agenda-google-calendario"
                                            className={agentiveInputClass(isDark)}
                                            value={calendarioEscolhido}
                                            onChange={(event) => setCalendarioEscolhido(event.target.value)}
                                            disabled={salvando}
                                        >
                                            <option value="">Selecione um calendário</option>
                                            {(calendarios ?? []).map((calendario) => (
                                                <option key={calendario.id} value={calendario.id}>
                                                    {calendario.summary || calendario.id}
                                                    {calendario.primary ? ' (principal)' : ''}
                                                    {calendario.time_zone ? ` · ${calendario.time_zone}` : ''}
                                                </option>
                                            ))}
                                        </select>
                                        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                                            <button
                                                type="button"
                                                onClick={() => setMostrarSeletor(false)}
                                                disabled={salvando}
                                                className={agentiveSecondaryButtonClass(isDark)}
                                            >
                                                Cancelar
                                            </button>
                                            <button
                                                type="button"
                                                onClick={aplicarCalendario}
                                                disabled={salvando || !calendarioEscolhido}
                                                className={agentivePrimaryButtonClass('px-4')}
                                            >
                                                {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                                Usar este calendário
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex items-center gap-3">
                        <AlertCircle className="h-4 w-4" />
                        <span className={`text-sm ${mutedClass}`}>Status indisponível.</span>
                    </div>
                )}
            </div>

            <AgentiveConfirmModal
                cancelText="Manter conexão"
                confirmText="Desconectar"
                isLoading={salvando}
                isOpen={confirmarDesconexao}
                message={
                    <>
                        A agenda <strong>{agendaNome || status?.agenda_nome || 'desta profissional'}</strong> deixa de ter a conta Google
                        autorizada{status?.google_account_email ? ` (${status.google_account_email})` : ''}. Eventos já criados no Google não são apagados.
                    </>
                }
                onClose={() => setConfirmarDesconexao(false)}
                onConfirm={desconectar}
                title="Desconectar o Google desta agenda?"
                variant="danger"
            />
        </section>
    );
};

export default AgendaGoogleCalendarCard;
