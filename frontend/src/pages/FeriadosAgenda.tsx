/**
 * Feriados da agenda — a tela onde o ADMIN DA CLÍNICA decide quem trabalha no feriado.
 *
 * Como a regra funciona (e o que esta tela NÃO faz):
 *   - feriado fechado = nenhum profissional atende naquele dia;
 *   - liberar profissional = aquele profissional volta a ter horário no feriado;
 *   - só o admin da clínica libera (`pode_configurar`); cadastrar feriado é do admin da
 *     plataforma (`admin_plataforma`) — a tela mostra o botão só para quem pode;
 *   - feriado NÃO cancela paciente: quando já existe agendamento no dia, a tela avisa quantos
 *     são, e a decisão (remarcar ou manter) é do admin.
 *
 * A disponibilidade vem do backend (`backend/services/feriados.py`), a mesma função que o agente
 * do WhatsApp usa. Nada é recalculado aqui — tela e agente não podem divergir.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    CalendarOff,
    CalendarCheck,
    Loader2,
    RefreshCw,
    AlertTriangle,
    UserCheck,
    Download,
} from 'lucide-react';
import { feriadosApi, type Feriado, type FeriadosDoAno } from '../services/feriadosApi.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';

const ROTULO_TIPO: Record<string, string> = {
    nacional: 'Nacional',
    estadual: 'Estadual',
    municipal: 'Municipal',
    pontual: 'Pontual',
};

const formatarDia = (iso: string) => {
    const [ano, mes, dia] = iso.split('-');
    return `${dia}/${mes}/${ano}`;
};

const diaDaSemana = (iso: string) => {
    const data = new Date(`${iso}T12:00:00`);
    return ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'][data.getDay()];
};

const FeriadosAgenda: React.FC = () => {
    const { isDark } = useTheme();
    const [ano, setAno] = useState<number>(() => new Date().getFullYear());
    const [dados, setDados] = useState<FeriadosDoAno | null>(null);
    const [carregando, setCarregando] = useState(true);
    const [salvando, setSalvando] = useState<number | null>(null);
    const [erro, setErro] = useState<string | null>(null);
    const [aviso, setAviso] = useState<string | null>(null);

    const carregar = useCallback(async (anoAlvo: number) => {
        setCarregando(true);
        setErro(null);
        try {
            const resposta = await feriadosApi.listar(anoAlvo);
            setDados(resposta);
        } catch (e: any) {
            const status = e?.response?.status;
            setErro(
                status === 403
                    ? 'Seu usuário não tem permissão para ver os feriados desta clínica.'
                    : `Não consegui carregar os feriados de ${anoAlvo}.`,
            );
        } finally {
            setCarregando(false);
        }
    }, []);

    useEffect(() => {
        void carregar(ano);
    }, [ano, carregar]);

    const alternarProfissional = async (feriado: Feriado, professionalId: number) => {
        if (!dados?.pode_configurar) return;
        const atual = new Set(feriado.liberados);
        if (atual.has(professionalId)) {
            atual.delete(professionalId);
        } else {
            atual.add(professionalId);
        }
        const novaLista = Array.from(atual);

        setSalvando(feriado.id);
        setErro(null);
        setAviso(null);
        // otimista: a tela responde na hora; se o backend recusar, volta atrás
        setDados((anterior) =>
            anterior
                ? {
                      ...anterior,
                      feriados: anterior.feriados.map((item) =>
                          item.id === feriado.id ? { ...item, liberados: novaLista } : item,
                      ),
                  }
                : anterior,
        );

        try {
            await feriadosApi.definirLiberacoes(feriado.id, novaLista);
            setAviso(
                novaLista.length === 0
                    ? `${formatarDia(feriado.data)}: nenhum profissional trabalha — dia fechado.`
                    : `${formatarDia(feriado.data)}: ${novaLista.length} profissional(is) liberado(s).`,
            );
        } catch (e: any) {
            setDados((anterior) =>
                anterior
                    ? {
                          ...anterior,
                          feriados: anterior.feriados.map((item) =>
                              item.id === feriado.id ? { ...item, liberados: feriado.liberados } : item,
                          ),
                      }
                    : anterior,
            );
            setErro(
                e?.response?.status === 403
                    ? 'Só o admin da clínica pode mudar quem trabalha no feriado.'
                    : 'Não consegui salvar essa liberação.',
            );
        } finally {
            setSalvando(null);
        }
    };

    const importarNacionais = async () => {
        setErro(null);
        setAviso(null);
        try {
            const resultado = await feriadosApi.importar(ano);
            setAviso(
                resultado.importados > 0
                    ? `${resultado.importados} feriado(s) nacional(is) importado(s) para ${ano}.`
                    : `Os feriados nacionais de ${ano} já estavam cadastrados.`,
            );
            await carregar(ano);
        } catch (e: any) {
            setErro(
                e?.response?.status === 403
                    ? 'Importar feriado é do admin da plataforma.'
                    : 'Não consegui importar os feriados nacionais.',
            );
        }
    };

    const resumo = useMemo(() => {
        const lista = dados?.feriados ?? [];
        const abertos = lista.filter((item) => item.liberados.length > 0).length;
        const comPaciente = lista.filter((item) => item.agendamentos_no_dia > 0).length;
        return { total: lista.length, abertos, comPaciente };
    }, [dados]);

    const pageCard = isDark
        ? 'border-white/10 bg-white/[0.06] text-white'
        : 'border-brand/10 bg-white text-brand';
    const muted = isDark ? 'text-white/55' : 'text-brand/55';
    const suave = isDark ? 'bg-black/20' : 'bg-brand-canvas';

    if (carregando && !dados) {
        return (
            <div className={`flex items-center gap-2 rounded-2xl border p-6 ${pageCard}`}>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm">Carregando feriados…</span>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className={`rounded-2xl border p-4 sm:p-5 ${pageCard}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${muted}`}>
                            Agenda de feriados
                        </div>
                        <h2 className="mt-1 text-lg font-semibold">
                            Feriado fecha para todos — libere quem precisa trabalhar
                        </h2>
                        <p className={`mt-1 max-w-2xl text-sm ${muted}`}>
                            O dia do feriado nasce fechado para todos os profissionais. Marque abaixo quem
                            vai atender naquele dia; o resto da clínica continua de folga.
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <select
                            value={ano}
                            onChange={(evento) => setAno(Number(evento.target.value))}
                            className={`rounded-xl border px-3 py-2 text-sm ${pageCard}`}
                        >
                            {[ano - 1, ano, ano + 1, ano + 2].map((valor) => (
                                <option key={valor} value={valor}>
                                    {valor}
                                </option>
                            ))}
                        </select>
                        <button
                            type="button"
                            onClick={() => void carregar(ano)}
                            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${pageCard}`}
                        >
                            <RefreshCw className="h-4 w-4" />
                            Atualizar
                        </button>
                        {dados?.admin_plataforma && (
                            <button
                                type="button"
                                onClick={() => void importarNacionais()}
                                className="inline-flex items-center gap-2 rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white"
                            >
                                <Download className="h-4 w-4" />
                                Importar nacionais {ano}
                            </button>
                        )}
                    </div>
                </div>

                <div className={`mt-4 grid gap-2 rounded-xl p-3 text-sm sm:grid-cols-3 ${suave}`}>
                    <div>
                        <span className={muted}>Feriados no ano: </span>
                        <strong>{resumo.total}</strong>
                    </div>
                    <div>
                        <span className={muted}>Com alguém liberado: </span>
                        <strong>{resumo.abertos}</strong>
                    </div>
                    <div>
                        <span className={muted}>Com paciente já marcado: </span>
                        <strong>{resumo.comPaciente}</strong>
                    </div>
                </div>

                {!dados?.pode_configurar && (
                    <div className={`mt-3 flex items-start gap-2 rounded-xl border p-3 text-sm ${pageCard}`}>
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>
                            Você pode consultar, mas só o <strong>admin da clínica</strong> libera
                            profissional no feriado.
                        </span>
                    </div>
                )}

                {erro && (
                    <div className="mt-3 rounded-xl border border-red-400/40 bg-red-500/10 p-3 text-sm text-red-500">
                        {erro}
                    </div>
                )}
                {aviso && (
                    <div className="mt-3 rounded-xl border border-emerald-400/40 bg-emerald-500/10 p-3 text-sm text-emerald-600">
                        {aviso}
                    </div>
                )}
            </div>

            <div className="space-y-3">
                {(dados?.feriados ?? []).length === 0 && (
                    <div className={`rounded-2xl border p-6 text-sm ${pageCard} ${muted}`}>
                        Nenhum feriado cadastrado em {ano}.
                        {dados?.admin_plataforma
                            ? ' Use “Importar nacionais” ou cadastre um feriado municipal.'
                            : ' Peça ao admin da plataforma para cadastrar.'}
                    </div>
                )}

                {(dados?.feriados ?? []).map((feriado) => {
                    const liberados = new Set(feriado.liberados);
                    const fechado = liberados.size === 0;
                    return (
                        <div key={feriado.id} className={`rounded-2xl border p-4 ${pageCard}`}>
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div className="flex items-start gap-3">
                                    <div className={`rounded-xl p-2 ${fechado ? 'bg-red-500/10' : 'bg-emerald-500/10'}`}>
                                        {fechado ? (
                                            <CalendarOff className="h-5 w-5 text-red-500" />
                                        ) : (
                                            <CalendarCheck className="h-5 w-5 text-emerald-500" />
                                        )}
                                    </div>
                                    <div>
                                        <div className="font-semibold">
                                            {formatarDia(feriado.data)} · {diaDaSemana(feriado.data)}
                                        </div>
                                        <div className={`text-sm ${muted}`}>
                                            {feriado.nome} · {ROTULO_TIPO[feriado.tipo] ?? feriado.tipo}
                                            {feriado.recorrente ? ' · todo ano' : ''}
                                            {feriado.cidade ? ` · ${feriado.cidade}` : ''}
                                            {feriado.uf ? `/${feriado.uf}` : ''}
                                        </div>
                                        <div className="mt-1 text-xs">
                                            {fechado ? (
                                                <span className="text-red-500">Dia fechado para todos</span>
                                            ) : (
                                                <span className="text-emerald-600">
                                                    {liberados.size} profissional(is) trabalhando
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {feriado.agendamentos_no_dia > 0 && (
                                    <div className="flex items-start gap-2 rounded-xl border border-amber-400/40 bg-amber-500/10 p-2 text-xs text-amber-600">
                                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                        <span>
                                            {feriado.agendamentos_no_dia} paciente(s) já marcado(s) neste dia.
                                            O feriado não cancela sozinho — decida se remarca ou mantém.
                                        </span>
                                    </div>
                                )}
                            </div>

                            <div className="mt-3 flex flex-wrap gap-2">
                                {(dados?.profissionais ?? []).length === 0 && (
                                    <span className={`text-sm ${muted}`}>
                                        Nenhum profissional ativo nesta clínica.
                                    </span>
                                )}
                                {(dados?.profissionais ?? []).map((profissional) => {
                                    const ativo = liberados.has(profissional.id);
                                    const salvandoEste = salvando === feriado.id;
                                    return (
                                        <button
                                            key={profissional.id}
                                            type="button"
                                            disabled={!dados?.pode_configurar || salvandoEste}
                                            onClick={() => void alternarProfissional(feriado, profissional.id)}
                                            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition-colors ${
                                                ativo
                                                    ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-600'
                                                    : isDark
                                                      ? 'border-white/15 text-white/70'
                                                      : 'border-brand/15 text-brand/70'
                                            } ${!dados?.pode_configurar ? 'cursor-not-allowed opacity-60' : ''}`}
                                        >
                                            <UserCheck className="h-4 w-4" />
                                            {profissional.name}
                                            {salvandoEste && <Loader2 className="h-3 w-3 animate-spin" />}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default FeriadosAgenda;
