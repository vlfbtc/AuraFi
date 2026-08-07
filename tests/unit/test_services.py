"""Testes de domínio BE-009 com adapters exclusivamente em memória.

Os nomes dos testes referenciam os critérios de aceite de ``MVP_RULES.md``.
Nenhum teste chama rede, banco, dbt, pytest ou provedor LLM real.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from services.conversation import (
    AuditMetadata,
    Consent,
    ConversationService,
    LlmResult,
    MessageEnvelope,
    MessageResponse,
    MessageRequest,
    SessionSnapshot,
    UnavailableLlm,
)
from services.identity import (
    Account,
    AuthenticationError,
    ChannelContext,
    IdentityService,
    InMemoryAccountRepository,
    InMemoryChannelIdentityRepository,
    InMemoryOtpChallengeRepository,
    InMemoryOtpSink,
    InMemorySessionRepository,
    UnsupportedChannelError,
)
from services.identity.service import HmacOtpHasher
from services.market_data import (
    CacheEntry,
    DeFiLlamaAdapter,
    InMemoryCache,
    MarketDataError,
    MarketDetailEnricher,
)
from services.notifications import (
    AlertDataSource,
    AlertObservation,
    AlertPolicy,
    AlertPreferences,
    AlertResultStatus,
    AlertService,
    AlertStatus,
    AlertType,
    ApyChangeRule,
    DataStaleRule,
    ExplicitEventRule,
    InMemoryDeduplicationStore,
    SuggestedAction,
)
from services.recommendation import (
    EligibilityPolicy,
    EligibilityRule,
    EligibilityStatus,
    Opportunity,
    RecommendationService,
    RecommendationStatus,
    RiskProfile,
    Suitability,
)
from services.simulated_channel import (
    DeterministicIdFactory,
    SimulatedChannelAdapter,
    SimulatedChannelError,
    SimulatedChannelInputError,
    SimulatedTransportMessage,
)
from services.simulation import AssumptionFixtureFormula, SimulationService


UTC = timezone.utc
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def now(self) -> datetime:
        return self.value


class SequenceGenerator:
    def __init__(self, *values: str) -> None:
        self.values = list(values)

    def generate(self) -> str:
        if not self.values:
            raise AssertionError("fixture esgotada")
        return self.values.pop(0)


class IdFactory:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{prefix}-fixture-{self.counts[prefix]}"


def make_identity(clock: MutableClock | None = None) -> tuple[IdentityService, MutableClock, InMemoryOtpSink]:
    clock = clock or MutableClock()
    account = Account("acc-1", "Maria@Example.com", created_at=NOW)
    sink = InMemoryOtpSink(capture_secrets=True)
    service = IdentityService(
        accounts=InMemoryAccountRepository([account]),
        challenges=InMemoryOtpChallengeRepository(),
        sessions=InMemorySessionRepository(),
        channel_identities=InMemoryChannelIdentityRepository(),
        otp_delivery=sink,
        clock=clock,
        otp_generator=SequenceGenerator("123456"),
        otp_hasher=HmacOtpHasher(b"be-009-test-pepper"),
        token_generator=SequenceGenerator("access-1", "refresh-1", "access-2", "refresh-2"),
        id_generator=IdFactory(),
    )
    return service, clock, sink


class IdentityDomainTests(unittest.TestCase):
    def test_self_signup_opt_in_creates_account_and_delivers_otp(self) -> None:
        sink = InMemoryOtpSink(capture_secrets=True)
        accounts = InMemoryAccountRepository()
        service = IdentityService(
            accounts=accounts,
            challenges=InMemoryOtpChallengeRepository(),
            sessions=InMemorySessionRepository(),
            channel_identities=InMemoryChannelIdentityRepository(),
            otp_delivery=sink,
            otp_generator=SequenceGenerator("123456"),
            otp_hasher=HmacOtpHasher(b"self-signup-test-pepper"),
            token_generator=SequenceGenerator("access", "refresh"),
            id_generator=IdFactory(),
            allow_self_signup=True,
        )

        challenge = service.request_otp("nova@example.com", "ios_app")
        account = accounts.find_by_email("nova@example.com")

        self.assertIsNotNone(account)
        self.assertEqual(sink.code_for(challenge.challenge_id), "123456")
        auth = service.verify_otp(challenge.challenge_id, "123456")
        self.assertEqual(auth.session.account.email, "nova@example.com")

    def test_otp_invalido_consumes_attempt_and_exposes_safe_error(self) -> None:
        service, _, sink = make_identity()
        challenge = service.request_otp(" maria@example.com ", "web_widget", request_id="req-1")

        with self.assertRaises(AuthenticationError) as raised:
            service.verify_otp(challenge.challenge_id, "999999")

        self.assertEqual(raised.exception.code, "AUTHENTICATION_FAILED")
        self.assertNotIn("123456", raised.exception.message)
        stored = service._challenges.get(challenge.challenge_id)  # adapter de memória controlado
        self.assertEqual(stored.attempts, 1)
        self.assertEqual(sink.code_for(challenge.challenge_id), "123456")

    def test_otp_expirado_e_reutilizado_sao_rejeitados(self) -> None:
        clock = MutableClock()
        service, _, sink = make_identity(clock)
        challenge = service.request_otp("maria@example.com", "web_widget")
        clock.value = NOW + timedelta(minutes=5)

        with self.assertRaises(AuthenticationError):
            service.verify_otp(challenge.challenge_id, sink.code_for(challenge.challenge_id) or "")
        self.assertEqual(service._challenges.get(challenge.challenge_id).status, "expired")

        # Um segundo desafio prova uso único: depois de verificado, o mesmo OTP
        # não cria uma nova sessão em retry.
        clock.value = NOW
        service._otp_generator = SequenceGenerator("654321")
        second = service.request_otp("maria@example.com", "web_widget")
        otp = sink.code_for(second.challenge_id)
        first_auth = service.verify_otp(second.challenge_id, otp or "")
        with self.assertRaises(AuthenticationError):
            service.verify_otp(second.challenge_id, otp or "")
        self.assertEqual(first_auth.identity["account_id"], "acc-1")
        self.assertEqual(service._challenges.get(second.challenge_id).status, "verified")

    def test_identidade_canônica_preserva_conta_entre_canais_sem_merge(self) -> None:
        service, _, sink = make_identity()
        challenge = service.request_otp("maria@example.com", "web_widget")
        auth = service.verify_otp(challenge.challenge_id, sink.code_for(challenge.challenge_id) or "")

        ios = service.resolve_session(auth.session.access_token, channel="ios_app")
        web = service.resolve_session(auth.session.access_token, channel="web_widget")
        self.assertEqual(ios.account.account_id, web.account.account_id)
        self.assertEqual(ios.session.session_id, web.session.session_id)
        self.assertNotEqual(ios.channel_association.channel.name, web.channel_association.channel.name)

        other = Account("acc-2", "other@example.com", created_at=NOW)
        service._accounts.add(other)  # fixture in-memory, sem banco
        foreign = service.associate_channel("acc-2", "simulated")
        with self.assertRaises(AuthenticationError):
            service.resolve_session(auth.session.access_token, channel_identity_id=foreign.channel_identity_id)


class RecommendationAndMarketDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.opportunity = Opportunity("pool-1", risk_level="unknown", attributes={"apy": 5.2})
        self.profile = RiskProfile(
            declared_profile="conservative",
            version="profile-v1",
            source="manual",
            declared_at=NOW,
        )
        self.rule = EligibilityRule(
            allowed_profiles=frozenset({"conservative"}),
            rationale=("Perfil declarado compatível com a regra de teste.",),
            risks=("Dados de mercado podem variar.",),
            suitability=Suitability.CAUTION,
        )

    def test_recomendacao_sem_perfil_falha_fechado(self) -> None:
        result = RecommendationService().recommend(None, [self.opportunity], None, recommendation_id="rec-1", now=NOW)
        self.assertEqual(result.status, RecommendationStatus.NO_MATCH)
        self.assertFalse(result.actionable)
        self.assertIn("PROFILE_REQUIRED", result.explanation)
        self.assertEqual(result.eligibility[0].status, EligibilityStatus.NEEDS_PROFILE)
        self.assertEqual(result.items, ())

    def test_recomendacao_sem_policy_e_sem_regra_ficam_pendentes(self) -> None:
        service = RecommendationService()
        without_policy = service.recommend(self.profile, [self.opportunity], None, now=NOW)
        self.assertIn("POLICY_REQUIRED", without_policy.explanation)
        self.assertEqual(without_policy.eligibility[0].status, EligibilityStatus.PENDING)

        policy = EligibilityPolicy.from_rules("policy-v1", {"other-pool": self.rule})
        missing_rule = service.recommend(self.profile, [self.opportunity], policy, now=NOW)
        self.assertEqual(missing_rule.eligibility[0].reason_code, "POLICY_RULE_MISSING")
        self.assertEqual(missing_rule.status, RecommendationStatus.NO_MATCH)

    def test_recomendacao_pronta_exige_explicacao_risco_e_disclaimer(self) -> None:
        policy = EligibilityPolicy.from_rules("policy-v1", {"pool-1": self.rule})
        result = RecommendationService().recommend(self.profile, [self.opportunity], policy, now=NOW)
        self.assertEqual(result.status, RecommendationStatus.READY)
        self.assertEqual(result.profile_used.value, "conservative")
        self.assertEqual(result.policy_version, "policy-v1")
        self.assertTrue(result.items[0].rationale)
        self.assertTrue(result.items[0].risks)
        self.assertIn("retorno", result.disclaimer.lower())

    def test_market_data_fallback_e_cache_stale_sao_visíveis_e_read_only(self) -> None:
        fallback = DeFiLlamaAdapter(clock=MutableClock()).read(mode="test")
        self.assertEqual(fallback.data_source.mode, "test")
        self.assertTrue(fallback.data_source.is_stale)
        self.assertTrue(fallback.data_source.read_only)
        self.assertIn("teste", (fallback.data_source.freshness_note or "").lower())

        class Http:
            def __init__(self) -> None:
                self.fail = False

            def get(self, url: str, *, timeout_seconds: float):
                if self.fail:
                    raise OSError("fonte fora do ar")
                return {"data": [{"pool": "p-1", "project": "P", "poolMeta": "Pool", "symbol": "USDC", "chain": "Ethereum", "apy": 5.0, "tvlUsd": 1000, "observed_at": NOW.isoformat()}]}

        clock = MutableClock()
        http = Http()
        adapter = DeFiLlamaAdapter(
            base_url="https://example.invalid",
            endpoint="markets",
            http_client=http,
            cache=InMemoryCache(),
            clock=clock,
        )
        fresh = adapter.read(mode="live")
        self.assertFalse(fresh.data_source.is_stale)
        clock.value = NOW + timedelta(seconds=301)
        http.fail = True
        stale = adapter.read(mode="auto")
        self.assertEqual(stale.data_source.mode, "cache")
        self.assertTrue(stale.data_source.is_stale)
        self.assertIn("stale", (stale.data_source.freshness_note or "").lower())

    def test_detalhe_reutiliza_cache_live_valido_sem_refetch_de_pools(self) -> None:
        class Http:
            calls = 0

            def get(self, url: str, *, timeout_seconds: float):
                self.calls += 1
                return {
                    "data": [{
                        "pool": "pool-cache-detail",
                        "project": "P",
                        "poolMeta": "Pool",
                        "symbol": "USDC",
                        "chain": "Base",
                        "apy": 5.0,
                        "tvlUsd": 1000.0,
                        "observed_at": NOW.isoformat(),
                    }]
                }

        http = Http()
        adapter = DeFiLlamaAdapter(
            base_url="https://example.invalid",
            endpoint="/pools",
            http_client=http,
            cache=InMemoryCache(),
            clock=MutableClock(),
        )

        live = adapter.read(mode="live")
        detail = adapter.read_for_detail(mode="live")

        self.assertEqual(http.calls, 1)
        self.assertEqual(live.items[0].opportunity_id, detail.items[0].opportunity_id)
        self.assertEqual(detail.data_source.mode, "cache")
        self.assertFalse(detail.data_source.is_stale)

    def test_market_data_rejeita_payload_sem_oportunidade(self) -> None:
        with self.assertRaises(MarketDataError):
            DeFiLlamaAdapter(fallback=lambda: {"data": []}).read(mode="fallback")

    def test_market_data_nao_exibe_uuid_como_nome_do_pool(self) -> None:
        class Http:
            def get(self, url: str, *, timeout_seconds: float):
                return {
                    "data": [{
                        "pool": "747c1d2a-c668-4682-b9f9-296708a3dd90",
                        "project": "lido",
                        "symbol": "STETH",
                        "chain": "Ethereum",
                        "apy": 2.2,
                        "tvlUsd": 1000,
                        "observed_at": NOW.isoformat(),
                    }]
                }

        adapter = DeFiLlamaAdapter(
            base_url="https://example.invalid",
            endpoint="markets",
            http_client=Http(),
            clock=MutableClock(),
        )
        item = adapter.read(mode="live").items[0]
        self.assertEqual(item.opportunity_id, "747c1d2a-c668-4682-b9f9-296708a3dd90")
        self.assertEqual(item.pool, "STETH pool")

    def test_market_data_prioriza_nome_humano_do_pool(self) -> None:
        class Http:
            def get(self, url: str, *, timeout_seconds: float):
                return {
                    "data": [{
                        "pool": "747c1d2a-c668-4682-b9f9-296708a3dd90",
                        "project": "maple",
                        "poolMeta": "Syrup USDC",
                        "symbol": "USDC",
                        "chain": "Ethereum",
                        "apy": 5.1,
                        "tvlUsd": 1000,
                        "observed_at": NOW.isoformat(),
                    }]
                }

        adapter = DeFiLlamaAdapter(
            base_url="https://example.invalid",
            endpoint="markets",
            http_client=Http(),
            clock=MutableClock(),
        )
        self.assertEqual(adapter.read(mode="live").items[0].pool, "Syrup USDC")

    def test_detalhe_enriquece_historico_7d_30d_e_ptax_sem_sintetizar(self) -> None:
        class Http:
            def get(self, url: str, *, timeout_seconds: float):
                if "/chart/pool-1" in url:
                    return {
                        "data": [
                            {
                                "timestamp": "2026-07-03T12:00:00Z",
                                "apy": 4.0,
                                "tvlUsd": 900.0,
                            },
                            {
                                "timestamp": "2026-07-26T12:00:00Z",
                                "apy": 5.0,
                                "tvlUsd": 1000.0,
                            },
                            {
                                "timestamp": "2026-08-02T12:00:00Z",
                                "apy": 7.0,
                                "tvlUsd": 1100.0,
                            },
                        ]
                    }
                assert "CotacaoDolarPeriodo" in url
                return {
                    "value": [
                        {
                            "cotacaoCompra": 5.20,
                            "cotacaoVenda": 5.22,
                            "dataHoraCotacao": "2026-08-01 13:00:00.000",
                            "tipoBoletim": "Fechamento",
                        }
                    ]
                }

        enricher = MarketDetailEnricher(
            defillama_base_url="https://yields.llama.fi",
            fx_base_url="https://olinda.bcb.gov.br/ptax",
            http_client=Http(),
            clock=MutableClock(),
        )
        detail = enricher.enrich(
            opportunity_id="pool-1", tvl_usd=1000.0, mode="live"
        )

        history = detail["history"]
        self.assertEqual(history["status"], "available")
        self.assertEqual(history["windows"]["7d"]["apy"]["average"], 6.0)
        self.assertEqual(history["windows"]["7d"]["apy"]["trend"], "up")
        self.assertEqual(
            history["windows"]["7d"]["tvl_usd"]["change_percent"], 10.0
        )
        self.assertEqual(history["windows"]["30d"]["point_count"], 3)
        display = detail["currency_display"]
        self.assertEqual(display["primary"], {"value": 5210.0, "currency": "BRL"})
        self.assertEqual(display["secondary"], {"value": 1000.0, "currency": "USD"})
        self.assertEqual(display["fx"]["rate"], 5.21)
        self.assertEqual(display["fx"]["observed_at"], "2026-08-01T16:00:00Z")

    def test_detalhe_fail_soft_usa_cache_identificado_e_depois_indisponivel(self) -> None:
        class Http:
            fail = False

            def get(self, url: str, *, timeout_seconds: float):
                if self.fail:
                    raise OSError("offline")
                if "/chart/" in url:
                    return {
                        "data": [{
                            "timestamp": NOW.isoformat(),
                            "apy": 5.0,
                            "tvlUsd": 1000.0,
                        }]
                    }
                return {
                    "value": [{
                        "cotacaoCompra": 5.0,
                        "cotacaoVenda": 5.2,
                        "dataHoraCotacao": "2026-08-02 09:00:00.000",
                    }]
                }

        clock = MutableClock()
        http = Http()
        enricher = MarketDetailEnricher(
            defillama_base_url="https://yields.llama.fi",
            fx_base_url="https://olinda.bcb.gov.br/ptax",
            http_client=http,
            clock=clock,
            history_ttl_seconds=300,
            fx_ttl_seconds=300,
        )
        enricher.enrich(opportunity_id="p", tvl_usd=100, mode="live")
        clock.value = NOW + timedelta(seconds=301)
        http.fail = True
        cached = enricher.enrich(opportunity_id="p", tvl_usd=100, mode="live")
        self.assertEqual(cached["history"]["data_source"]["mode"], "cache")
        self.assertTrue(cached["history"]["data_source"]["is_stale"])
        self.assertEqual(cached["currency_display"]["fx"]["mode"], "cache")
        self.assertTrue(cached["currency_display"]["fx"]["is_stale"])

        empty = MarketDetailEnricher(
            defillama_base_url="https://yields.llama.fi",
            fx_base_url="https://olinda.bcb.gov.br/ptax",
            http_client=http,
            clock=clock,
        ).enrich(opportunity_id="other", tvl_usd=100, mode="live")
        self.assertEqual(empty["history"]["status"], "unavailable")
        self.assertEqual(empty["currency_display"]["primary"]["currency"], "USD")
        self.assertIsNone(empty["currency_display"]["secondary"])

    def test_listagem_reutiliza_uma_unica_cotacao_ptax(self) -> None:
        class Http:
            calls = 0

            def get(self, url: str, *, timeout_seconds: float):
                self.calls += 1
                return {
                    "value": [{
                        "cotacaoCompra": 5.0,
                        "cotacaoVenda": 5.2,
                        "dataHoraCotacao": "2026-08-02 09:00:00.000",
                    }]
                }

        http = Http()
        enricher = MarketDetailEnricher(
            defillama_base_url=None,
            fx_base_url="https://olinda.bcb.gov.br/ptax",
            http_client=http,
            clock=MutableClock(),
        )
        displays = enricher.currency_displays([100.0, 200.0, 300.0], mode="live")

        self.assertEqual(http.calls, 1)
        self.assertEqual([item["primary"]["value"] for item in displays], [510.0, 1020.0, 1530.0])
        self.assertTrue(all(item["secondary"]["currency"] == "USD" for item in displays))


class SimulationAndConversationTests(unittest.TestCase):
    def test_simulacao_gera_30_180_365_sem_execucao(self) -> None:
        service = SimulationService(AssumptionFixtureFormula(), id_factory=lambda: "sim-1", clock=lambda: NOW)
        result = service.simulate({
            "opportunity_id": "pool-1",
            "amount": "1000",
            "asset": "USDC",
            "apy": {"value": 5.2, "unit": "percent_annualized"},
            "horizons_days": [30, 180, 365],
            "data_source": {"source": "defillama", "mode": "test", "is_stale": True},
        })
        payload = result.to_dict()
        self.assertEqual([item.horizon_days for item in result.scenarios], [30, 180, 365])
        self.assertTrue(all(item.idle_stablecoin_value == Decimal("1000") for item in result.scenarios))
        self.assertFalse(result.execution_supported)
        self.assertFalse(payload["execution_supported"])
        self.assertIn("formula_version", payload)
        self.assertTrue(payload["assumptions"])
        self.assertIn("retorno", payload["disclaimer"].lower())
        self.assertTrue(payload["data_source"]["is_stale"])

    def test_simulacao_rejeita_horizonte_invalido_sem_cenário_parcial(self) -> None:
        service = SimulationService(AssumptionFixtureFormula())
        with self.assertRaisesRegex(Exception, "horizonte|horizons"):
            service.simulate({"opportunity_id": "p", "amount": 1, "asset": "USDC", "apy": 5, "horizons_days": [30, 90]})

    def _authenticated_conversation(self) -> tuple[IdentityService, str, Consent]:
        identity, _, sink = make_identity()
        challenge = identity.request_otp("maria@example.com", "simulated")
        auth = identity.verify_otp(challenge.challenge_id, sink.code_for(challenge.challenge_id) or "")
        consent = Consent("conversation", "granted", "consent-v1", NOW)
        return identity, auth.session.access_token, consent

    def test_aura_core_llm_fallback_e_disclaimer(self) -> None:
        identity, token, consent = self._authenticated_conversation()
        conversation = ConversationService(
            identity=identity,
            llm=UnavailableLlm(),
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("be009"),
        )
        created = conversation.create_conversation(token, "simulated", consent, request_id="req-conv", correlation_id="cor-conv")
        response = conversation.send_message(token, created.conversation.conversation_id, MessageRequest("olá Aura", "simulated", consent), request_id="req-msg")
        assistant = response.assistant_message
        self.assertEqual(assistant.payload["kind"], "educational_fallback")
        self.assertTrue(assistant.payload["fallback_used"])
        self.assertEqual(assistant.payload["llm"]["fallback"], "faq")
        self.assertFalse(assistant.payload["llm"]["llm_available"])
        self.assertEqual(assistant.payload["llm"]["service_status"], "unavailable")
        self.assertEqual(response.metadata["failure_code"], "LLM_UNAVAILABLE")
        self.assertIn("retorno", assistant.disclaimer.lower())
        self.assertEqual(assistant.request_id, "req-msg")
        self.assertEqual(assistant.correlation_id, created.conversation.correlation_id)

    def test_explain_compare_e_cash_and_carry_degradam_sem_exigir_policy(self) -> None:
        identity, token, consent = self._authenticated_conversation()
        service = ConversationService(
            identity=identity,
            llm=UnavailableLlm(),
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("educational-fallback"),
        )
        created = service.create_conversation(token, "simulated", consent)

        for prompt, expected in (
            ("Explique o risco desta pool", "contrato inteligente"),
            ("Compare as duas alternativas", "apy observado"),
            ("Como funciona cash-and-carry?", "derivativos"),
        ):
            response = service.send_message(
                token,
                created.conversation.conversation_id,
                MessageRequest(prompt, "simulated", consent),
            )
            payload = response.assistant_message.payload
            self.assertEqual(payload["kind"], "educational_fallback")
            self.assertIn(expected, payload["text"].casefold())
            self.assertNotIn("política de elegibilidade", payload["text"].casefold())
            self.assertEqual(payload["llm"]["service_status"], "unavailable")

    def test_simulacao_sem_inputs_retorna_requisitos_sem_culpar_llm(self) -> None:
        identity, token, consent = self._authenticated_conversation()
        service = ConversationService(
            identity=identity,
            simulation=SimulationService(AssumptionFixtureFormula()),
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("simulation-input"),
        )
        created = service.create_conversation(token, "simulated", consent)
        response = service.send_message(
            token,
            created.conversation.conversation_id,
            MessageRequest("Quero simular", "simulated", consent, action="simulate"),
        )
        payload = response.assistant_message.payload
        self.assertEqual(payload["kind"], "simulation_input_required")
        self.assertEqual(payload["llm"]["service_status"], "not_required")
        self.assertEqual(payload["required_inputs"], ["opportunity_id", "amount", "asset", "horizons_days"])

    def test_external_message_id_reenvia_par_existente_sem_duplicar(self) -> None:
        class CountingProvider:
            def __init__(self):
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                return LlmResult("Resposta educativa.", mode="provider", provider="claude")

        identity, token, consent = self._authenticated_conversation()
        provider = CountingProvider()
        service = ConversationService(
            identity=identity,
            llm=provider,
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("idempotent-message"),
        )
        created = service.create_conversation(token, "simulated", consent)
        request = MessageRequest(
            "Explique esta oportunidade",
            "simulated",
            consent,
            external_message_id="ios-message-uuid-1",
        )
        first = service.send_message(token, created.conversation.conversation_id, request)
        replay = service.send_message(token, created.conversation.conversation_id, request)
        stored = service.get_conversation(token, created.conversation.conversation_id)

        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(stored.conversation.messages), 2)
        self.assertEqual(first.user_message.message_id, replay.user_message.message_id)
        self.assertEqual(first.assistant_message.message_id, replay.assistant_message.message_id)
        self.assertTrue(replay.metadata["idempotent_replay"])

    def test_provider_output_requesting_secrets_is_replaced_by_safe_faq(self) -> None:
        class UnsafeProvider:
            def complete(self, request):
                return LlmResult(
                    "Envie sua seed phrase e assine a transação para continuar.",
                    mode="provider",
                    provider="claude",
                    model="provider-test",
                )

        identity, token, consent = self._authenticated_conversation()
        conversation = ConversationService(
            identity=identity,
            llm=UnsafeProvider(),
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("provider-output"),
        )
        created = conversation.create_conversation(token, "simulated", consent)
        response = conversation.send_message(
            token,
            created.conversation.conversation_id,
            MessageRequest("Como começo?", "simulated", consent),
        )

        text = response.assistant_message.payload["text"].casefold()
        self.assertNotIn("seed phrase", text)
        self.assertNotIn("assine a transação", text)
        self.assertTrue(response.assistant_message.payload["fallback_used"])

    def test_hub_sends_prior_context_only_when_memory_is_granted(self) -> None:
        class CapturingProvider:
            def __init__(self):
                self.requests = []

            def complete(self, request):
                self.requests.append(request)
                return LlmResult(
                    "Resposta educativa sem promessa de retorno.",
                    mode="provider",
                    provider="claude",
                    model="provider-test",
                )

        identity, token, _ = self._authenticated_conversation()
        provider = CapturingProvider()
        memory_consent = Consent(
            "conversation", "granted", "consent-v1", NOW, memory=True
        )
        conversation = ConversationService(
            identity=identity,
            llm=provider,
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("memory-context"),
        )
        created = conversation.create_conversation(
            token, "simulated", memory_consent
        )
        conversation.send_message(
            token,
            created.conversation.conversation_id,
            MessageRequest("Primeira pergunta", "simulated", memory_consent),
        )
        conversation.send_message(
            token,
            created.conversation.conversation_id,
            MessageRequest("Continue", "simulated", memory_consent),
        )

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(len(provider.requests[0].context), 0)
        self.assertEqual(
            [item["role"] for item in provider.requests[1].context],
            ["user", "assistant"],
        )

    def test_hub_resumes_same_account_context_in_another_channel(self) -> None:
        identity, token, _ = self._authenticated_conversation()
        consent = Consent(
            "conversation", "granted", "consent-v1", NOW, memory=True
        )
        conversation = ConversationService(
            identity=identity,
            clock=lambda: NOW,
            id_factory=DeterministicIdFactory("cross-channel"),
        )
        first = conversation.create_conversation(
            token, "simulated", consent
        )
        conversation.send_message(
            token,
            first.conversation.conversation_id,
            MessageRequest("Guarde este contexto", "simulated", consent),
        )

        resumed = conversation.create_conversation(token, "ios_app", consent)

        self.assertEqual(
            resumed.conversation.conversation_id,
            first.conversation.conversation_id,
        )
        self.assertEqual(resumed.conversation.channel.name, "ios_app")
        self.assertEqual(len(resumed.conversation.messages), 2)


class SimulatedChannelTests(unittest.TestCase):
    def _response(self, request_id: str, correlation_id: str, external_id: str) -> MessageResponse:
        channel = ChannelContext.from_value("simulated", external_message_id=external_id)
        consent = Consent("conversation", "granted", "consent-v1", NOW)
        session = SessionSnapshot("ses-1", NOW, NOW + timedelta(minutes=30))

        def envelope(kind: str) -> MessageEnvelope:
            return MessageEnvelope(
                "1.0", f"msg-{kind}", kind, NOW, request_id, correlation_id,
                {"account_id": "acc-1", "subject_type": "account"}, session,
                channel, consent, {"text": kind},
                "Apoio à decisão; não garante retorno e não executa alocações.",
                AuditMetadata("hub", "hub", correlation_id),
            )

        return MessageResponse(envelope("user_message"), envelope("assistant_message"),
                               type("Meta", (), {"to_dict": lambda self: {}})())

    def test_adapter_simulado_delega_preserva_contexto_e_redige_token(self) -> None:
        class Core:
            def __init__(self) -> None:
                self.received = None

            def handle_message(self, access_token, conversation_id, request, **kwargs):
                self.received = (access_token, conversation_id, request, kwargs)
                return self_response

        core = Core()
        self_response = self._response("req_fixture_001", "cor_fixture_001", "ext-1")
        adapter = SimulatedChannelAdapter(core, deterministic=True)
        transport = SimulatedTransportMessage(
            "secret-token", "cnv-1", "olá", {"purpose": "conversation", "status": "granted", "policy_version": "v1"},
            request_id="req_fixture_001", correlation_id="cor_fixture_001", external_message_id="ext-1",
        )
        result = adapter.receive(transport)
        self.assertIs(result, self_response)
        self.assertEqual(core.received[0], "secret-token")
        self.assertEqual(core.received[2].channel.name, "simulated")
        self.assertEqual(core.received[2].external_message_id, "ext-1")
        self.assertNotIn("access_token", transport.to_dict())

    def test_adapter_simulado_rejeita_wallet_e_canal_real(self) -> None:
        class Core:
            def handle_message(self, *args, **kwargs):
                raise AssertionError("não deve chamar o core")

        adapter = SimulatedChannelAdapter(Core())
        with self.assertRaises(SimulatedChannelInputError):
            SimulatedTransportMessage.from_mapping({
                "access_token": "x", "conversation_id": "c", "text": "x", "channel": "simulated",
                "consent": {}, "wallet_address": "0x-sensitive",
            })
        with self.assertRaises(UnsupportedChannelError):
            adapter.receive({
                "access_token": "x", "conversation_id": "c", "text": "x", "channel": "web_widget",
                "consent": {"purpose": "conversation", "status": "granted", "policy_version": "v1"},
            })


class AlertTests(unittest.TestCase):
    def setUp(self) -> None:
        source = AlertDataSource("defillama", "test", NOW, NOW, True, freshness_note="fixture stale")
        self.previous = AlertObservation("pool-1", source, apy=5.0, observation_id="obs-1")
        self.current = AlertObservation("pool-1", source, apy=4.0, observation_id="obs-2")
        self.preferences = AlertPreferences(
            enabled_types=frozenset({AlertType.APY_CHANGE}),
            suggested_actions={AlertType.APY_CHANGE: SuggestedAction.SIMULATE},
        )

    def test_alerta_pending_sem_politica_ou_threshold(self) -> None:
        service = AlertService()
        event_policy_missing = service.evaluate_apy_change("acc-1", self.previous, self.current, None)
        self.assertEqual(event_policy_missing.status, AlertResultStatus.PENDING)

        policy = AlertPolicy(version="alert-v1", preferences=self.preferences, apy_change=ApyChangeRule())
        pending = service.evaluate_apy_change("acc-1", self.previous, self.current, policy)
        self.assertEqual(pending.reason_code, "THRESHOLD_NOT_CONFIGURED")

    def test_alerta_dedup_dry_run_stale_e_marcar_lido(self) -> None:
        dedup = InMemoryDeduplicationStore()
        service = AlertService(deduplication=dedup, id_generator=lambda: "alert-1", clock=lambda: NOW)
        policy = AlertPolicy(
            version="alert-v1", preferences=self.preferences,
            apy_change=ApyChangeRule(threshold=0.5, threshold_kind="absolute", direction="decrease"),
        )
        dry = service.evaluate_apy_change("acc-1", self.previous, self.current, policy, dry_run=True)
        self.assertEqual(dry.status, AlertResultStatus.DRY_RUN)
        self.assertTrue(dry.alert.dry_run)
        generated = service.evaluate_apy_change("acc-1", self.previous, self.current, policy)
        self.assertEqual(generated.status, AlertResultStatus.GENERATED)
        self.assertEqual(generated.alert.suggested_action, SuggestedAction.SIMULATE)
        self.assertIn("retorno", generated.alert.disclaimer.lower())
        self.assertTrue(generated.alert.data_source.is_stale)
        self.assertIn("stale", generated.alert.message.lower() if generated.alert.type is AlertType.DATA_STALE else generated.alert.data_source.freshness_note.lower())
        duplicate = service.evaluate_apy_change("acc-1", self.previous, self.current, policy)
        self.assertEqual(duplicate.status, AlertResultStatus.DEDUPLICATED)
        self.assertEqual(generated.alert.mark_read().status, AlertStatus.READ)

    def test_alerta_stale_exige_regra_e_preferencia_e_nao_e_live(self) -> None:
        preferences = AlertPreferences(enabled_types=frozenset({AlertType.DATA_STALE}))
        policy = AlertPolicy(version="alert-v1", preferences=preferences, data_stale=DataStaleRule())
        service = AlertService(id_generator=lambda: "alert-stale")
        result = service.evaluate_data_stale("acc-1", self.current, policy)
        self.assertEqual(result.status, AlertResultStatus.GENERATED)
        self.assertEqual(result.alert.data_source.mode, "test")
        self.assertTrue(result.alert.data_source.is_stale)


if __name__ == "__main__":
    unittest.main()
