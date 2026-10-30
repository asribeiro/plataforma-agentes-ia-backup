import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Building2, CheckCircle2, Loader2, Save } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import {
  companyRegistrationApi,
  type CompanyRegistrationPayload,
} from '../services/companyRegistrationApi.ts';

const initialPayload: CompanyRegistrationPayload = {
  person_type: 'PJ',
  document: '',
  legal_name: '',
  trade_name: '',
  business_hours: {},
  administrative_responsible_name: '',
  administrative_responsible_email: '',
  administrative_responsible_phone: '',
  accepts_insurance: false,
  accepted_insurance: [],
  plan: 'consultorio',
  billing_interval: 'monthly',
  is_founder_customer: false,
  trial_days: 7,
};

const formatDocument = (value: string, type: 'PF' | 'PJ') => {
  const digits = value.replace(/\D/g, '').slice(0, type === 'PF' ? 11 : 14);
  if (type === 'PF') {
    return digits
      .replace(/(\d{3})(\d)/, '$1.$2')
      .replace(/(\d{3})(\d)/, '$1.$2')
      .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
  }
  return digits
    .replace(/(\d{2})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1/$2')
    .replace(/(\d{4})(\d{1,2})$/, '$1-$2');
};

const formatCep = (value: string) => value.replace(/\D/g, '').slice(0, 8).replace(/(\d{5})(\d)/, '$1-$2');
const formatPhone = (value: string) => {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  return digits.length > 10
    ? digits.replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3')
    : digits.replace(/(\d{2})(\d{4})(\d{4})/, '($1) $2-$3');
};

const Field = ({ label, children, required = false }: { label: string; children: React.ReactNode; required?: boolean }) => {
  const { isDark } = useTheme();
  return (
    <label className="block">
      <span className={agentiveLabelClass(isDark)}>{label}{required ? ' *' : ''}</span>
      {children}
    </label>
  );
};

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => {
  const { isDark } = useTheme();
  return (
    <section className={`rounded-2xl border p-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      <div className="grid gap-4 md:grid-cols-2">{children}</div>
    </section>
  );
};

const NewCompanyAdminPage: React.FC = () => {
  const { isDark } = useTheme();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedDraftId = Number(searchParams.get('draftId') || 0) || null;
  const requestedCustomerId = Number(searchParams.get('customerId') || 0) || null;
  const editingCurrentCompany = searchParams.get('mode') === 'edit';
  const [payload, setPayload] = useState<CompanyRegistrationPayload>(initialPayload);
  const [draftId, setDraftId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [reviewing, setReviewing] = useState(false);

  useEffect(() => {
    if (requestedCustomerId && !requestedDraftId) {
      setPayload((current) => ({ ...current, customer_id: requestedCustomerId }));
    }
  }, [requestedCustomerId, requestedDraftId]);

  useEffect(() => {
    if (!editingCurrentCompany) return;
    setLoading(true);
    companyRegistrationApi.getCurrent()
      .then((current) => setPayload(current))
      .catch((requestError: any) => {
        setError(requestError.response?.data?.detail || 'Não foi possível carregar o cadastro da empresa.');
      })
      .finally(() => setLoading(false));
  }, [editingCurrentCompany]);

  useEffect(() => {
    if (!requestedDraftId) return;
    setLoading(true);
    companyRegistrationApi.getDraft(requestedDraftId)
      .then((draft) => {
        setDraftId(draft.id);
        setPayload(draft.payload);
      })
      .catch((requestError: any) => {
        setError(requestError.response?.data?.detail || 'Não foi possível carregar o rascunho.');
      })
      .finally(() => setLoading(false));
  }, [requestedDraftId]);

  const update = <K extends keyof CompanyRegistrationPayload>(key: K, value: CompanyRegistrationPayload[K]) => {
    setPayload((current) => ({ ...current, [key]: value }));
  };

  const requiredComplete = useMemo(() => (
    payload.document.replace(/\D/g, '').length >= 11 &&
    payload.legal_name.trim() &&
    payload.trade_name.trim() &&
    payload.city?.trim() &&
    payload.state?.trim() &&
    payload.administrative_responsible_name.trim() &&
    payload.administrative_responsible_email.trim() &&
    payload.administrative_responsible_phone.replace(/\D/g, '').length >= 10 &&
    payload.plan
  ), [payload]);

  const saveDraft = async () => {
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      const draft = draftId
        ? await companyRegistrationApi.updateDraft(draftId, payload)
        : await companyRegistrationApi.createDraft(payload);
      setDraftId(draft.id);
      if (logoFile) {
        await companyRegistrationApi.uploadDraftLogo(draft.id, logoFile);
      }
      setSuccess(`Rascunho #${draft.id} salvo. Ele ficará disponível para os administradores da plataforma.`);
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Não foi possível salvar o rascunho.');
    } finally {
      setLoading(false);
    }
  };

  const saveCurrentCompany = async () => {
    setError('');
    setSuccess('');
    if (!requiredComplete) {
      setError('Preencha os campos obrigatórios antes de salvar a empresa.');
      return;
    }
    setLoading(true);
    try {
      await companyRegistrationApi.updateCurrent(payload);
      setSuccess('Cadastro completo da empresa atualizado com sucesso.');
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Não foi possível atualizar o cadastro da empresa.');
    } finally {
      setLoading(false);
    }
  };

  const createCompany = async () => {
    setError('');
    setSuccess('');
    if (!requiredComplete) {
      setError('Preencha os campos obrigatórios antes de criar a empresa.');
      return;
    }
    setLoading(true);
    try {
      const draft = draftId
        ? await companyRegistrationApi.updateDraft(draftId, payload)
        : await companyRegistrationApi.createDraft(payload);
      setDraftId(draft.id);
      if (logoFile) {
        await companyRegistrationApi.uploadDraftLogo(draft.id, logoFile);
      }
      const result = await companyRegistrationApi.createCompany(draft.id);
      setSuccess(`${result.message} Convite pendente de envio ao responsável administrativo.`);
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Não foi possível criar a empresa.');
    } finally {
      setLoading(false);
    }
  };

  const lookupCep = async () => {
    const cep = (payload.postal_code || '').replace(/\D/g, '');
    if (cep.length !== 8) return;
    try {
      const response = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
      if (!response.ok) throw new Error('Falha ao consultar o CEP');
      const data = await response.json();
      if (data.erro) throw new Error('CEP não encontrado');
      setPayload((current) => ({
        ...current,
        address: data.logradouro || current.address,
        province: data.bairro || current.province,
        city: data.localidade || current.city,
        state: data.uf || current.state,
      }));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Não foi possível consultar o CEP.');
    }
  };

  return (
    <main className={agentivePageClass(isDark, 'px-4 py-8 sm:px-6')}>
      <div className="mx-auto w-full max-w-4xl">
        <button type="button" onClick={() => navigate(editingCurrentCompany ? '/company' : '/plataforma')} className={agentiveSecondaryButtonClass(isDark, 'mb-4')}>
          <ArrowLeft className="h-4 w-4" /> Voltar
        </button>
        <section className={agentivePanelClass(isDark, 'p-5 sm:p-6')}>
          <div className="mb-6 flex items-start gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand text-white"><Building2 className="h-5 w-5" /></div>
            <div>
              <h1 className="text-xl font-semibold">{editingCurrentCompany ? 'Editar cadastro da empresa' : 'Criar nova empresa'}</h1>
              <p className={isDark ? 'mt-1 text-sm text-white/55' : 'mt-1 text-sm text-brand/55'}>
                {editingCurrentCompany
                  ? 'Atualize os dados cadastrais, responsáveis, funcionamento e cobrança da empresa.'
                  : 'Preencha os dados, salve um rascunho ou revise antes de criar o workspace.'}
              </p>
            </div>
            {reviewing && (
              <section className={`mb-4 rounded-2xl border p-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                <h2 className="font-semibold">Resumo para revisão</h2>
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                  <div><dt className="opacity-60">Nome fantasia</dt><dd>{payload.trade_name || '—'}</dd></div>
                  <div><dt className="opacity-60">Documento</dt><dd>{payload.document || '—'}</dd></div>
                  <div><dt className="opacity-60">Administrador</dt><dd>{payload.administrative_responsible_name || '—'}</dd></div>
                  <div><dt className="opacity-60">Plano</dt><dd>{payload.plan === 'redes_clinicas' ? 'Redes de Clínicas — até 30 unidades' : payload.plan}</dd></div>
                  <div><dt className="opacity-60">Periodicidade</dt><dd>{payload.billing_interval === 'yearly' ? 'Anual — 10% de desconto' : 'Mensal'}</dd></div>
                  <div><dt className="opacity-60">Cliente fundador</dt><dd>{payload.is_founder_customer ? 'Sim — desconto adicional de 10%' : 'Não'}</dd></div>
                </dl>
                <p className="mt-3 text-xs opacity-70">Revise os dados acima. O workspace, o usuário administrador e o convite serão criados somente após a confirmação.</p>
              </section>
            )}
          </div>
          {error && <AgentiveAlert variant="error" className="mb-4">{error}</AgentiveAlert>}
          {success && <AgentiveAlert variant="success" className="mb-4"><div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4" />{success}</div></AgentiveAlert>}

          <div className="space-y-4">
            <Section title="1. Dados da empresa">
              <Field label="Tipo de pessoa" required>
                <select className={agentiveInputClass(isDark)} value={payload.person_type} onChange={(e) => update('person_type', e.target.value as 'PF' | 'PJ')}>
                  <option value="PJ">Pessoa jurídica</option><option value="PF">Pessoa física</option>
                </select>
              </Field>
              <Field label="CPF/CNPJ" required>
                <input className={agentiveInputClass(isDark)} value={formatDocument(payload.document, payload.person_type)} onChange={(e) => update('document', e.target.value)} />
              </Field>
              <Field label="Razão social" required><input className={agentiveInputClass(isDark)} value={payload.legal_name} onChange={(e) => update('legal_name', e.target.value)} /></Field>
              <Field label="Nome fantasia" required><input className={agentiveInputClass(isDark)} value={payload.trade_name} onChange={(e) => update('trade_name', e.target.value)} /></Field>
              <Field label="Inscrição municipal"><input className={agentiveInputClass(isDark)} value={payload.municipal_registration || ''} onChange={(e) => update('municipal_registration', e.target.value)} /></Field>
              <Field label="Logo da clínica"><input className={agentiveInputClass(isDark)} type="file" accept="image/*" onChange={(e) => setLogoFile(e.target.files?.[0] || null)} /></Field>
            </Section>

            <Section title="2. Endereço e contato">
              <Field label="CEP"><input className={agentiveInputClass(isDark)} value={formatCep(payload.postal_code || '')} onChange={(e) => update('postal_code', e.target.value)} onBlur={() => void lookupCep()} /></Field>
              <Field label="Rua"><input className={agentiveInputClass(isDark)} value={payload.address || ''} onChange={(e) => update('address', e.target.value)} /></Field>
              <Field label="Número"><input className={agentiveInputClass(isDark)} value={payload.address_number || ''} onChange={(e) => update('address_number', e.target.value)} /></Field>
              <Field label="Complemento"><input className={agentiveInputClass(isDark)} value={payload.address_complement || ''} onChange={(e) => update('address_complement', e.target.value)} /></Field>
              <Field label="Bairro"><input className={agentiveInputClass(isDark)} value={payload.province || ''} onChange={(e) => update('province', e.target.value)} /></Field>
              <Field label="Cidade" required><input className={agentiveInputClass(isDark)} value={payload.city || ''} onChange={(e) => update('city', e.target.value)} /></Field>
              <Field label="UF" required><input className={agentiveInputClass(isDark)} maxLength={2} value={payload.state || ''} onChange={(e) => update('state', e.target.value.toUpperCase())} /></Field>
              <Field label="Telefone fixo"><input className={agentiveInputClass(isDark)} value={formatPhone(payload.fixed_phone || '')} onChange={(e) => update('fixed_phone', e.target.value)} /></Field>
              <Field label="Site"><input className={agentiveInputClass(isDark)} type="url" value={payload.website || ''} onChange={(e) => update('website', e.target.value)} /></Field>
              <Field label="Instagram"><input className={agentiveInputClass(isDark)} value={payload.instagram || ''} onChange={(e) => update('instagram', e.target.value)} /></Field>
            </Section>

            <Section title="3. Responsáveis">
              <Field label="Responsável administrativo" required><input className={agentiveInputClass(isDark)} value={payload.administrative_responsible_name} onChange={(e) => update('administrative_responsible_name', e.target.value)} /></Field>
              <Field label="E-mail do administrador" required><input className={agentiveInputClass(isDark)} type="email" value={payload.administrative_responsible_email} onChange={(e) => update('administrative_responsible_email', e.target.value)} /></Field>
              <Field label="Celular do administrador" required><input className={agentiveInputClass(isDark)} value={formatPhone(payload.administrative_responsible_phone)} onChange={(e) => update('administrative_responsible_phone', e.target.value)} /></Field>
              <Field label="Profissional responsável técnico (opcional)"><input className={agentiveInputClass(isDark)} type="number" value={payload.technical_responsible_professional_id || ''} onChange={(e) => update('technical_responsible_professional_id', e.target.value ? Number(e.target.value) : undefined)} /></Field>
              <Field label="CRO"><input className={agentiveInputClass(isDark)} value={payload.technical_responsible_cro || ''} onChange={(e) => update('technical_responsible_cro', e.target.value)} /></Field>
              <Field label="UF do CRO"><input className={agentiveInputClass(isDark)} maxLength={2} value={payload.technical_responsible_cro_uf || ''} onChange={(e) => update('technical_responsible_cro_uf', e.target.value.toUpperCase())} /></Field>
            </Section>

            <Section title="4. Funcionamento">
              <Field label="WhatsApp da secretária IA"><input className={agentiveInputClass(isDark)} value={formatPhone(payload.ai_whatsapp || '')} onChange={(e) => update('ai_whatsapp', e.target.value)} /></Field>
              <Field label="Atende convênios?"><select className={agentiveInputClass(isDark)} value={payload.accepts_insurance ? 'yes' : 'no'} onChange={(e) => update('accepts_insurance', e.target.value === 'yes')}><option value="no">Não</option><option value="yes">Sim</option></select></Field>
              {payload.accepts_insurance && <Field label="Convênios aceitos"><input className={agentiveInputClass(isDark)} placeholder="Unimed, Bradesco..." value={payload.accepted_insurance.join(', ')} onChange={(e) => update('accepted_insurance', e.target.value.split(',').map((item) => item.trim()).filter(Boolean))} /></Field>}
              <Field label="Horários de atendimento"><textarea className={agentiveInputClass(isDark, 'min-h-24')} placeholder="Configure os dias, horários e intervalo de almoço" value={JSON.stringify(payload.business_hours, null, 2)} onChange={(e) => { try { update('business_hours', JSON.parse(e.target.value)); } catch { /* validação final */ } }} /></Field>
            </Section>

            <Section title="5. Plano e cobrança">
              <Field label="Plano" required><select className={agentiveInputClass(isDark)} value={payload.plan} onChange={(e) => update('plan', e.target.value as CompanyRegistrationPayload['plan'])}><option value="consultorio">Consultório — 1 profissional</option><option value="clinica">Clínica — até 4 profissionais</option><option value="clinica_plus">Clínica Plus — até 10 profissionais</option><option value="redes_clinicas">Redes de Clínicas — até 30 unidades</option></select></Field>
              <Field label="Periodicidade"><select className={agentiveInputClass(isDark)} value={payload.billing_interval} onChange={(e) => update('billing_interval', e.target.value as 'monthly' | 'yearly')}><option value="monthly">Mensal</option><option value="yearly">Anual — 10% de desconto</option></select></Field>
              <Field label="Cliente fundador"><select className={agentiveInputClass(isDark)} value={payload.is_founder_customer ? 'yes' : 'no'} onChange={(e) => update('is_founder_customer', e.target.value === 'yes')}><option value="no">Não</option><option value="yes">Sim — mais 10% de desconto</option></select></Field>
              <Field label="Dias de teste"><input className={agentiveInputClass(isDark)} type="number" min={0} value={payload.trial_days} onChange={(e) => update('trial_days', Number(e.target.value))} /></Field>
              <Field label="Data de início"><input className={agentiveInputClass(isDark)} type="date" value={payload.start_date || ''} onChange={(e) => update('start_date', e.target.value)} /></Field>
              <Field label="E-mail de cobrança"><input className={agentiveInputClass(isDark)} type="email" value={payload.billing_email || ''} onChange={(e) => update('billing_email', e.target.value)} /></Field>
              <Field label="Forma de pagamento"><input className={agentiveInputClass(isDark)} value={payload.preferred_payment_method || ''} onChange={(e) => update('preferred_payment_method', e.target.value)} /></Field>
            </Section>
          </div>

          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            {editingCurrentCompany ? (
              <button type="button" onClick={() => void saveCurrentCompany()} disabled={loading} className={agentivePrimaryButtonClass()}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Salvar cadastro completo
              </button>
            ) : (
              <>
                <button type="button" onClick={() => void saveDraft()} disabled={loading} className={agentiveSecondaryButtonClass(isDark)}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Salvar rascunho
                </button>
                <button type="button" onClick={() => (reviewing ? void createCompany() : setReviewing(true))} disabled={loading} className={agentivePrimaryButtonClass()}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Building2 className="h-4 w-4" />} {reviewing ? 'Confirmar e criar empresa' : 'Revisar e criar'}
                </button>
              </>
            )}
          </div>
        </section>
      </div>
    </main>
  );
};

export default NewCompanyAdminPage;
