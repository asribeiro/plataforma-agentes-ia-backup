import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    CalendarClock,
    CalendarDays,
    Check,
    Clock3,
    Copy,
    Globe2,
    Link2,
    Loader2,
    Lock,
    Plus,
    RefreshCw,
    Trash2,
    Unlink,
    UserRound,
    X,
} from 'lucide-react';
import { calendarApi, type Agenda, type AgendaCreate, type Schedule, type Slot } from '../services/calendar_api.ts';
import { mensagemDeErro, profissionaisApi, type Profissional } from '../services/clinicApi.ts';
import {
    createGoogleCalendarForAgenda,
    getGoogleCalendarIntegration,
    GoogleCalendarIntegration,
    GoogleCalendarOption,
    linkGoogleCalendarToAgenda,
    listGoogleCalendars,
    unlinkGoogleCalendarFromAgenda,
} from '../services/api';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
    AgentiveEmptyState,
    agentiveIconButtonClass,
    agentiveInputClass,
    agentiveLabelClass,
    agentivePanelClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';

/**
 * Agenda POR PROFISSIONAL (F1-11).
 *
 * A ordem da tela é a regra de negócio: primeiro o profissional, depois a agenda
 * dele. O backend (F1-10) garante 1 profissional = 1 agenda ATIVA, então a tela
 * não oferece "lista de agendas da empresa" — oferece o dono e o que o agente
 * oferece em nome dele.
 *
 * Horários trafegam como 'HH:MM:SS' na API e 'HH:MM' no <input type="time">.
 * A conversão vive em `paraApi` / `paraInput` para não depender de sorte.
 */

const DAY_LABELS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];

type TimeField =
    | 'morning_start'
    | 'morning_end'
    | 'afternoon_start'
    | 'afternoon_end'
    | 'night_start'
    | 'night_end';

const TIME_FIELDS: TimeField[] = [
    'morning_start',
    'morning_end',
    'afternoon_start',
    'afternoon_end',
    'night_start',
    'night_end',
];

const CAMPO_LABEL: Record<TimeField, string> = {
    morning_start: 'manhã início',
    morning_end: 'manhã fim',
    afternoon_start: 'tarde início',
    afternoon_end: 'tarde fim',
    night_start: 'noite início',
    night_end: 'noite fim',
};

const TURNOS: Array<{ rotulo: string; inicio: TimeField; fim: TimeField }> = [
    { rotulo: 'manhã', inicio: 'morning_start', fim: 'morning_end' },
    { rotulo: 'tarde', inicio: 'afternoon_start', fim: 'afternoon_end' },
    { rotulo: 'noite', inicio: 'night_start', fim: 'night_end' },
];

const TIMEZONES = [
    { valor: 'America/Sao_Paulo', rotulo: 'Brasília (BRT) - America/Sao_Paulo' },
    { valor: 'America/Manaus', rotulo: 'Manaus (AMT) - America/Manaus' },
    { valor: 'America/Belem', rotulo: 'Belém (BRT) - America/Belem' },
    { valor: 'America/Fortaleza', rotulo: 'Fortaleza (BRT) - America/Fortaleza' },
    { valor: 'America/Recife', rotulo: 'Recife (BRT) - America/Recife' },
    { valor: 'America/Cuiaba', rotulo: 'Cuiabá (AMT) - America/Cuiaba' },
    { valor: 'America/Porto_Velho', rotulo: 'Porto Velho (AMT) - America/Porto_Velho' },
    { valor: 'America/Boa_Vista', rotulo: 'Boa Vista (AMT) - America/Boa_Vista' },
    { valor: 'America/Maceio', rotulo: 'Maceió (BRT) - America/Maceio' },
    { valor: 'America/Bahia', rotulo: 'Salvador (BRT) - America/Bahia' },
    { valor: 'America/Rio_Branco', rotulo: 'Rio Branco (ACT) - America/Rio_Branco' },
    { valor: 'America/Noronha', rotulo: 'Fernando de Noronha (FNT) - America/Noronha' },
];

const TZ_PADRAO = 'America/Sao_Paulo';
const MARGEM_PADRAO = 30;

interface FormState {
    name: string;
    slot_duration: number;
    safety_margin_minutes: number;
    timezone: string;
    active: boolean;
    /** Sempre 7 entradas, day_of_week 0..6, horários em 'HH:MM'. */
    schedules: Schedule[];
}

type Banner = { variant: 'success' | 'error' | 'info' | 'warning'; titulo?: string; texto: React.ReactNode };

// ---------------------------------------------------------------------------
// Conversões de horário e formato
// ---------------------------------------------------------------------------

/** 'HH:MM' (input) -> 'HH:MM:SS' (API). Vazio -> null. */
const paraApi = (valor?: string | null): string | null => {
    if (!valor) return null;
    const limpo = valor.trim();
    if (!limpo) return null;
    return limpo.length === 5 ? `${limpo}:00` : limpo;
};

/** 'HH:MM:SS' (API) -> 'HH:MM' (input). */
const paraInput = (valor?: string | null): string | null => {
    if (!valor) return null;
    return valor.slice(0, 5);
};

const formatMargin = (minutes?: number | null) => {
    const valor = minutes ?? MARGEM_PADRAO;
    if (valor === 0) return 'Sem margem';
    if (valor < 60) return `${valor} min`;
    if (valor === 60) return '1 hora';
    if (valor % 1440 === 0) return valor / 1440 === 1 ? '1 dia' : `${valor / 1440} dias`;
    if (valor % 60 === 0) return `${valor / 60} horas`;
    return `${valor} min`;
};

const diaTemTurno = (schedule?: Schedule | null) =>
    Boolean(schedule && TIME_FIELDS.some((campo) => Boolean(schedule[campo])));

const isoDaData = (data: Date) => {
    const ano = data.getFullYear();
    const mes = `${data.getMonth() + 1}`.padStart(2, '0');
    const dia = `${data.getDate()}`.padStart(2, '0');
    return `${ano}-${mes}-${dia}`;
};

const maisDias = (data: Date, dias: number) => {
    const copia = new Date(data);
    copia.setDate(copia.getDate() + dias);
    return copia;
};

/** Relógio de parede 'YYYY-MM-DDTHH:MM:SS' no fuso da agenda. */
const relogioNoFuso = (timezone: string): string => {
    const agora = new Date();
    try {
        const partes = new Intl.DateTimeFormat('sv-SE', {
            timeZone: timezone,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }).format(agora);
        return partes.replace(' ', 'T');
    } catch {
        // Fuso desconhecido no runtime: cai para o relógio do navegador.
        const deslocamento = new Date(agora.getTime() - agora.getTimezoneOffset() * 60000);
        return deslocamento.toISOString().slice(0, 19);
    }
};

/** Soma minutos a um relógio de parede (string, sem fuso) e devolve string. */
const somarMinutos = (relogio: string, minutos: number): string => {
    const base = new Date(`${relogio}Z`);
    if (Number.isNaN(base.getTime())) return relogio;
    base.setUTCMinutes(base.getUTCMinutes() + minutos);
    return base.toISOString().slice(0, 19);
};

const formatarDiaHora = (relogio: string) => {
    const [data, hora = ''] = relogio.split('T');
    const [ano, mes, dia] = data.split('-');
    return `${dia}/${mes}/${ano} ${hora.slice(0, 5)}`;
};

const iniciais = (nome: string) =>
    nome
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((parte) => parte[0]?.toUpperCase() ?? '')
        .join('');

// ---------------------------------------------------------------------------
// Formulário
// ---------------------------------------------------------------------------

const formVazio = (nomeSugerido = ''): FormState => ({
    name: nomeSugerido,
    slot_duration: 30,
    safety_margin_minutes: MARGEM_PADRAO,
    timezone: TZ_PADRAO,
    active: true,
    schedules: DAY_LABELS.map((_, index) => ({ day_of_week: index })),
});

const formDeAgenda = (agenda: Agenda): FormState => {
    const porDia = new Map<number, Schedule>();
    (agenda.schedules || []).forEach((schedule) => {
        if (typeof schedule.day_of_week === 'number') porDia.set(schedule.day_of_week, schedule);
    });

    return {
        name: agenda.name ?? '',
        slot_duration: agenda.slot_duration ?? 30,
        safety_margin_minutes: agenda.safety_margin_minutes ?? MARGEM_PADRAO,
        timezone: agenda.timezone || TZ_PADRAO,
        active: agenda.active ?? true,
        schedules: DAY_LABELS.map((_, index) => {
            const origem = porDia.get(index);
            return {
                day_of_week: index,
                morning_start: paraInput(origem?.morning_start),
                morning_end: paraInput(origem?.morning_end),
                afternoon_start: paraInput(origem?.afternoon_start),
                afternoon_end: paraInput(origem?.afternoon_end),
                night_start: paraInput(origem?.night_start),
                night_end: paraInput(origem?.night_end),
            };
        }),
    };
};

const montarPayload = (form: FormState) => ({
    name: form.name.trim(),
    slot_duration: Math.trunc(form.slot_duration),
    active: form.active,
    timezone: form.timezone,
    safety_margin_minutes: Math.trunc(form.safety_margin_minutes),
    schedules: form.schedules.map((schedule) => ({
        day_of_week: schedule.day_of_week,
        morning_start: paraApi(schedule.morning_start),
        morning_end: paraApi(schedule.morning_end),
        afternoon_start: paraApi(schedule.afternoon_start),
        afternoon_end: paraApi(schedule.afternoon_end),
        night_start: paraApi(schedule.night_start),
        night_end: paraApi(schedule.night_end),
    })),
});

/**
 * O backend aceita turno pela metade (início sem fim) e simplesmente não gera
 * vaga nenhuma — o Dono veria "sem horário" sem entender por quê. Aqui a
 * inconsistência é explicada antes de salvar.
 */
const validarFormulario = (form: FormState): string | null => {
    if (!form.name.trim()) return 'Dê um nome à agenda — é como ela aparece para a equipe e para o agente.';
    if (!Number.isFinite(form.slot_duration) || form.slot_duration < 1) {
        return 'A duração do slot precisa ser de pelo menos 1 minuto.';
    }
    if (!Number.isFinite(form.safety_margin_minutes) || form.safety_margin_minutes < 0) {
        return 'A margem de segurança não pode ser negativa.';
    }

    for (const schedule of form.schedules) {
        for (const turno of TURNOS) {
            const inicio = schedule[turno.inicio];
            const fim = schedule[turno.fim];

            if (!inicio && !fim) continue;
            if (!inicio || !fim) {
                return `${DAY_LABELS[schedule.day_of_week]} (${turno.rotulo}): preencha início e fim, ou deixe os dois vazios. Turno pela metade não gera nenhum horário.`;
            }
            if (inicio >= fim) {
                return `${DAY_LABELS[schedule.day_of_week]} (${turno.rotulo}): o fim precisa ser depois do início.`;
            }
        }
    }

    return null;
};

// ---------------------------------------------------------------------------
// Tela
// ---------------------------------------------------------------------------

export const CalendarConfig: React.FC = () => {
    const { isDark } = useTheme();

    // --- profissionais (a primeira escolha da tela)
    const [profissionais, setProfissionais] = useState<Profissional[]>([]);
    const [agendasPorProfissional, setAgendasPorProfissional] = useState<Record<number, Agenda[]>>({});
    const [profissionalSelecionado, setProfissionalSelecionado] = useState<number | null>(null);
    const [carregandoProfissionais, setCarregandoProfissionais] = useState(true);
    const [erroProfissionais, setErroProfissionais] = useState<string | null>(null);

    // --- agenda do profissional escolhido
    const [agenda, setAgenda] = useState<Agenda | null>(null);
    const [carregandoAgenda, setCarregandoAgenda] = useState(false);
    const [erroAgenda, setErroAgenda] = useState<string | null>(null);

    // --- formulário
    const [form, setForm] = useState<FormState>(() => formVazio());
    const [salvando, setSalvando] = useState(false);
    const [banner, setBanner] = useState<Banner | null>(null);
    const [diaOrigem, setDiaOrigem] = useState(0);

    // --- prévia de horários
    const [slots, setSlots] = useState<Slot[]>([]);
    const [carregandoSlots, setCarregandoSlots] = useState(false);
    const [erroSlots, setErroSlots] = useState<string | null>(null);

    // --- vínculo Google (funcionalidade que já existia nesta tela)
    const [google, setGoogle] = useState<GoogleCalendarIntegration | null>(null);
    const [googleCalendars, setGoogleCalendars] = useState<GoogleCalendarOption[]>([]);
    const [linkAgenda, setLinkAgenda] = useState<Agenda | null>(null);
    const [selectedGoogleCalendarId, setSelectedGoogleCalendarId] = useState('');
    const [isCreatingGoogleCalendar, setIsCreatingGoogleCalendar] = useState(false);
    const [newGoogleCalendarName, setNewGoogleCalendarName] = useState('');
    const [agendaToUnlink, setAgendaToUnlink] = useState<Agenda | null>(null);

    const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
    const eyebrowClass = `text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`;
    const cardBorderClass = isDark ? 'border-white/10' : 'border-brand/10';
    const softBoxClass = isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas';

    const profissionaisRef = useRef<Profissional[]>([]);
    useEffect(() => {
        profissionaisRef.current = profissionais;
    }, [profissionais]);

    const profissionalAtual = useMemo(
        () => profissionais.find((p) => p.id === profissionalSelecionado) ?? null,
        [profissionais, profissionalSelecionado]
    );

    const isGoogleConnected = Boolean(google?.google_oauth_connected);
    const linkAgendaHasGoogleLink = Boolean(linkAgenda?.google_calendar_id);
    const linkedGoogleCalendarLabel = linkAgenda?.google_calendar_summary || linkAgenda?.google_calendar_id || '';

    // -----------------------------------------------------------------------
    // Carga
    // -----------------------------------------------------------------------

    const carregarMapaDeAgendas = useCallback(async () => {
        const agendas = await calendarApi.listAgendas({ incluir_inativas: true });
        const mapa: Record<number, Agenda[]> = {};
        agendas.forEach((item) => {
            const dono = item.professional_id;
            if (!dono) return;
            mapa[dono] = [...(mapa[dono] ?? []), item];
        });
        setAgendasPorProfissional(mapa);
    }, []);

    const carregarProfissionais = useCallback(async () => {
        setCarregandoProfissionais(true);
        setErroProfissionais(null);
        try {
            const lista = await profissionaisApi.listar(false);
            setProfissionais(lista);
            setProfissionalSelecionado((atual) => {
                if (atual && lista.some((p) => p.id === atual)) return atual;
                return lista[0]?.id ?? null;
            });
            await carregarMapaDeAgendas();
        } catch (erro) {
            setErroProfissionais(mensagemDeErro(erro));
        } finally {
            setCarregandoProfissionais(false);
        }
    }, [carregarMapaDeAgendas]);

    useEffect(() => {
        carregarProfissionais();
    }, [carregarProfissionais]);

    const slotsAlvo = useRef<number | null>(null);

    const carregarSlots = useCallback(async (agendaId: number) => {
        // Duas trocas de profissional em sequência podem deixar uma resposta
        // antiga chegando depois: só a última agenda pedida pinta a prévia.
        slotsAlvo.current = agendaId;
        setCarregandoSlots(true);
        setErroSlots(null);
        try {
            const hoje = new Date();
            const dados = await calendarApi.getSlots(agendaId, isoDaData(hoje), isoDaData(maisDias(hoje, 7)));
            if (slotsAlvo.current !== agendaId) return;
            setSlots(Array.isArray(dados) ? dados : []);
        } catch (erro) {
            if (slotsAlvo.current !== agendaId) return;
            setSlots([]);
            setErroSlots(mensagemDeErro(erro));
        } finally {
            if (slotsAlvo.current === agendaId) setCarregandoSlots(false);
        }
    }, []);

    // Agenda do profissional escolhido: GET /api/calendar/?professional_id=<id>
    useEffect(() => {
        if (!profissionalSelecionado) {
            setAgenda(null);
            setCarregandoAgenda(false);
            setForm(formVazio());
            setSlots([]);
            return;
        }

        let cancelado = false;
        setCarregandoAgenda(true);
        setErroAgenda(null);
        setBanner(null);
        setSlots([]);
        setErroSlots(null);

        calendarApi
            .listAgendas({ professional_id: profissionalSelecionado, incluir_inativas: true })
            .then((lista) => {
                if (cancelado) return;
                const ativa = lista.find((item) => item.active) ?? lista[0] ?? null;
                setAgenda(ativa);
                if (ativa) {
                    setForm(formDeAgenda(ativa));
                } else {
                    const dono = profissionaisRef.current.find((p) => p.id === profissionalSelecionado);
                    setForm(formVazio(dono ? `Agenda — ${dono.name}` : ''));
                }
                if (ativa?.active) {
                    carregarSlots(ativa.id);
                } else {
                    setSlots([]);
                }
            })
            .catch((erro) => {
                if (cancelado) return;
                setAgenda(null);
                setErroAgenda(mensagemDeErro(erro));
            })
            .finally(() => {
                if (!cancelado) setCarregandoAgenda(false);
            });

        return () => {
            cancelado = true;
        };
    }, [profissionalSelecionado, carregarSlots]);

    const carregarGoogle = useCallback(async () => {
        try {
            const dados = await getGoogleCalendarIntegration();
            setGoogle(dados);
            if (dados.google_oauth_connected) {
                const items = await listGoogleCalendars();
                setGoogleCalendars(items);
            } else {
                setGoogleCalendars([]);
            }
        } catch {
            setGoogleCalendars([]);
        }
    }, []);

    useEffect(() => {
        carregarGoogle();
    }, [carregarGoogle]);

    // -----------------------------------------------------------------------
    // Edição do formulário
    // -----------------------------------------------------------------------

    const payloadAtual = useMemo(() => JSON.stringify(montarPayload(form)), [form]);
    const payloadBase = useMemo(() => {
        const base = agenda ? formDeAgenda(agenda) : formVazio(form.name);
        return JSON.stringify(montarPayload(base));
    }, [agenda, form.name]);
    const alterado = payloadAtual !== payloadBase;
    const podeSalvar = (agenda ? alterado : true) && !salvando && Boolean(profissionalAtual);

    const atualizarTurno = (dia: number, campo: TimeField, valor: string) => {
        setForm((anterior) => ({
            ...anterior,
            schedules: anterior.schedules.map((schedule) => {
                if (schedule.day_of_week !== dia) return schedule;
                const proximo: Schedule = { ...schedule };
                proximo[campo] = valor === '' ? null : valor;
                return proximo;
            }),
        }));
    };

    const copiarTurnosDoDia = (origem: number) => {
        const base = form.schedules.find((s) => s.day_of_week === origem);
        if (!diaTemTurno(base)) {
            setBanner({
                variant: 'warning',
                titulo: 'Nada para copiar',
                texto: `${DAY_LABELS[origem]} está sem turnos. Preencha esse dia antes de copiar.`,
            });
            return;
        }

        setForm((anterior) => ({
            ...anterior,
            schedules: anterior.schedules.map((schedule) => {
                if (schedule.day_of_week === origem) return schedule;
                const copia: Schedule = { day_of_week: schedule.day_of_week };
                TIME_FIELDS.forEach((campo) => {
                    copia[campo] = base ? base[campo] ?? null : null;
                });
                return copia;
            }),
        }));
        setBanner({
            variant: 'info',
            titulo: `Turnos de ${DAY_LABELS[origem]} copiados`,
            texto: 'Os outros 6 dias receberam os mesmos horários. Nada foi gravado ainda — clique em Salvar alterações.',
        });
    };

    const limparDia = (dia: number) => {
        setForm((anterior) => ({
            ...anterior,
            schedules: anterior.schedules.map((schedule) => {
                if (schedule.day_of_week !== dia) return schedule;
                const limpo: Schedule = { day_of_week: dia };
                TIME_FIELDS.forEach((campo) => {
                    limpo[campo] = null;
                });
                return limpo;
            }),
        }));
    };

    const descartarAlteracoes = () => {
        setForm(agenda ? formDeAgenda(agenda) : formVazio(profissionalAtual ? `Agenda — ${profissionalAtual.name}` : ''));
        setBanner(null);
    };

    const salvar = async () => {
        if (!profissionalAtual) return;

        const problema = validarFormulario(form);
        if (problema) {
            setBanner({ variant: 'error', titulo: 'Corrija antes de salvar', texto: problema });
            return;
        }

        setSalvando(true);
        setBanner(null);

        try {
            const payload = { ...montarPayload(form), professional_id: profissionalAtual.id };
            const salva = agenda
                ? await calendarApi.updateAgenda(agenda.id, payload)
                : await calendarApi.createAgenda(payload as AgendaCreate);

            setAgenda(salva);
            setForm(formDeAgenda(salva));
            setBanner({
                variant: 'success',
                titulo: agenda ? 'Agenda atualizada' : 'Agenda criada',
                texto: agenda
                    ? `As alterações de ${profissionalAtual.name} já valem para o agente. A prévia abaixo foi recarregada.`
                    : `${profissionalAtual.name} agora tem agenda ativa. A prévia abaixo veio de GET /api/calendar/${salva.id}/slots.`,
            });

            if (salva.active) {
                await carregarSlots(salva.id);
            } else {
                setSlots([]);
            }
            await carregarMapaDeAgendas();
        } catch (erro) {
            // 409/404 do backend são mensagens de negócio escritas para o Dono:
            // vão para a tela exatamente como vieram.
            setBanner({ variant: 'error', titulo: 'A API recusou a alteração', texto: mensagemDeErro(erro) });
        } finally {
            setSalvando(false);
        }
    };

    // -----------------------------------------------------------------------
    // Google (comportamento anterior preservado)
    // -----------------------------------------------------------------------

    const openLinkModal = (destino: Agenda) => {
        setLinkAgenda(destino);
        setSelectedGoogleCalendarId(destino.google_calendar_id ? '' : googleCalendars[0]?.id || '');
        setIsCreatingGoogleCalendar(false);
        setNewGoogleCalendarName('');
    };

    const closeLinkModal = () => {
        setLinkAgenda(null);
        setIsCreatingGoogleCalendar(false);
        setNewGoogleCalendarName('');
    };

    const recarregarAgendaEAgendaMapa = async () => {
        await carregarMapaDeAgendas();
        if (agenda) {
            try {
                const atualizada = await calendarApi.getAgenda(agenda.id);
                setAgenda(atualizada);
                setForm(formDeAgenda(atualizada));
            } catch {
                /* mantém o que está na tela */
            }
        }
    };

    const handleLinkExisting = async () => {
        if (!linkAgenda || !selectedGoogleCalendarId) {
            setBanner({ variant: 'error', texto: 'Selecione uma agenda Google.' });
            return;
        }
        setSalvando(true);
        try {
            await linkGoogleCalendarToAgenda(linkAgenda.id, selectedGoogleCalendarId);
            closeLinkModal();
            await recarregarAgendaEAgendaMapa();
            setBanner({ variant: 'success', texto: 'Agenda vinculada ao Google Agenda.' });
        } catch (erro) {
            setBanner({ variant: 'error', titulo: 'Não foi possível vincular', texto: mensagemDeErro(erro) });
        } finally {
            setSalvando(false);
        }
    };

    const handleCreateAndLink = async () => {
        if (!linkAgenda || !newGoogleCalendarName.trim()) {
            setBanner({ variant: 'error', texto: 'Informe um nome para a nova agenda Google.' });
            return;
        }
        setSalvando(true);
        try {
            await createGoogleCalendarForAgenda(linkAgenda.id, newGoogleCalendarName.trim());
            closeLinkModal();
            await recarregarAgendaEAgendaMapa();
            setBanner({ variant: 'success', texto: 'Agenda Google criada e vinculada.' });
        } catch (erro) {
            setBanner({ variant: 'error', titulo: 'Não foi possível criar', texto: mensagemDeErro(erro) });
        } finally {
            setSalvando(false);
        }
    };

    const handleUnlink = async () => {
        if (!agendaToUnlink) return;
        setSalvando(true);
        try {
            await unlinkGoogleCalendarFromAgenda(agendaToUnlink.id);
            setAgendaToUnlink(null);
            await recarregarAgendaEAgendaMapa();
            setBanner({ variant: 'success', texto: 'Agenda Google desvinculada.' });
        } catch (erro) {
            setBanner({ variant: 'error', titulo: 'Não foi possível desvincular', texto: mensagemDeErro(erro) });
        } finally {
            setSalvando(false);
        }
    };

    // -----------------------------------------------------------------------
    // Prévia de horários
    // -----------------------------------------------------------------------

    const corteDaMargem = useMemo(() => {
        const fuso = form.timezone || TZ_PADRAO;
        const agora = relogioNoFuso(fuso);
        return somarMinutos(agora, Math.max(0, form.safety_margin_minutes || 0));
    }, [form.timezone, form.safety_margin_minutes]);

    const slotsPorDia = useMemo(() => {
        const mapa = new Map<string, Slot[]>();
        slots.forEach((slot) => {
            const dia = (slot.start_time || '').slice(0, 10);
            mapa.set(dia, [...(mapa.get(dia) ?? []), slot]);
        });
        return Array.from(mapa.entries())
            .sort(([a], [b]) => a.localeCompare(b))
            .slice(0, 3);
    }, [slots]);

    const vagasAntesDoCorte = useMemo(
        () => slots.filter((slot) => (slot.start_time || '') < corteDaMargem).length,
        [slots, corteDaMargem]
    );

    // -----------------------------------------------------------------------
    // Estados de carga / erro
    // -----------------------------------------------------------------------

    if (carregandoProfissionais) {
        return (
            <div className={agentivePanelClass(isDark, 'p-8')}>
                <div className="flex items-center justify-center gap-3">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span className="text-sm font-medium">Carregando profissionais</span>
                </div>
            </div>
        );
    }

    if (erroProfissionais) {
        return (
            <div className={agentivePanelClass(isDark, 'p-5')}>
                <AgentiveAlert variant="error" title="Não foi possível carregar os profissionais">
                    <p>{erroProfissionais}</p>
                    <button type="button" onClick={carregarProfissionais} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
                        <RefreshCw className="h-4 w-4" />
                        Tentar de novo
                    </button>
                </AgentiveAlert>
            </div>
        );
    }

    if (profissionais.length === 0) {
        return (
            <div className={agentivePanelClass(isDark, 'p-4')}>
                <AgentiveEmptyState
                    icon={UserRound}
                    title="Nenhum profissional ativo"
                    description="A agenda é sempre de um profissional. Cadastre (ou reative) um profissional para definir os horários que o agente pode oferecer em nome dele."
                    action={<a href="/profissionais" className={agentivePrimaryButtonClass('px-4')}>Ir para Profissionais</a>}
                />
            </div>
        );
    }

    const agendaDoProfissional = profissionalSelecionado ? agendasPorProfissional[profissionalSelecionado] ?? [] : [];
    const temAgendaAtiva = agendaDoProfissional.some((item) => item.active);

    // Agenda de profissional inativo não aparece na lista de ativos: sem este
    // aviso, o Dono conclui que a agenda desapareceu.
    const agendasSemDonoAtivo = Object.entries(agendasPorProfissional)
        .filter(([id]) => !profissionais.some((profissional) => profissional.id === Number(id)))
        .reduce((total, [, lista]) => total + lista.length, 0);

    return (
        <div className="space-y-4">
            {banner && (
                <AgentiveAlert variant={banner.variant} title={banner.titulo} onClose={() => setBanner(null)}>
                    {banner.texto}
                </AgentiveAlert>
            )}

            {/* 1. O profissional é a primeira escolha */}
            <section className={`rounded-2xl border p-4 sm:p-5 shadow-flat-md ${isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'}`}>
                <div className="flex flex-col gap-1">
                    <p className={eyebrowClass}>Passo 1 de 2</p>
                    <h2 className="text-lg font-semibold">De quem é a agenda?</h2>
                    <p className={`max-w-3xl text-sm ${mutedClass}`}>
                        Cada profissional tem <strong>uma única agenda ativa</strong>. Escolha o profissional para ver e ajustar o que o agente
                        oferece em nome dele — duração da vaga, margem de segurança, fuso e turnos.
                    </p>
                </div>

                {agendasSemDonoAtivo > 0 && (
                    <div className="mt-3">
                        <AgentiveAlert variant="info" title={`${agendasSemDonoAtivo} agenda(s) pertencem a profissional inativo`}>
                            A lista acima mostra apenas profissionais ativos, então essas agendas não aparecem. Reative o profissional em
                            {' '}
                            <strong>Profissionais</strong> para voltar a editar os horários dele — a agenda continua salva.
                        </AgentiveAlert>
                    </div>
                )}

                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                    {profissionais.map((profissional) => {
                        const selecionado = profissional.id === profissionalSelecionado;
                        const ativa = (agendasPorProfissional[profissional.id] ?? []).some((item) => item.active);
                        return (
                            <button
                                key={profissional.id}
                                type="button"
                                aria-pressed={selecionado}
                                onClick={() => setProfissionalSelecionado(profissional.id)}
                                className={`flex items-center gap-3 rounded-2xl border px-3 py-2.5 text-left transition ${
                                    selecionado
                                        ? 'border-brand-accent bg-brand-accent/5 ring-1 ring-brand-accent/30'
                                        : isDark
                                            ? 'border-white/10 bg-white/[0.04] hover:bg-white/[0.08]'
                                            : 'border-brand/10 bg-white hover:bg-brand-canvas'
                                }`}
                            >
                                <span
                                    className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-xs font-bold ${
                                        selecionado
                                            ? 'bg-brand-accent text-white'
                                            : isDark
                                                ? 'bg-white/10 text-white/70'
                                                : 'bg-brand-canvas text-brand/60'
                                    }`}
                                >
                                    {iniciais(profissional.name) || <UserRound className="h-4 w-4" />}
                                </span>
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-semibold">{profissional.name}</span>
                                    <span className={`block truncate text-[11px] ${mutedClass}`}>
                                        {profissional.cro ? `CRO ${profissional.cro}` : profissional.email}
                                    </span>
                                </span>
                                <span className={agentivePillClass(isDark, ativa, 'shrink-0')}>
                                    {ativa ? 'Agenda ativa' : 'Sem agenda'}
                                </span>
                            </button>
                        );
                    })}
                </div>
            </section>

            {/* 2. Agenda do profissional escolhido */}
            <section className={`rounded-2xl border shadow-flat-md ${isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'}`}>
                {carregandoAgenda ? (
                    <div className="flex items-center justify-center gap-3 p-8">
                        <Loader2 className="h-5 w-5 animate-spin" />
                        <span className="text-sm font-medium">Carregando agenda de {profissionalAtual?.name}</span>
                    </div>
                ) : erroAgenda ? (
                    <div className="p-4">
                        <AgentiveAlert variant="error" title="Não foi possível carregar a agenda">
                            <p>{erroAgenda}</p>
                        </AgentiveAlert>
                    </div>
                ) : !profissionalAtual ? (
                    <div className="p-4">
                        <AgentiveEmptyState
                            icon={UserRound}
                            title="Escolha um profissional"
                            description="A agenda pertence a um profissional. Selecione acima para ver os horários dele."
                        />
                    </div>
                ) : (
                    <>
                        <header className={`flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5 ${cardBorderClass}`}>
                            <div className="min-w-0">
                                <p className={eyebrowClass}>Passo 2 de 2</p>
                                <h2 className="mt-1 flex flex-wrap items-center gap-2 text-lg font-semibold">
                                    <CalendarDays className="h-5 w-5 shrink-0 opacity-60" />
                                    <span className="truncate">{agenda ? form.name || agenda.name : `Criar agenda para ${profissionalAtual.name}`}</span>
                                </h2>
                                <p className={`mt-1 text-sm ${mutedClass}`}>
                                    Agenda de <strong>{profissionalAtual.name}</strong> · {agenda ? '1 agenda ativa por profissional' : 'este profissional ainda não tem agenda'}
                                </p>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <span className={agentivePillClass(isDark, Boolean(agenda?.active))}>
                                    {agenda ? (agenda.active ? 'Ativa' : 'Inativa') : 'Sem agenda'}
                                </span>
                                {agenda && (
                                    <>
                                        <span className={agentivePillClass(isDark)} title="Duração de cada vaga">
                                            <Clock3 className="h-3.5 w-3.5" />
                                            {form.slot_duration} min
                                        </span>
                                        <span className={agentivePillClass(isDark)} title="Margem de segurança">
                                            {formatMargin(form.safety_margin_minutes)}
                                        </span>
                                    </>
                                )}
                            </div>
                        </header>

                        {agenda && !agenda.active && (
                            <div className="px-4 pt-4 sm:px-5">
                                <AgentiveAlert variant="warning" title="Agenda inativa">
                                    Enquanto estiver inativa, a API de horários devolve lista vazia: o agente não oferece nenhuma vaga deste profissional.
                                    Marque “Agenda ativa” e salve para voltar a oferecer.
                                </AgentiveAlert>
                            </div>
                        )}

                        <div className="p-4 sm:p-5">
                            {!agenda && !temAgendaAtiva && (
                                <div className="mb-5">
                                    <AgentiveEmptyState
                                        icon={CalendarDays}
                                        title={`${profissionalAtual.name} ainda não tem agenda`}
                                        description="Sem agenda, nenhum horário é oferecido em nome deste profissional. Preencha abaixo e crie a primeira — ela já nasce vinculada a ele."
                                    />
                                </div>
                            )}

                            {/* Nome + status */}
                            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                                <div>
                                    <label className={agentiveLabelClass(isDark)} htmlFor="agenda-nome">Nome da agenda</label>
                                    <input
                                        id="agenda-nome"
                                        type="text"
                                        className={agentiveInputClass(isDark)}
                                        value={form.name}
                                        placeholder={`Agenda — ${profissionalAtual.name}`}
                                        onChange={(event) => setForm({ ...form, name: event.target.value })}
                                    />
                                    <p className={`mt-1.5 text-xs ${mutedClass}`}>Identifica a agenda na equipe e nos vínculos do Google.</p>
                                </div>
                                <div>
                                    <span className={agentiveLabelClass(isDark)}>Status</span>
                                    <label className={`flex min-h-10 items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold ${softBoxClass}`}>
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
                                            checked={form.active}
                                            onChange={(event) => setForm({ ...form, active: event.target.checked })}
                                        />
                                        Agenda ativa
                                    </label>
                                    <p className={`mt-1.5 text-xs ${mutedClass}`}>
                                        Só a agenda ativa é oferecida. Ativar esta desativa a oferta de qualquer outra do mesmo profissional.
                                    </p>
                                </div>
                            </div>

                            {/* Regras: duração, margem, fuso */}
                            <div className={`mt-6 rounded-2xl border p-4 ${cardBorderClass}`}>
                                <div className="mb-3 flex items-center gap-2">
                                    <Globe2 className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                    <h3 className="text-sm font-semibold">Como o agente monta e oferece a vaga</h3>
                                </div>

                                <div className="grid gap-4 lg:grid-cols-3">
                                    <div>
                                        <label className={agentiveLabelClass(isDark)} htmlFor="agenda-duracao">Duração do slot (min)</label>
                                        <input
                                            id="agenda-duracao"
                                            type="number"
                                            min={5}
                                            step={5}
                                            className={agentiveInputClass(isDark)}
                                            value={Number.isFinite(form.slot_duration) ? form.slot_duration : ''}
                                            onChange={(event) =>
                                                setForm({ ...form, slot_duration: event.target.value === '' ? 0 : Number(event.target.value) })
                                            }
                                        />
                                        <p className={`mt-1.5 text-xs ${mutedClass}`}>
                                            Define o tamanho da vaga. Com 30 min e turno de 08:00 às 12:00, o agente oferece 08:00, 08:30, 09:00…
                                        </p>
                                    </div>

                                    <div>
                                        <label className={agentiveLabelClass(isDark)} htmlFor="agenda-margem">Margem de segurança (min)</label>
                                        <input
                                            id="agenda-margem"
                                            type="number"
                                            min={0}
                                            step={15}
                                            className={agentiveInputClass(isDark)}
                                            value={Number.isFinite(form.safety_margin_minutes) ? form.safety_margin_minutes : ''}
                                            onChange={(event) =>
                                                setForm({
                                                    ...form,
                                                    safety_margin_minutes: event.target.value === '' ? 0 : Number(event.target.value),
                                                })
                                            }
                                        />
                                        <p className={`mt-1.5 text-xs ${mutedClass}`}>
                                            Nenhum horário antes de <strong>agora + esta margem</strong> é oferecido — é o que evita oferecer vaga em cima da hora.
                                            0 oferece o próximo horário livre.
                                        </p>
                                    </div>

                                    <div>
                                        <label className={agentiveLabelClass(isDark)} htmlFor="agenda-fuso">Fuso horário</label>
                                        <select
                                            id="agenda-fuso"
                                            className={agentiveInputClass(isDark)}
                                            value={form.timezone || TZ_PADRAO}
                                            onChange={(event) => setForm({ ...form, timezone: event.target.value })}
                                        >
                                            {TIMEZONES.map((tz) => (
                                                <option key={tz.valor} value={tz.valor}>{tz.rotulo}</option>
                                            ))}
                                        </select>
                                        <p className={`mt-1.5 text-xs ${mutedClass}`}>
                                            Fuso em que os turnos são lidos e em que “agora” é calculado para a margem.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {/* Turnos por dia */}
                            <div className={`mt-6 overflow-hidden rounded-2xl border ${cardBorderClass}`}>
                                <div className={`flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${cardBorderClass} ${isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}`}>
                                    <div className="flex items-center gap-2">
                                        <CalendarClock className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                        <h3 className="text-sm font-semibold">Turnos por dia da semana</h3>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <label className={`text-xs font-medium ${mutedClass}`} htmlFor="copiar-dia">Copiar de</label>
                                        <select
                                            id="copiar-dia"
                                            className={agentiveInputClass(isDark, 'w-auto py-1.5 text-xs')}
                                            value={diaOrigem}
                                            onChange={(event) => setDiaOrigem(Number(event.target.value))}
                                        >
                                            {DAY_LABELS.map((dia, index) => (
                                                <option key={dia} value={index}>{dia}</option>
                                            ))}
                                        </select>
                                        <button type="button" onClick={() => copiarTurnosDoDia(diaOrigem)} className={agentiveSecondaryButtonClass(isDark, 'py-1.5 text-xs')}>
                                            <Copy className="h-3.5 w-3.5" />
                                            Copiar para os outros dias
                                        </button>
                                        <button type="button" onClick={() => limparDia(diaOrigem)} className={agentiveSecondaryButtonClass(isDark, 'py-1.5 text-xs')}>
                                            <Trash2 className="h-3.5 w-3.5" />
                                            Limpar dia
                                        </button>
                                    </div>
                                </div>

                                <div className="overflow-x-auto">
                                    <table className="w-full min-w-[860px] divide-y divide-brand/10 text-sm">
                                        <thead className={isDark ? 'bg-white/[0.04] text-white/45' : 'bg-brand-canvas text-brand/45'}>
                                            <tr className="text-left text-[10px] font-bold uppercase tracking-[0.16em]">
                                                <th className="px-3 py-2">Dia</th>
                                                <th className="px-3 py-2 text-center" colSpan={2}>Manhã</th>
                                                <th className="px-3 py-2 text-center" colSpan={2}>Tarde</th>
                                                <th className="px-3 py-2 text-center" colSpan={2}>Noite</th>
                                                <th className="px-3 py-2 text-right">Ações</th>
                                            </tr>
                                            <tr className="text-center text-[10px] font-medium">
                                                <th />
                                                <th className="pb-2">Início</th>
                                                <th className="pb-2">Fim</th>
                                                <th className="pb-2">Início</th>
                                                <th className="pb-2">Fim</th>
                                                <th className="pb-2">Início</th>
                                                <th className="pb-2">Fim</th>
                                                <th />
                                            </tr>
                                        </thead>
                                        <tbody className={isDark ? 'divide-white/10' : 'divide-brand/10'}>
                                            {DAY_LABELS.map((dia, index) => {
                                                const schedule = form.schedules.find((item) => item.day_of_week === index);
                                                const fechado = !diaTemTurno(schedule);
                                                return (
                                                    <tr key={dia} className={isDark ? 'hover:bg-white/[0.04]' : 'hover:bg-brand-canvas/70'}>
                                                        <td className="whitespace-nowrap px-3 py-2">
                                                            <span className="flex items-center gap-2 font-semibold">
                                                                {dia}
                                                                {fechado && <span className={`text-[10px] font-medium ${mutedClass}`}>sem atendimento</span>}
                                                            </span>
                                                        </td>
                                                        {TIME_FIELDS.map((campo) => (
                                                            <td key={campo} className="px-1 py-1">
                                                                <input
                                                                    type="time"
                                                                    aria-label={`${dia} ${CAMPO_LABEL[campo]}`}
                                                                    className={agentiveInputClass(isDark, 'min-w-[92px] px-2 py-1.5 text-xs')}
                                                                    value={schedule?.[campo] ?? ''}
                                                                    onChange={(event) => atualizarTurno(index, campo, event.target.value)}
                                                                />
                                                            </td>
                                                        ))}
                                                        <td className="px-2 py-1">
                                                            <div className="flex items-center justify-end gap-1">
                                                                <button
                                                                    type="button"
                                                                    onClick={() => copiarTurnosDoDia(index)}
                                                                    className={agentiveIconButtonClass(isDark, 'neutral')}
                                                                    title={`Copiar turnos de ${dia} para os outros dias`}
                                                                >
                                                                    <Copy className="h-4 w-4" />
                                                                </button>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => limparDia(index)}
                                                                    className={agentiveIconButtonClass(isDark, 'danger')}
                                                                    title={`Limpar turnos de ${dia}`}
                                                                >
                                                                    <Trash2 className="h-4 w-4" />
                                                                </button>
                                                            </div>
                                                        </td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                                <div className={`border-t px-4 py-2 text-xs ${cardBorderClass} ${mutedClass}`}>
                                    Deixe início e fim vazios no dia em que o profissional não atende. Turno pela metade não gera nenhum horário.
                                </div>
                            </div>

                            {/* Barra de salvar */}
                            <div className="mt-6 flex flex-col gap-2 border-t border-brand/10 pt-4 sm:flex-row sm:items-center sm:justify-between">
                                <p className={`text-xs ${mutedClass}`}>
                                    {agenda
                                        ? alterado ? 'Há alterações não salvas.' : 'Tudo salvo.'
                                        : 'Esta agenda ainda não existe — ela será criada vinculada a este profissional.'}
                                </p>
                                <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                                    <button
                                        type="button"
                                        onClick={descartarAlteracoes}
                                        disabled={!agenda || !alterado || salvando}
                                        className={agentiveSecondaryButtonClass(isDark)}
                                    >
                                        Descartar
                                    </button>
                                    <button type="button" onClick={salvar} disabled={!podeSalvar} className={agentivePrimaryButtonClass('px-4')}>
                                        {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : agenda ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                                        {agenda ? 'Salvar alterações' : 'Criar agenda'}
                                    </button>
                                </div>
                            </div>

                            {/* Credencial — somente leitura */}
                            <div className={`mt-6 rounded-2xl border p-4 ${cardBorderClass}`}>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Lock className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                    <h3 className="text-sm font-semibold">Credencial de calendário desta agenda</h3>
                                    <span className={agentivePillClass(isDark)}>Somente leitura</span>
                                </div>

                                <dl className="mt-3 grid gap-3 sm:grid-cols-3">
                                    {[
                                        { rotulo: 'Google Calendar ID', valor: agenda?.google_calendar_id },
                                        { rotulo: 'Agenda Google', valor: agenda?.google_calendar_summary },
                                        { rotulo: 'Fuso da agenda Google', valor: agenda?.google_calendar_time_zone },
                                    ].map((item) => (
                                        <div key={item.rotulo} className={`rounded-xl border px-3 py-2 ${softBoxClass}`}>
                                            <dt className={`text-[10px] font-bold uppercase tracking-[0.14em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                                                {item.rotulo}
                                            </dt>
                                            <dd className="mt-1 break-all text-sm font-medium">
                                                {item.valor || <span className={mutedClass}>Não vinculado</span>}
                                            </dd>
                                        </div>
                                    ))}
                                </dl>

                                <p className={`mt-3 text-xs leading-relaxed ${mutedClass}`}>
                                    Hoje a credencial é <strong>da empresa</strong>: a conta Google conectada em Integrações atende as agendas da clínica.
                                    A credencial por profissional é o card <strong>F1-06</strong> — esta tela não edita esses campos.
                                </p>

                                {agenda && (
                                    <div className="mt-3 flex flex-wrap items-center gap-2">
                                        {agenda.google_calendar_id ? (
                                            <button type="button" onClick={() => setAgendaToUnlink(agenda)} disabled={salvando} className={agentiveSecondaryButtonClass(isDark, 'py-1.5 text-xs')}>
                                                <Unlink className="h-3.5 w-3.5" />
                                                Desvincular agenda Google
                                            </button>
                                        ) : (
                                            <button
                                                type="button"
                                                onClick={() => openLinkModal(agenda)}
                                                disabled={salvando}
                                                className={agentiveSecondaryButtonClass(isDark, 'py-1.5 text-xs')}
                                                title={isGoogleConnected ? 'Vincular a uma agenda Google da conta conectada' : 'Conecte o Google na aba Integrações primeiro'}
                                            >
                                                <Link2 className="h-3.5 w-3.5" />
                                                Vincular agenda Google
                                            </button>
                                        )}
                                        {!isGoogleConnected && (
                                            <span className={`text-xs ${mutedClass}`}>Google Agenda não conectado — aba Integrações.</span>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Prévia de horários */}
                            <div className={`mt-6 overflow-hidden rounded-2xl border ${cardBorderClass}`}>
                                <div className={`flex flex-col gap-2 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${cardBorderClass} ${isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}`}>
                                    <div className="flex items-center gap-2">
                                        <Clock3 className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                        <h3 className="text-sm font-semibold">Prévia de horários</h3>
                                        <span className={agentivePillClass(isDark)}>hoje + 7 dias</span>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => (agenda ? carregarSlots(agenda.id) : undefined)}
                                        disabled={!agenda || carregandoSlots}
                                        className={agentiveSecondaryButtonClass(isDark, 'py-1.5 text-xs')}
                                    >
                                        {carregandoSlots ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                                        Recarregar
                                    </button>
                                </div>

                                <div className="p-4">
                                    {!agenda ? (
                                        <p className={`text-sm ${mutedClass}`}>
                                            A prévia aparece depois que a agenda existir: ela é a resposta real de <code>GET /api/calendar/&#123;id&#125;/slots</code>.
                                        </p>
                                    ) : carregandoSlots ? (
                                        <div className="flex items-center gap-3">
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                            <span className={`text-sm ${mutedClass}`}>Consultando horários…</span>
                                        </div>
                                    ) : erroSlots ? (
                                        <AgentiveAlert variant="error" title="A API de horários falhou">{erroSlots}</AgentiveAlert>
                                    ) : !agenda.active ? (
                                        <p className={`text-sm ${mutedClass}`}>
                                            Agenda inativa: a API devolve <strong>lista vazia</strong> de horários para ela.
                                        </p>
                                    ) : slots.length === 0 ? (
                                        <p className={`text-sm ${mutedClass}`}>
                                            Nenhum horário nos próximos 7 dias. Confira se os turnos desta agenda cobrem os dias da semana e salve.
                                        </p>
                                    ) : (
                                        <div className="space-y-3">
                                            <p className={`text-xs ${mutedClass}`}>
                                                {slots.length} vagas devolvidas pela API · {Math.max(0, slots.length - vagasAntesDoCorte)} depois do corte da margem
                                                {vagasAntesDoCorte > 0 ? ` · ${vagasAntesDoCorte} seriam descartadas por estarem dentro da margem` : ''}.
                                            </p>

                                            {slotsPorDia.map(([dia, lista]) => (
                                                <div key={dia}>
                                                    <p className={`mb-1.5 text-[10px] font-bold uppercase tracking-[0.14em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                                                        {DAY_LABELS[(new Date(`${dia}T12:00:00`).getDay() + 6) % 7]} · {dia.split('-').reverse().join('/')}
                                                    </p>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {lista.slice(0, 8).map((slot) => {
                                                            const antesDoCorte = (slot.start_time || '') < corteDaMargem;
                                                            return (
                                                                <span
                                                                    key={`${slot.start_time}-${slot.end_time}`}
                                                                    title={
                                                                        antesDoCorte
                                                                            ? 'Antes de agora + margem de segurança: o agente não oferece este horário'
                                                                            : 'Oferecido pelo agente'
                                                                    }
                                                                    className={
                                                                        antesDoCorte
                                                                            ? `inline-flex items-center rounded-lg border border-brand/10 bg-white px-2 py-1 text-xs line-through ${isDark ? 'border-white/10 bg-white/[0.04] text-white/40' : 'text-brand/40'}`
                                                                            : `inline-flex items-center rounded-lg border px-2 py-1 text-xs font-semibold ${isDark ? 'border-white/10 bg-white/[0.08] text-white' : 'border-brand/10 bg-brand-canvas text-brand'}`
                                                                    }
                                                                >
                                                                    {(slot.start_time || '').slice(11, 16)}
                                                                </span>
                                                            );
                                                        })}
                                                        {lista.length > 8 && (
                                                            <span className={`inline-flex items-center px-1 py-1 text-xs ${mutedClass}`}>+{lista.length - 8}</span>
                                                        )}
                                                    </div>
                                                </div>
                                            ))}

                                            <div className={`rounded-xl border px-3 py-2 text-xs ${softBoxClass}`}>
                                                <p className="font-semibold">Corte da margem: {formatarDiaHora(corteDaMargem)}</p>
                                                <p className={`mt-1 leading-relaxed ${mutedClass}`}>
                                                    Calculado nesta tela como <strong>agora no fuso {form.timezone || TZ_PADRAO} + {formatMargin(form.safety_margin_minutes)}</strong>.
                                                    Horários riscados ficam antes desse corte. A rota de prévia não aplica a margem — quem aplica é o agente no
                                                    momento de oferecer a vaga, então a marcação acima é a leitura honesta do que ele vai descartar.
                                                </p>
                                            </div>
                                        </div>
                                    )}

                                    <p className={`mt-3 text-xs ${mutedClass}`}>
                                        Prévia calculada com o que está <strong>salvo</strong>. Mudou margem ou turno? Salve e recarregue.
                                    </p>
                                </div>
                            </div>
                        </div>
                    </>
                )}
            </section>

            {/* Modal de vínculo Google — comportamento anterior preservado */}
            {linkAgenda && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
                    <div className="fixed inset-0 bg-brand/55 backdrop-blur-sm" onClick={salvando ? undefined : closeLinkModal} />
                    <div className={`relative z-[10000] w-full max-w-xl overflow-hidden rounded-2xl border p-5 shadow-[0_24px_70px_rgba(17,17,17,0.28)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className="flex items-start justify-between gap-4">
                            <div className="flex items-start gap-3">
                                <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <Link2 className="h-5 w-5" />
                                </span>
                                <div>
                                    <h3 className="text-base font-semibold leading-tight">Vincular Google Agenda</h3>
                                    <p className={`mt-1.5 text-sm leading-relaxed ${mutedClass}`}>{linkAgenda.name}</p>
                                </div>
                            </div>
                            <button type="button" onClick={closeLinkModal} disabled={salvando} className={agentiveIconButtonClass(isDark)} aria-label="Fechar modal">
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="mt-5">
                            {linkAgendaHasGoogleLink ? (
                                <div className={`rounded-2xl border p-4 ${isDark ? 'border-amber-400/20 bg-amber-400/10' : 'border-amber-200 bg-amber-50'}`}>
                                    <p className={`text-sm font-semibold ${isDark ? 'text-amber-100' : 'text-amber-900'}`}>Esta agenda já tem um vínculo Google</p>
                                    <p className={`mt-2 text-sm leading-relaxed ${isDark ? 'text-amber-100/75' : 'text-amber-900/70'}`}>
                                        Para trocar por outra agenda Google, desvincule o vínculo atual e depois vincule novamente usando uma agenda disponível na integração.
                                    </p>
                                    <div className={`mt-4 rounded-xl border px-3 py-2 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-amber-200/70 bg-white/70'}`}>
                                        <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Vínculo atual</p>
                                        <p className="mt-1 truncate text-sm font-semibold" title={linkedGoogleCalendarLabel || undefined}>
                                            {linkedGoogleCalendarLabel}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (!linkAgenda) return;
                                            const alvo = linkAgenda;
                                            closeLinkModal();
                                            setAgendaToUnlink(alvo);
                                        }}
                                        disabled={salvando}
                                        className={agentiveSecondaryButtonClass(isDark, 'mt-4')}
                                    >
                                        <Unlink className="h-4 w-4" />
                                        Desvincular vínculo atual
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-5">
                                    <div>
                                        <label className={agentiveLabelClass(isDark)} htmlFor="google-agenda-existente">Agenda Google existente</label>
                                        <select
                                            id="google-agenda-existente"
                                            value={selectedGoogleCalendarId}
                                            onChange={(event) => setSelectedGoogleCalendarId(event.target.value)}
                                            disabled={salvando || googleCalendars.length === 0}
                                            className={agentiveInputClass(isDark)}
                                        >
                                            <option value="">{googleCalendars.length === 0 ? 'Nenhuma agenda Google disponível' : 'Selecione uma agenda Google'}</option>
                                            {googleCalendars.map((calendar) => (
                                                <option key={calendar.id} value={calendar.id}>
                                                    {calendar.summary || calendar.id}
                                                    {calendar.primary ? ' (principal)' : ''}
                                                </option>
                                            ))}
                                        </select>
                                        <p className={`mt-1.5 text-xs ${mutedClass}`}>
                                            A lista mostra apenas agendas disponíveis na conta Google conectada em Integrações.
                                        </p>
                                        <button type="button" onClick={handleLinkExisting} disabled={salvando || !selectedGoogleCalendarId} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
                                            {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
                                            Vincular existente
                                        </button>
                                    </div>

                                    <div className={`rounded-2xl border p-4 ${softBoxClass}`}>
                                        {!isCreatingGoogleCalendar ? (
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setIsCreatingGoogleCalendar(true);
                                                    setNewGoogleCalendarName('');
                                                }}
                                                disabled={salvando}
                                                className={agentiveSecondaryButtonClass(isDark)}
                                            >
                                                <Plus className="h-4 w-4" />
                                                Criar nova agenda Google
                                            </button>
                                        ) : (
                                            <div>
                                                <div className="mb-3 flex items-start justify-between gap-3">
                                                    <label className={`block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`} htmlFor="nova-agenda-google">
                                                        Nome da nova agenda Google
                                                    </label>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            setIsCreatingGoogleCalendar(false);
                                                            setNewGoogleCalendarName('');
                                                        }}
                                                        disabled={salvando}
                                                        className={`text-xs font-semibold transition-colors ${isDark ? 'text-white/50 hover:text-white' : 'text-brand/50 hover:text-brand'}`}
                                                    >
                                                        Cancelar
                                                    </button>
                                                </div>
                                                <input
                                                    id="nova-agenda-google"
                                                    autoFocus
                                                    value={newGoogleCalendarName}
                                                    onChange={(event) => setNewGoogleCalendarName(event.target.value)}
                                                    disabled={salvando}
                                                    placeholder="Digite o nome da agenda"
                                                    className={agentiveInputClass(isDark)}
                                                />
                                                <button type="button" onClick={handleCreateAndLink} disabled={salvando || !newGoogleCalendarName.trim()} className={agentivePrimaryButtonClass('mt-3 px-4')}>
                                                    {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                                                    Criar e vincular
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <AgentiveConfirmModal
                cancelText="Manter vínculo"
                confirmText="Desvincular"
                isLoading={salvando}
                isOpen={Boolean(agendaToUnlink)}
                message={(
                    <>
                        A agenda local <strong>{agendaToUnlink?.name}</strong> deixará de criar novos eventos nesse Google Agenda. Eventos já existentes no Google não serão apagados.
                    </>
                )}
                onClose={() => setAgendaToUnlink(null)}
                onConfirm={handleUnlink}
                title="Desvincular Google Agenda?"
                variant="warning"
            />
        </div>
    );
};
