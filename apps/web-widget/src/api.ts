
export type ApiMode = 'fixture' | 'api' | 'api-with-fixture-fallback';
export type Channel = 'web_widget' | 'ios_app' | 'simulated';
export type ProfileLevel = 'conservative' | 'moderate' | 'aggressive';
export type OpportunityRisk = 'low' | 'medium' | 'high' | 'unknown';
export type AuditStatus = 'audited' | 'partially_audited' | 'not_verified' | 'unknown';
export type SimulationHorizon = 30 | 180 | 365;
export type AlertStatus = 'unread' | 'read';
export type AlertType = 'apy_change' | 'risk_change' | 'new_opportunity' | 'data_stale';

export interface RequestContext {
  requestId?: string;
  correlationId?: string;
}

export interface ApiMeta {
  requestId: string;
  correlationId: string;
  generatedAt: string;
  disclaimer: string;
  source: 'api' | 'fixture';
  fallbackReason?: string;
}

export interface ApiResult<T> {
  data: T;
  meta: ApiMeta;
}

export interface HealthData {
  status: 'ok' | 'degraded';
  version: string;
  checks: Record<string, 'ok' | 'degraded' | 'unavailable' | 'not_configured'>;
}

export interface OtpChallenge {
  challengeId: string;
  expiresAt: string;
  delivery: 'email' | 'mock';
}

export interface AuthSession {
  accessToken: string;
  refreshToken: string;
  tokenType: 'Bearer';
  expiresAt: string;
  accountId: string;
  email: string;
}

export const DEFAULT_PUBLIC_API_BASE_URL = 'https://aurafi-api.onrender.com';

export interface RiskProfile {
  declaredProfile: ProfileLevel;
  status: 'declared' | 'missing';
  version: string;
  declaredAt: string;
  source: 'questionnaire' | 'manual';
}

export interface ProfileData {
  account: {
    accountId: string;
    email: string;
    emailVerified: boolean;
  };
  riskProfile: RiskProfile | null;
}

export interface SetProfileInput {
  declaredProfile: ProfileLevel;
  answers: Record<string, string>;
}

export interface DataSource {
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

export interface Opportunity {
  opportunityId: string;
  protocol: string;
  pool: string;
  asset: string;
  blockchain: string;
  apy: { value: number; unit: 'percent_annualized'; observedAt: string; display?: string };
  tvl: { value: number; currency: string; observedAt: string; display?: string; displayCompact?: string };
  liquidity: { level: OpportunityRisk; observedAt: string };
  auditStatus?: AuditStatus;
  risk: { score: number; level: OpportunityRisk; dimensions: string[] };
  dataSource: DataSource;
  disclaimer: string;
}

export interface OpportunityListParams {
  page?: number;
  pageSize?: number;
  riskProfile?: ProfileLevel;
  asset?: string;
  blockchain?: string;
}

export interface OpportunityListData {
  items: Opportunity[];
  pagination: { page: number; pageSize: number; total: number; hasNext: boolean };
}

export interface SimulationInput {
  opportunityId: string;
  amount: number;
  asset: string;
  horizonsDays: SimulationHorizon[];
  compareIdleStablecoin?: boolean;
  amountDisplay?: string;
}

export interface SimulationData {
  simulationId: string;
  opportunityId: string;
  input: SimulationInput;
  scenarios: Array<{
    horizonDays: SimulationHorizon;
    projectedValue: number;
    projectedYield: number;
    idleStablecoinValue?: number;
    currency: string;
    projectedGain?: number;
    projectedValueDisplay?: string;
    projectedYieldDisplay?: string;
    projectedGainDisplay?: string;
    idleStablecoinValueDisplay?: string;
  }>;
  assumptions: string[];
  generatedAt: string;
  dataSource?: DataSource;
  executionSupported: false;
  disclaimer: string;
}

export interface Consent {
  purpose: 'decision_support' | 'conversation' | 'memory' | 'analytics';
  status: 'granted' | 'denied' | 'revoked';
  policyVersion: string;
  capturedAt?: string;
  memory?: boolean;
  analytics?: boolean;
}

export interface ConversationCreateInput {
  consent: Consent;
  initialMessage?: string;
}

export interface MessageInput {
  text: string;
  consent: Consent;
  action?: 'ask_why' | 'simulate' | 'explain_risk' | 'request_human' | null;
}

export interface MessageEnvelope {
  envelopeVersion: string;
  messageId: string;
  messageType: 'user_message' | 'assistant_message' | 'system_event' | 'alert';
  occurredAt: string;
  requestId: string;
  correlationId: string;
  payload: Record<string, unknown>;
  disclaimer: string;
}

export interface ConversationData {
  conversationId: string;
  status: 'active' | 'waiting_human' | 'closed';
  messages: MessageEnvelope[];
}

export interface Alert {
  alertId: string;
  type: AlertType;
  opportunityId?: string;
  title: string;
  message: string;
  status: AlertStatus;
  createdAt: string;
  observedAt?: string;
  dataSource?: DataSource;
  suggestedAction?: 'view_opportunity' | 'simulate' | 'ask_hub' | 'none';
  disclaimer: string;
}

export interface AlertListParams {
  page?: number;
  pageSize?: number;
  unreadOnly?: boolean;
}

export interface AlertListData {
  items: Alert[];
  pagination: { page: number; pageSize: number; total: number; hasNext: boolean };
}

export interface ApiClientOptions {
  baseUrl?: string;
  mode?: ApiMode;
  token?: string;
  fetcher?: typeof fetch;
  timeoutMs?: number;
}

export type ApiErrorCode = 'API_BASE_URL_MISSING' | 'NETWORK_ERROR' | 'API_ERROR' | string;

const PUBLIC_API_ERROR_MESSAGE = 'N\u00e3o foi poss\u00edvel concluir agora. Verifique sua conex\u00e3o e tente novamente.';

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;
  readonly correlationId: string | undefined;
  readonly retryAfterSeconds: number | undefined;
  readonly retryable: boolean;

  constructor(message: string = PUBLIC_API_ERROR_MESSAGE, details: {
    status: number;
    code?: string;
    requestId?: string;
    correlationId?: string;
    retryAfterSeconds?: number;
    retryable?: boolean;
  }) {
    super(message);
    this.name = 'ApiClientError';
    this.status = details.status;
    this.code = details.code ?? 'API_ERROR';
    this.requestId = details.requestId;
    this.correlationId = details.correlationId;
    this.retryAfterSeconds = details.retryAfterSeconds;
    this.retryable = details.retryable ?? (details.status === 0 || details.status >= 500);
  }
}

const FIXTURE_DISCLAIMER = 'Fixture local sintética para desenvolvimento; não representa dado real, recomendação ou execução financeira.';
const FIXTURE_DATE = '2026-08-02T12:00:00.000Z';
const FIXTURE_SOURCE: DataSource = {
  source: 'defillama',
  mode: 'test',
  observedAt: '2026-08-02T11:45:00.000Z',
  retrievedAt: FIXTURE_DATE,
  readOnly: true,
  isStale: true,
  freshnessNote: 'Fixture sintética de teste; pode estar desatualizada.',
};

const FIXTURE_OPPORTUNITIES: Opportunity[] = [
  {
    opportunityId: 'fixture-aave-usdc-base',
    protocol: 'Aave',
    pool: 'USDC Supply',
    asset: 'USDC',
    blockchain: 'Base',
    apy: { value: 5.2, unit: 'percent_annualized', observedAt: FIXTURE_SOURCE.observedAt },
    tvl: { value: 1200000, currency: 'USD', observedAt: FIXTURE_SOURCE.observedAt },
    liquidity: { level: 'high', observedAt: FIXTURE_SOURCE.observedAt },
    auditStatus: 'partially_audited',
    risk: { score: 48, level: 'medium', dimensions: ['smart_contract', 'liquidity', 'underlying_asset'] },
    dataSource: FIXTURE_SOURCE,
    disclaimer: FIXTURE_DISCLAIMER,
  },
  {
    opportunityId: 'fixture-compound-dai-ethereum',
    protocol: 'Compound',
    pool: 'DAI Supply',
    asset: 'DAI',
    blockchain: 'Ethereum',
    apy: { value: 3.8, unit: 'percent_annualized', observedAt: FIXTURE_SOURCE.observedAt },
    tvl: { value: 860000, currency: 'USD', observedAt: FIXTURE_SOURCE.observedAt },
    liquidity: { level: 'medium', observedAt: FIXTURE_SOURCE.observedAt },
    auditStatus: 'not_verified',
    risk: { score: 65, level: 'unknown', dimensions: ['smart_contract', 'liquidity', 'data_quality'] },
    dataSource: FIXTURE_SOURCE,
    disclaimer: FIXTURE_DISCLAIMER,
  },
  {
    opportunityId: 'fixture-uniswap-eth-usdc-arbitrum',
    protocol: 'Uniswap',
    pool: 'ETH / USDC',
    asset: 'ETH + USDC',
    blockchain: 'Arbitrum',
    apy: { value: 8.1, unit: 'percent_annualized', observedAt: FIXTURE_SOURCE.observedAt },
    tvl: { value: 430000, currency: 'USD', observedAt: FIXTURE_SOURCE.observedAt },
    liquidity: { level: 'medium', observedAt: FIXTURE_SOURCE.observedAt },
    auditStatus: 'partially_audited',
    risk: { score: 78, level: 'high', dimensions: ['smart_contract', 'liquidity', 'volatility'] },
    dataSource: FIXTURE_SOURCE,
    disclaimer: FIXTURE_DISCLAIMER,
  },
];

const PRIMARY_FIXTURE_OPPORTUNITY = FIXTURE_OPPORTUNITIES[0]!;

const makeMeta = (source: ApiMeta['source'], context: RequestContext = {}, fallbackReason?: string): ApiMeta => {
  const meta: ApiMeta = {
    requestId: context.requestId ?? `req_fixture_${Date.now()}`,
    correlationId: context.correlationId ?? `corr_fixture_${Date.now()}`,
    generatedAt: new Date().toISOString(),
    disclaimer: source === 'fixture' ? FIXTURE_DISCLAIMER : 'Resposta da API AuraFi; consulte o contrato para limites e disclaimers.',
    source,
  };
  if (fallbackReason) meta.fallbackReason = fallbackReason;
  return meta;
};

const fixtureResult = <T>(data: T, context?: RequestContext, fallbackReason?: string): ApiResult<T> => ({
  data,
  meta: makeMeta('fixture', context, fallbackReason),
});

const fixtureProfile: ProfileData = {
  account: { accountId: 'account_fixture_001', email: 'maria.fixture@example.test', emailVerified: true },
  riskProfile: null,
};

const fixtureConversation: ConversationData = {
  conversationId: 'conversation_fixture_001',
  status: 'active',
  messages: [],
};

const fixtureAlerts: Alert[] = [
  {
    alertId: 'alert_fixture_stale_001',
    type: 'data_stale',
    opportunityId: PRIMARY_FIXTURE_OPPORTUNITY.opportunityId,
    title: 'Snapshot de estudo desatualizado',
    message: 'A oportunidade possui dados sintéticos em modo test.',
    status: 'unread',
    createdAt: FIXTURE_DATE,
    observedAt: FIXTURE_SOURCE.observedAt,
    dataSource: FIXTURE_SOURCE,
    suggestedAction: 'view_opportunity',
    disclaimer: FIXTURE_DISCLAIMER,
  },
];

const PRIMARY_FIXTURE_ALERT = fixtureAlerts[0]!;

interface RawMeta {
  request_id?: string;
  correlation_id?: string;
  generated_at?: string;
  disclaimer?: string;
}

interface RawOpportunity {
  opportunity_id: string;
  protocol: string;
  pool: string;
  asset: string;
  blockchain: string;
  apy: { value: number; unit: 'percent_annualized'; observed_at: string; display?: string };
  tvl: { value: number; currency: string; observed_at: string; display?: string; display_compact?: string };
  liquidity: { level: OpportunityRisk; observed_at: string };
  risk: { score: number; level: OpportunityRisk; dimensions: string[] };
  audit_status?: AuditStatus;
  data_source: {
    source: 'defillama';
    mode: DataSource['mode'];
    observed_at: string;
    retrieved_at: string;
    read_only: true;
    is_stale: boolean;
    freshness_note?: string;
    source_label?: string;
    status_label?: string;
  };
  disclaimer: string;
}

interface RawOpportunityListResponse {
  items: RawOpportunity[];
  pagination: { page: number; page_size: number; total: number; has_next: boolean };
  meta: RawMeta;
}

interface RawOpportunityResponse { opportunity: RawOpportunity; meta: RawMeta }

const toOpportunity = (raw: RawOpportunity): Opportunity => ({
  opportunityId: raw.opportunity_id,
  protocol: raw.protocol,
  pool: raw.pool,
  asset: raw.asset,
  blockchain: raw.blockchain,
  apy: {
    value: raw.apy.value,
    unit: raw.apy.unit,
    observedAt: raw.apy.observed_at,
    ...(raw.apy.display ? { display: raw.apy.display } : {}),
  },
  tvl: {
    value: raw.tvl.value,
    currency: raw.tvl.currency,
    observedAt: raw.tvl.observed_at,
    ...(raw.tvl.display ? { display: raw.tvl.display } : {}),
    ...(raw.tvl.display_compact ? { displayCompact: raw.tvl.display_compact } : {}),
  },
  liquidity: { ...raw.liquidity, observedAt: raw.liquidity.observed_at },
  risk: raw.risk,
  disclaimer: raw.disclaimer,
  dataSource: {
    source: raw.data_source.source,
    mode: raw.data_source.mode,
    observedAt: raw.data_source.observed_at,
    retrievedAt: raw.data_source.retrieved_at,
    readOnly: raw.data_source.read_only,
    isStale: raw.data_source.is_stale,
    ...(raw.data_source.freshness_note ? { freshnessNote: raw.data_source.freshness_note } : {}),
    ...(raw.data_source.source_label ? { sourceLabel: raw.data_source.source_label } : {}),
    ...(raw.data_source.status_label ? { statusLabel: raw.data_source.status_label } : {}),
  },
  ...(raw.audit_status ? { auditStatus: raw.audit_status } : {}),
});

const toDataSource = (raw: RawOpportunity['data_source']): DataSource => ({
  source: raw.source,
  mode: raw.mode,
  observedAt: raw.observed_at,
  retrievedAt: raw.retrieved_at,
  readOnly: raw.read_only,
  isStale: raw.is_stale,
  ...(raw.freshness_note ? { freshnessNote: raw.freshness_note } : {}),
  ...(raw.source_label ? { sourceLabel: raw.source_label } : {}),
  ...(raw.status_label ? { statusLabel: raw.status_label } : {}),
});

const toMeta = (raw: RawMeta | undefined, response: Response, requested: RequestContext, source: ApiMeta['source']): ApiMeta => ({
  requestId: raw?.request_id ?? response.headers.get('X-Request-ID') ?? requested.requestId ?? `req_${Date.now()}`,
  correlationId: raw?.correlation_id ?? response.headers.get('X-Correlation-ID') ?? requested.correlationId ?? `corr_${Date.now()}`,
  generatedAt: raw?.generated_at ?? new Date().toISOString(),
  disclaimer: raw?.disclaimer ?? (source === 'fixture' ? FIXTURE_DISCLAIMER : 'Resposta da API AuraFi.'),
  source,
});

const joinUrl = (baseUrl: string, path: string): string => `${baseUrl.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;

const reportApiFailure = (error: ApiClientError, operation: string): void => {
  if (typeof console === 'undefined' || typeof console.error !== 'function') return;
  console.error('[AuraFi] API request failed', {
    operation,
    code: error.code,
    status: error.status,
    retryable: error.retryable,
    requestId: error.requestId,
    correlationId: error.correlationId,
  });
};

export function createWidgetApi(options: ApiClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_PUBLIC_API_BASE_URL).trim();
  const allowDemoData = import.meta.env.VITE_ALLOW_DEMO_DATA === 'true';
  const requestedMode = options.mode;
  const mode = allowDemoData
    ? (requestedMode ?? (baseUrl ? 'api-with-fixture-fallback' : 'fixture'))
    : 'api';
  const fetcher = options.fetcher ?? globalThis.fetch;
  const timeoutMs = options.timeoutMs ?? 8000;

  const request = async <T>(method: string, path: string, context: RequestContext, body?: unknown, parse?: (value: unknown, response: Response, requested: RequestContext) => T): Promise<ApiResult<T>> => {
    const requestId = context.requestId ?? `req_${crypto.randomUUID()}`;
    const correlationId = context.correlationId ?? `corr_${crypto.randomUUID()}`;
    const operation = `${method} ${path}`;
    if (!baseUrl && mode !== 'fixture') {
      const error = new ApiClientError(PUBLIC_API_ERROR_MESSAGE, {
        status: 0,
        code: 'API_BASE_URL_MISSING',
        requestId,
        correlationId,
        retryable: false,
      });
      reportApiFailure(error, operation);
      throw error;
    }
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
    const headers = new Headers({
      Accept: 'application/json',
      'X-Request-ID': requestId,
      'X-Correlation-ID': correlationId,
    });
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    if (options.token) headers.set('Authorization', `Bearer ${options.token}`);
    const requestInit: RequestInit = { method, headers, signal: controller.signal };
    if (body !== undefined) requestInit.body = JSON.stringify(body);

    try {
      const response = await fetcher(joinUrl(baseUrl, path), requestInit);
      const responseBody: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined);
      if (!response.ok) {
        const raw = responseBody as { error?: { code?: string; message?: string; retryable?: boolean }; meta?: RawMeta } | undefined;
        const errorDetails: { status: number; code?: string; requestId?: string; correlationId?: string; retryAfterSeconds?: number; retryable?: boolean } = {
          status: response.status,
          code: raw?.error?.code ?? `HTTP_${response.status}`,
          requestId: raw?.meta?.request_id ?? response.headers.get('X-Request-ID') ?? requestId,
          correlationId: raw?.meta?.correlation_id ?? response.headers.get('X-Correlation-ID') ?? correlationId,
          retryable: raw?.error?.retryable ?? (response.status === 429 || response.status >= 500),
        };
        const retryAfterSeconds = Number(response.headers.get('Retry-After') ?? '');
        if (retryAfterSeconds > 0) errorDetails.retryAfterSeconds = retryAfterSeconds;
        throw new ApiClientError(PUBLIC_API_ERROR_MESSAGE, errorDetails);
      }
      const parsed = parse ? parse(responseBody, response, { requestId, correlationId }) : responseBody as T;
      const rawMeta = (responseBody as { meta?: RawMeta } | undefined)?.meta;
      return { data: parsed, meta: toMeta(rawMeta, response, { requestId, correlationId }, 'api') };
    } catch (error) {
      if (error instanceof ApiClientError) {
        reportApiFailure(error, operation);
        throw error;
      }
      const message = error instanceof DOMException && error.name === 'AbortError'
        ? 'A API excedeu o tempo limite.'
        : 'Não foi possível conectar à API AuraFi.';
      const apiError = new ApiClientError(message, { status: 0, code: 'NETWORK_ERROR', requestId, correlationId, retryable: true });
      reportApiFailure(apiError, operation);
      throw apiError;
    } finally {
      globalThis.clearTimeout(timeout);
    }
  };

  const shouldFallback = (error: unknown): boolean => error instanceof ApiClientError && (error.status === 0 || error.status >= 500);

  const withFallback = async <T>(context: RequestContext, fixture: () => ApiResult<T>, apiCall: () => Promise<ApiResult<T>>): Promise<ApiResult<T>> => {
    if (mode === 'fixture') return fixture();
    try {
      return await apiCall();
    } catch (error) {
      if (mode === 'api-with-fixture-fallback' && shouldFallback(error)) {
        const reason = error instanceof Error ? error.message : 'Falha não identificada na API.';
        return fixtureResult(fixture().data, context, reason);
      }
      throw error;
    }
  };

  const methods = {
      health: (context: RequestContext = {}): Promise<ApiResult<HealthData>> => withFallback(
      context,
      () => fixtureResult({ status: 'ok', version: 'fixture', checks: { api: 'ok', marketData: 'not_configured' } }, context),
      () => request('GET', '/health', context, undefined, (value) => {
        const raw = value as { status: HealthData['status']; version: string; checks: HealthData['checks'] };
        return { status: raw.status, version: raw.version, checks: raw.checks };
      }),
    ),

    requestOtp: (email: string, context: RequestContext = {}): Promise<ApiResult<OtpChallenge>> => withFallback(
      context,
      () => fixtureResult({ challengeId: 'challenge_fixture_001', expiresAt: new Date(Date.now() + 300000).toISOString(), delivery: 'mock' }, context),
      () => request('POST', '/v1/auth/otp/request', context, { email, channel: 'web_widget' }, (value) => {
        const raw = value as { challenge_id: string; expires_at: string; delivery: 'email' | 'mock' };
        return { challengeId: raw.challenge_id, expiresAt: raw.expires_at, delivery: raw.delivery };
      }),
    ),

    verifyOtp: (challengeId: string, otp: string, context: RequestContext = {}): Promise<ApiResult<AuthSession>> => withFallback(
      context,
      () => fixtureResult({ accessToken: 'token_fixture', refreshToken: 'refresh_fixture', tokenType: 'Bearer', expiresAt: new Date(Date.now() + 3600000).toISOString(), accountId: 'account_fixture_001', email: 'maria.fixture@example.test' }, context),
      () => request('POST', '/v1/auth/otp/verify', context, { challenge_id: challengeId, otp }, (value) => {
        const raw = value as { session: { access_token: string; refresh_token: string; token_type: 'Bearer'; expires_at: string; account: { account_id: string; email: string } } };
        return { accessToken: raw.session.access_token, refreshToken: raw.session.refresh_token, tokenType: raw.session.token_type, expiresAt: raw.session.expires_at, accountId: raw.session.account.account_id, email: raw.session.account.email };
      }),
    ),

    refreshSession: (refreshToken: string, context: RequestContext = {}): Promise<ApiResult<AuthSession>> => withFallback(
      context,
      () => fixtureResult({ accessToken: 'token_fixture_rotated', refreshToken: 'refresh_fixture_rotated', tokenType: 'Bearer', expiresAt: new Date(Date.now() + 3600000).toISOString(), accountId: 'account_fixture_001', email: 'maria.fixture@example.test' }, context),
      () => request('POST', '/v1/auth/refresh', context, { refresh_token: refreshToken }, (value) => {
        const raw = value as { session: { access_token: string; refresh_token: string; token_type: 'Bearer'; expires_at: string; account: { account_id: string; email: string } } };
        return { accessToken: raw.session.access_token, refreshToken: raw.session.refresh_token, tokenType: raw.session.token_type, expiresAt: raw.session.expires_at, accountId: raw.session.account.account_id, email: raw.session.account.email };
      }),
    ),

    logout: (context: RequestContext = {}): Promise<ApiResult<null>> => withFallback(
      context,
      () => fixtureResult(null, context),
      () => request('POST', '/v1/auth/logout', context, undefined, () => null),
    ),

    getProfile: (context: RequestContext = {}): Promise<ApiResult<ProfileData>> => withFallback(
      context,
      () => fixtureResult(fixtureProfile, context),
      () => request('GET', '/v1/profile', context, undefined, (value) => toProfile(value)),
    ),

    setProfile: (input: SetProfileInput, context: RequestContext = {}): Promise<ApiResult<ProfileData>> => withFallback(
      context,
      () => fixtureResult({ ...fixtureProfile, riskProfile: { declaredProfile: input.declaredProfile, status: 'declared', version: 'fixture-v1', declaredAt: new Date().toISOString(), source: 'questionnaire' } }, context),
      () => request('PUT', '/v1/profile/risk', context, { declared_profile: input.declaredProfile, answers: Object.entries(input.answers).map(([questionId, answer]) => ({ question_id: questionId, answer })) }, (value) => toProfile(value)),
    ),

    listOpportunities: (params: OpportunityListParams = {}, context: RequestContext = {}): Promise<ApiResult<OpportunityListData>> => withFallback(
      context,
      () => fixtureResult({ items: FIXTURE_OPPORTUNITIES, pagination: { page: 1, pageSize: FIXTURE_OPPORTUNITIES.length, total: FIXTURE_OPPORTUNITIES.length, hasNext: false } }, context),
      () => request('GET', `/v1/opportunities${toQuery({ page: params.page, page_size: params.pageSize, risk_profile: params.riskProfile, asset: params.asset, blockchain: params.blockchain })}`, context, undefined, (value) => {
        const raw = value as RawOpportunityListResponse;
        return { items: raw.items.map(toOpportunity), pagination: { page: raw.pagination.page, pageSize: raw.pagination.page_size, total: raw.pagination.total, hasNext: raw.pagination.has_next } };
      }),
    ),

    getOpportunity: (opportunityId: string, context: RequestContext = {}): Promise<ApiResult<Opportunity>> => withFallback(
      context,
      () => fixtureResult(FIXTURE_OPPORTUNITIES.find((item) => item.opportunityId === opportunityId) ?? PRIMARY_FIXTURE_OPPORTUNITY, context),
      () => request('GET', `/v1/opportunities/${encodeURIComponent(opportunityId)}`, context, undefined, (value) => toOpportunity((value as RawOpportunityResponse).opportunity)),
    ),

    createSimulation: (input: SimulationInput, context: RequestContext = {}): Promise<ApiResult<SimulationData>> => withFallback(
      context,
      () => fixtureResult(makeFixtureSimulation(input), context),
      () => request('POST', '/v1/simulations', context, { opportunity_id: input.opportunityId, amount: input.amount, asset: input.asset, horizons_days: input.horizonsDays, compare_idle_stablecoin: input.compareIdleStablecoin ?? true }, (value) => toSimulation(value)),
    ),

    createConversation: (input: ConversationCreateInput, context: RequestContext = {}): Promise<ApiResult<ConversationData>> => withFallback(
      context,
      () => fixtureResult(fixtureConversation, context),
      () => request('POST', '/v1/conversations', context, { channel: 'web_widget', consent: toApiConsent(input.consent), initial_message: input.initialMessage }, (value) => toConversation(value)),
    ),

    getConversation: (conversationId: string, context: RequestContext = {}): Promise<ApiResult<ConversationData>> => withFallback(
      context,
      () => fixtureResult({ ...fixtureConversation, conversationId }, context),
      () => request('GET', `/v1/conversations/${encodeURIComponent(conversationId)}`, context, undefined, (value) => toConversation(value)),
    ),

    sendConversationMessage: (conversationId: string, input: MessageInput, context: RequestContext = {}): Promise<ApiResult<ConversationData>> => withFallback(
      context,
      () => fixtureResult({ ...fixtureConversation, conversationId, messages: [...fixtureConversation.messages, makeFixtureMessage(input.text, context)] }, context),
      () => request('POST', `/v1/conversations/${encodeURIComponent(conversationId)}/messages`, context, { text: input.text, channel: 'web_widget', action: input.action ?? null, consent: toApiConsent(input.consent) }, (value) => toConversationMessage(conversationId, value)),
    ),

    listAlerts: (params: AlertListParams = {}, context: RequestContext = {}): Promise<ApiResult<AlertListData>> => withFallback(
      context,
      () => fixtureResult({ items: params.unreadOnly ? fixtureAlerts.filter((alert) => alert.status === 'unread') : fixtureAlerts, pagination: { page: 1, pageSize: fixtureAlerts.length, total: fixtureAlerts.length, hasNext: false } }, context),
      () => request('GET', `/v1/alerts${toQuery({ page: params.page, page_size: params.pageSize, unread_only: params.unreadOnly })}`, context, undefined, (value) => {
        const raw = value as { items: RawAlert[]; pagination: { page: number; page_size: number; total: number; has_next: boolean } };
        return { items: raw.items.map(toAlert), pagination: { page: raw.pagination.page, pageSize: raw.pagination.page_size, total: raw.pagination.total, hasNext: raw.pagination.has_next } };
      }),
    ),

    markAlertRead: (alertId: string, context: RequestContext = {}): Promise<ApiResult<Alert>> => withFallback(
      context,
      () => fixtureResult({ ...(fixtureAlerts.find((alert) => alert.alertId === alertId) ?? PRIMARY_FIXTURE_ALERT), status: 'read' }, context),
      () => request('PATCH', `/v1/alerts/${encodeURIComponent(alertId)}`, context, { status: 'read' }, (value) => toAlert((value as { alert: RawAlert }).alert)),
    ),
  };

  return { ...methods, mode };
}

const toQuery = (params: Record<string, string | number | boolean | undefined>): string => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : '';
};

const toProfile = (value: unknown): ProfileData => {
  const raw = value as { account: { account_id: string; email: string; email_verified: boolean }; risk_profile: { declared_profile: ProfileLevel; status: 'declared' | 'missing'; version: string; declared_at: string; source: 'questionnaire' | 'manual' } | null };
  return {
    account: { accountId: raw.account.account_id, email: raw.account.email, emailVerified: raw.account.email_verified },
    riskProfile: raw.risk_profile ? { declaredProfile: raw.risk_profile.declared_profile, status: raw.risk_profile.status, version: raw.risk_profile.version, declaredAt: raw.risk_profile.declared_at, source: raw.risk_profile.source } : null,
  };
};

const makeFixtureSimulation = (input: SimulationInput): SimulationData => {
  const opportunity = FIXTURE_OPPORTUNITIES.find((item) => item.opportunityId === input.opportunityId) ?? PRIMARY_FIXTURE_OPPORTUNITY;
  return {
    simulationId: `simulation_fixture_${Date.now()}`,
    opportunityId: input.opportunityId,
    input,
    scenarios: input.horizonsDays.map((horizonDays) => {
      const projectedYield = opportunity.apy.value * horizonDays / 365;
      return { horizonDays, projectedValue: input.amount * (1 + projectedYield / 100), projectedYield, idleStablecoinValue: input.amount, currency: input.asset };
    }),
    assumptions: ['[ASSUNÇÃO DE TESTE] APY aplicado linearmente por dias / 365.', '[ASSUNÇÃO DE TESTE] A comparação preserva o principal e considera rendimento zero.'],
    generatedAt: new Date().toISOString(),
    dataSource: FIXTURE_SOURCE,
    executionSupported: false,
    disclaimer: 'Simulação educativa com fixture local. Nenhuma transação é criada ou executada.',
  };
};

const toSimulation = (value: unknown): SimulationData => {
  const raw = value as { simulation: { simulation_id: string; opportunity_id: string; input: { opportunity_id: string; amount: number; asset: string; horizons_days: SimulationHorizon[]; compare_idle_stablecoin?: boolean; amount_display?: string }; scenarios: Array<{ horizon_days: SimulationHorizon; projected_value: number; projected_yield: number; idle_stablecoin_value?: number; currency: string; projected_gain?: number; projected_value_display?: string; projected_yield_display?: string; projected_gain_display?: string; idle_stablecoin_value_display?: string }>; assumptions: string[]; generated_at?: string; data_source?: RawOpportunity['data_source']; execution_supported: false; disclaimer: string } };
  const input: SimulationInput = {
    opportunityId: raw.simulation.input.opportunity_id,
    amount: raw.simulation.input.amount,
    asset: raw.simulation.input.asset,
    horizonsDays: raw.simulation.input.horizons_days,
    ...(raw.simulation.input.compare_idle_stablecoin === undefined ? {} : { compareIdleStablecoin: raw.simulation.input.compare_idle_stablecoin }),
    ...(raw.simulation.input.amount_display ? { amountDisplay: raw.simulation.input.amount_display } : {}),
  };
  const simulation: SimulationData = {
    simulationId: raw.simulation.simulation_id,
    opportunityId: raw.simulation.opportunity_id,
    input,
    scenarios: raw.simulation.scenarios.map((scenario) => ({
      horizonDays: scenario.horizon_days,
      projectedValue: scenario.projected_value,
      projectedYield: scenario.projected_yield,
      currency: scenario.currency,
      ...(scenario.idle_stablecoin_value === undefined ? {} : { idleStablecoinValue: scenario.idle_stablecoin_value }),
      ...(scenario.projected_gain === undefined ? {} : { projectedGain: scenario.projected_gain }),
      ...(scenario.projected_value_display ? { projectedValueDisplay: scenario.projected_value_display } : {}),
      ...(scenario.projected_yield_display ? { projectedYieldDisplay: scenario.projected_yield_display } : {}),
      ...(scenario.projected_gain_display ? { projectedGainDisplay: scenario.projected_gain_display } : {}),
      ...(scenario.idle_stablecoin_value_display ? { idleStablecoinValueDisplay: scenario.idle_stablecoin_value_display } : {}),
    })),
    assumptions: raw.simulation.assumptions,
    generatedAt: raw.simulation.generated_at ?? new Date().toISOString(),
    executionSupported: raw.simulation.execution_supported,
    disclaimer: raw.simulation.disclaimer,
  };
  if (raw.simulation.data_source) simulation.dataSource = toDataSource(raw.simulation.data_source);
  return simulation;
};

interface RawAlert {
  alert_id: string;
  type: AlertType;
  opportunity_id?: string;
  title: string;
  message: string;
  status: AlertStatus;
  created_at: string;
  observed_at?: string;
  data_source?: RawOpportunity['data_source'];
  suggested_action?: Alert['suggestedAction'];
  disclaimer: string;
}

const toAlert = (raw: RawAlert): Alert => ({
  alertId: raw.alert_id,
  type: raw.type,
  title: raw.title,
  message: raw.message,
  status: raw.status,
  createdAt: raw.created_at,
  disclaimer: raw.disclaimer,
  ...(raw.opportunity_id ? { opportunityId: raw.opportunity_id } : {}),
  ...(raw.observed_at ? { observedAt: raw.observed_at } : {}),
  ...(raw.suggested_action ? { suggestedAction: raw.suggested_action } : {}),
  ...(raw.data_source ? { dataSource: toDataSource(raw.data_source) } : {}),
});

const toApiConsent = (consent: Consent) => ({
  purpose: consent.purpose,
  status: consent.status,
  policy_version: consent.policyVersion,
  captured_at: consent.capturedAt,
  memory: consent.memory,
  analytics: consent.analytics,
});

const makeFixtureMessage = (text: string, context: RequestContext): MessageEnvelope => ({
  envelopeVersion: '1.0',
  messageId: `message_fixture_${Date.now()}`,
  messageType: 'assistant_message',
  occurredAt: new Date().toISOString(),
  requestId: context.requestId ?? `req_fixture_${Date.now()}`,
  correlationId: context.correlationId ?? `corr_fixture_${Date.now()}`,
  payload: { text: `Fixture local: recebi sua mensagem sobre “${text}”.` },
  disclaimer: FIXTURE_DISCLAIMER,
});

const toMessage = (raw: { envelope_version: string; message_id: string; message_type: MessageEnvelope['messageType']; occurred_at: string; request_id: string; correlation_id: string; payload: Record<string, unknown>; disclaimer: string }): MessageEnvelope => ({
  envelopeVersion: raw.envelope_version,
  messageId: raw.message_id,
  messageType: raw.message_type,
  occurredAt: raw.occurred_at,
  requestId: raw.request_id,
  correlationId: raw.correlation_id,
  payload: raw.payload,
  disclaimer: raw.disclaimer,
});

const toConversation = (value: unknown): ConversationData => {
  const raw = value as { conversation: { conversation_id: string; status: ConversationData['status']; messages: Array<{ envelope_version: string; message_id: string; message_type: MessageEnvelope['messageType']; occurred_at: string; request_id: string; correlation_id: string; payload: Record<string, unknown>; disclaimer: string }> } };
  return { conversationId: raw.conversation.conversation_id, status: raw.conversation.status, messages: raw.conversation.messages.map(toMessage) };
};

const toConversationMessage = (conversationId: string, value: unknown): ConversationData => {
  const raw = value as { user_message: Parameters<typeof toMessage>[0]; assistant_message: Parameters<typeof toMessage>[0] };
  return { conversationId, status: 'active', messages: [toMessage(raw.user_message), toMessage(raw.assistant_message)] };
};

export const widgetApi = createWidgetApi();
