import React, { FormEvent, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Heart, Loader2, MessageSquare, RefreshCw, Send, Users, X } from 'lucide-react';
import { AgentiveAlert, AgentiveEmptyState, agentiveInputClass, agentiveLabelClass, agentivePanelClass, agentivePrimaryButtonClass, agentiveSecondaryButtonClass } from '../components/AgentiveUI.tsx';
import { PatientListItem, ReactivationPatient, RecurrenceConflictTask, SatisfactionDashboard, SatisfactionSurvey, patientRecordApi } from '../services/patientRecordApi.ts';

const panelClass = agentivePanelClass(false);
const inputClass = agentiveInputClass(false);
const labelClass = agentiveLabelClass(false);
const primaryButtonClass = agentivePrimaryButtonClass();
const secondaryButtonClass = agentiveSecondaryButtonClass(false);
const errorMessage = (error: any) => error?.response?.data?.detail || error?.message || 'Não foi possível carregar o painel.';
const EmptyState: React.FC<{ title: string; description: string }> = props => <AgentiveEmptyState icon={Users} {...props} />;

const SurveyResponseModal: React.FC<{ survey: SatisfactionSurvey; onClose: () => void; onSaved: () => void }> = ({ survey, onClose, onSaved }) => {
  const [form, setForm] = useState({ nps_score: '', procedure_score: '5', comment: '' });
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await patientRecordApi.respondSatisfaction(survey.id, {
        nps_score: Number(form.nps_score),
        procedure_score: Number(form.procedure_score),
        comment: form.comment || undefined,
      });
      onSaved();
    } catch (e) { setError(errorMessage(e)); }
  };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
    <form onSubmit={submit} className={`${panelClass} w-full max-w-lg space-y-4 bg-white shadow-2xl`}>
      <div className="flex items-center justify-between"><div><h2 className="text-xl font-semibold">Registrar resposta</h2><p className="text-sm text-slate-500">A resposta será vinculada à pesquisa enviada.</p></div><button type="button" onClick={onClose}><X /></button></div>
      {error && <AgentiveAlert variant="error">{error}</AgentiveAlert>}
      <label className={labelClass}>NPS (0 a 10)<input required type="number" min="0" max="10" className={inputClass} value={form.nps_score} onChange={e => setForm({ ...form, nps_score: e.target.value })} /></label>
      <label className={labelClass}>Nota do procedimento (1 a 5)<input required type="number" min="1" max="5" className={inputClass} value={form.procedure_score} onChange={e => setForm({ ...form, procedure_score: e.target.value })} /></label>
      <label className={labelClass}>Comentário<textarea className={inputClass} value={form.comment} onChange={e => setForm({ ...form, comment: e.target.value })} /></label>
      <div className="flex justify-end gap-2"><button type="button" className={secondaryButtonClass} onClick={onClose}>Cancelar</button><button className={primaryButtonClass}><CheckCircle2 size={16} /> Registrar resposta</button></div>
    </form>
  </div>;
};

const PatientJourneyPage: React.FC = () => {
  const [dashboard, setDashboard] = useState<SatisfactionDashboard | null>(null);
  const [patients, setPatients] = useState<PatientListItem[]>([]);
  const [reactivation, setReactivation] = useState<ReactivationPatient[]>([]);
  const [surveys, setSurveys] = useState<SatisfactionSurvey[]>([]);
  const [tasks, setTasks] = useState<RecurrenceConflictTask[]>([]);
  const [selectedSurvey, setSelectedSurvey] = useState<SatisfactionSurvey | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [nextDashboard, nextPatients, nextReactivation, nextSurveys, nextTasks] = await Promise.all([
        patientRecordApi.getSatisfactionDashboard(),
        patientRecordApi.listPatients(),
        patientRecordApi.listReactivation(),
        patientRecordApi.listSatisfactionSurveys(),
        patientRecordApi.listRecurrenceTasks('pending'),
      ]);
      setDashboard(nextDashboard);
      setPatients(nextPatients);
      setReactivation(nextReactivation);
      setSurveys(nextSurveys);
      setTasks(nextTasks);
      setMessage('');
    } catch (e) { setMessage(errorMessage(e)); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  const processNoShows = async () => {
    try {
      const result = await patientRecordApi.processNoShows();
      setMessage(`${result.marked_no_shows} atendimento(s) marcado(s) como no-show.`);
      await load();
    } catch (e) { setMessage(errorMessage(e)); }
  };
  const updateTask = async (task: RecurrenceConflictTask, status: 'resolved' | 'dismissed') => {
    try { await patientRecordApi.updateRecurrenceTask(task.id, status); setTasks(tasks.filter(item => item.id !== task.id)); setMessage('Tarefa atualizada.'); }
    catch (e) { setMessage(errorMessage(e)); }
  };
  if (loading) return <main className="flex min-h-[60vh] items-center justify-center"><Loader2 className="animate-spin text-blue-600" /></main>;
  const cards = [
    { label: 'Pacientes cadastrados', value: patients.length, icon: Users, tone: 'text-blue-700 bg-blue-50' },
    { label: 'NPS', value: dashboard?.nps ?? '—', icon: Heart, tone: 'text-rose-700 bg-rose-50' },
    { label: 'Taxa de no-show', value: dashboard ? `${dashboard.no_show_rate}%` : '—', icon: AlertTriangle, tone: 'text-amber-700 bg-amber-50' },
    { label: 'Pacientes inativos', value: dashboard?.inactive_patients ?? '—', icon: RefreshCw, tone: 'text-slate-700 bg-slate-100' },
  ];
  return <main className="mx-auto max-w-7xl space-y-6 p-4 md:p-8">
    <div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-sm font-medium text-blue-600">Prontuário</p><h1 className="text-3xl font-semibold text-slate-900">Jornada do paciente</h1><p className="mt-1 text-slate-500">Acompanhe risco, retorno, no-show e satisfação da clínica.</p></div><div className="flex gap-2"><button className={secondaryButtonClass} onClick={load}><RefreshCw size={16} /> Atualizar</button><button className={primaryButtonClass} onClick={processNoShows}><AlertTriangle size={16} /> Processar no-shows</button></div></div>
    {message && <AgentiveAlert variant="info" onClose={() => setMessage('')}>{message}</AgentiveAlert>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{cards.map(card => <div key={card.label} className={`${panelClass} flex items-center gap-4`}><div className={`rounded-xl p-3 ${card.tone}`}><card.icon size={20} /></div><div><p className="text-sm text-slate-500">{card.label}</p><p className="text-2xl font-semibold text-slate-900">{card.value}</p></div></div>)}</div>
    <div className="grid gap-6 lg:grid-cols-2">
      <section className={panelClass}><div className="mb-4 flex items-center justify-between"><div><h2 className="font-semibold text-slate-900">Reativação</h2><p className="text-sm text-slate-500">Pacientes sem retorno no período configurado.</p></div><Send size={18} className="text-blue-600" /></div>{reactivation.length ? <div className="space-y-3">{reactivation.map(item => <div key={item.patient_id} className="flex items-center justify-between rounded-lg bg-slate-50 p-3"><div><p className="font-medium">{item.name}</p><p className="text-xs text-slate-500">Último atendimento: {item.last_attended_at ? new Date(item.last_attended_at).toLocaleDateString('pt-BR') : 'não registrado'}</p></div><button className={secondaryButtonClass} onClick={() => setMessage('A campanha será enviada pelo job de reativação configurado.')}>Preparar contato</button></div>)}</div> : <EmptyState title="Nenhum paciente para reativar" description="A lista será atualizada conforme o ciclo de vida." />}</section>
      <section className={panelClass}><h2 className="mb-4 font-semibold text-slate-900">Comentários negativos recentes</h2>{dashboard?.recent_negative_comments.length ? <div className="space-y-3">{dashboard.recent_negative_comments.map(comment => <div key={comment.survey_id} className="rounded-lg border border-red-100 bg-red-50 p-3"><div className="flex justify-between"><span className="font-medium text-red-800">NPS {comment.nps_score}</span><span className="text-xs text-red-600">Ação necessária</span></div><p className="mt-1 text-sm text-red-900">{comment.comment}</p></div>)}</div> : <EmptyState title="Sem comentários negativos" description="Respostas com NPS até 6 aparecerão aqui." />}</section>
    </div>
    <section className={panelClass}><div className="mb-4 flex items-center justify-between"><div><h2 className="font-semibold text-slate-900">Pesquisas de satisfação</h2><p className="text-sm text-slate-500">Acompanhe pesquisas enviadas e registre respostas recebidas fora do WhatsApp.</p></div><MessageSquare className="text-blue-600" size={18} /></div>{surveys.length ? <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-500"><th className="pb-3">Status</th><th>NPS</th><th>Procedimento</th><th>Enviada em</th><th /></tr></thead><tbody>{surveys.map(survey => <tr key={survey.id} className="border-b border-slate-100 last:border-0"><td className="py-3">{survey.status}</td><td>{survey.nps_score ?? '—'}</td><td>{survey.procedure_score ?? '—'}</td><td>{survey.sent_at ? new Date(survey.sent_at).toLocaleString('pt-BR') : '—'}</td><td>{survey.status === 'sent' && <button className={secondaryButtonClass} onClick={() => setSelectedSurvey(survey)}>Registrar resposta</button>}</td></tr>)}</tbody></table></div> : <EmptyState title="Nenhuma pesquisa registrada" description="As pesquisas aparecerão após o envio pelo WhatsApp." />}</section>
    <section className={panelClass}><div className="mb-4 flex items-center justify-between"><div><h2 className="font-semibold text-slate-900">Conflitos de recorrência</h2><p className="text-sm text-slate-500">Sessões que precisam de confirmação antes de entrar na agenda.</p></div><AlertTriangle className="text-amber-600" size={18} /></div>{tasks.length ? <div className="space-y-3">{tasks.map(task => <div key={task.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-amber-50 p-3"><div><p className="font-medium text-amber-900">{task.title}</p><p className="text-xs text-amber-700">Paciente: {task.patient_id} · Criado em {new Date(task.created_at).toLocaleString('pt-BR')}</p></div><div className="flex gap-2"><button className={secondaryButtonClass} onClick={() => updateTask(task, 'dismissed')}>Dispensar</button><button className={primaryButtonClass} onClick={() => updateTask(task, 'resolved')}>Resolver</button></div></div>)}</div> : <EmptyState title="Nenhum conflito pendente" description="A geração de recorrências está sem pendências." />}</section>
    <section className={panelClass}><h2 className="mb-4 font-semibold text-slate-900">Indicadores de satisfação</h2><div className="grid gap-4 sm:grid-cols-3"><div><p className="text-sm text-slate-500">Pesquisas enviadas</p><p className="text-2xl font-semibold">{dashboard?.total_surveys ?? 0}</p></div><div><p className="text-sm text-slate-500">Respondidas</p><p className="text-2xl font-semibold">{dashboard?.answered_surveys ?? 0}</p></div><div><p className="text-sm text-slate-500">Nota do procedimento</p><p className="text-2xl font-semibold">{dashboard?.average_procedure_score ?? '—'}<span className="text-sm font-normal text-slate-500">/5</span></p></div></div></section>
    {selectedSurvey && <SurveyResponseModal survey={selectedSurvey} onClose={() => setSelectedSurvey(null)} onSaved={() => { setSelectedSurvey(null); setMessage('Resposta registrada.'); load(); }} />}
  </main>;
};

export default PatientJourneyPage;
