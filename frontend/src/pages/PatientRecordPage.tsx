import React, { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, CalendarDays, CheckCircle2, Download, FilePlus2, HeartPulse, Loader2,
  Plus, Search, ShieldCheck, Stethoscope, UserRound, X,
} from 'lucide-react';
import {
  AgentiveAlert, AgentiveEmptyState, agentiveInputClass, agentiveLabelClass,
  agentivePanelClass, agentivePrimaryButtonClass, agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import {
  ClinicalAttachment, PatientAppointment, PatientDetail, PatientListItem, Treatment,
  patientRecordApi,
} from '../services/patientRecordApi.ts';
import { profissionaisApi, type Profissional } from '../services/clinicApi.ts';
import { equipeApi } from '../services/clinicUsersApi.ts';

const panelClass = agentivePanelClass(false);
const inputClass = agentiveInputClass(false);
const labelClass = agentiveLabelClass(false);
const primaryButtonClass = agentivePrimaryButtonClass();
const secondaryButtonClass = agentiveSecondaryButtonClass(false);
const EmptyState: React.FC<{ title: string; description: string }> = props => (
  <AgentiveEmptyState icon={HeartPulse} {...props} />
);

const dateTime = (value?: string | null) => value
  ? new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
  : '—';
const dateOnly = (value?: string | null) => value
  ? new Date(`${value}T00:00:00`).toLocaleDateString('pt-BR')
  : '—';
const statusLabel: Record<string, string> = {
  lead: 'Lead', active: 'Ativo', in_treatment: 'Em tratamento', at_risk: 'Em risco', inactive: 'Inativo',
  scheduled: 'Agendado', confirmed: 'Confirmado', attended: 'Atendido', no_show: 'No-show',
  proposed: 'Proposto', approved: 'Aprovado', completed: 'Concluído', abandoned: 'Abandonado',
};
const statusClass: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700', in_treatment: 'bg-blue-100 text-blue-700',
  at_risk: 'bg-amber-100 text-amber-700', inactive: 'bg-slate-100 text-slate-600',
  attended: 'bg-emerald-100 text-emerald-700', no_show: 'bg-red-100 text-red-700',
  scheduled: 'bg-blue-100 text-blue-700', confirmed: 'bg-indigo-100 text-indigo-700',
};
const errorMessage = (error: any) => {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry: any) => typeof entry === 'string' ? entry : entry?.msg || entry?.message || entry?.error || JSON.stringify(entry))
      .filter(Boolean);
    if (messages.length) return messages.join(' ');
  }
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    const message = detail.msg || detail.message || detail.error;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return error?.response?.data?.message || error?.message || 'Não foi possível concluir a operação.';
};

const onlyDigits = (value: string) => value.replace(/\D/g, '');

const formatCpf = (value: string) => {
  const digits = onlyDigits(value).slice(0, 11);
  if (digits.length <= 3) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`;
  if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`;
  return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`;
};

const formatPhone = (value: string) => {
  const digits = onlyDigits(value).slice(0, 11);
  if (digits.length <= 2) return digits;

  const ddd = digits.slice(0, 2);
  const local = digits.slice(2);

  if (digits.length <= 10) {
    const formatted = local.length <= 4 ? local : `${local.slice(0, 4)}-${local.slice(4)}`;
    return `(${ddd}) ${formatted}`;
  }

  return `(${ddd}) ${local.slice(0, 5)}-${local.slice(5)}`;
};

const hasRepeatedDigits = (digits: string) => digits.length > 0 && digits === digits[0].repeat(digits.length);

const isValidCpf = (value: string) => {
  const digits = onlyDigits(value);
  if (digits.length !== 11 || hasRepeatedDigits(digits)) return false;
  const numbers = digits.split('').map(Number);
  const firstWeight = [10, 9, 8, 7, 6, 5, 4, 3, 2];
  const secondWeight = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2];
  const firstDigit = numbers.slice(0, 9).reduce((sum, value, index) => sum + value * firstWeight[index], 0) % 11;
  const expectedFirst = firstDigit < 2 ? 0 : 11 - firstDigit;
  const secondDigit = numbers.slice(0, 10).reduce((sum, value, index) => sum + value * secondWeight[index], 0) % 11;
  const expectedSecond = secondDigit < 2 ? 0 : 11 - secondDigit;
  return numbers[9] === expectedFirst && numbers[10] === expectedSecond;
};

const isValidPhone = (value: string) => {
  const digits = onlyDigits(value);
  return digits.length >= 10 && digits.length <= 11;
};

const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

const validatePatientForm = (form: { name: string; cpf: string; birth_date: string; phone: string; email: string; insurance: string; source: string; }) => {
  const nextErrors: Record<string, string> = {};

  if (!form.name.trim()) nextErrors.name = 'Informe o nome completo.';
  else if (form.name.trim().length < 2) nextErrors.name = 'Nome deve ter ao menos 2 caracteres.';

  if (form.cpf && !isValidCpf(form.cpf)) nextErrors.cpf = 'CPF inválido.';

  if (form.phone && !isValidPhone(form.phone)) nextErrors.phone = 'Telefone/WhatsApp inválido.';

  if (form.email && !isValidEmail(form.email)) nextErrors.email = 'E-mail inválido.';

  return nextErrors;
};

const PatientForm: React.FC<{ onClose: () => void; onCreated: (patient: PatientListItem) => void }> = ({ onClose, onCreated }) => {
  const [form, setForm] = useState({ name: '', cpf: '', birth_date: '', phone: '', email: '', insurance: '', source: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const handleFieldChange = (key: keyof typeof form, value: string) => {
    const nextValue = key === 'cpf' ? formatCpf(value) : key === 'phone' ? formatPhone(value) : key === 'email' ? value.trimStart().toLowerCase() : value;
    const nextForm = { ...form, [key]: nextValue };
    setForm(nextForm);

    const nextErrors = { ...fieldErrors };
    if (nextErrors[key]) {
      delete nextErrors[key];
      setFieldErrors(nextErrors);
    }

    if (key === 'name' || key === 'cpf' || key === 'phone' || key === 'email') {
      const validation = validatePatientForm(nextForm);
      setFieldErrors({ ...nextErrors, ...Object.fromEntries(Object.entries(validation).filter(([field]) => field === key || field in nextErrors)) });
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const validation = validatePatientForm(form);
    setFieldErrors(validation);
    if (Object.keys(validation).length > 0) {
      setError('Corrija os campos destacados antes de salvar.');
      return;
    }

    setSaving(true); setError('');
    try {
      const payload = {
        ...form,
        name: form.name.trim(),
        cpf: form.cpf ? onlyDigits(form.cpf) : undefined,
        phone: form.phone ? onlyDigits(form.phone) : undefined,
        email: form.email ? form.email.trim().toLowerCase() : undefined,
      };
      onCreated(await patientRecordApi.createPatient(payload));
    } catch (e) { setError(errorMessage(e)); } finally { setSaving(false); }
  };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
    <form onSubmit={submit} className={`${panelClass} w-full max-w-2xl space-y-5 bg-white shadow-2xl`}>
      <div className="flex items-center justify-between"><div><h2 className="text-xl font-semibold text-slate-900">Novo paciente</h2><p className="text-sm text-slate-500">Cadastre os dados administrativos e o consentimento separadamente.</p></div><button type="button" onClick={onClose}><X /></button></div>
      {error && <AgentiveAlert variant="error">{error}</AgentiveAlert>}
      <div className="grid gap-4 md:grid-cols-2">
        {([['name', 'Nome completo', true], ['cpf', 'CPF', false], ['birth_date', 'Data de nascimento', false], ['phone', 'Telefone/WhatsApp', false], ['email', 'E-mail', false], ['insurance', 'Convênio', false], ['source', 'Origem', false]] as const).map(([key, label, required]) => (
          <label key={key} className={labelClass}>
            {label}
            <input
              required={required}
              type={key === 'birth_date' ? 'date' : key === 'email' ? 'email' : 'text'}
              className={`${inputClass} ${fieldErrors[key] ? 'border-red-500 ring-red-500/20' : ''}`}
              value={form[key]}
              aria-invalid={Boolean(fieldErrors[key])}
              onChange={e => handleFieldChange(key, e.target.value)}
            />
            {fieldErrors[key] && <span className="mt-1 block text-xs text-red-500">{fieldErrors[key]}</span>}
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-3"><button type="button" className={secondaryButtonClass} onClick={onClose}>Cancelar</button><button className={primaryButtonClass} disabled={saving}>{saving ? <Loader2 className="animate-spin" size={16} /> : <Plus size={16} />} Criar paciente</button></div>
    </form>
  </div>;
};

const AppointmentRow: React.FC<{ appointment: PatientAppointment; onNote: (appointment: PatientAppointment) => void; onSatisfaction: (appointment: PatientAppointment) => void }> = ({ appointment, onNote, onSatisfaction }) =>
  <div className="flex flex-col gap-3 border-b border-slate-100 py-4 last:border-0 md:flex-row md:items-center md:justify-between">
    <div><p className="font-medium text-slate-800">{dateTime(appointment.starts_at)}</p><p className="text-sm text-slate-500">{appointment.duration_minutes} min · Profissional #{appointment.professional_id} · {appointment.source}</p></div>
    <div className="flex flex-wrap items-center gap-3"><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusClass[appointment.status] || 'bg-slate-100 text-slate-600'}`}>{statusLabel[appointment.status] || appointment.status}</span>{appointment.status === 'attended' && <><button className={secondaryButtonClass} onClick={() => onNote(appointment)}><FilePlus2 size={15} /> Evolução</button><button className={secondaryButtonClass} onClick={() => onSatisfaction(appointment)}><HeartPulse size={15} /> Enviar NPS</button></>}</div>
  </div>;

const PatientDetailView: React.FC<{ patient: PatientDetail; onBack: () => void; onRefresh: () => void }> = ({ patient, onBack, onRefresh }) => {
  const [tab, setTab] = useState<'summary' | 'timeline' | 'appointments' | 'treatments' | 'attachments'>('summary');
  const [treatments, setTreatments] = useState<Treatment[]>([]);
  const [attachments, setAttachments] = useState<ClinicalAttachment[]>([]);
  const [selectedAppointment, setSelectedAppointment] = useState<PatientAppointment | null>(null);
  const [noteText, setNoteText] = useState('');
  const [noteId, setNoteId] = useState<string | null>(null);
  const [addendum, setAddendum] = useState({ reason: '', content: '' });
  const [message, setMessage] = useState('');
  const loadTreatments = async () => { try { setTreatments(await patientRecordApi.listTreatments(patient.id)); } catch (e) { setMessage(errorMessage(e)); } };
  const loadAttachments = async () => { try { setAttachments(await patientRecordApi.listClinicalAttachments(patient.id)); } catch (e) { setMessage(errorMessage(e)); } };
  useEffect(() => { loadTreatments(); loadAttachments(); }, [patient.id]);
  const createNote = async (event: FormEvent) => {
    event.preventDefault(); if (!selectedAppointment) return;
    try { const note = await patientRecordApi.createClinicalNote(patient.id, selectedAppointment.id, { note_text: noteText }); setNoteId(note.id); setMessage('Evolução registrada. Assine para torná-la imutável.'); setNoteText(''); } catch (e) { setMessage(errorMessage(e)); }
  };
  const signNote = async () => { if (!noteId) return; try { await patientRecordApi.signClinicalNote(noteId); setMessage('Evolução assinada com sucesso.'); setNoteId(null); setSelectedAppointment(null); onRefresh(); } catch (e) { setMessage(errorMessage(e)); } };
  const exportHistory = async () => { try { const blob = await patientRecordApi.exportPatientHistory(patient.id); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `prontuario-${patient.name.replace(/\s+/g, '-').toLowerCase()}.pdf`; anchor.click(); URL.revokeObjectURL(url); } catch (e) { setMessage(errorMessage(e)); } };
  const addendumSubmit = async (event: FormEvent) => { event.preventDefault(); if (!noteId) return; try { await patientRecordApi.createAddendum(noteId, addendum); setMessage('Adendo registrado.'); setAddendum({ reason: '', content: '' }); } catch (e) { setMessage(errorMessage(e)); } };
  const sendSatisfaction = async (appointment: PatientAppointment) => { try { await patientRecordApi.sendSatisfaction(appointment.id); setMessage('Pesquisa de satisfação enviada pelo WhatsApp.'); } catch (e) { setMessage(errorMessage(e)); } };
  const uploadAttachment = async (file: File) => { try { await patientRecordApi.uploadClinicalAttachment(patient.id, file); setMessage('Anexo armazenado com segurança.'); await loadAttachments(); } catch (e) { setMessage(errorMessage(e)); } };
  const downloadAttachment = async (attachment: ClinicalAttachment) => { try { const blob = await patientRecordApi.downloadClinicalAttachment(attachment.id); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${attachment.id}${attachment.mime_type === 'application/pdf' ? '.pdf' : '.img'}`; anchor.click(); URL.revokeObjectURL(url); } catch (e) { setMessage(errorMessage(e)); } };
  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><button onClick={onBack} className={secondaryButtonClass}><ArrowLeft size={16} /> Pacientes</button><button onClick={exportHistory} className={secondaryButtonClass}><Download size={16} /> Exportar PDF</button></div>
    <section className={`${panelClass} flex flex-wrap items-start justify-between gap-5`}>
      <div className="flex items-center gap-4"><div className="rounded-2xl bg-blue-100 p-4 text-blue-700"><UserRound /></div><div><h1 className="text-2xl font-semibold text-slate-900">{patient.name}</h1><p className="text-sm text-slate-500">{patient.phone || 'Sem telefone'} · {patient.email || 'Sem e-mail'}</p><span className={`mt-2 inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusClass[patient.lifecycle_status] || 'bg-slate-100 text-slate-600'}`}>{statusLabel[patient.lifecycle_status] || patient.lifecycle_status}</span></div></div>
      <div className="grid grid-cols-2 gap-5 text-sm"><div><p className="text-slate-500">Atendimentos</p><strong>{patient.total_appointments}</strong></div><div><p className="text-slate-500">No-shows</p><strong className="text-red-600">{patient.no_show_count}</strong></div><div><p className="text-slate-500">Último atendimento</p><strong>{dateTime(patient.last_appointment_at)}</strong></div><div><p className="text-slate-500">Próximo atendimento</p><strong>{dateTime(patient.next_appointment_at)}</strong></div></div>
    </section>
    {message && <AgentiveAlert variant="info" onClose={() => setMessage('')}>{message}</AgentiveAlert>}
    <div className="flex gap-2 overflow-x-auto border-b border-slate-200">{(['summary', 'timeline', 'appointments', 'treatments', 'attachments'] as const).map(item => <button key={item} onClick={() => setTab(item)} className={`border-b-2 px-4 py-3 text-sm font-medium ${tab === item ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500'}`}>{({ summary: 'Resumo', timeline: 'Timeline', appointments: 'Atendimentos', treatments: 'Tratamentos', attachments: 'Anexos' } as Record<string, string>)[item]}</button>)}</div>
    {tab === 'summary' && <div className="grid gap-6 md:grid-cols-3"><div className={`${panelClass} md:col-span-2`}><h2 className="mb-4 flex items-center gap-2 font-semibold"><HeartPulse size={18} /> Dados administrativos</h2><dl className="grid gap-4 text-sm sm:grid-cols-2"><div><dt className="text-slate-500">CPF</dt><dd>{patient.cpf || '—'}</dd></div><div><dt className="text-slate-500">Nascimento</dt><dd>{dateOnly(patient.birth_date)}</dd></div><div><dt className="text-slate-500">Convênio</dt><dd>{patient.insurance || 'Particular'}</dd></div><div><dt className="text-slate-500">Origem</dt><dd>{patient.source || '—'}</dd></div></dl></div><div className={`${panelClass} bg-blue-50`}><ShieldCheck className="mb-2 text-blue-700" /><h2 className="font-semibold">LGPD</h2><p className="mt-2 text-sm text-slate-600">{patient.lgpd_consent_at ? `Consentimento em ${dateTime(patient.lgpd_consent_at)}` : 'Consentimento ainda não registrado.'}</p></div></div>}
    {tab === 'timeline' && <div className={panelClass}>{patient.timeline.length ? patient.timeline.map(item => <div key={item.id} className="flex gap-4 border-b border-slate-100 py-4 last:border-0"><div className="mt-1 h-2.5 w-2.5 rounded-full bg-blue-600" /><div><p className="font-medium text-slate-800">{item.event_type.replaceAll('_', ' ')}</p><p className="text-sm text-slate-500">{dateTime(item.occurred_at)}</p></div></div>) : <EmptyState title="Timeline vazia" description="Eventos clínicos e administrativos aparecerão aqui." />}</div>}
    {tab === 'appointments' && <div className={panelClass}><h2 className="mb-2 font-semibold">Histórico de atendimentos</h2>{patient.appointments.length ? patient.appointments.map(item => <AppointmentRow key={item.id} appointment={item} onNote={setSelectedAppointment} onSatisfaction={sendSatisfaction} />) : <EmptyState title="Nenhum atendimento" description="A agenda deste paciente ainda não possui atendimentos." />}</div>}
    {tab === 'treatments' && <div className={panelClass}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">Planos de tratamento</h2><Link to={`/prontuario/pacientes/${patient.id}/tratamentos`} className={primaryButtonClass}><Plus size={16} /> Gerenciar</Link></div>{treatments.length ? treatments.map(treatment => <div key={treatment.id} className="border-b border-slate-100 py-4 last:border-0"><div className="flex justify-between"><div><p className="font-medium">{treatment.title}</p><p className="text-sm text-slate-500">{treatment.description || 'Sem descrição'}</p></div><span className="text-sm">{statusLabel[treatment.status] || treatment.status}</span></div><div className="mt-3 space-y-2">{treatment.procedures.map(procedure => <div key={procedure.id} className="flex justify-between rounded-lg bg-slate-50 p-3 text-sm"><span>{procedure.name}</span><span>{procedure.sessions_completed}/{procedure.sessions_planned || '—'} sessões</span></div>)}</div></div>) : <EmptyState title="Nenhum plano de tratamento" description="Crie o primeiro plano de tratamento para acompanhar a jornada clínica do paciente." />}</div>}
    {tab === 'attachments' && <div className={panelClass}><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Anexos clínicos</h2><p className="text-sm text-slate-500">PDF e imagens até 10 MB, armazenados em pasta privada da clínica.</p></div><label className={`${secondaryButtonClass} cursor-pointer`}><FilePlus2 size={16} /> Enviar anexo<input type="file" className="hidden" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={event => { const file = event.target.files?.[0]; if (file) uploadAttachment(file); event.target.value = ''; }} /></label></div>{attachments.length ? <div className="space-y-3">{attachments.map(attachment => <div key={attachment.id} className="flex items-center justify-between rounded-lg bg-slate-50 p-3"><div><p className="font-medium">{attachment.mime_type}</p><p className="text-xs text-slate-500">{(attachment.size_bytes / 1024 / 1024).toFixed(2)} MB {attachment.note_id ? `· evolução ${attachment.note_id.slice(0, 8)}` : ''}</p></div><button className={secondaryButtonClass} onClick={() => downloadAttachment(attachment)}><Download size={15} /> Baixar</button></div>)}</div> : <EmptyState title="Nenhum anexo" description="Envie exames, fotos ou documentos clínicos permitidos." />}</div>}
    {selectedAppointment && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><form onSubmit={createNote} className={`${panelClass} w-full max-w-xl space-y-4 bg-white`}><div className="flex justify-between"><h2 className="text-lg font-semibold">Evolução clínica</h2><button type="button" onClick={() => setSelectedAppointment(null)}><X /></button></div><p className="text-sm text-slate-500">Atendimento de {dateTime(selectedAppointment.starts_at)}. O conteúdo é restrito ao perfil clínico.</p><textarea required minLength={1} rows={7} className={inputClass} value={noteText} onChange={e => setNoteText(e.target.value)} placeholder="Descreva a evolução, conduta e orientações..." /><div className="flex justify-end gap-2"><button type="button" className={secondaryButtonClass} onClick={() => setSelectedAppointment(null)}>Cancelar</button><button className={primaryButtonClass}>Salvar evolução</button></div></form></div>}
    {noteId && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><div className={`${panelClass} w-full max-w-xl space-y-4 bg-white`}><h2 className="text-lg font-semibold">Assinar evolução</h2><p className="text-sm text-slate-600">Após a assinatura, a nota não poderá ser editada. Correções devem ser feitas por adendo.</p><div className="flex justify-end gap-2"><button className={secondaryButtonClass} onClick={() => setNoteId(null)}>Depois</button><button className={primaryButtonClass} onClick={signNote}><CheckCircle2 size={16} /> Assinar agora</button></div><form onSubmit={addendumSubmit} className="border-t pt-4"><h3 className="mb-2 font-medium">Registrar adendo</h3><input required className={inputClass} placeholder="Motivo" value={addendum.reason} onChange={e => setAddendum({ ...addendum, reason: e.target.value })} /><textarea required className={`${inputClass} mt-2`} placeholder="Conteúdo do adendo" value={addendum.content} onChange={e => setAddendum({ ...addendum, content: e.target.value })} /><button className={`${secondaryButtonClass} mt-2`}>Salvar adendo</button></form></div></div>}
  </div>;
};

const TreatmentManager: React.FC<{ patientId: string }> = ({ patientId }) => {
  const [treatments, setTreatments] = useState<Treatment[]>([]);
  const [professionals, setProfessionals] = useState<Profissional[]>([]);
  const treatmentProfessionalHelp = 'Apenas profissionais ativos vinculados a usuários do sistema com perfil de Profissional de atendimento ou Admin da Clínica aparecem aqui. A gestão desses usuários fica em Configurações → Minha Empresa → Administração de usuários.';
  const noAuthorizedProfessionalsText = 'Ainda não há profissionais autorizados para atendimento neste cadastro. Ative o vínculo entre o profissional e um usuário com perfil de Profissional de atendimento ou Admin da Clínica em Configurações → Minha Empresa → Administração de usuários.';
  const [form, setForm] = useState({ title: '', description: '', professional_id: '', total_value: '' });
  const [procedure, setProcedure] = useState({ treatmentId: '', name: '', recurrence_frequency: '', recurrence_sessions: '', recurrence_end_date: '' });
  const [recurrence, setRecurrence] = useState({ procedureId: '', start_at: '', duration_minutes: '30' });
  const [message, setMessage] = useState('');
  const [loadingProfessionals, setLoadingProfessionals] = useState(false);
  const load = async () => { try { setTreatments(await patientRecordApi.listTreatments(patientId)); } catch (e) { setMessage(errorMessage(e)); } };
  const loadProfessionals = async () => {
    setLoadingProfessionals(true);
    try {
      const [catalogo, usuarios] = await Promise.all([
        profissionaisApi.listar(true),
        equipeApi.listar(true),
      ]);
      const profissionaisValidos = new Set(
        usuarios
          .filter(usuario => usuario.is_active && usuario.professional_id != null && ['clinic_admin', 'clinical_professional'].includes(usuario.role))
          .map(usuario => usuario.professional_id as number),
      );
      setProfessionals(
        catalogo
          .filter(profissional => profissional.active && profissionaisValidos.has(profissional.id))
          .sort((a, b) => a.name.localeCompare(b.name)),
      );
    } catch (e) {
      setMessage(errorMessage(e));
    } finally {
      setLoadingProfessionals(false);
    }
  };
  useEffect(() => { load(); loadProfessionals(); }, [patientId]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const professionalId = Number(form.professional_id);
    if (!professionalId) {
      setMessage('Selecione um profissional ativo vinculado a um usuário autorizado do sistema. O perfil deve ser Profissional de atendimento ou Admin da Clínica. Verifique em Configurações → Minha Empresa → Administração de usuários.');
      return;
    }
    try {
      await patientRecordApi.createTreatment(patientId, { ...form, professional_id: professionalId, total_value: Number(form.total_value || 0) });
      setForm({ title: '', description: '', professional_id: '', total_value: '' }); setMessage('Plano de tratamento criado com sucesso.'); load();
    } catch (e) { setMessage(errorMessage(e)); }
  };
  const createProcedure = async (event: FormEvent) => {
    event.preventDefault();
    if (procedure.recurrence_sessions && procedure.recurrence_end_date) {
      setMessage('Informe apenas sessões ou apenas data final para a recorrência. Não use os dois campos ao mesmo tempo.');
      return;
    }
    if (procedure.recurrence_frequency && !procedure.recurrence_sessions && !procedure.recurrence_end_date) {
      setMessage('Quando houver recorrência, informe o número de sessões ou a data final do plano.');
      return;
    }
    try {
      await patientRecordApi.createTreatmentProcedure(procedure.treatmentId, {
        name: procedure.name,
        recurrence_frequency: procedure.recurrence_frequency || undefined,
        recurrence_sessions: procedure.recurrence_sessions ? Number(procedure.recurrence_sessions) : undefined,
        recurrence_end_date: procedure.recurrence_end_date || undefined,
      });
      setProcedure({ treatmentId: '', name: '', recurrence_frequency: '', recurrence_sessions: '', recurrence_end_date: '' });
      setMessage('Procedimento adicionado ao plano de tratamento.'); load();
    } catch (e) { setMessage(errorMessage(e)); }
  };
  const generate = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const result = await patientRecordApi.generateRecurrence(recurrence.procedureId, {
        start_at: new Date(recurrence.start_at).toISOString(),
        duration_minutes: Number(recurrence.duration_minutes),
      });
      setMessage(`${result.length} sessão(ões) gerada(s). Conflitos ficam pendentes de confirmação.`); load();
    } catch (e) { setMessage(errorMessage(e)); }
  };
  return <div className="space-y-6">
    <Link to={`/prontuario/pacientes/${patientId}`} className={secondaryButtonClass}><ArrowLeft size={16} /> Voltar à ficha</Link>
    {message && <AgentiveAlert variant="info" onClose={() => setMessage('')}>{message}</AgentiveAlert>}
    <form onSubmit={submit} className={`${panelClass} grid gap-4 md:grid-cols-4`}>
      <div className="md:col-span-4">
        <h2 className="font-semibold text-slate-900">Novo plano de tratamento</h2>
        <p className="mt-1 text-sm text-slate-500">Selecione o profissional responsável pelo atendimento. Apenas usuários com perfil de Profissional de atendimento ou Admin da Clínica podem ser vinculados. A gestão de usuários e perfis fica em Configurações → Minha Empresa → Administração de usuários.</p>
      </div>
      <label className={labelClass}>Título<input required className={inputClass} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label>
      <div className={labelClass}>
        <span>Profissional do atendimento</span>
        <select required className={inputClass} value={form.professional_id} onChange={e => setForm({ ...form, professional_id: e.target.value })} disabled={loadingProfessionals || professionals.length === 0}>
          <option value="">{loadingProfessionals ? 'Carregando...' : professionals.length === 0 ? 'Sem profissional autorizado' : 'Selecione'}</option>
          {professionals.map(profissional => (
            <option key={profissional.id} value={profissional.id}>{profissional.name}</option>
          ))}
        </select>
        <span className="mt-1 block text-xs text-slate-500">{treatmentProfessionalHelp}</span>
        {professionals.length === 0 && (
          <span className="mt-2 block rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800">
            {noAuthorizedProfessionalsText}
          </span>
        )}
      </div>
      <label className={labelClass}>Valor total<input type="number" min="0" step="0.01" className={inputClass} value={form.total_value} onChange={e => setForm({ ...form, total_value: e.target.value })} /></label>
      <label className={`${labelClass} md:col-span-4`}>Descrição<textarea className={inputClass} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
      <button className={`${primaryButtonClass} md:col-span-1`} disabled={loadingProfessionals || professionals.length === 0}>Criar plano de tratamento</button>
    </form>
    <form onSubmit={createProcedure} className={`${panelClass} grid gap-4 md:grid-cols-4`}>
      <div className="md:col-span-4"><h2 className="font-semibold">Adicionar procedimento recorrente</h2><p className="text-sm text-slate-500">Associe o procedimento ao plano de tratamento e defina a recorrência antes de gerar as sessões na agenda.</p></div>
      {treatments.length === 0 && (
        <div className="md:col-span-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Ainda não há plano de tratamento cadastrado para este paciente. Crie o primeiro plano de tratamento para então adicionar procedimentos e gerar sessões na agenda.
        </div>
      )}
      <label className={labelClass}>Plano de tratamento<select required className={inputClass} value={procedure.treatmentId} onChange={e => setProcedure({ ...procedure, treatmentId: e.target.value })} disabled={treatments.length === 0}><option value="">{treatments.length === 0 ? 'Crie um plano primeiro' : 'Selecione'}</option>{treatments.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
      <label className={labelClass}>Procedimento<input required className={inputClass} value={procedure.name} onChange={e => setProcedure({ ...procedure, name: e.target.value })} /></label>
      <label className={labelClass}>Frequência<select className={inputClass} value={procedure.recurrence_frequency} onChange={e => setProcedure({ ...procedure, recurrence_frequency: e.target.value })}><option value="">Sem recorrência</option><option value="weekly">Semanal</option><option value="biweekly">Quinzenal</option><option value="monthly">Mensal</option><option value="semiannual">Semestral</option><option value="custom">Personalizada</option></select></label>
      <label className={labelClass}>Sessões<input type="number" min="1" className={inputClass} value={procedure.recurrence_sessions} onChange={e => setProcedure({ ...procedure, recurrence_sessions: e.target.value })} /></label>
      <label className={labelClass}>Data final<input type="date" className={inputClass} value={procedure.recurrence_end_date} onChange={e => setProcedure({ ...procedure, recurrence_end_date: e.target.value })} /></label>
      <button className={`${primaryButtonClass} md:col-span-1`}>Adicionar procedimento</button>
    </form>
    <div className={panelClass}><h1 className="mb-4 text-xl font-semibold">Tratamentos e recorrência</h1>{treatments.length ? treatments.map(t => <div key={t.id} className="border-b py-4 last:border-0"><div className="flex justify-between"><div><h2 className="font-medium">{t.title}</h2><p className="text-sm text-slate-500">{t.description || 'Sem descrição'}</p></div><span>{statusLabel[t.status] || t.status}</span></div>{t.procedures.map(p => <div key={p.id} className="mt-3 rounded-lg bg-slate-50 p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><span>{p.name}</span><span>{p.sessions_completed}/{p.sessions_planned || '—'} sessões</span></div><div className="mt-2 h-2 rounded bg-slate-200"><div className="h-2 rounded bg-blue-600" style={{ width: `${p.sessions_planned ? Math.min(100, p.sessions_completed / p.sessions_planned * 100) : 0}%` }} /></div>{p.recurrence_frequency && <form onSubmit={generate} className="mt-3 flex flex-wrap items-end gap-2"><input type="hidden" value={recurrence.procedureId} /><label className={labelClass}>Primeira sessão<input required type="datetime-local" className={inputClass} value={recurrence.procedureId === p.id ? recurrence.start_at : ''} onChange={e => setRecurrence({ ...recurrence, procedureId: p.id, start_at: e.target.value })} /></label><label className={labelClass}>Duração<input type="number" min="5" className={inputClass} value={recurrence.procedureId === p.id ? recurrence.duration_minutes : '30'} onChange={e => setRecurrence({ ...recurrence, procedureId: p.id, duration_minutes: e.target.value })} /></label><button className={secondaryButtonClass} disabled={recurrence.procedureId !== p.id}><CalendarDays size={15} /> Gerar sessões</button></form>}</div>)}</div>) : <EmptyState title="Nenhum plano de tratamento cadastrado" description="Crie o primeiro plano de tratamento para iniciar o acompanhamento clínico." />}</div>
  </div>;
};

const PatientRecordPage: React.FC = () => {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const [patients, setPatients] = useState<PatientListItem[]>([]);
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const loadPatients = async () => { setLoading(true); try { setPatients(await patientRecordApi.listPatients({ search: search || undefined })); setError(''); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } };
  const loadPatient = async () => { if (!patientId) return; setLoading(true); try { setPatient(await patientRecordApi.getPatient(patientId)); setError(''); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } };
  useEffect(() => { patientId ? loadPatient() : loadPatients(); }, [patientId]);
  const filteredPatients = useMemo(() => patients, [patients]);
  if (patientId?.endsWith('/tratamentos')) return null;
  if (patientId && patient) return <main className="mx-auto max-w-7xl p-4 md:p-8"><PatientDetailView patient={patient} onBack={() => navigate('/prontuario/pacientes')} onRefresh={loadPatient} /></main>;
  return <main className="mx-auto max-w-7xl space-y-6 p-4 md:p-8"><div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-sm font-medium text-blue-600">Prontuário</p><h1 className="text-3xl font-semibold text-slate-900">Pacientes</h1><p className="mt-1 text-slate-500">Ficha administrativa, jornada e histórico clínico em um só lugar.</p></div><button className={primaryButtonClass} onClick={() => setShowForm(true)}><Plus size={17} /> Novo paciente</button></div><div className={`${panelClass} flex flex-wrap gap-3`}><div className="relative min-w-[260px] flex-1"><Search className="absolute left-3 top-2.5 text-slate-400" size={18} /><input className={`${inputClass} pl-10`} placeholder="Buscar por nome, telefone ou CPF" value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && loadPatients()} /></div><button className={secondaryButtonClass} onClick={loadPatients}>Buscar</button></div>{error && <AgentiveAlert variant="error">{error}</AgentiveAlert>}{loading ? <div className="flex justify-center p-16"><Loader2 className="animate-spin text-blue-600" /></div> : filteredPatients.length ? <div className={`${panelClass} overflow-x-auto`}><table className="w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-500"><th className="pb-3">Paciente</th><th>Status</th><th>Último atendimento</th><th>Próximo</th><th>No-shows</th><th /></tr></thead><tbody>{filteredPatients.map(item => <tr key={item.id} className="border-b border-slate-100 last:border-0"><td className="py-4"><p className="font-medium text-slate-800">{item.name}</p><p className="text-xs text-slate-500">{item.phone || item.email || 'Sem contato'}</p></td><td><span className={`rounded-full px-2.5 py-1 text-xs ${statusClass[item.lifecycle_status] || 'bg-slate-100 text-slate-600'}`}>{statusLabel[item.lifecycle_status] || item.lifecycle_status}</span></td><td>{dateTime(item.last_appointment_at)}</td><td>{dateTime(item.next_appointment_at)}</td><td>{item.no_show_count}</td><td><Link className="font-medium text-blue-600 hover:underline" to={`/prontuario/pacientes/${item.id}`}>Abrir ficha</Link></td></tr>)}</tbody></table></div> : <div className={panelClass}><EmptyState title="Nenhum paciente encontrado" description="Ajuste a busca ou cadastre o primeiro paciente." /></div>}{showForm && <PatientForm onClose={() => setShowForm(false)} onCreated={created => { setShowForm(false); navigate(`/prontuario/pacientes/${created.id}`); }} />}</main>;
};

export { PatientRecordPage, TreatmentManager };
export default PatientRecordPage;
