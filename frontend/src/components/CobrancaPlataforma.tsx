/**
 * Cobrança no painel da plataforma: catálogo de planos (com preço) e a área
 * "Plano & cobrança" de cada empresa cliente.
 *
 * Por que estes dois blocos existem juntos: nenhum dos dois se sustenta sozinho.
 * Os três planos nascem com `preco_centavos = null` (preço "ainda não
 * combinado"), e plano sem preço não emite fatura. Sem a tela de preços, a
 * emissão por empresa seria um botão permanentemente desabilitado; sem a área
 * por empresa, o preço definido não teria onde virar cobrança.
 *
 * O que a tela NÃO faz, de propósito:
 *   - não calcula valor de fatura. O valor vem do plano no backend, e a fatura
 *     emitida guarda o preço daquele dia (snapshot): reajustar o plano depois
 *     não reescreve o passado, e a tela nunca "recalcula" uma fatura antiga;
 *   - não trata erro por conta própria. Todo erro é `detail` do backend — 400
 *     de plano sem preço, 409 de assinatura ausente ou competência repetida.
 *     Reescrever a mensagem aqui é como o front e o back divergem;
 *   - não oferece mudar o status da assinatura. O GET devolve só a assinatura
 *     ativa; suspender ou encerrar por aqui faria a empresa desaparecer da tela
 *     sem caminho de volta. O status é exibido, não editável.
 */
import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  BadgeDollarSign,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  RefreshCw,
  Save,
  Wallet,
} from 'lucide-react';
import {
  AgentiveAlert,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import { formatarPreco } from '../services/clinicApi.ts';
import {
  centavosParaReais,
  competenciaAtual,
  formatarVencimento,
  reaisParaCentavos,
  rotuloCompetencia,
  type CobrancaEmpresa,
  type Fatura,
  type Plano,
  type PlanoAtualizacao,
  type StatusFatura,
} from '../services/cobrancaApi.ts';

const joinClasses = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

// --------------------------------------------------------------------------
// Planos e preços
// --------------------------------------------------------------------------
interface PlanoRowProps {
  isDark: boolean;
  onSalvar: (planoId: number, dados: PlanoAtualizacao) => void;
  plano: Plano;
  salvando: boolean;
}

/**
 * Uma linha do catálogo. O rascunho é local: digitar `349,00` em um plano e
 * salvar OUTRO não pode enviar um preço que ninguém confirmou.
 *
 * O input é em REAIS porque é assim que o preço é combinado; a conversão para
 * centavos acontece no envio (`reaisParaCentavos`) e o valor volta formatado
 * quando o backend responde.
 */
const PlanoRow: React.FC<PlanoRowProps> = ({ isDark, onSalvar, plano, salvando }) => {
  const [preco, setPreco] = useState<string>(centavosParaReais(plano.preco_centavos));
  const [ativo, setAtivo] = useState<boolean>(plano.ativo);

  // O backend devolve o plano salvo: se o valor gravado difere do rascunho
  // (arredondamento, alteração por outro operador), o input acompanha.
  useEffect(() => {
    setPreco(centavosParaReais(plano.preco_centavos));
    setAtivo(plano.ativo);
  }, [plano.preco_centavos, plano.ativo]);

  const centavos = reaisParaCentavos(preco);
  // Vazio NÃO é null "sem preço": null apaga o preço do catálogo e trava a
  // emissão. Campo vazio é rascunho incompleto, e não se salva rascunho.
  const invalido = centavos === null;
  const mudou = !invalido && (centavos !== plano.preco_centavos || ativo !== plano.ativo);
  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const faintClass = isDark ? 'text-white/40' : 'text-brand/45';
  const inputId = `plano-preco-${plano.id}`;
  const ativoId = `plano-ativo-${plano.id}`;

  return (
    <div className={joinClasses('rounded-2xl border p-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="min-w-0 sm:flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
            <span className="truncate">{plano.nome}</span>
            <span className={pillNeutro(isDark)}>{plano.tier}</span>
            {!plano.ativo && <span className={pillNeutro(isDark)}>inativo</span>}
          </p>
          <p className={joinClasses('mt-1 text-xs', mutedClass)}>
            {plano.preco_centavos === null
              ? 'Sem preço definido — este plano não emite fatura'
              : `${formatarPreco(plano.preco_centavos)} · cobrança ${plano.ciclo}`}
          </p>
        </div>

        <div className="w-full sm:w-40">
          <label htmlFor={inputId} className={agentiveLabelClass(isDark)}>
            Preço mensal (R$)
          </label>
          <input
            id={inputId}
            type="text"
            inputMode="decimal"
            value={preco}
            onChange={(event) => setPreco(event.target.value)}
            placeholder="0,00"
            disabled={salvando}
            className={agentiveInputClass(isDark)}
            aria-invalid={invalido}
          />
        </div>

        <div className="flex items-center gap-2 pb-2">
          <input
            id={ativoId}
            type="checkbox"
            checked={ativo}
            onChange={(event) => setAtivo(event.target.checked)}
            disabled={salvando}
            className="h-4 w-4 shrink-0 rounded border-brand/20"
          />
          <label htmlFor={ativoId} className={joinClasses('whitespace-nowrap text-xs', mutedClass)}>
            Ativo
          </label>
        </div>

        <button
          type="button"
          onClick={() => {
            if (centavos === null) return;
            onSalvar(plano.id, { preco_centavos: centavos, ativo });
          }}
          disabled={!mudou || salvando}
          className={agentivePrimaryButtonClass('shrink-0')}
        >
          {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {salvando ? 'Salvando...' : 'Salvar'}
        </button>
      </div>

      {invalido && (
        <p className="mt-2 text-xs text-red-500">
          {preco.trim() === ''
            ? 'Informe o valor em reais, por exemplo 349,00. Para gravar zero, digite 0,00.'
            : 'Valor inválido: use apenas números, com vírgula para os centavos (349,00).'}
        </p>
      )}
      {!invalido && !plano.ativo && (
        <p className={joinClasses('mt-2 text-xs', faintClass)}>
          Plano inativo continua no histórico das assinaturas que o usaram, mas não pode ser contratado de novo.
        </p>
      )}
    </div>
  );
};

interface PlanosPanelProps {
  aberto: boolean;
  carregando: boolean;
  erro: string | null;
  isDark: boolean;
  onAlternar: () => void;
  onRecarregar: () => void;
  onSalvar: (planoId: number, dados: PlanoAtualizacao) => void;
  planos: Plano[];
  salvandoId: number | null;
}

/**
 * Catálogo com preço. Bloco recolhível no topo da tela: a lista de clientes é a
 * tarefa principal, e preço é configuração de mexer de vez em quando.
 */
export const PlanosPanel: React.FC<PlanosPanelProps> = ({
  aberto,
  carregando,
  erro,
  isDark,
  onAlternar,
  onRecarregar,
  onSalvar,
  planos,
  salvandoId,
}) => {
  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const semPreco = planos.filter((plano) => plano.preco_centavos === null).length;

  return (
    <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <button type="button" onClick={onAlternar} aria-expanded={aberto} className="flex min-w-0 items-start gap-3 text-left">
          <span
            className={joinClasses(
              'grid h-9 w-9 shrink-0 place-items-center rounded-xl',
              isDark ? 'bg-white/10 text-white' : 'bg-brand-canvas text-brand',
            )}
          >
            <BadgeDollarSign className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-sm font-semibold">
              Planos e preços
              {aberto ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </span>
            <span className={joinClasses('mt-0.5 block text-xs', mutedClass)}>
              {planos.length === 0
                ? 'Nenhum plano carregado ainda'
                : `${planos.length} planos · ${
                    semPreco === 0 ? 'todos com preço definido' : `${semPreco} sem preço (não emitem fatura)`
                  }`}
            </span>
          </span>
        </button>
        {aberto && (
          <button type="button" onClick={onRecarregar} disabled={carregando} className={agentiveSecondaryButtonClass(isDark)}>
            <RefreshCw className={joinClasses('h-4 w-4', carregando && 'animate-spin')} />
            Recarregar planos
          </button>
        )}
      </div>

      {aberto && (
        <div className="mt-4">
          {erro && (
            <AgentiveAlert variant="error" title="Não foi possível carregar os planos">
              <p>{erro}</p>
            </AgentiveAlert>
          )}

          {!erro && carregando && planos.length === 0 && (
            <div className="flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              Carregando os planos
            </div>
          )}

          {!erro && planos.length > 0 && (
            <div className="flex flex-col gap-3">
              {planos.map((plano) => (
                <PlanoRow
                  key={plano.id}
                  plano={plano}
                  isDark={isDark}
                  salvando={salvandoId === plano.id}
                  onSalvar={onSalvar}
                />
              ))}
              <p className={joinClasses('text-xs', mutedClass)}>
                O preço vale daqui para frente: faturas já emitidas mantêm o valor da emissão.
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

// --------------------------------------------------------------------------
// Pills
// --------------------------------------------------------------------------
const pillBase = 'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium';

const pillNeutro = (isDark: boolean) =>
  joinClasses(pillBase, isDark ? 'border-white/10 bg-white/[0.06] text-white/65' : 'border-brand/10 bg-white text-brand/60');

/**
 * Cor por status de fatura. As classes são literais: o Tailwind só gera o que
 * encontra escrito no código, então nada de montar `text-${cor}`.
 */
const pillStatusFatura = (isDark: boolean, status: string) => {
  if (status === 'paga') {
    return joinClasses(pillBase, isDark ? 'border-emerald-700/50 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700');
  }
  if (status === 'aberta') {
    return joinClasses(pillBase, isDark ? 'border-amber-700/50 bg-amber-900/20 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-800');
  }
  return joinClasses(pillBase, isDark ? 'border-white/10 bg-white/[0.06] text-white/45' : 'border-brand/10 bg-white text-brand/45');
};

// --------------------------------------------------------------------------
// Plano & cobrança da empresa
// --------------------------------------------------------------------------
interface CobrancaEmpresaPanelProps {
  aberto: boolean;
  /** Outra ação da tela em andamento (trocar contexto, salvar modalidade). */
  bloqueado: boolean;
  carregando: boolean;
  cobranca: CobrancaEmpresa | null;
  empresaNome: string;
  emitindo: boolean;
  erro: string | null;
  /** Fatura cujo PATCH está em voo. */
  faturaEmAndamento: number | null;
  isDark: boolean;
  onAlternar: () => void;
  onAtualizarFatura: (fatura: Fatura, status: StatusFatura) => void;
  onEmitir: () => void;
  onRecarregar: () => void;
  onSalvarAssinatura: (planoId: number, diaVencimento: number) => void;
  planos: Plano[];
  salvando: boolean;
}

/**
 * Área "Plano & cobrança" de um cartão de empresa. Fechada por padrão: são
 * campos, totais e uma lista de faturas por cliente — aberto em todas as
 * empresas de uma vez, a lista de clientes viraria um formulário gigante.
 *
 * O GET só acontece na primeira abertura. Até lá o cartão mostra o resumo e não
 * paga o custo de uma chamada por empresa.
 */
export const CobrancaEmpresaPanel: React.FC<CobrancaEmpresaPanelProps> = ({
  aberto,
  bloqueado,
  carregando,
  cobranca,
  empresaNome,
  emitindo,
  erro,
  faturaEmAndamento,
  isDark,
  onAlternar,
  onAtualizarFatura,
  onEmitir,
  onRecarregar,
  onSalvarAssinatura,
  planos,
  salvando,
}) => {
  const assinatura = cobranca?.assinatura ?? null;
  const [planoEscolhido, setPlanoEscolhido] = useState<string>(assinatura ? String(assinatura.plano_id) : '');
  const [dia, setDia] = useState<string>(assinatura ? String(assinatura.dia_vencimento) : '');

  useEffect(() => {
    setPlanoEscolhido(assinatura ? String(assinatura.plano_id) : '');
    setDia(assinatura ? String(assinatura.dia_vencimento) : '');
  }, [assinatura?.id, assinatura?.plano_id, assinatura?.dia_vencimento]);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const faintClass = isDark ? 'text-white/40' : 'text-brand/45';
  const borderClass = isDark ? 'border-white/10' : 'border-brand/10';
  const softClass = isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas';

  // Plano inativo não pode ser contratado (o backend responde 409). Ele fica na
  // lista só enquanto É o plano atual, para o select não exibir um valor que
  // não está entre as opções.
  const opcoes = planos.filter((plano) => plano.ativo || plano.id === assinatura?.plano_id);
  const planoAtual = planos.find((plano) => plano.id === assinatura?.plano_id) ?? null;
  const diaNumero = Number(dia);
  const diaValido = dia.trim() !== '' && Number.isInteger(diaNumero) && diaNumero >= 1 && diaNumero <= 28;
  const planoNumero = Number(planoEscolhido);
  const mudouPlano = planoEscolhido !== '' && planoNumero !== (assinatura?.plano_id ?? 0);
  const mudouDia = diaValido && diaNumero !== (assinatura?.dia_vencimento ?? 0);
  const podeSalvar = planoEscolhido !== '' && diaValido && (mudouPlano || mudouDia) && !salvando && !bloqueado;

  const competencia = competenciaAtual();
  const faturaDoMes = cobranca?.faturas.find((fatura) => fatura.competencia === competencia) ?? null;

  /**
   * Por que o botão de emitir está desabilitado. A razão fica escrita ao lado:
   * desabilitar sem dizer o motivo é o mesmo que esconder a ação.
   */
  const impedimento = (() => {
    if (!cobranca) return 'Carregue o plano desta empresa para emitir.';
    if (!assinatura) return 'Defina o plano e o dia de vencimento acima para poder emitir.';
    if (!planoAtual) return 'O plano desta assinatura não está no catálogo carregado. Recarregue os planos.';
    if (planoAtual.preco_centavos === null) {
      return `O plano ${planoAtual.nome} está sem preço. Defina o preço em "Planos e preços" para poder emitir.`;
    }
    if (faturaDoMes) return `A fatura de ${rotuloCompetencia(competencia)} já foi emitida (${faturaDoMes.status}).`;
    return null;
  })();

  const resumo = (() => {
    if (!cobranca) return 'ver plano, faturas e totais';
    if (!assinatura) return 'sem plano definido';
    return `${assinatura.plano_nome} · vence dia ${assinatura.dia_vencimento} · em aberto ${formatarPreco(
      cobranca.total_aberto_centavos,
    )}`;
  })();

  return (
    <div className={joinClasses('mt-4 rounded-2xl border', borderClass)}>
      <button
        type="button"
        onClick={onAlternar}
        aria-expanded={aberto}
        className={joinClasses(
          'flex w-full items-start gap-2 rounded-2xl p-3 text-left transition-colors',
          isDark ? 'hover:bg-white/[0.04]' : 'hover:bg-brand-canvas',
        )}
      >
        <Wallet className={joinClasses('mt-0.5 h-3.5 w-3.5 shrink-0', mutedClass)} />
        <span className="min-w-0 flex-1">
          <span
            className={joinClasses(
              'flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em]',
              mutedClass,
            )}
          >
            Plano &amp; cobrança
            {aberto ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            {carregando ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          </span>
          <span className="mt-0.5 block truncate text-xs">{resumo}</span>
        </span>
        {assinatura && (
          <span className={pillStatusFatura(isDark, assinatura.status === 'ativa' ? 'paga' : 'cancelada')}>
            {assinatura.status}
          </span>
        )}
      </button>

      {aberto && (
        <div className={joinClasses('border-t px-3 pb-3 pt-3', borderClass)}>
          {erro && (
            <AgentiveAlert variant="error" title="Não foi possível ler a cobrança">
              <p>{erro}</p>
              <button type="button" onClick={onRecarregar} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
                <RefreshCw className="h-4 w-4" />
                Tentar novamente
              </button>
            </AgentiveAlert>
          )}

          {!erro && !cobranca && carregando && (
            <div className="flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              Carregando plano e faturas
            </div>
          )}

          {!erro && cobranca && (
            <div className="flex flex-col gap-3">
              {/* Plano e vencimento */}
              <div className={joinClasses('rounded-2xl border p-3', borderClass, softClass)}>
                <p className={joinClasses('text-[11px] font-semibold uppercase tracking-[0.08em]', mutedClass)}>
                  Plano contratado
                </p>
                <p className="mt-1 text-sm leading-snug">
                  {assinatura ? (
                    <>
                      <strong>{assinatura.plano_nome}</strong> · vence todo dia{' '}
                      <strong>{assinatura.dia_vencimento}</strong> · desde {formatarVencimento(assinatura.inicio)}
                      {planoAtual ? ` · ${formatarPreco(planoAtual.preco_centavos)}` : ''}
                    </>
                  ) : (
                    <span className={mutedClass}>Esta empresa ainda não tem plano. Nada é cobrado até definir um.</span>
                  )}
                </p>

                <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
                  <div className="min-w-0 sm:flex-1">
                    <label htmlFor={`plano-empresa-${cobranca.company_id}`} className={agentiveLabelClass(isDark)}>
                      Plano
                    </label>
                    <select
                      id={`plano-empresa-${cobranca.company_id}`}
                      value={planoEscolhido}
                      onChange={(event) => setPlanoEscolhido(event.target.value)}
                      disabled={salvando || bloqueado}
                      className={agentiveInputClass(isDark)}
                    >
                      <option value="">Selecione o plano</option>
                      {opcoes.map((plano) => (
                        <option key={plano.id} value={plano.id}>
                          {plano.nome}
                          {plano.preco_centavos === null ? ' — sem preço' : ` — ${formatarPreco(plano.preco_centavos)}`}
                          {plano.ativo ? '' : ' (inativo)'}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="w-full sm:w-36">
                    <label htmlFor={`dia-empresa-${cobranca.company_id}`} className={agentiveLabelClass(isDark)}>
                      Dia de vencimento
                    </label>
                    <input
                      id={`dia-empresa-${cobranca.company_id}`}
                      type="number"
                      min={1}
                      max={28}
                      step={1}
                      value={dia}
                      onChange={(event) => setDia(event.target.value)}
                      disabled={salvando || bloqueado}
                      className={agentiveInputClass(isDark)}
                      aria-invalid={dia.trim() !== '' && !diaValido}
                    />
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      if (podeSalvar) onSalvarAssinatura(planoNumero, diaNumero);
                    }}
                    disabled={!podeSalvar}
                    className={agentivePrimaryButtonClass('shrink-0')}
                  >
                    {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    {salvando ? 'Salvando...' : 'Salvar plano'}
                  </button>
                </div>

                {dia.trim() !== '' && !diaValido && (
                  <p className="mt-2 text-xs text-red-500">
                    O dia vai de 1 a 28 — 29, 30 e 31 não existem em fevereiro.
                  </p>
                )}
                <p className={joinClasses('mt-2 text-xs', faintClass)}>
                  {assinatura
                    ? 'Trocar o plano encerra a assinatura atual e abre outra a partir de hoje; as faturas já emitidas não mudam.'
                    : 'Definir o plano cria a assinatura desta empresa. A primeira fatura só existe quando você emitir.'}
                </p>
              </div>

              {/* Totais */}
              <div className="grid grid-cols-2 gap-3">
                <div className={joinClasses('rounded-2xl border p-3', borderClass, softClass)}>
                  <p
                    className={joinClasses(
                      'flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.08em]',
                      mutedClass,
                    )}
                  >
                    <AlertCircle className="h-3.5 w-3.5" />
                    Em aberto
                  </p>
                  <p className="mt-1 text-sm font-semibold">{formatarPreco(cobranca.total_aberto_centavos)}</p>
                </div>
                <div className={joinClasses('rounded-2xl border p-3', borderClass, softClass)}>
                  <p
                    className={joinClasses(
                      'flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.08em]',
                      mutedClass,
                    )}
                  >
                    <CalendarDays className="h-3.5 w-3.5" />
                    Pago
                  </p>
                  <p className="mt-1 text-sm font-semibold">{formatarPreco(cobranca.total_pago_centavos)}</p>
                </div>
              </div>

              {/* Emissão */}
              <div className={joinClasses('rounded-2xl border p-3', borderClass, softClass)}>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">Fatura de {rotuloCompetencia(competencia)}</p>
                    <p className={joinClasses('mt-0.5 text-xs', impedimento ? faintClass : mutedClass)}>
                      {impedimento ??
                        `Emite ${formatarPreco(planoAtual?.preco_centavos ?? null)} com vencimento em ${formatarVencimento(
                          vencimentoPrevisto(competencia, diaValido ? diaNumero : assinatura?.dia_vencimento ?? 1),
                        )}.`}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={onEmitir}
                    disabled={Boolean(impedimento) || emitindo || bloqueado}
                    className={agentivePrimaryButtonClass('shrink-0')}
                    title={impedimento ?? `Emite a fatura de ${competencia} para ${empresaNome}`}
                  >
                    {emitindo ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                    {emitindo ? 'Emitindo...' : 'Emitir fatura do mês'}
                  </button>
                </div>
              </div>

              {/* Faturas */}
              <div className={joinClasses('rounded-2xl border p-3', borderClass, softClass)}>
                <p
                  className={joinClasses(
                    'flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.08em]',
                    mutedClass,
                  )}
                >
                  <FileText className="h-3.5 w-3.5" />
                  Faturas ({cobranca.faturas.length})
                </p>

                {cobranca.faturas.length === 0 ? (
                  <p className={joinClasses('mt-2 text-xs', faintClass)}>
                    Nenhuma fatura emitida. A primeira só existe quando você clicar em &quot;Emitir fatura do mês&quot;.
                  </p>
                ) : (
                  <ul className="mt-2 flex flex-col gap-2">
                    {cobranca.faturas.map((fatura) => {
                      const emVoo = faturaEmAndamento === fatura.id;
                      const podeMarcarPaga = fatura.status === 'aberta';
                      return (
                        <li
                          key={fatura.id}
                          className={joinClasses(
                            'flex flex-col gap-2 rounded-xl border p-2.5 sm:flex-row sm:items-center sm:justify-between',
                            isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white',
                          )}
                        >
                          <div className="flex min-w-0 flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold">{rotuloCompetencia(fatura.competencia)}</span>
                            <span className="text-sm">{formatarPreco(fatura.valor_centavos)}</span>
                            <span className={joinClasses('text-xs', mutedClass)}>
                              venc. {formatarVencimento(fatura.vencimento)}
                            </span>
                            <span className={pillStatusFatura(isDark, fatura.status)}>{fatura.status}</span>
                            {fatura.pago_em && (
                              <span className={joinClasses('text-xs', faintClass)}>
                                paga em {formatarVencimento(fatura.pago_em)}
                              </span>
                            )}
                          </div>

                          <div className="flex shrink-0 items-center gap-2">
                            <button
                              type="button"
                              onClick={() => onAtualizarFatura(fatura, podeMarcarPaga ? 'paga' : 'aberta')}
                              disabled={emVoo || bloqueado}
                              className={agentiveSecondaryButtonClass(isDark)}
                              title={
                                podeMarcarPaga
                                  ? 'Registra o pagamento desta fatura'
                                  : 'Volta a fatura para em aberto e limpa a data de pagamento'
                              }
                            >
                              {emVoo ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                              {podeMarcarPaga ? 'Marcar paga' : 'Reabrir'}
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Vencimento que o backend vai calcular: dia da assinatura dentro da
 * competência, limitado ao último dia do mês (fevereiro não tem 30).
 *
 * É só o texto do botão; quem grava a data é o backend.
 */
function vencimentoPrevisto(competencia: string, dia: number): string {
  const [anoTexto, mesTexto] = competencia.split('-');
  const ano = Number(anoTexto);
  const mes = Number(mesTexto);
  if (!Number.isInteger(ano) || !Number.isInteger(mes)) return '';
  const ultimoDia = new Date(ano, mes, 0).getDate();
  const diaFinal = Math.min(Math.max(dia, 1), ultimoDia);
  return `${anoTexto}-${mesTexto}-${String(diaFinal).padStart(2, '0')}`;
}
