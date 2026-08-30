import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiClientError, createWidgetApi, widgetApi } from './api';
import type { Alert as ApiAlert, AlertType, ApiMeta, AuthSession, ConversationData, MessageEnvelope, Opportunity as ApiOpportunity } from './api';

type View = 'welcome' | 'email' | 'otp' | 'quiz' | 'result' | 'dashboard' | 'opportunity' | 'simulation' | 'hub' | 'alerts';
type ProfileLevel = 'conservative' | 'moderate' | 'aggressive';
type ErrorKind = 'empty' | 'invalid' | 'network' | null;
type ErrorContext = 'email' | 'otp' | 'quiz' | 'profile' | 'simulation';
type RiskLevel = 'low' | 'medium' | 'high' | 'unknown';
type AuditStatus = 'audited' | 'partially_audited' | 'not_verified' | 'unknown';
type SimulationHorizon = 30 | 180 | 365;
type SimulationState = 'idle' | 'loading' | 'ready' | 'error';
type SimulationErrorField = 'amount' | 'horizons' | null;
type DecisionStatus = 'accepted' | 'refused';
type DecisionFilter = 'all' | DecisionStatus;

interface QuestionOption {
  value: string;
  label: string;
}

interface Question {
  id: string;
  title: string;
  prompt: string;
  helper: string;
  options: readonly QuestionOption[];
}

interface OtpChallenge {
  challengeId: string;
  expiresAt: string;
}

interface SavedProfile {
  declaredProfile: ProfileLevel;
  answers: Record<string, string>;
  declaredAt: string;
}

interface OpportunityDataSource {
  source: 'defillama';
  mode: 'live' | 'cache' | 'test' | 'fallback';
  observedAt: string;
  retrievedAt: string;
  readOnly: true;
  isStale: boolean;
  freshnessNote?: string;
  sourceLabel?: string;
  statusLabel?: string;
}

interface SyntheticOpportunity {
  opportunityId: string;
  protocol: string;
  pool: string;
  asset: string;
  blockchain: string;
  category: string;
  apy: { value: number; observedAt: string; display?: string };
  tvl: { value: number; currency: string; observedAt: string; display?: string; displayCompact?: string };
  liquidity: { level: 'low' | 'medium' | 'high' | 'unknown'; observedAt: string };
  risk: { level: RiskLevel; dimensions: readonly string[] };
  auditStatus: AuditStatus;
  gasEstimate: string;
  dataSource: OpportunityDataSource;
  disclaimer: string;
}

interface SimulationScenario {
  horizonDays: SimulationHorizon;
  projectedValue: number;
  projectedYield: number;
  idleStablecoinValue: number;
  currency: string;
  projectedValueDisplay?: string;
  projectedYieldDisplay?: string;
  projectedGainDisplay?: string;
  idleStablecoinValueDisplay?: string;
}

interface SimulationResult {
  simulationId: string;
  opportunityId: string;
  amount: number;
  amountDisplay?: string;
  asset: string;
  horizons: readonly SimulationHorizon[];
  scenarios: readonly SimulationScenario[];
  assumptions: readonly string[];
  formulaVersion: string;
  generatedAt: string;
  dataSource: OpportunityDataSource;
  executionSupported: false;
  disclaimer: string;
}

interface SavedSimulationPlan {
  planId: string;
  opportunityId: string;
  protocol: string;
  pool: string;
  amount: number;
  asset: string;
  horizons: readonly SimulationHorizon[];
  simulationId: string;
  savedAt: string;
}

interface DecisionRecord {
  decisionId: string;
  opportunityId: string;
  protocol: string;
  pool: string;
  amount: number;
  asset: string;
  horizons: readonly SimulationHorizon[];
  status: DecisionStatus;
  reason: string;
  decidedAt: string;
  formulaVersion: string;
}

const IS_FIXTURE_MODE = widgetApi.mode === 'fixture';

const questions: readonly Question[] = [
  {
    id: 'q1',
    title: 'Seu ponto de partida',
    prompt: 'Como você prefere receber uma explicação sobre uma oportunidade?',
    helper: 'Escolha a opção que mais combina com você hoje.',
    options: [
      { value: 'simple', label: 'Em linguagem simples, com os pontos principais' },
      { value: 'complete', label: 'Com detalhes, fontes e contexto para comparar' },
      { value: 'guided', label: 'Com uma trilha passo a passo e exemplos' },
    ],
  },
  {
    id: 'q2',
    title: 'Como você decide',
    prompt: 'O que ajuda você a se sentir seguro para avançar em uma análise?',
    helper: 'Não existe resposta certa ou errada.',
    options: [
      { value: 'time', label: 'Ter tempo para ler e pensar com calma' },
      { value: 'comparison', label: 'Comparar alternativas e seus riscos' },
      { value: 'support', label: 'Contar com orientações claras em cada etapa' },
    ],
  },
  {
    id: 'q3',
    title: 'Seu ritmo',
    prompt: 'Qual ritmo de descoberta você prefere?',
    helper: 'A AuraFi pode adaptar a profundidade das explicações depois.',
    options: [
      { value: 'slow', label: 'Ir com calma, uma novidade por vez' },
      { value: 'balanced', label: 'Equilibrar novidades e tempo para revisar' },
      { value: 'fast', label: 'Conhecer mais possibilidades de uma vez' },
    ],
  },
  {
    id: 'q4',
    title: 'Sua prioridade',
    prompt: 'Ao conhecer uma alternativa, o que você quer ver primeiro?',
    helper: 'Sua resposta ajuda a organizar a próxima experiência.',
    options: [
      { value: 'risks', label: 'Riscos, limites e o que pode dar errado' },
      { value: 'context', label: 'Contexto, critérios e como comparar' },
      { value: 'possibilities', label: 'Possibilidades e cenários para estudar' },
    ],
  },
  {
    id: 'q5',
    title: 'Sua declaração',
    prompt: 'Qual perfil você deseja declarar para organizar suas próximas explicações?',
    helper: 'Esta é uma escolha sua. A AuraFi não calcula ou infere o perfil a partir de dados externos.',
    options: [
      { value: 'conservative', label: 'Conservador — priorizo cautela e previsibilidade' },
      { value: 'moderate', label: 'Moderado — busco equilíbrio entre cautela e possibilidades' },
      { value: 'aggressive', label: 'Arrojado — aceito estudar mais oscilações e possibilidades' },
    ],
  },
];

const profileCopy: Record<ProfileLevel, { label: string; description: string }> = {
  conservative: {
    label: 'Conservador',
    description: 'Você declarou preferência por cautela, clareza de limites e mais tempo para revisar.',
  },
  moderate: {
    label: 'Moderado',
    description: 'Você declarou preferência por equilibrar cautela, contexto e possibilidades.',
  },
  aggressive: {
    label: 'Arrojado',
    description: 'Você declarou abertura para estudar mais oscilações e possibilidades com contexto.',
  },
};

const syntheticDataSource: OpportunityDataSource = {
  source: 'defillama',
  mode: 'test',
  observedAt: '2026-08-02T11:45:00.000Z',
  retrievedAt: '2026-08-02T12:00:00.000Z',
  readOnly: true,
  isStale: true,
  freshnessNote: 'Fixture sintética de teste; não representa uma leitura live e pode estar desatualizada.',
};

const opportunities: readonly SyntheticOpportunity[] = [
  {
    opportunityId: 'fixture-aave-usdc-base',
    protocol: 'Aave',
    pool: 'USDC Supply',
    asset: 'USDC',
    blockchain: 'Base',
    category: 'Lending',
    apy: { value: 5.2, observedAt: syntheticDataSource.observedAt },
    tvl: { value: 1200000, currency: 'USD', observedAt: syntheticDataSource.observedAt },
    liquidity: { level: 'high', observedAt: syntheticDataSource.observedAt },
    risk: { level: 'medium', dimensions: ['smart_contract', 'liquidity', 'underlying_asset'] },
    auditStatus: 'partially_audited',
    gasEstimate: 'US$ 3,40',
    dataSource: syntheticDataSource,
    disclaimer: 'Fixture sintética para estudo; APY, TVL, gas e risco não são promessa, recomendação ou cotação atual.',
  },
  {
    opportunityId: 'fixture-compound-dai-ethereum',
    protocol: 'Compound',
    pool: 'DAI Supply',
    asset: 'DAI',
    blockchain: 'Ethereum',
    category: 'Lending',
    apy: { value: 3.8, observedAt: syntheticDataSource.observedAt },
    tvl: { value: 860000, currency: 'USD', observedAt: syntheticDataSource.observedAt },
    liquidity: { level: 'medium', observedAt: syntheticDataSource.observedAt },
    risk: { level: 'unknown', dimensions: ['smart_contract', 'liquidity', 'data_quality'] },
    auditStatus: 'not_verified',
    gasEstimate: 'US$ 8,10',
    dataSource: syntheticDataSource,
    disclaimer: 'Fixture sintética para estudo; faltam dados suficientes para concluir sobre segurança ou adequação.',
  },
  {
    opportunityId: 'fixture-uniswap-eth-usdc-arbitrum',
    protocol: 'Uniswap',
    pool: 'ETH / USDC',
    asset: 'ETH + USDC',
    blockchain: 'Arbitrum',
    category: 'DEX / Liquidez',
    apy: { value: 8.1, observedAt: syntheticDataSource.observedAt },
    tvl: { value: 430000, currency: 'USD', observedAt: syntheticDataSource.observedAt },
    liquidity: { level: 'medium', observedAt: syntheticDataSource.observedAt },
    risk: { level: 'high', dimensions: ['smart_contract', 'liquidity', 'volatility', 'underlying_asset'] },
    auditStatus: 'partially_audited',
    gasEstimate: 'US$ 0,42',
    dataSource: syntheticDataSource,
    disclaimer: 'Fixture sintética para estudo; pools de liquidez podem envolver volatilidade e perda impermanente.',
  },
];

function mapApiOpportunity(item: ApiOpportunity): SyntheticOpportunity {
  return {
    opportunityId: item.opportunityId,
    protocol: item.protocol,
    pool: item.pool,
    asset: item.asset,
    blockchain: item.blockchain,
    category: item.pool.toLowerCase().includes('supply') ? 'Lending' : 'Liquidity',
    apy: {
      value: item.apy.value,
      observedAt: item.apy.observedAt,
      ...(item.apy.display ? { display: item.apy.display } : {}),
    },
    tvl: {
      value: item.tvl.value,
      currency: item.tvl.currency,
      observedAt: item.tvl.observedAt,
      ...(item.tvl.display ? { display: item.tvl.display } : {}),
      ...(item.tvl.displayCompact ? { displayCompact: item.tvl.displayCompact } : {}),
    },
    liquidity: { level: item.liquidity.level, observedAt: item.liquidity.observedAt },
    risk: { level: item.risk.level, dimensions: item.risk.dimensions },
    auditStatus: item.auditStatus ?? 'unknown',
    gasEstimate: 'Não informado pela fonte',
    dataSource: {
      source: item.dataSource.source,
      mode: item.dataSource.mode,
      observedAt: item.dataSource.observedAt,
      retrievedAt: item.dataSource.retrievedAt,
      readOnly: true,
      isStale: item.dataSource.isStale,
      ...(item.dataSource.freshnessNote ? { freshnessNote: item.dataSource.freshnessNote } : {}),
      ...(item.dataSource.sourceLabel ? { sourceLabel: item.dataSource.sourceLabel } : {}),
      ...(item.dataSource.statusLabel ? { statusLabel: item.dataSource.statusLabel } : {}),
    },
    disclaimer: item.disclaimer,
  };
}

const SIMULATION_ASSUMPTIONS: readonly string[] = [
  'O APY observado é tratado como percentual anualizado e aplicado linearmente por dias / 365.',
  'A comparação com stablecoin parada preserva o principal e considera rendimento zero.',
  'A variação projetada representa o percentual acumulado do cenário.',
];
const SIMULATION_FORMULA_VERSION = 'linear-educational-v1';
const SIMULATION_DISCLAIMER = 'Simulação educativa baseada em premissas explícitas. Os valores não são promessa, recomendação, cotação ou resultado esperado. Nenhuma wallet é conectada e nenhuma transação é executada.';
const SIMULATION_HORIZONS: readonly SimulationHorizon[] = [30, 180, 365];
const DECISION_HISTORY_KEY = 'aurafi-widget-decision-history-v1';
const SAVED_PLANS_KEY = 'aurafi-widget-saved-plans-v1';
const AUTH_SESSION_KEY = 'aurafi-widget-auth-session-v1';
const CONVERSATION_KEY = 'aurafi-widget-conversation-v1';

function readSession(): AuthSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(AUTH_SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as AuthSession;
    if (!value.accessToken || !value.refreshToken || !value.expiresAt || !Number.isFinite(Date.parse(value.expiresAt))) {
      window.sessionStorage.removeItem(AUTH_SESSION_KEY);
      window.sessionStorage.removeItem(CONVERSATION_KEY);
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

function saveSession(value: AuthSession | null): void {
  if (typeof window === 'undefined') return;
  if (value) window.sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(value));
  else {
    window.sessionStorage.removeItem(AUTH_SESSION_KEY);
    window.sessionStorage.removeItem(CONVERSATION_KEY);
  }
}

function messageText(message: MessageEnvelope): string {
  return typeof message.payload.text === 'string' ? message.payload.text : 'Mensagem sem conteúdo textual.';
}

/** The model emits **bold** markdown; render it as elements so the literal
 *  asterisks stop showing up in the bubbles. Parsed into React nodes rather
 *  than injected as HTML, so model output is never treated as markup. */
function renderMessageText(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => (part.startsWith('**') && part.endsWith('**') && part.length > 4
    ? <strong key={index}>{part.slice(2, -2)}</strong>
    : <React.Fragment key={index}>{part}</React.Fragment>));
}

function readLocalArray<T>(key: string): T[] {
  if (typeof window === 'undefined') return [];
  try {
    const stored = window.localStorage.getItem(key);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed as T[] : [];
  } catch {
    return [];
  }
}

function writeLocalArray<T>(key: string, value: readonly T[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
  }
}

function getErrorMessage(kind: ErrorKind, context: ErrorContext): string {
  if (kind === 'empty') {
    return context === 'email'
      ? 'Digite seu e-mail para continuar.'
      : context === 'otp'
        ? 'Digite o código de seis números que enviamos.'
        : context === 'quiz'
        ? 'Escolha uma opção para continuar.'
        : context === 'profile'
          ? 'Escolha um perfil declarado para continuar.'
          : 'Informe um valor maior que zero e selecione ao menos um cenário.';
  }
  if (kind === 'invalid') {
    return 'Esse código não confere. Confira os seis números e tente novamente.';
  }
  return 'Não foi possível concluir agora. Verifique sua conexão e tente novamente.';
}

function maskEmail(email: string): string {
  const [name, domain] = email.split('@');
  if (!name || !domain) return email;
  const visibleName = name.length > 2 ? `${name.slice(0, 2)}•••` : `${name.slice(0, 1)}•••`;
  return `${visibleName}@${domain}`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatPercent(value: number): string {
  return `${value.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function formatAssetAmount(value: number): string {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function parseSimulationAmount(value: string): number {
  const normalized = value.trim().replace(/\s/g, '');
  if (!normalized) return Number.NaN;
  return Number(normalized.includes(',') ? normalized.replace(/\./g, '').replace(',', '.') : normalized);
}

function decisionStatusLabel(status: DecisionStatus): string {
  return status === 'accepted' ? 'Aceita' : 'Recusada';
}

function alertTypeLabel(type: AlertType): string {
  return {
    apy_change: 'Mudança de APY',
    risk_change: 'Mudança de risco',
    new_opportunity: 'Nova oportunidade',
    data_stale: 'Dado desatualizado',
  }[type];
}

function riskLabel(level: RiskLevel): string {
  return {
    low: 'Baixo',
    medium: 'Médio',
    high: 'Alto',
    unknown: 'Não informado',
  }[level];
}

function dataModeLabel(mode: OpportunityDataSource['mode']): string {
  return {
    live: 'Dados atualizados',
    cache: 'Última leitura disponível',
    test: 'Ambiente de demonstração',
    fallback: 'Atualização pendente',
  }[mode];
}

function dataModeDescription(mode: OpportunityDataSource['mode']): string {
  return {
    live: 'Leitura atual da fonte DeFiLlama',
    cache: 'Última leitura preservada para continuidade',
    test: 'Ambiente de demonstração explicitamente habilitado',
    fallback: 'A fonte está indisponível; revise a atualização antes de decidir',
  }[mode];
}

function auditLabel(status: AuditStatus): string {
  return {
    audited: 'Auditado',
    partially_audited: 'Parcialmente auditado',
    not_verified: 'Não verificado',
    unknown: 'Não informado',
  }[status];
}

function publicAssumption(value: string): string {
  return value.replace(/^\[[^\]]+\]\s*/u, '').replace(/fixture local/giu, 'dados disponíveis');
}

function AuraMark() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

function InlineAlert({ message, onRetry, id }: { message: string; onRetry?: () => void; id?: string }) {
  return (
    <div id={id} className="inline-alert" role="alert">
      <span className="alert-icon" aria-hidden="true">!</span>
      <p>{message}</p>
      {onRetry ? (
        <button className="text-button alert-retry" type="button" onClick={onRetry}>
          Tentar novamente
        </button>
      ) : null}
    </div>
  );
}

function isInvalidOtpError(error: unknown): boolean {
  return error instanceof ApiClientError && error.code === 'AUTHENTICATION_FAILED';
}

function ProgressBar({ current }: { current: number }) {
  const percentage = Math.round((current / questions.length) * 100);
  return (
    <div className="progress-block" role="group" aria-label={`Pergunta ${current} de ${questions.length}`}>
      <div className="progress-meta">
        <span>Seu perfil</span>
        <span>{current} de {questions.length}</span>
      </div>
      <div className="progress-track" role="progressbar" aria-valuemin={1} aria-valuemax={questions.length} aria-valuenow={current}>
        <div className="progress-value" style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

export default function App() {
  const [restoredSession] = useState<AuthSession | null>(() => readSession());
  const [authSession, setAuthSession] = useState<AuthSession | null>(restoredSession);
  const [view, setView] = useState<View>(() => restoredSession ? 'dashboard' : 'welcome');
  const [email, setEmail] = useState(() => restoredSession?.email ?? '');
  const [accessToken, setAccessToken] = useState<string | null>(() => restoredSession && Date.parse(restoredSession.expiresAt) > Date.now() ? restoredSession.accessToken : null);
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [otp, setOtp] = useState('');
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [declaredProfile, setDeclaredProfile] = useState<ProfileLevel | null>(null);
  const [savedProfile, setSavedProfile] = useState<SavedProfile | null>(null);
  const [errorKind, setErrorKind] = useState<ErrorKind>(null);
  const [errorContext, setErrorContext] = useState<ErrorContext>('email');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [favoriteOpportunityIds, setFavoriteOpportunityIds] = useState<string[]>([]);
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<string | null>(null);
  const [simulationOpportunityId, setSimulationOpportunityId] = useState<string | null>(null);
  const [simulationAmount, setSimulationAmount] = useState('');
  const [simulationHorizons, setSimulationHorizons] = useState<SimulationHorizon[]>([30, 180, 365]);
  const [simulationState, setSimulationState] = useState<SimulationState>('idle');
  const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [simulationErrorField, setSimulationErrorField] = useState<SimulationErrorField>(null);
  const [savedPlans, setSavedPlans] = useState<SavedSimulationPlan[]>(() => readLocalArray<SavedSimulationPlan>(SAVED_PLANS_KEY));
  const [savedPlanId, setSavedPlanId] = useState<string | null>(null);
  const [decisionHistory, setDecisionHistory] = useState<DecisionRecord[]>(() => readLocalArray<DecisionRecord>(DECISION_HISTORY_KEY));
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>('all');
  const [decisionDraftStatus, setDecisionDraftStatus] = useState<DecisionStatus | null>(null);
  const [decisionReason, setDecisionReason] = useState('');
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionMessage, setDecisionMessage] = useState<string | null>(null);
  const [isEducationOpen, setIsEducationOpen] = useState(false);
  const [dashboardOpportunities, setDashboardOpportunities] = useState<SyntheticOpportunity[]>(() => IS_FIXTURE_MODE ? [...opportunities] : []);
  const [opportunityState, setOpportunityState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [opportunityError, setOpportunityError] = useState<string | null>(null);
  const [opportunityMeta, setOpportunityMeta] = useState<ApiMeta | null>(null);
  const [opportunityFilter, setOpportunityFilter] = useState<'all' | RiskLevel>('all');
  const [opportunityRefreshKey, setOpportunityRefreshKey] = useState(0);
  const [alertItems, setAlertItems] = useState<ApiAlert[]>([]);
  const [alertsState, setAlertsState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [alertsRefreshKey, setAlertsRefreshKey] = useState(0);
  const unreadAlertCount = alertItems.filter((alert) => alert.status === 'unread').length;
  const [conversation, setConversation] = useState<ConversationData | null>(null);
  const [conversationDraft, setConversationDraft] = useState('');
  const [conversationState, setConversationState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [conversationError, setConversationError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const educationCloseRef = useRef<HTMLButtonElement>(null);
  const educationModalRef = useRef<HTMLElement>(null);
  const educationTriggerRef = useRef<HTMLElement | null>(null);
  const conversationLogRef = useRef<HTMLDivElement>(null);
  const apiClient = useMemo(
    () => accessToken ? createWidgetApi({ token: accessToken }) : widgetApi,
    [accessToken],
  );

  const clearAuthenticatedState = () => {
    saveSession(null);
    setAuthSession(null);
    setAccessToken(null);
    setConversation(null);
    setConversationDraft('');
    setConversationState('idle');
    setConversationError(null);
  };

  const currentQuestion = questions[currentQuestionIndex];
  const selectedAnswer = currentQuestion ? answers[currentQuestion.id] : undefined;
  const answeredCount = useMemo(() => Object.keys(answers).length, [answers]);
  const filteredDecisionHistory = useMemo(
    () => decisionFilter === 'all'
      ? decisionHistory
      : decisionHistory.filter((decision) => decision.status === decisionFilter),
    [decisionFilter, decisionHistory],
  );
  const filteredOpportunities = useMemo(
    () => opportunityFilter === 'all'
      ? dashboardOpportunities
      : dashboardOpportunities.filter((item) => item.risk.level === opportunityFilter),
    [dashboardOpportunities, opportunityFilter],
  );

  useEffect(() => {
    headingRef.current?.focus();
  }, [view, currentQuestionIndex]);

  // Keep the newest message in view, including the "Aura está organizando"
  // indicator while the reply is in flight.
  useEffect(() => {
    const log = conversationLogRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [conversation?.messages.length, conversationState]);

  useEffect(() => {
    writeLocalArray(SAVED_PLANS_KEY, savedPlans);
  }, [savedPlans]);

  useEffect(() => {
    writeLocalArray(DECISION_HISTORY_KEY, decisionHistory);
  }, [decisionHistory]);

  useEffect(() => {
    if (!authSession?.refreshToken) return undefined;
    const refreshInMs = Math.max(0, Date.parse(authSession.expiresAt) - Date.now() - 60_000);
    const timeout = window.setTimeout(() => {
      widgetApi.refreshSession(authSession.refreshToken, {
        requestId: `widget_refresh_${Date.now()}`,
      }).then((result) => {
        saveSession(result.data);
        setAuthSession(result.data);
        setAccessToken(result.data.accessToken);
      }).catch(() => {
        clearAuthenticatedState();
        setView('email');
        setErrorContext('email');
        setErrorKind('network');
      });
    }, Math.min(refreshInMs, 2_147_000_000));
    return () => window.clearTimeout(timeout);
  }, [authSession]);

  useEffect(() => {
    if (!accessToken) return;
    apiClient.getProfile().then((result) => {
      const profile = result.data.riskProfile;
      if (!profile || profile.status !== 'declared') return;
      setEmail(result.data.account.email);
      setDeclaredProfile(profile.declaredProfile);
      setSavedProfile({ declaredProfile: profile.declaredProfile, answers: {}, declaredAt: profile.declaredAt });
    }).catch((error: unknown) => {
      if (error instanceof ApiClientError && error.status === 401) {
        clearAuthenticatedState();
        setView('email');
      }
    });
  }, [accessToken, apiClient]);

  useEffect(() => {
    if (!accessToken) return;
    const conversationId = window.sessionStorage.getItem(CONVERSATION_KEY);
    if (!conversationId) return;
    setConversationState('loading');
    apiClient.getConversation(conversationId).then((result) => {
      setConversation(result.data);
      setConversationState('ready');
    }).catch((error: unknown) => {
      if (error instanceof ApiClientError && error.status === 401) {
        clearAuthenticatedState();
        setView('email');
      }
      setConversationState('error');
      setConversationError('Não foi possível retomar a conversa. Você pode iniciar uma nova conversa com segurança.');
    });
  }, [accessToken, apiClient]);

  useEffect(() => {
    if (view !== 'dashboard') return undefined;

    let cancelled = false;
    setOpportunityState('loading');
    setOpportunityError(null);
    setDashboardOpportunities([]);

    apiClient.listOpportunities(
      { page: 1, pageSize: 12, ...(declaredProfile ? { riskProfile: declaredProfile } : {}) },
      { requestId: `widget_opportunities_${Date.now()}` },
    ).then((result) => {
      if (cancelled) return;
      setDashboardOpportunities(result.data.items.map(mapApiOpportunity));
      setOpportunityMeta(result.meta);
      setOpportunityState('ready');
    }).catch((error: unknown) => {
      if (cancelled) return;
      setOpportunityState('error');
      setOpportunityError(error instanceof Error ? error.message : 'Não foi possível carregar as oportunidades agora.');
    });

    return () => {
      cancelled = true;
    };
  }, [apiClient, declaredProfile, opportunityRefreshKey, view]);

  useEffect(() => {
    if (!accessToken) return undefined;

    let cancelled = false;
    setAlertsState('loading');
    setAlertsError(null);

    apiClient.listAlerts(
      { page: 1, pageSize: 50 },
      { requestId: `widget_alerts_${Date.now()}` },
    ).then((result) => {
      if (cancelled) return;
      setAlertItems(result.data.items);
      setAlertsState('ready');
    }).catch((error: unknown) => {
      if (cancelled) return;
      if (error instanceof ApiClientError && error.status === 401) {
        clearAuthenticatedState();
        setView('email');
        return;
      }
      setAlertsState('error');
      setAlertsError(error instanceof Error ? error.message : 'Não foi possível carregar os alertas agora.');
    });

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiClient, alertsRefreshKey]);

  const handleMarkAlertRead = (alertId: string) => {
    apiClient.markAlertRead(alertId, { requestId: `widget_alert_read_${Date.now()}` }).then((result) => {
      setAlertItems((current) => current.map((alert) => (alert.alertId === alertId ? result.data : alert)));
    }).catch(() => {
      // Melhor esforço: o alerta permanece não lido na tela e o usuário pode tentar de novo.
    });
  };

  useEffect(() => {
    if (!isEducationOpen) return undefined;

    educationTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsEducationOpen(false);
        return;
      }
      if (event.key !== 'Tab') return;

      const modal = educationModalRef.current;
      if (!modal) return;
      const focusable = Array.from(modal.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute('disabled'));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    educationCloseRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      educationTriggerRef.current?.focus();
      educationTriggerRef.current = null;
    };
  }, [isEducationOpen]);

  const clearError = () => setErrorKind(null);

  const startOnboarding = () => {
    clearError();
    setView('email');
  };

  const openDashboard = () => {
    setIsEducationOpen(false);
    setSelectedOpportunityId(null);
    setView('dashboard');
  };

  const openOpportunity = (opportunityId: string) => {
    setSelectedOpportunityId(opportunityId);
    setView('opportunity');
  };

  const toggleFavorite = (opportunityId: string) => {
    setFavoriteOpportunityIds((previous) => previous.includes(opportunityId)
      ? previous.filter((id) => id !== opportunityId)
      : [...previous, opportunityId]);
  };

  const handleStartSimulation = (opportunityId: string) => {
    setSimulationOpportunityId(opportunityId);
    setSimulationAmount('');
    setSimulationHorizons([30, 180, 365]);
    setSimulationState('idle');
    setSimulationResult(null);
    setSimulationError(null);
    setSimulationErrorField(null);
    setSavedPlanId(null);
    setDecisionDraftStatus(null);
    setDecisionReason('');
    setDecisionError(null);
    setDecisionMessage(null);
    setView('simulation');
  };

  const runSimulation = async (opportunity: SyntheticOpportunity, amount: number) => {
    setSimulationState('loading');
    setSimulationError(null);
    setSimulationErrorField(null);
    setDecisionMessage(null);
    try {
      const response = await apiClient.createSimulation({
        opportunityId: opportunity.opportunityId,
        amount,
        asset: opportunity.asset,
        horizonsDays: [...simulationHorizons],
        compareIdleStablecoin: true,
      });
      const data = response.data;
      setSimulationResult({
        simulationId: data.simulationId,
        opportunityId: data.opportunityId,
        amount: data.input.amount,
        ...(data.input.amountDisplay ? { amountDisplay: data.input.amountDisplay } : {}),
        asset: data.input.asset,
        horizons: data.input.horizonsDays,
        scenarios: data.scenarios.map((scenario) => ({
          horizonDays: scenario.horizonDays,
          projectedValue: scenario.projectedValue,
          projectedYield: scenario.projectedYield,
          idleStablecoinValue: scenario.idleStablecoinValue ?? data.input.amount,
          currency: scenario.currency,
          ...(scenario.projectedValueDisplay ? { projectedValueDisplay: scenario.projectedValueDisplay } : {}),
          ...(scenario.projectedYieldDisplay ? { projectedYieldDisplay: scenario.projectedYieldDisplay } : {}),
          ...(scenario.projectedGainDisplay ? { projectedGainDisplay: scenario.projectedGainDisplay } : {}),
          ...(scenario.idleStablecoinValueDisplay ? { idleStablecoinValueDisplay: scenario.idleStablecoinValueDisplay } : {}),
        })),
        assumptions: data.assumptions,
        formulaVersion: data.assumptions[0] ? 'api-assumption-v1' : SIMULATION_FORMULA_VERSION,
        generatedAt: data.generatedAt,
        dataSource: data.dataSource ?? opportunity.dataSource,
        executionSupported: false,
        disclaimer: data.disclaimer,
      });
      setSimulationState('ready');
    } catch {
      setSimulationResult(null);
      setSimulationState('error');
      setSimulationErrorField(null);
      setSimulationError('Não foi possível gerar os cenários agora. Você pode tentar novamente ou voltar ao detalhe com segurança.');
    }
  };

  const handleSimulationSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const opportunity = dashboardOpportunities.find((item) => item.opportunityId === simulationOpportunityId);
    const amount = parseSimulationAmount(simulationAmount);
    if (!opportunity || !Number.isFinite(amount) || amount <= 0 || simulationHorizons.length === 0) {
      setSimulationResult(null);
      setSimulationState('error');
      setSimulationErrorField(!Number.isFinite(amount) || amount <= 0 ? 'amount' : 'horizons');
      setSimulationError(getErrorMessage('empty', 'simulation'));
      return;
    }
    await runSimulation(opportunity, amount);
  };

  const toggleSimulationHorizon = (horizon: SimulationHorizon) => {
    setSimulationHorizons((current) => current.includes(horizon)
      ? current.filter((item) => item !== horizon)
      : [...current, horizon].sort((a, b) => a - b) as SimulationHorizon[]);
    setSimulationResult(null);
    setSimulationState('idle');
    setSimulationError(null);
    setSimulationErrorField(null);
    setSavedPlanId(null);
    setDecisionDraftStatus(null);
    setDecisionReason('');
    setDecisionError(null);
  };

  const handleSaveSimulationPlan = () => {
    const opportunity = dashboardOpportunities.find((item) => item.opportunityId === simulationOpportunityId);
    if (!opportunity || !simulationResult) return;
    const plan: SavedSimulationPlan = {
      planId: `plan_fixture_${Date.now()}`,
      opportunityId: opportunity.opportunityId,
      protocol: opportunity.protocol,
      pool: opportunity.pool,
      amount: simulationResult.amount,
      asset: simulationResult.asset,
      horizons: simulationResult.horizons,
      simulationId: simulationResult.simulationId,
      savedAt: new Date().toISOString(),
    };
    setSavedPlans((current) => [plan, ...current]);
    setSavedPlanId(plan.planId);
    setDecisionMessage('Plano salvo neste dispositivo. Nenhuma ação financeira foi criada.');
  };

  const handleDecisionSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const opportunity = dashboardOpportunities.find((item) => item.opportunityId === simulationOpportunityId);
    if (!opportunity || !simulationResult || !decisionDraftStatus) return;
    const normalizedReason = decisionReason.trim();
    if (!normalizedReason) {
      setDecisionError('Registre um motivo curto para salvar esta decisão no histórico.');
      return;
    }
    const decision: DecisionRecord = {
      decisionId: `decision_fixture_${Date.now()}`,
      opportunityId: opportunity.opportunityId,
      protocol: opportunity.protocol,
      pool: opportunity.pool,
      amount: simulationResult.amount,
      asset: simulationResult.asset,
      horizons: simulationResult.horizons,
      status: decisionDraftStatus,
      reason: normalizedReason,
      decidedAt: new Date().toISOString(),
      formulaVersion: simulationResult.formulaVersion,
    };
    setDecisionHistory((current) => [decision, ...current]);
    setDecisionDraftStatus(null);
    setDecisionReason('');
    setDecisionError(null);
    setDecisionMessage(decision.status === 'accepted'
      ? 'Decisão aceita e registrada neste dispositivo. Isso não executa uma transação.'
      : 'Decisão recusada e registrada neste dispositivo. Nenhuma ação foi executada.');
  };

  const handleRequestOtp = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail || !normalizedEmail.includes('@')) {
      setErrorContext('email');
      setErrorKind('empty');
      return;
    }

    setIsSubmitting(true);
    clearError();
    try {
      const nextChallenge = (await apiClient.requestOtp(normalizedEmail)).data;
      setEmail(normalizedEmail);
      setChallenge(nextChallenge);
      setOtp('');
      setView('otp');
    } catch (error) {
      setErrorContext('email');
      setErrorKind('network');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResendOtp = async () => {
    if (!email) return;
    setIsSubmitting(true);
    clearError();
    try {
      const nextChallenge = (await apiClient.requestOtp(email)).data;
      setChallenge(nextChallenge);
      setOtp('');
    } catch {
      setErrorContext('otp');
      setErrorKind('network');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyOtp = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(otp)) {
      setErrorContext('otp');
      setErrorKind('empty');
      return;
    }

    setIsSubmitting(true);
    clearError();
    try {
      const session = (await apiClient.verifyOtp(challenge?.challengeId ?? '', otp)).data;
      saveSession(session);
      setAuthSession(session);
      setAccessToken(session.accessToken);
      setCurrentQuestionIndex(0);
      setView('quiz');
    } catch (error) {
      setErrorContext('otp');
      setErrorKind(isInvalidOtpError(error) ? 'invalid' : 'network');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAnswer = (value: string) => {
    if (!currentQuestion) return;
    setAnswers((previous) => ({ ...previous, [currentQuestion.id]: value }));
    setSavedProfile(null);
    clearError();
  };

  const handleNextQuestion = () => {
    if (!selectedAnswer) {
      setErrorContext('quiz');
      setErrorKind('empty');
      return;
    }

    if (currentQuestionIndex === questions.length - 1) {
      setDeclaredProfile(selectedAnswer as ProfileLevel);
      setView('result');
      return;
    }

    setCurrentQuestionIndex((index) => index + 1);
    clearError();
  };

  const handlePreviousQuestion = () => {
    if (currentQuestionIndex === 0) {
      setView('otp');
      return;
    }
    setCurrentQuestionIndex((index) => index - 1);
    clearError();
  };

  const handleSaveProfile = async () => {
    if (!declaredProfile) {
      setErrorContext('profile');
      setErrorKind('empty');
      return;
    }
    setIsSubmitting(true);
    clearError();
    try {
      const profileResponse = await apiClient.setProfile({ declaredProfile, answers });
      setSavedProfile({
        declaredProfile,
        answers,
        declaredAt: profileResponse.data.riskProfile?.declaredAt ?? new Date().toISOString(),
      });
    } catch {
      setErrorContext('profile');
      setErrorKind('network');
    } finally {
      setIsSubmitting(false);
    }
  };

  const restart = () => {
    clearAuthenticatedState();
    setView('welcome');
    setEmail('');
    setChallenge(null);
    setOtp('');
    setCurrentQuestionIndex(0);
    setAnswers({});
    setDeclaredProfile(null);
    setSavedProfile(null);
    setFavoriteOpportunityIds([]);
    setSelectedOpportunityId(null);
    setSimulationOpportunityId(null);
    setSimulationAmount('');
    setSimulationHorizons([30, 180, 365]);
    setSimulationState('idle');
    setSimulationResult(null);
    setSimulationError(null);
    setSimulationErrorField(null);
    setSavedPlanId(null);
    setDecisionDraftStatus(null);
    setDecisionReason('');
    setDecisionError(null);
    setDecisionMessage(null);
    setIsEducationOpen(false);
    clearError();
  };

  const handleLogout = async () => {
    setIsSubmitting(true);
    try {
      if (accessToken) await apiClient.logout({ requestId: `widget_logout_${Date.now()}` });
    } catch {
    } finally {
      restart();
      setIsSubmitting(false);
    }
  };

  const openHub = async () => {
    setView('hub');
    setConversationError(null);
    if (conversation) return;
    setConversationState('loading');
    try {
      const result = await apiClient.createConversation({
        consent: {
          purpose: 'conversation',
          status: 'granted',
          policyVersion: 'aurafi-privacy-2026-08',
          memory: true,
          analytics: false,
        },
      });
      setConversation(result.data);
      window.sessionStorage.setItem(CONVERSATION_KEY, result.data.conversationId);
      setConversationState('ready');
    } catch {
      setConversationState('error');
      setConversationError('A Aura está em manutenção rápida. O catálogo continua disponível e você pode tentar novamente.');
    }
  };

  const sendHubMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = conversationDraft.trim();
    if (!text || !conversation) return;
    // Show the message straight away and clear the box. The model round trip
    // runs about ten seconds; without this the composer just sat there full
    // and the sent message was invisible until the reply landed.
    const pendingId = `pending_${crypto.randomUUID()}`;
    const pending: MessageEnvelope = {
      envelopeVersion: '1.0',
      messageId: pendingId,
      messageType: 'user_message',
      occurredAt: new Date().toISOString(),
      requestId: pendingId,
      correlationId: conversation.messages.at(-1)?.correlationId ?? pendingId,
      payload: { text },
      disclaimer: '',
    };
    setConversation((current) => (current ? { ...current, messages: [...current.messages, pending] } : current));
    setConversationDraft('');
    setConversationState('loading');
    setConversationError(null);
    try {
      const result = await apiClient.sendConversationMessage(conversation.conversationId, {
        text,
        consent: {
          purpose: 'conversation',
          status: 'granted',
          policyVersion: 'aurafi-privacy-2026-08',
          memory: true,
          analytics: false,
        },
      }, conversation.messages.at(-1)?.correlationId
        ? { correlationId: conversation.messages.at(-1)!.correlationId }
        : {});
      // The server echoes the user message back, so drop the placeholder
      // rather than showing the question twice.
      setConversation((current) => current ? {
        ...current,
        status: result.data.status,
        messages: [...current.messages.filter((m) => m.messageId !== pendingId), ...result.data.messages],
      } : result.data);
      setConversationState('ready');
    } catch {
      setConversation((current) => (current
        ? { ...current, messages: current.messages.filter((m) => m.messageId !== pendingId) }
        : current));
      setConversationDraft(text);
      setConversationState('error');
      setConversationError('Não consegui responder agora. Sua mensagem voltou para a caixa de texto; tente enviar novamente.');
    }
  };

  const renderWelcome = () => (
    <section className="welcome-grid" aria-labelledby="welcome-title">
      <div className="welcome-copy">
        <p className="eyebrow">AuraFi · Clareza para investir</p>
        <h1 id="welcome-title" ref={headingRef} tabIndex={-1}>Onde colocar suas stablecoins em 2026.</h1>
        <p className="lead">Uma conversa clara para estudar oportunidades DeFi, declarar seu perfil e entender os próximos passos antes de decidir.</p>
        <button className="primary-button" type="button" onClick={startOnboarding}>
          Começar meu perfil <span aria-hidden="true">→</span>
        </button>
        <p className="quiet-note"><span className="quiet-dot" aria-hidden="true" /> Leva cerca de 3 minutos · você pode revisar tudo</p>
      </div>
      <aside className="welcome-card" aria-label="Como funciona o onboarding">
        <div className="card-orbit" aria-hidden="true"><span /><span /><span /></div>
        <p className="card-kicker">Hub conversacional · Web Widget</p>
        <h2>Clareza para decidir melhor.</h2>
        <ol className="journey-list">
          <li><span>01</span><div><strong>Entrar com e-mail</strong><small>Uma conta interna simples e segura.</small></div></li>
          <li><span>02</span><div><strong>Responder cinco perguntas</strong><small>Sem certo ou errado, no seu ritmo.</small></div></li>
          <li><span>03</span><div><strong>Receber seu resultado</strong><small>Com contexto para a próxima conversa.</small></div></li>
        </ol>
      </aside>
    </section>
  );

  const renderEmail = () => (
    <section className="narrow-panel" aria-labelledby="email-title">
      <p className="eyebrow">Etapa 1 · Acesso</p>
      <h1 id="email-title" ref={headingRef} tabIndex={-1}>Vamos começar pelo seu e-mail.</h1>
      <p className="lead compact">Enviaremos um código de uso único para confirmar sua conta interna.</p>
      <form className="form-stack" onSubmit={handleRequestOtp} noValidate>
        <div className="field-group">
          <label htmlFor="email">Seu e-mail</label>
          <input id="email" name="email" type="email" autoComplete="email" placeholder="voce@exemplo.com" value={email} onChange={(event) => { setEmail(event.target.value); clearError(); }} aria-invalid={errorContext === 'email' && Boolean(errorKind)} aria-describedby={errorContext === 'email' && errorKind ? 'email-hint email-error' : 'email-hint'} required />
          <span id="email-hint" className="field-hint">Usaremos este endereço somente para sua entrada.</span>
        </div>
        {errorContext === 'email' && errorKind ? <InlineAlert id="email-error" message={getErrorMessage(errorKind, 'email')} {...(errorKind === 'network' ? { onRetry: () => { void handleRequestOtp({ preventDefault: () => {} } as FormEvent<HTMLFormElement>); } } : {})} /> : null}
        <button className="primary-button full-width" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Enviando código…' : 'Enviar código'} <span aria-hidden="true">→</span>
        </button>
      </form>
      <button className="back-button" type="button" onClick={() => setView('welcome')}>← Voltar</button>
    </section>
  );

  const renderOtp = () => (
    <section className="narrow-panel" aria-labelledby="otp-title">
      <p className="eyebrow">Etapa 1 · Confirmação</p>
      <h1 id="otp-title" ref={headingRef} tabIndex={-1}>Confira sua caixa de entrada.</h1>
      <p className="lead compact">Enviamos um código de seis números para <strong>{maskEmail(email)}</strong>.</p>
      <form className="form-stack" onSubmit={handleVerifyOtp} noValidate>
        <div className="field-group">
          <label htmlFor="otp">Código de acesso</label>
          <input id="otp" name="otp" className="otp-input" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} placeholder="000000" value={otp} onChange={(event) => { setOtp(event.target.value.replace(/\D/g, '').slice(0, 6)); clearError(); }} aria-invalid={errorContext === 'otp' && Boolean(errorKind)} aria-describedby={errorContext === 'otp' && errorKind ? 'otp-hint otp-error' : 'otp-hint'} required />
          <span id="otp-hint" className="field-hint">O código expira em 5 minutos.{IS_FIXTURE_MODE ? ' Para a demonstração, use 123456.' : ''}</span>
        </div>
        {errorContext === 'otp' && errorKind ? <InlineAlert id="otp-error" message={getErrorMessage(errorKind, 'otp')} {...(errorKind === 'network' ? { onRetry: handleResendOtp } : {})} /> : null}
        <button className="primary-button full-width" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Conferindo…' : 'Confirmar e continuar'} <span aria-hidden="true">→</span>
        </button>
      </form>
      <div className="secondary-actions">
        <button className="text-button" type="button" onClick={handleResendOtp} disabled={isSubmitting}>Reenviar código</button>
        <button className="back-button" type="button" onClick={() => setView('email')}>← Trocar e-mail</button>
      </div>
    </section>
  );

  const renderQuiz = () => {
    if (!currentQuestion) return null;
    return (
      <section className="quiz-panel" aria-labelledby="quiz-title">
        <ProgressBar current={currentQuestionIndex + 1} />
        <div className="quiz-heading">
          <p className="eyebrow">Pergunta {currentQuestionIndex + 1}</p>
          <h1 id="quiz-title" ref={headingRef} tabIndex={-1}>{currentQuestion.prompt}</h1>
          <p className="helper-copy">{currentQuestion.helper}</p>
        </div>
        <div className="option-list" role="group" aria-labelledby="quiz-title" aria-describedby={errorKind && errorContext === 'quiz' ? 'quiz-error' : undefined}>
          {currentQuestion.options.map((option) => (
            <button key={option.value} className={`option-button${selectedAnswer === option.value ? ' selected' : ''}`} type="button" aria-pressed={selectedAnswer === option.value} onClick={() => handleAnswer(option.value)}>
              <span className="option-radio" aria-hidden="true">{selectedAnswer === option.value ? '✓' : ''}</span>
              <span>{option.label}</span>
            </button>
          ))}
        </div>
        {errorKind && errorContext === 'quiz' ? <InlineAlert id="quiz-error" message={getErrorMessage(errorKind, 'quiz')} /> : null}
        <div className="quiz-footer">
          <button className="back-button" type="button" onClick={handlePreviousQuestion}>← Voltar</button>
          <span className="answered-count" aria-live="polite">{answeredCount} de {questions.length} respondidas</span>
          <button className="primary-button" type="button" onClick={handleNextQuestion}>{currentQuestionIndex === questions.length - 1 ? 'Ver meu resultado' : 'Próxima pergunta'} <span aria-hidden="true">→</span></button>
        </div>
      </section>
    );
  };

  const renderAlerts = () => (
    <section className="history-section" aria-labelledby="alerts-title">
      <div className="section-heading-row">
        <div><p className="eyebrow">Avisos de mercado</p><h1 id="alerts-title" tabIndex={-1}>Alertas</h1></div>
        <span className="list-count">{unreadAlertCount} não lidos</span>
      </div>
      <p className="section-intro">Avisos gerados quando o mercado observado muda de forma relevante. São informativos e não executam nenhuma ação financeira.</p>
      <button className="back-button" type="button" onClick={() => setView('dashboard')}>← Voltar ao painel</button>

      {alertsState === 'error' ? (
        <InlineAlert message={alertsError ?? 'Não foi possível carregar os alertas agora.'} onRetry={() => setAlertsRefreshKey((key) => key + 1)} id="alerts-error" />
      ) : alertsState === 'loading' && alertItems.length === 0 ? (
        <div className="history-empty" role="status"><strong>Carregando alertas…</strong></div>
      ) : alertItems.length === 0 ? (
        <div className="history-empty" role="status">
          <strong>Nenhum alerta por aqui.</strong>
          <span>Quando o mercado observado mudar de forma relevante, os alertas aparecem aqui.</span>
        </div>
      ) : (
        <div className="history-list">
          {alertItems.map((alert) => (
            <article className="history-card" key={alert.alertId}>
              <div className="history-card-top">
                <div><span className="opportunity-category">{alertTypeLabel(alert.type)}</span><h3>{alert.title}</h3></div>
                <time dateTime={alert.createdAt}>{formatDateTime(alert.createdAt)}</time>
              </div>
              <p>{alert.message}</p>
              <p className="disclaimer">{alert.disclaimer}</p>
              <div className="history-card-top">
                <span className={`alert-badge ${alert.status}`}>{alert.status === 'unread' ? 'Não lido' : 'Lido'}</span>
                {alert.status === 'unread' ? (
                  <button className="text-button" type="button" onClick={() => handleMarkAlertRead(alert.alertId)}>Marcar como lido</button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );

  const renderDecisionHistory = () => (
    <section className="history-section" aria-labelledby="history-title">
      <div className="section-heading-row">
        <div><p className="eyebrow">Histórico pessoal</p><h2 id="history-title">Histórico de decisões</h2></div>
        <span className="list-count">{decisionHistory.length} registros</span>
      </div>
      <p className="section-intro">Registros guardados somente neste navegador para você revisar o caminho. Eles não são ordens, posições ou transações.</p>
      <div className="history-filters" role="group" aria-label="Filtrar histórico de decisões">
        {(['all', 'accepted', 'refused'] as const).map((filter) => (
          <button key={filter} className={`filter-button${decisionFilter === filter ? ' selected' : ''}`} type="button" aria-pressed={decisionFilter === filter} onClick={() => setDecisionFilter(filter)}>
            {filter === 'all' ? 'Tudo' : filter === 'accepted' ? 'Aceitas' : 'Recusadas'}
          </button>
        ))}
      </div>
      {filteredDecisionHistory.length === 0 ? (
        <div className="history-empty" role="status">
          <strong>{decisionHistory.length === 0 ? 'Ainda não há decisões salvas.' : 'Nenhum registro neste filtro.'}</strong>
          <span>{decisionHistory.length === 0 ? 'Abra um detalhe, gere uma simulação e aceite ou recuse com um motivo.' : 'Escolha outro filtro para revisar as decisões locais.'}</span>
        </div>
      ) : (
        <div className="history-list">
          {filteredDecisionHistory.map((decision) => (
            <article className="history-card" key={decision.decisionId}>
              <div className="history-card-top">
                <div><span className="opportunity-category">{decisionStatusLabel(decision.status)} · modelo educativo</span><h3>{decision.protocol} <span aria-hidden="true">·</span> {decision.pool}</h3></div>
                <time dateTime={decision.decidedAt}>{formatDateTime(decision.decidedAt)}</time>
              </div>
              <div className="history-meta"><span>Valor: {formatAssetAmount(decision.amount)} {decision.asset}</span><span>Cenários: {decision.horizons.map((horizon) => `${horizon}d`).join(' · ')}</span></div>
              <p><strong>Motivo:</strong> {decision.reason}</p>
              <span className={`decision-badge ${decision.status}`}>{decision.status === 'accepted' ? 'Aceita para estudo' : 'Recusada para estudo'}</span>
            </article>
          ))}
        </div>
      )}
      <p className="disclaimer"><strong>Estado:</strong> histórico deste dispositivo e educativo. Não há wallet, Open Finance, ordem, execução ou transação associada a estes registros.</p>
    </section>
  );

  const renderDashboard = () => {
    const profile = declaredProfile ? profileCopy[declaredProfile] : null;
    const currentMode = dashboardOpportunities[0]?.dataSource.mode ?? (opportunityMeta?.source === 'api' ? 'live' : 'cache');
    const isSyntheticSource = currentMode === 'test' || currentMode === 'fallback';
    return (
      <section className="dashboard-panel" aria-labelledby="dashboard-title">
        <div className="dashboard-heading">
          <div>
            <p className="eyebrow">Painel de estudo</p>
            <h1 id="dashboard-title" ref={headingRef} tabIndex={-1}>Explore com mais contexto.</h1>
            <p className="lead compact">Oportunidades de mercado para comparar dados, riscos e explicações antes de qualquer próxima etapa.</p>
          </div>
          <div className="dashboard-actions">
            <button className="primary-button" type="button" onClick={() => { void openHub(); }}>Conversar com a Aura <span aria-hidden="true">→</span></button>
            <button className="secondary-button" type="button" onClick={() => setIsEducationOpen(true)}>Como ler este painel</button>
            <button className="back-button" type="button" onClick={() => setView('result')}>← Ver meu resultado</button>
          </div>
        </div>

        {(() => {
          const sourceLabel = opportunityMeta?.source === 'api' ? 'DeFiLlama · fonte de mercado' : 'AuraFi · dados disponíveis';
          return (
            <div className="dashboard-livebar" role="status" aria-live="polite">
              <div className="livebar-main">
                <span className={`source-indicator source-${currentMode}`} aria-hidden="true" />
                <div><strong>{sourceLabel}</strong><span>{dataModeDescription(currentMode)}</span></div>
              </div>
              <div className="source-legend" aria-label={`Estado da fonte: ${dataModeLabel(currentMode)}`}>
                <span className={`source-pill ${currentMode}`}><span aria-hidden="true">●</span> {dataModeLabel(currentMode)}</span>
                <span className="read-only-pill">Informativo</span>
              </div>
            </div>
          );
        })()}

        <div className="dashboard-overview" aria-label="Resumo do painel">
          <article className="overview-card overview-market-card">
            <div className="overview-card-head"><span className="card-kicker">Mercado observado</span><span className="overview-icon" aria-hidden="true">↗</span></div>
            <strong>{dashboardOpportunities.length} <small>oportunidades</small></strong>
            <p>Dados comparáveis por APY, TVL, liquidez e risco informado.</p>
            <div className="overview-foot"><span>Última leitura</span><strong>{opportunityMeta ? formatDateTime(opportunityMeta.generatedAt) : 'aguardando leitura'}</strong></div>
          </article>
          <article className="overview-card overview-profile-card">
            <div className="overview-card-head"><span className="card-kicker">Seu contexto</span><span className="profile-initial" aria-hidden="true">{profile?.label?.slice(0, 1) ?? 'A'}</span></div>
            <strong>{profile?.label ?? 'Ainda não declarado'}</strong>
            <p>{profile?.description ?? 'Declare um perfil para organizar as explicações, sem score automático.'}</p>
            <div className="overview-foot"><span>Decisão apoiada por contexto</span><strong>sem recomendação automática</strong></div>
          </article>
          <article className="overview-card overview-safety-card">
            <div className="overview-card-head"><span className="card-kicker">Limites do produto</span><span className="overview-icon" aria-hidden="true">✓</span></div>
            <strong>Você decide</strong>
            <p>Sem custódia, sem conexão de wallet e sem execução de ordens.</p>
            <div className="overview-foot"><span>Dados</span><strong>explicáveis e rastreáveis</strong></div>
          </article>
        </div>

        {isSyntheticSource ? (
          <div className="synthetic-banner" role="status">
            <span className="status-dot" aria-hidden="true" />
            <div><strong>{currentMode === 'fallback' ? 'Atualização da fonte pendente' : 'Ambiente de demonstração'}</strong><span>{currentMode === 'fallback' ? 'A fonte está indisponível. Os dados exibidos precisam ser revisados antes de qualquer decisão.' : 'Dados de demonstração estão habilitados nesta instalação. Eles não representam saldo, posição ou recomendação.'}</span></div>
          </div>
        ) : null}

        <div className="dashboard-summary">
          <article className="summary-card synthetic-wealth-card">
            <div className="summary-card-top"><span className="card-kicker">Escopo da análise</span><span className="fixture-tag">Informativo</span></div>
            <strong className="summary-value">Sem custódia</strong>
            <p>A AuraFi organiza dados de mercado e explicações. Não acessa saldo, carteira ou alocação da sua conta.</p>
            <div className="synthetic-bar" aria-hidden="true"><span /></div>
          </article>
          <article className="summary-card profile-summary-card">
            <span className="card-kicker">Seu contexto declarado</span>
            <strong className="summary-value">{profile?.label ?? 'Ainda não declarado'}</strong>
            <p>{profile?.description ?? 'Conclua o onboarding para organizar as explicações por um perfil que você declarou.'}</p>
            <span className="summary-footnote">Perfil declarado · sem score automático</span>
          </article>
        </div>

        <section className="opportunities-section" aria-labelledby="opportunities-title" data-opportunity-state={opportunityState}>
          <div className="section-heading-row">
            <div><p className="eyebrow">Catálogo de mercado</p><h2 id="opportunities-title">Oportunidades para estudar</h2></div>
            <span className="list-count">{dashboardOpportunities.length} resultados</span>
          </div>
          {opportunityState === 'loading' ? (
            <div className="opportunity-loading" role="status" aria-live="polite">
              <span className="loading-orb" aria-hidden="true" />
              <div><strong>Atualizando o catálogo</strong><span>Consultando a fonte de mercado e organizando os dados para comparação.</span></div>
            </div>
          ) : null}
          {opportunityState === 'error' ? (
            <InlineAlert message={opportunityError ?? 'Não foi possível carregar as oportunidades agora.'} onRetry={() => setOpportunityRefreshKey((value) => value + 1)} />
          ) : null}
          <div className="opportunity-toolbar" aria-label="Filtros do catálogo">
            <div className="filter-group" role="group" aria-label="Filtrar por risco">
              {(['all', 'low', 'medium', 'high', 'unknown'] as const).map((filter) => (
                <button key={filter} className={`filter-button${opportunityFilter === filter ? ' selected' : ''}`} type="button" aria-pressed={opportunityFilter === filter} onClick={() => setOpportunityFilter(filter)}>
                  {filter === 'all' ? 'Todos' : filter === 'low' ? 'Baixo' : filter === 'medium' ? 'Médio' : filter === 'high' ? 'Alto' : 'Sem dado'}
                </button>
              ))}
            </div>
            <button className="refresh-button" type="button" onClick={() => setOpportunityRefreshKey((value) => value + 1)} disabled={opportunityState === 'loading'}>
              <span aria-hidden="true">↻</span> Atualizar leitura
            </button>
          </div>
          <div className="opportunity-list">
            {filteredOpportunities.map((opportunity) => {
              const isFavorite = favoriteOpportunityIds.includes(opportunity.opportunityId);
              return (
                <article className="opportunity-card" key={opportunity.opportunityId}>
                  <div className="opportunity-card-head">
                    <div><span className="opportunity-category">{opportunity.category} · {opportunity.blockchain}</span><h3>{opportunity.protocol} <span aria-hidden="true">·</span> {opportunity.pool}</h3><p>{opportunity.asset}</p></div>
                    <button className={`favorite-button${isFavorite ? ' is-favorite' : ''}`} type="button" aria-label={isFavorite ? `Remover ${opportunity.protocol} dos favoritos` : `Favoritar ${opportunity.protocol}`} aria-pressed={isFavorite} onClick={() => toggleFavorite(opportunity.opportunityId)}>{isFavorite ? '★' : '☆'}</button>
                  </div>
                  <div className="opportunity-metrics">
                    <div><span>APY observado</span><strong>{opportunity.apy.display ?? formatPercent(opportunity.apy.value)}</strong></div>
                    <div><span>TVL observado</span><strong>{opportunity.tvl.displayCompact ?? `${opportunity.tvl.currency} ${opportunity.tvl.value.toLocaleString('pt-BR')}`}</strong></div>
                    <div><span>Risco informado</span><strong>{riskLabel(opportunity.risk.level)}</strong></div>
                  </div>
                  {/* Source and freshness stated once each: this row used to
                      repeat "dados atualizados"/"atualizado nesta leitura" and
                      then restate the source again on the row below. */}
                  {/* Source and freshness only; the non-custody note lives in
                      the page footer rather than repeating on all 12 cards. */}
                  <div className={`card-source-row source-${opportunity.dataSource.mode}`}>
                    <span><i aria-hidden="true" /> {opportunity.dataSource.sourceLabel ?? 'DeFiLlama'} · {opportunity.dataSource.isStale ? 'pode estar desatualizado' : 'atualizado nesta leitura'}</span>
                  </div>
                  <div className="opportunity-card-footer"><button className="text-button" type="button" onClick={() => openOpportunity(opportunity.opportunityId)}>Abrir detalhe <span aria-hidden="true">→</span></button></div>
                </article>
              );
            })}
          </div>
        </section>

        {renderDecisionHistory()}

        <p className="disclaimer"><strong>Importante:</strong> APY, TVL, risco, auditoria e gas são campos observados ou ilustrativos, não garantias de retorno. Este painel não acessa wallet, não executa transações e não constitui recomendação personalizada.</p>
      </section>
    );
  };

  const renderSimulation = () => {
    const opportunity = dashboardOpportunities.find((item) => item.opportunityId === simulationOpportunityId);
    if (!opportunity) {
      return (
        <section className="empty-state" aria-labelledby="simulation-empty-title">
          <div className="empty-icon" aria-hidden="true">○</div>
          <p className="eyebrow">Simulação indisponível</p>
          <h1 id="simulation-empty-title" ref={headingRef} tabIndex={-1}>Não encontramos os dados desta oportunidade.</h1>
          <p className="lead compact">Volte ao dashboard para escolher uma oportunidade disponível. Nenhuma ação foi executada.</p>
          <button className="primary-button" type="button" onClick={openDashboard}>Voltar ao dashboard</button>
        </section>
      );
    }

    const savedPlan = savedPlanId ? savedPlans.find((plan) => plan.planId === savedPlanId) : undefined;
    return (
      <section className="simulation-panel" aria-labelledby="simulation-title">
        <button className="back-button" type="button" onClick={() => setView('opportunity')}>← Voltar ao detalhe</button>
        <div className="simulation-heading">
          <div><p className="eyebrow">Simulação educativa</p><h1 id="simulation-title" ref={headingRef} tabIndex={-1}>{opportunity.protocol} <span aria-hidden="true">·</span> {opportunity.pool}</h1><p className="lead compact">Estude um valor hipotético em {opportunity.asset}, usando os dados observados e o perfil {declaredProfile ? profileCopy[declaredProfile].label : 'declarado'}.</p></div>
          <span className="fixture-tag simulation-status-tag">Informativo</span>
        </div>

        <div className="stale-banner" role="status"><strong>Atualização da fonte</strong><span>DeFiLlama · {dataModeDescription(opportunity.dataSource.mode)}. {opportunity.dataSource.freshnessNote ?? 'Revise a data da leitura antes de decidir.'}</span></div>

        <form className="simulation-form" onSubmit={handleSimulationSubmit} noValidate>
          <div className="simulation-input-grid">
            <div className="field-group">
              <label htmlFor="simulation-amount">Valor hipotético ({opportunity.asset})</label>
              <input id="simulation-amount" name="simulation-amount" type="text" inputMode="decimal" placeholder="Ex.: 1.000,00" value={simulationAmount} onChange={(event) => { setSimulationAmount(event.target.value); setSimulationState('idle'); setSimulationResult(null); setSimulationError(null); setSimulationErrorField(null); setSavedPlanId(null); setDecisionDraftStatus(null); setDecisionReason(''); setDecisionError(null); }} aria-invalid={simulationErrorField === 'amount'} aria-describedby={simulationErrorField === 'amount' ? 'simulation-amount-hint simulation-error' : 'simulation-amount-hint'} required />
              <span id="simulation-amount-hint" className="field-hint">Use um valor de estudo; não é saldo, patrimônio ou aporte real.</span>
            </div>
            <fieldset className="horizon-fieldset" aria-invalid={simulationErrorField === 'horizons'} aria-describedby={simulationErrorField === 'horizons' ? 'horizon-hint simulation-error' : 'horizon-hint'}>
              <legend>Cenários para comparar</legend>
              <span id="horizon-hint" className="field-hint">Selecione um ou mais horizontes aprovados no contrato.</span>
              <div className="horizon-options">
                {SIMULATION_HORIZONS.map((horizon) => (
                  <label className={`horizon-option${simulationHorizons.includes(horizon) ? ' selected' : ''}`} key={horizon}>
                    <input type="checkbox" checked={simulationHorizons.includes(horizon)} onChange={() => toggleSimulationHorizon(horizon)} />
                    <span>{horizon} dias</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          {simulationError ? <InlineAlert id="simulation-error" message={simulationError} {...(simulationAmount && simulationHorizons.length > 0 ? { onRetry: () => { void handleSimulationSubmit({ preventDefault: () => {} } as FormEvent<HTMLFormElement>); } } : {})} /> : null}
          <button className="primary-button" type="submit" disabled={simulationState === 'loading'}>{simulationState === 'loading' ? 'Gerando cenários…' : 'Gerar simulação educativa'} <span aria-hidden="true">→</span></button>
        </form>

        <section className="assumptions-card" aria-labelledby="assumptions-title">
          <div><p className="eyebrow">Premissas explícitas</p><h2 id="assumptions-title">Como a projeção é calculada</h2></div>
          <p>A simulação usa uma fórmula educativa linear para tornar os cenários comparáveis. Ela não é uma previsão, cotação ou promessa de resultado.</p>
          <ul>{SIMULATION_ASSUMPTIONS.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
          <span className="formula-version">Modelo de cálculo: {SIMULATION_FORMULA_VERSION}</span>
        </section>
        <p className="disclaimer"><strong>Limite:</strong> esta é uma simulação educativa. Não usa patrimônio real, não recomenda uma ação, não conecta wallet e não executa transação.</p>

        {simulationState === 'ready' && simulationResult ? (
          <section className="simulation-results" aria-labelledby="simulation-results-title">
            <div className="section-heading-row"><div><p className="eyebrow">Comparação educativa</p><h2 id="simulation-results-title">Cenários para {simulationResult.amountDisplay ?? `${formatAssetAmount(simulationResult.amount)} ${simulationResult.asset}`}</h2></div><span className="list-count">{simulationResult.scenarios.length} cenários</span></div>
            <div className="scenario-grid">
              {simulationResult.scenarios.map((scenario) => {
                const comparison = scenario.projectedValue - scenario.idleStablecoinValue;
                return (
                  <article className="scenario-card" key={scenario.horizonDays}>
                    <span className="scenario-horizon">{scenario.horizonDays} dias</span>
                    <strong>{scenario.projectedValueDisplay ?? `${formatAssetAmount(scenario.projectedValue)} ${scenario.currency}`}</strong>
                    <dl><div><dt>Projeção do cenário</dt><dd>{scenario.projectedYieldDisplay ?? formatPercent(scenario.projectedYield)}</dd></div><div><dt>Stablecoin parada</dt><dd>{scenario.idleStablecoinValueDisplay ?? `${formatAssetAmount(scenario.idleStablecoinValue)} ${scenario.currency}`}</dd></div><div><dt>Diferença educativa</dt><dd>{scenario.projectedGainDisplay ? `${comparison >= 0 ? '+' : ''}${scenario.projectedGainDisplay}` : `${comparison >= 0 ? '+' : ''}${formatAssetAmount(comparison)} ${scenario.currency}`}</dd></div></dl>
                  </article>
                );
              })}
            </div>
            <div className="simulation-source"><strong>Origem e atualização:</strong> {simulationResult.dataSource.source} · {dataModeLabel(simulationResult.dataSource.mode)} · {simulationResult.dataSource.isStale ? 'atualização pendente' : 'leitura atual'} · gerado em {formatDateTime(simulationResult.generatedAt)}.<br /><strong>Limite:</strong> salvar, aceitar ou recusar registra apenas sua intenção de estudo; nenhuma operação financeira é criada.</div>
            <p className="disclaimer"><strong>Disclaimer:</strong> {publicAssumption(simulationResult.disclaimer)}</p>

            <div className="simulation-actions">
              <button className="secondary-button" type="button" onClick={handleSaveSimulationPlan} disabled={Boolean(savedPlan)}>{savedPlan ? 'Plano salvo neste dispositivo' : 'Salvar plano neste dispositivo'}</button>
              <button className="primary-button" type="button" onClick={() => { setDecisionDraftStatus('accepted'); setDecisionError(null); setDecisionMessage(null); }}>Aceitar para estudo</button>
              <button className="text-button" type="button" onClick={() => { setDecisionDraftStatus('refused'); setDecisionError(null); setDecisionMessage(null); }}>Recusar para estudo</button>
            </div>
            {savedPlan ? <p className="saved-message" role="status">Plano {savedPlan.planId} salvo neste dispositivo em {formatDateTime(savedPlan.savedAt)}.</p> : null}
            {decisionMessage ? <div className="simulation-notice" role="status"><strong>Histórico atualizado</strong><span>{decisionMessage}</span></div> : null}

            {decisionDraftStatus ? (
              <form className="decision-form" onSubmit={handleDecisionSubmit}>
                <p className="eyebrow">Registrar decisão</p>
                <h3>{decisionDraftStatus === 'accepted' ? 'Por que você aceita estudar este plano?' : 'Por que você recusa estudar este plano?'}</h3>
                <label htmlFor="decision-reason">Motivo</label>
                <textarea id="decision-reason" value={decisionReason} onChange={(event) => { setDecisionReason(event.target.value); setDecisionError(null); }} placeholder="Ex.: quero revisar os riscos antes de avançar." rows={3} aria-invalid={Boolean(decisionError)} aria-describedby={decisionError ? 'decision-reason-error' : undefined} required />
                {decisionError ? <InlineAlert id="decision-reason-error" message={decisionError} /> : null}
                <div className="decision-form-actions"><button className="back-button" type="button" onClick={() => { setDecisionDraftStatus(null); setDecisionReason(''); setDecisionError(null); }}>Cancelar</button><button className="primary-button" type="submit">Salvar no histórico</button></div>
              </form>
            ) : null}
          </section>
        ) : (
          <div className="simulation-empty" role="status"><strong>{simulationState === 'error' ? 'Os cenários não estão disponíveis agora.' : 'Preencha o valor e escolha os horizontes.'}</strong><span>{simulationState === 'error' ? 'Tente novamente ou retorne ao detalhe para revisar os dados.' : 'A simulação só será gerada depois da sua confirmação; nada é conectado ou executado.'}</span></div>
        )}
      </section>
    );
  };

  const renderHub = () => (
    <section className="hub-panel" aria-labelledby="hub-title">
      <div className="hub-heading">
        <div>
          <p className="eyebrow">Aura · Hub conversacional</p>
          <h1 id="hub-title" ref={headingRef} tabIndex={-1}>Converse com a mesma Aura, em qualquer canal.</h1>
          <p className="lead compact">Seu contexto fica associado à sua conta. Aqui você pode pedir explicações, comparar riscos e retomar esta conversa durante a sessão.</p>
        </div>
        <button className="back-button" type="button" onClick={openDashboard}>← Voltar ao painel</button>
      </div>

      <div className="hub-status" role="status">
        <span className={`source-indicator ${conversationState === 'error' ? 'source-fallback' : 'source-live'}`} aria-hidden="true" />
        <div><strong>{conversationState === 'error' ? 'Fallback disponível' : 'Contexto conectado'}</strong><span>Conta autenticada · memória desta conversa ativa · analytics desativado</span></div>
      </div>

      {conversationError ? <InlineAlert message={conversationError} onRetry={() => { setConversation(null); void openHub(); }} /> : null}

      <div className="conversation-log" ref={conversationLogRef} role="log" aria-live="polite" aria-relevant="additions text">
        {!conversation || conversation.messages.length === 0 ? (
          <div className="hub-empty">
            <span className="aura-avatar" aria-hidden="true">A</span>
            <div><strong>Olá, sou a Aura.</strong><p>Posso explicar os dados do painel, os riscos informados e as premissas das simulações. Não executo operações e não prometo retorno.</p></div>
          </div>
        ) : conversation.messages.map((message) => (
          <article className={`chat-message ${message.messageType === 'user_message' ? 'from-user' : 'from-aura'}${message.messageId.startsWith('pending_') ? ' is-pending' : ''}`} key={message.messageId}>
            <span className="message-author">{message.messageType === 'user_message' ? 'Você' : 'Aura'}</span>
            <p>{renderMessageText(messageText(message))}</p>
            <time dateTime={message.occurredAt}>{message.messageId.startsWith('pending_') ? 'enviando…' : formatDateTime(message.occurredAt)}</time>
          </article>
        ))}
        {conversationState === 'loading' ? <div className="chat-thinking" role="status"><span aria-hidden="true" /><span aria-hidden="true" /><span aria-hidden="true" /> <em>Aura está organizando a resposta…</em></div> : null}
      </div>

      {conversation ? (
        <form className="hub-composer" onSubmit={sendHubMessage}>
          <label className="sr-only" htmlFor="hub-message">Mensagem para a Aura</label>
          <textarea
            id="hub-message"
            rows={2}
            maxLength={2000}
            value={conversationDraft}
            onChange={(event) => setConversationDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter breaks the line, as in any chat.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Pergunte sobre APY, risco ou uma oportunidade…"
            disabled={conversationState === 'loading'}
          />
          <button className="primary-button" type="submit" disabled={conversationState === 'loading' || !conversationDraft.trim()}>Enviar <span aria-hidden="true">→</span></button>
        </form>
      ) : conversationState !== 'loading' ? <button className="primary-button" type="button" onClick={() => { void openHub(); }}>Iniciar nova conversa</button> : null}
      <p className="disclaimer"><strong>Privacidade e limites:</strong> a conversa usa consentimento explícito, não habilita analytics e não acessa wallet, saldo ou conta bancária. Não compartilhe senhas, OTP ou chaves.</p>
    </section>
  );

  const renderOpportunity = () => {
    const opportunity = dashboardOpportunities.find((item) => item.opportunityId === selectedOpportunityId);
    if (!opportunity) {
      return (
        <section className="empty-state" aria-labelledby="opportunity-empty-title">
          <div className="empty-icon" aria-hidden="true">○</div>
          <p className="eyebrow">Detalhe indisponível</p>
          <h1 id="opportunity-empty-title" ref={headingRef} tabIndex={-1}>Escolha uma oportunidade para estudar.</h1>
          <button className="primary-button" type="button" onClick={openDashboard}>Voltar ao dashboard</button>
        </section>
      );
    }

    const isFavorite = favoriteOpportunityIds.includes(opportunity.opportunityId);
    return (
      <section className="opportunity-detail" aria-labelledby="opportunity-title">
        <button className="back-button" type="button" onClick={openDashboard}>← Voltar às oportunidades</button>
        <div className="detail-heading">
          <div><p className="eyebrow">Detalhe da oportunidade</p><h1 id="opportunity-title" ref={headingRef} tabIndex={-1}>{opportunity.protocol} <span aria-hidden="true">·</span> {opportunity.pool}</h1><p className="lead compact">{opportunity.asset} · {opportunity.blockchain} · {opportunity.category}</p></div>
          <button className={`favorite-button large${isFavorite ? ' is-favorite' : ''}`} type="button" aria-label={isFavorite ? 'Remover oportunidade dos favoritos' : 'Favoritar oportunidade'} aria-pressed={isFavorite} onClick={() => toggleFavorite(opportunity.opportunityId)}>{isFavorite ? '★' : '☆'} <span>{isFavorite ? 'Favoritada' : 'Favoritar'}</span></button>
        </div>

        {opportunity.dataSource.isStale ? <div className="stale-banner" role="status"><strong>Atualização da fonte pendente</strong><span>{opportunity.dataSource.freshnessNote ?? 'O dado pode estar desatualizado; revise a data da leitura.'}</span></div> : null}
        <div className={`detail-source-banner source-${opportunity.dataSource.mode}`} role="status">
          <span className="source-indicator" aria-hidden="true" />
          <div><strong>{dataModeLabel(opportunity.dataSource.mode)} · DeFiLlama</strong><span>{dataModeDescription(opportunity.dataSource.mode)} · observado em {formatDateTime(opportunity.dataSource.observedAt)}.</span></div>
        </div>

        <div className="detail-metrics" aria-label="Métricas da oportunidade">
          <div><span>APY observado</span><strong>{formatPercent(opportunity.apy.value)}</strong><small>percentual anualizado</small></div>
          <div><span>TVL observado</span><strong>{opportunity.tvl.currency} {opportunity.tvl.value.toLocaleString('pt-BR')}</strong><small>no momento observado</small></div>
          <div><span>Gas estimado</span><strong>{opportunity.gasEstimate}</strong><small>estimativa da fonte quando disponível</small></div>
          <div><span>Auditoria</span><strong>{auditLabel(opportunity.auditStatus)}</strong><small>não é selo de segurança</small></div>
        </div>

        <div className="detail-columns">
          <section className="detail-card" aria-labelledby="risk-title"><p className="eyebrow">Leitura de risco</p><h2 id="risk-title">O que está informado</h2><div className="risk-callout"><span className={`risk-indicator ${opportunity.risk.level}`} aria-hidden="true" /><strong>{riskLabel(opportunity.risk.level)}</strong></div><p className="detail-note">Este nível é informado pela fonte e não representa adequação ao seu perfil. A AuraFi não calcula score, pesos ou limiar financeiro.</p><ul className="dimension-list">{opportunity.risk.dimensions.map((dimension) => <li key={dimension}>{dimension.replaceAll('_', ' ')}</li>)}</ul></section>
          <section className="detail-card" aria-labelledby="source-title"><p className="eyebrow">Origem e atualização</p><h2 id="source-title">Fonte e frescor</h2><dl className="source-list"><div><dt>Fonte</dt><dd>DeFiLlama · informativo</dd></div><div><dt>Atualização</dt><dd>{dataModeLabel(opportunity.dataSource.mode)}</dd></div><div><dt>Observado em</dt><dd>{formatDateTime(opportunity.dataSource.observedAt)}</dd></div><div><dt>Recuperado em</dt><dd>{formatDateTime(opportunity.dataSource.retrievedAt)}</dd></div><div><dt>Estado</dt><dd>{opportunity.dataSource.isStale ? 'Atualização pendente' : 'Leitura atual'}</dd></div></dl></section>
        </div>

        <div className="detail-actions"><button className="primary-button" type="button" onClick={() => handleStartSimulation(opportunity.opportunityId)}>Iniciar simulação educativa <span aria-hidden="true">→</span></button><button className="secondary-button" type="button" onClick={() => setIsEducationOpen(true)}>Entender APY, risco e gas</button></div>
        <p className="disclaimer"><strong>Importante:</strong> este detalhe é informativo e educativo. Nenhuma ação executa compra, depósito, saque, conexão de wallet ou qualquer operação financeira.</p>
      </section>
    );
  };

  const renderEducationModal = () => {
    if (!isEducationOpen) return null;
    return (
      <div className="modal-backdrop" role="presentation">
        <section ref={educationModalRef} className="education-modal" role="dialog" aria-modal="true" aria-labelledby="education-title" aria-describedby="education-description">
          <div className="modal-header"><div><p className="eyebrow">Explicação educativa</p><h2 id="education-title">Como ler uma oportunidade?</h2></div><button ref={educationCloseRef} className="modal-close" type="button" onClick={() => setIsEducationOpen(false)} aria-label="Fechar explicação">×</button></div>
          <p id="education-description" className="modal-intro">Estes campos ajudam a fazer perguntas melhores. Eles não transformam uma oportunidade em uma promessa ou recomendação.</p>
          <div className="education-grid"><article><span className="education-number">01</span><h3>APY observado</h3><p>É uma taxa anualizada informada no momento da observação. Pode variar, não é garantida e não representa o resultado da sua conta.</p></article><article><span className="education-number">02</span><h3>Risco e auditoria</h3><p>Dimensões como contrato, liquidez e volatilidade mostram o que precisa ser investigado. Auditoria não elimina risco e “não informado” continua desconhecido.</p></article><article><span className="education-number">03</span><h3>TVL e gas</h3><p>TVL descreve valor agregado observado no protocolo. Gas é uma estimativa de custo de rede. Nenhum dos dois indica adequação ao seu perfil.</p></article><article><span className="education-number">04</span><h3>Atualização e fonte</h3><p>A data de observação mostra quando o dado foi coletado. Quando houver atraso, trate a informação como contexto e revise a fonte antes de decidir.</p></article></div>
          <p className="modal-disclaimer"><strong>Limite do MVP:</strong> a AuraFi apoia estudo e comparação. Não acessa saldo, não conecta wallet, não executa transações e não garante retorno.</p>
        </section>
      </div>
    );
  };

  const renderResult = () => {
    if (!declaredProfile) {
      return (
        <section className="empty-state" aria-labelledby="empty-title">
          <div className="empty-icon" aria-hidden="true">○</div>
          <p className="eyebrow">Resultado indisponível</p>
          <h1 id="empty-title" ref={headingRef} tabIndex={-1}>Ainda não há um perfil declarado.</h1>
          <p className="lead compact">Responda às cinco perguntas para visualizar um resultado.</p>
          <button className="primary-button" type="button" onClick={() => setView('quiz')}>Voltar ao questionário</button>
        </section>
      );
    }

    const profile = profileCopy[declaredProfile];
    return (
      <section className="result-panel" aria-labelledby="result-title">
        <div className="result-intro">
          <p className="eyebrow">Seu resultado</p>
          <h1 id="result-title" ref={headingRef} tabIndex={-1}>Um perfil para orientar sua jornada.</h1>
          <p className="lead compact">Este é o perfil que você declarou a partir das suas respostas.</p>
        </div>
        <article className="profile-card">
          <div className="profile-card-top"><span className="profile-label">Perfil declarado</span><span className="profile-status">{savedProfile ? 'Salvo' : 'Para revisar'}</span></div>
          <div className="profile-name-row"><span className={`profile-symbol ${declaredProfile}`} aria-hidden="true">✦</span><h2>{profile.label}</h2></div>
          <p>{profile.description}</p>
        </article>
        <div className="result-columns">
          <section className="result-section" aria-labelledby="answers-title">
            <h2 id="answers-title">O que você respondeu</h2>
            <ul className="answer-summary">
              {questions.map((question) => {
                const answer = question.options.find((option) => option.value === answers[question.id]);
                return <li key={question.id}><span>{question.title}</span><strong>{answer?.label ?? 'Não respondida'}</strong></li>;
              })}
            </ul>
          </section>
          <aside className="safe-next-step" aria-labelledby="next-step-title">
            <span className="safe-icon" aria-hidden="true">✓</span>
            <h2 id="next-step-title">Próxima ação segura</h2>
            <p>Revise suas respostas e leia explicações gerais antes de tomar qualquer decisão.</p>
            {!savedProfile ? <button className="secondary-button" type="button" onClick={() => { void handleSaveProfile(); }} disabled={isSubmitting}>{isSubmitting ? 'Salvando…' : 'Confirmar meu perfil'}</button> : <p className="saved-message" role="status">Perfil salvo na sua conta AuraFi.</p>}
          </aside>
        </div>
        <div className="result-dashboard-cta">
          <div><strong>Pronto para estudar com contexto?</strong><span>Abra o dashboard para comparar oportunidades, critérios e origem dos dados.</span></div>
          <button className="primary-button" type="button" onClick={openDashboard}>Explorar dashboard <span aria-hidden="true">→</span></button>
        </div>
        {errorKind && errorContext === 'profile' ? <InlineAlert message={getErrorMessage(errorKind, 'profile')} {...(errorKind === 'network' ? { onRetry: () => { void handleSaveProfile(); } } : {})} /> : null}
        <p className="disclaimer"><strong>Importante:</strong> este resultado organiza apenas as respostas que você declarou. É uma referência educativa, não uma recomendação personalizada e não garante resultados.</p>
        <div className="result-actions"><button className="back-button" type="button" onClick={() => setView('quiz')}>← Revisar respostas</button><button className="text-button" type="button" onClick={() => { void handleLogout(); }}>Sair e começar novamente</button></div>
      </section>
    );
  };

  return (
    <div className="app-shell">
      <header className="site-header">
        <button className="brand-button" type="button" onClick={() => { if (accessToken) setView('dashboard'); else setView('welcome'); }} aria-label="AuraFi — voltar ao início"><AuraMark /><span>AuraFi</span></button>
        <div className="header-session">
          <span className="header-caption">Web Widget · {view === 'hub' ? 'Aura conectada' : view === 'dashboard' || view === 'opportunity' || view === 'simulation' ? 'estudo informativo' : 'onboarding'}</span>
          {accessToken ? (
            <button
              className="header-alerts-button"
              type="button"
              onClick={() => setView('alerts')}
              aria-label={unreadAlertCount > 0 ? `Alertas, ${unreadAlertCount} não lidos` : 'Alertas'}
            >
              {/* Inline SVG rather than the 🔔 emoji: colour emoji ignore `color`
                  and rendered near-black on the dark header. */}
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.7 21a2 2 0 0 1-3.4 0" />
              </svg>
              {unreadAlertCount > 0 ? <span className="alert-count-badge">{unreadAlertCount}</span> : null}
            </button>
          ) : null}
          {accessToken ? <button className="header-logout" type="button" onClick={() => { void handleLogout(); }} disabled={isSubmitting}>Sair</button> : null}
        </div>
      </header>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {isSubmitting ? (view === 'email' ? 'Enviando código.' : view === 'otp' ? 'Conferindo código.' : 'Salvando perfil.') : simulationState === 'loading' ? 'Gerando cenários educativos.' : ''}
      </div>
      <main className={`main-content view-${view}`} aria-busy={isSubmitting || simulationState === 'loading'}>
        {view === 'welcome' ? renderWelcome() : null}
        {view === 'email' ? renderEmail() : null}
        {view === 'otp' ? renderOtp() : null}
        {view === 'quiz' ? renderQuiz() : null}
        {view === 'result' ? renderResult() : null}
        {view === 'dashboard' ? renderDashboard() : null}
        {view === 'opportunity' ? renderOpportunity() : null}
        {view === 'simulation' ? renderSimulation() : null}
        {view === 'hub' ? renderHub() : null}
        {view === 'alerts' ? renderAlerts() : null}
      </main>
      <footer className="site-footer"><span>Dados de mercado da DeFiLlama · conteúdo informativo</span><span>Sem custódia · sem execução de ordens</span></footer>
      {renderEducationModal()}
    </div>
  );
}
