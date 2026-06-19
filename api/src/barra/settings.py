import json
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ambiente: Literal["desenvolvimento", "teste", "producao"] = "desenvolvimento"
    log_level: str = "INFO"

    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str | None = None

    redis_url: str = ""

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket_media: str = "barra-media"
    minio_use_ssl: bool = False

    @field_validator("minio_endpoint", mode="before")
    @classmethod
    def normalizar_minio_endpoint(cls, v: object) -> str:
        """MinIO exige host[:porta] sem esquema e sem path (evita ValueError no client)."""
        if v is None:
            return "localhost:9000"
        s = str(v).strip()
        if not s:
            return "localhost:9000"
        if "://" in s:
            parsed = urlparse(s)
            host = parsed.hostname or ""
            if not host:
                return "localhost:9000"
            if parsed.port:
                return f"{host}:{parsed.port}"
            return host
        if "/" in s:
            s = s.split("/", 1)[0].strip()
        return s

    @model_validator(mode="before")
    @classmethod
    def _carregar_secrets_de_arquivo(cls, data: object) -> object:
        """Padrão *_FILE (Docker/Swarm secret): se `<CAMPO>_FILE` aponta para um arquivo
        existente, seu conteúdo (sem espaços nas pontas) vence o valor inline. Mantém o
        segredo fora do env e do git — em prod a chave vive só no Swarm secret montado em
        /run/secrets/minio_secret_key, lido via MINIO_SECRET_KEY_FILE (DEPLOY-01)."""
        if isinstance(data, dict):
            for campo in ("minio_secret_key",):
                caminho = os.environ.get(f"{campo.upper()}_FILE")
                if caminho and Path(caminho).is_file():
                    data[campo] = Path(caminho).read_text(encoding="utf-8").strip()
        return data

    llm_chat_provider: Literal["openrouter", "anthropic", "deepseek"] = "deepseek"
    llm_vision_provider: Literal["openrouter"] = "openrouter"
    llm_audio_provider: Literal["openrouter"] = "openrouter"
    openrouter_api_key: str | None = None
    openrouter_model_chat: str | None = None
    # Chat #1 DIRETO na API DeepSeek (api.deepseek.com), quando llm_chat_provider=deepseek. Preferido
    # em escala: garante o cache automatico de prefixo (so o endpoint oficial cacheia; o prefixo
    # global byte-identico fica quente -> 98% mais barato no hit) E crava modelo/quant (sem roleta de
    # FP4 do load-balance OpenRouter). `deepseek-chat` = V4 Flash non-thinking (nao precisa de
    # reasoning_off; nomes legados saem em 2026-07-24 -> depois `deepseek-v4-flash` direto).
    deepseek_api_key: str | None = None
    deepseek_model_chat: str = "deepseek-chat"
    # Temperatura do chat #1 (qualquer provider que sirva o chat: deepseek-direct ou openrouter).
    # Recomendacao oficial DeepSeek p/ chat/traducao ~1.3 (vs ~1.0 default). So e honrada em modo
    # non-thinking (deepseek-chat ja e; no OpenRouter exige reasoning OFF, que _criar_chat_principal
    # seta). Escopo: SO o chat #1 — extracao (#2) e judge (#3) chamam sem temperatura (determinismo).
    chat_temperature: float = Field(
        default=1.3,
        ge=0.0,
        description="Temperatura do chat #1 (DeepSeek V4 Flash). 1.3 = recomendacao oficial DeepSeek p/ chat; so vale non-thinking.",
    )
    # Piso de quantizacao do roteamento OpenRouter (provider.quantizations). O deepseek-v4-flash e
    # servido em FP4 (Wafer/DeepInfra), FP8 (~8 provedores) e Unknown por ~18 endpoints; sem piso o
    # load-balance pode cair num FP4 que degrada voz/structured output de forma imprevisivel (e fura
    # o cache, que e por-provedor). ["fp8"] = piso de qualidade COM disponibilidade (8 provedores).
    # Aplicado aos 3 caminhos V4 Flash (chat #1, extracao #2, judge #3). [] reabre tudo (kill-switch).
    openrouter_quantizations: list[str] = Field(
        default_factory=lambda: ["fp8"],
        description="Niveis de quantizacao aceitos no roteamento OpenRouter do V4 Flash. ['fp8'] = piso de qualidade; [] = sem restricao.",
    )
    openrouter_model_vision_pix: str | None = None
    # TODO(M5-final): aposentar (sabatina 2026-05-23 §1.3 — STT migrou para OpenAI direto).
    openrouter_model_audio_transcribe: str | None = None
    anthropic_api_key: str | None = None
    anthropic_modelo_principal: str = "claude-sonnet-4-6"
    anthropic_model_chat: str | None = None
    # Modelo do LLM-judge dos evals (EVAL-02). None -> usa o `anthropic_modelo_principal`, i.e. o
    # MESMO modelo do agente sob teste -> vies de auto-concordancia (self-preference). Apontar p/
    # um modelo diferente (ex. "claude-opus-4-8") mitiga: pesos distintos reduzem o vies. Cross-
    # familia real (GPT/Gemini via OpenRouter) e o alvo final, exige wiring de provider -> P1.
    anthropic_modelo_judge: str | None = None

    # STT do agente (06 §1.3): Whisper direto da OpenAI. Sai do OpenRouter porque o hop
    # extra nao compensa num STT critico de baixa latencia sob o orcamento de 8s (sabatina
    # 2026-05-23 §1.3). Default whisper-1 porque a resposta verbose_json inclui .duration
    # nativamente; gpt-4o-mini-transcribe exigiria calculo local de duracao.
    openai_api_key: str | None = None
    openai_model_audio_transcribe: str = "whisper-1"

    # Chat Anthropic (grilling 2026-05-23; docs/agente/03 §6.1): TTL de cache por bloco +
    # parâmetros do ChatAnthropic. cache_ttl_geral (BP1/BP2) não pode ser mais curto que
    # cache_ttl_modelo (BP3) — a Anthropic exige o TTL mais longo antes do mais curto (03 §1/§5).
    cache_ttl_geral: str = "1h"
    cache_ttl_modelo: str = "1h"
    anthropic_thinking: Literal["enabled", "disabled"] = "disabled"
    anthropic_effort: Literal["low", "medium", "high"] = "low"
    anthropic_max_tokens: int = 1024

    # Fonte unica do alvo de custo por turno (CUSTO-06). Antes o numero estava duplicado em
    # comentarios/help de core/metrics.py, agente/nos/llm.py e _custo.py; agora todos apontam
    # para este campo.
    custo_alvo_brl: float = Field(
        default=0.12,
        gt=0.0,
        description="Alvo de custo estimado por turno do agente em BRL (Sonnet 4.6 com cache; 03 §4.2).",
    )

    # Cotacao USD->BRL p/ a metrica AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta em settings.custo_alvo_brl).
    # Reajustar por settings em vez de hardcoded p/ nao requerer deploy a cada flutuacao cambial.
    usd_brl_cotacao: float = Field(
        default=5.50,
        gt=0.0,
        description="Cotacao USD->BRL usada p/ converter o custo estimado do turno (Sonnet 4.6).",
    )

    # Strict mode em tools (doc oficial Anthropic `strict-tool-use`): grammar-constrained
    # decoding + cache de grammar 24h. Master-switch do strict PER-TOOL: quando True, aplica strict
    # SO as tools de `STRICT_TOOLS` (`agente/ferramentas/__init__.py` — hoje {"escalar"}), nao a
    # todas. O default ANTES era False porque o strict GLOBAL estourava "Schema is too complex"
    # (limite somado em todas as tools strict da request); per-tool no `escalar` (1 enum de
    # roteamento + 2 strings, apos `_sanitizar_para_strict` remover min/maxLength) cabe nos limites
    # e foi VALIDADO contra a API real (2026-05-28: 200 OK, sem 400). `registrar_extracao` (~15
    # campos, muitos union types `X | None`) fica FORA de STRICT_TOOLS ate o schema ser enxugado
    # (limite de 16 union types). Setar False mata o strict sem deploy (kill-switch).
    anthropic_strict_tools: bool = Field(
        default=True,
        description="Master-switch do strict PER-TOOL (STRICT_TOOLS em ferramentas/__init__.py). False desliga.",
    )
    preaquecer_cache_no_startup: bool = Field(
        default=True,
        description="Pre-aquece o prefixo global de cache (tools+BP_GERAL) com 1 request no startup do worker, evitando o burst de cache writes a 2x apos deploy de prompt ou gap > TTL (pesquisa §1.7 / 03 §4.5).",
    )
    forcar_extracao_por_turno: bool = Field(
        default=True,
        description="Fallback deterministico (#2): quando o LLM encerra o turno sem chamar registrar_extracao, forca 1 chamada (tool_choice) antes de fechar o turno, garantindo que a FSM nao defase. Custa 1 request extra so nos turnos onde o modelo esqueceu. False = comportamento dependente da boa vontade do LLM (kill-switch sem deploy).",
    )
    # Reducao de custo (Langfuse 06-2026: ~half das geracoes Sonnet sao a extracao forcada, cada
    # uma relendo ~14,7k tokens de prefixo a 0.1x). A extracao e nota interna estruturada — nao
    # precisa da persona/regras/FAQ nem da voz do Sonnet. Quando ON, a chamada FORCADA de
    # registrar_extracao roteia p/ `extracao_modelo` (Haiku) com prompt minimo (janela sem o
    # SystemMessage geral), em vez do Sonnet com o prefixo inteiro. NAO afeta o caminho normal
    # (quando o LLM extrai sozinho no loop). Default OFF: virar p/ True exige validar paridade da
    # FSM via `make evals` antes (a extracao alimenta transicoes no caminho do dinheiro).
    extracao_no_modelo_barato: bool = Field(
        default=True,
        description="Roteia a chamada FORCADA de registrar_extracao p/ extracao_modelo (barato) com prompt minimo, em vez do Sonnet com prefixo inteiro. Default ON (Haiku) — kill-switch: setar False reverte ao Sonnet. Paridade de FSM via `make evals` ainda nao validada ao vivo (gasta credito).",
    )
    extracao_modelo: str = Field(
        default="claude-haiku-4-5",
        description="Modelo da extracao forcada barata quando extracao_no_modelo_barato=True. Haiku 4.5 (~1/3 do custo do Sonnet); classificacao estruturada, nao a voz da IA. Haiku NAO aceita `effort` -> chat criado com com_effort=False.",
    )
    # Provider da extracao forcada (#2). `deepseek` (default) -> deepseek_model_chat via
    # criar_chat_deepseek (api.deepseek.com direto); `anthropic` -> extracao_modelo (Haiku) via
    # ChatAnthropic; `openrouter` -> openrouter_model_extracao via ChatOpenAI (base_url OpenRouter).
    # Toggle dedicado (nao reusa llm_chat_provider, que e semantico da #1) -> kill-switch por-chamada
    # sem deploy. DeepSeek-direct: ~30x mais barato que Haiku E cacheia o prefixo (system minimo +
    # janela) automaticamente; `deepseek-chat` e non-thinking, nao corrompe o structured output da
    # extracao (tool_choice).
    extracao_provider: Literal["anthropic", "openrouter", "deepseek"] = "deepseek"
    openrouter_model_extracao: str | None = Field(
        default=None,
        description="Id OpenRouter da extracao forcada quando extracao_provider=openrouter. Exige tool-calling forcado confiavel no schema de registrar_extracao (12+ campos nullable).",
    )
    # Output-guard de saida antes da bolha (AGENTE-OG / ADR 0016).
    output_guard_habilitado: bool = Field(
        default=True,
        description="Liga o no output_guard (scan deterministico + LLM-judge de AUP) antes do despacho da bolha. False desliga o no inteiro (bolha sai como hoje) — kill-switch sem deploy.",
    )
    output_guard_judge_habilitado: bool = Field(
        default=True,
        description="Liga a Etapa 2 (LLM-judge de AUP vinculante) do output_guard. False roda so a Etapa 1 (scan deterministico barato), util se o judge nao-calibrado causar over-refusal. Falha de infra do judge -> default seguro (bloqueia+escala), nunca configuravel p/ passar.",
    )
    output_guard_modelo: str = Field(
        default="claude-haiku-4-5",
        description="Modelo do LLM-judge de AUP (Etapa 2). E classificacao binaria (viola/nao), nao a voz da IA -> roda em Haiku 4.5 (1/3 do custo do Sonnet) sem afetar a conversa. Prompt curto (~580 tok < minimo de cache 4096) entao nao ha cache a perder. Haiku NAO aceita `effort` -> o chat e criado com com_effort=False (senao 400). Voltar p/ claude-sonnet-4-6 se o Haiku regredir a precisao do guard.",
    )
    # Provider do judge de AUP (#3). `deepseek` (default) -> deepseek_model_chat via
    # criar_chat_deepseek (cacheia o prefixo aup_saida.md, o mesmo system antes de CADA bolha);
    # `anthropic` -> output_guard_modelo (Haiku) via ChatAnthropic; `openrouter` ->
    # openrouter_model_judge via ChatOpenAI. E CAMINHO DE SEGURANCA (ADR 0016): o default-seguro do
    # _julgar_aup continua valendo em qualquer veredito inconclusivo (refusal/truncado/parse).
    output_guard_provider: Literal["anthropic", "openrouter", "deepseek"] = "deepseek"
    openrouter_model_judge: str | None = Field(
        default=None,
        description="Id OpenRouter do judge de AUP quando output_guard_provider=openrouter. Classificacao binaria com structured output; exige nao recusar conteudo adulto legitimo (senao over-refusal pelo default-seguro).",
    )
    # Rede final de saida no enviar_turno (SEC-OUT-01/SEC-PII-02): cobre tambem os caminhos
    # canned/reengajamento que pulam o no output_guard do grafo.
    envio_guard_habilitado: bool = Field(
        default=True,
        description="Liga a rede final no enviar_turno: bloqueia+escala bolha que admite ser IA (auto-referencia) e redige por eco a PII do cliente (CPF/RG/telefone) — nao a chave Pix da modelo, que nao vem do cliente. False = bolha sai como hoje (kill-switch sem deploy).",
    )
    reincidencia_seguranca_habilitada: bool = Field(
        default=True,
        description="Conta tentativas de disclosure/jailbreak por telefone (cliente) em 24h e escala a Fernando ao atingir o limiar, SEM bloquear o cliente (SEC-JB-02/AUP). False desliga a contagem.",
    )
    filtro_emoji_habilitado: bool = Field(
        default=True,
        description="Normaliza o emoji da bolha de saida (camada de voz, nao seguranca): remove todo glyph fora do whitelist {🥰,😊}, limita a 1 por bolha e seca emoji na cotacao/sondagem/desconto/logistica (espelha a regra seca-da-cotacao-em-diante da persona). Vale para todos os caminhos do enviar_turno. False = bolha sai como o modelo gerou (kill-switch sem deploy).",
    )
    reincidencia_seguranca_limiar: int = Field(
        default=3,
        ge=1,
        description="Nº de tentativas de disclosure/jailbreak do mesmo telefone em 24h que dispara a escalada de reincidencia (1x por janela).",
    )
    eval_online_sample_rate: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="EVAL-11: fracao dos turnos 'ok' amostrados p/ a rubrica online de non_disclosure (deterministica, sem custo de LLM) observada em agente_eval_pass_rate{suite=online_non_disclosure}. 0 desliga.",
    )

    # Comportamento comercial do agente (grilling 2026-05-23; docs/agente + ADR-0004)
    desconto_max_pct: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Teto do Desconto de fechamento sobre o Preço de tabela do programa (ADR-0004). 0 desliga o desconto (IA escala todo pedido abaixo da tabela).",
    )
    reengajamento_ativo: bool = Field(
        default=True,
        description="Liga a reabertura proativa de cliente que sumiu após a cotação. Piloto ligado em 15/06 (docs/agente/07 §4); desligue via REENGAJAMENTO_ATIVO=false.",
    )
    reengajamento_delay_min: int = Field(
        default=45,
        ge=1,
        description=(
            "Minutos de silêncio do cliente após a cotação antes do toque único de reengajamento. "
            "45 calibrado no corpus do Vendedor (corpus.eval_reengajamento): retorno faz platô de "
            "~40min a 2h (~83%) e despenca após 12h; o humano nunca cutuca antes de 40min."
        ),
    )
    agenda_buffer_min: int = Field(
        default=30,
        ge=0,
        description=(
            "Buffer em minutos de preparo/intervalo ao redor de um bloqueio (ADR 0025). Regra DURA "
            "da reservabilidade: antecedência mínima (inicio >= now + buffer) e gap entre "
            "atendimentos (>= buffer) em criar_bloqueio_previo; e a sugestão do próximo slot "
            "adjacente (proximo_livre + horario_minimo) no contexto dinâmico. Global."
        ),
    )
    operacao_hora_inicio: int = Field(
        default=10,
        ge=0,
        le=23,
        description="Hora local de início da operação; reengajamento não dispara fora dela.",
    )
    operacao_hora_fim: int = Field(
        default=2,
        ge=0,
        le=23,
        description="Hora local de fim da operação (pode ser < início, ex.: 10-2h cruza a meia-noite).",
    )
    lembrete_valor_ativo: bool = Field(
        default=True,
        description="Liga o Lembrete de fechamento: cobra o valor_final da modelo no grupo após o fim previsto do atendimento (ADR-0009). Mensagem interna no grupo de 2 pessoas, baixo risco -> default on.",
    )
    lembrete_valor_tolerancia_min: int = Field(
        default=15,
        ge=0,
        description="Minutos após bloqueios.fim antes do 1º lembrete de valor (o atendimento pode esticar).",
    )
    lembrete_valor_intervalo_min: int = Field(
        default=30,
        ge=1,
        description="Minutos entre reenvios do lembrete de valor (e antes de escalar após o máximo de toques).",
    )
    lembrete_valor_max_toques: int = Field(
        default=3,
        ge=1,
        description="Máximo de cards de lembrete de valor antes de escalar para Fernando via handoff.",
    )
    fluxo_drift_ativo: bool = Field(
        default=False,
        description="Liga o sensor semanal de deriva de fluxo conversacional (corpus humano vs. agente). Observacional: só lê conversas (barravips.mensagens) e escreve dataset+score no Langfuse, nunca toca o agente ao vivo. Começa OFF; ligue via FLUXO_DRIFT_ATIVO=true.",
    )
    fluxo_drift_janela_dias: int = Field(
        default=7,
        ge=1,
        description="Janela (dias) de conversas do agente que o sensor de fluxo agrega a cada corrida.",
    )
    pix_deslocamento_valor: Decimal = Field(
        default=Decimal("100.00"),
        description="Valor esperado do Pix de deslocamento, em BRL (06 §2.2/§0 item 6). Comparação é `valor >= esperado`: underpay → em_revisao; valor maior é aceito como validado.",
    )
    # Taxa de cartão default (ADR 0013): cobrada por cima do serviço quando forma_pagamento='cartao'.
    # Snapshot por atendimento em atendimentos.taxa_cartao_snapshot; este e so o DEFAULT da UI/fechamento.
    taxa_cartao_padrao_pct: Decimal = Field(
        default=Decimal("10.00"),
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Percentual default da Taxa de cartão (ADR 0013), cobrado por cima do serviço no cartão. Isentável por atendimento; snapshot fica em atendimentos.taxa_cartao_snapshot.",
    )

    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "barra-vips-dev"

    # Langfuse self-hosted — tracing de PRODUÇÃO (ADR 0019; substituiu o LangSmith). Lido por
    # setup_langfuse; ausência das chaves = tracing langfuse off.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://langfuse.procexai.tech"

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_webhook_token: str = ""
    midia_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        description="Teto de bytes ao baixar mídia da Evolution; download aborta acima disso (defesa DoS).",
    )
    webhook_max_body_bytes: int = Field(
        default=36 * 1024 * 1024,
        description="Teto do corpo do POST /webhook/evolution (Content-Length). Com WEBHOOK_BASE64 a mídia vem inline (base64, ~+33%), então precisa caber midia_max_bytes (25 MiB) inflado + folga de JSON. Acima disso → 413 (defesa DoS de memória).",
    )
    evolution_webhook_callback_url: str | None = Field(
        default=None,
        description="URL pública do nosso /webhook/evolution. Quando definida, é passada à Evolution no POST /instance/create.",
    )
    evolution_grupo_coordenacao_jid: str | None = None
    evolution_fernando_jids: list[str] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cors_origin_regex: str | None = None

    jid_permitido: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Allowlist de TESTE da Fase 1.5: quando não-vazia, o webhook só processa mensagens "
            "cujo remote_jid esteja na lista. Default [] = desligado. Aceita VÁRIOS JIDs (formato "
            "JSON no env) para um teste E2E pinar tanto o grupo do cliente quanto o seu grupo de "
            "Coordenação — senão o comando de fechamento no grupo (`finalizado`/`perdido`) leva "
            "403 na porta. NÃO é defesa de produção — a borda real é token + instância cadastrada "
            "+ UNIQUE evolution_instance_id."
        ),
    )

    @field_validator("jid_permitido", mode="before")
    @classmethod
    def _parse_jid_permitido(cls, v: object) -> object:
        """Parser explícito (o campo é `NoDecode`, então recebe a string crua do env). Aceita:
        vazio → []; lista JSON (`["a","b"]`) → parseada; um único JID cru (compat com o formato
        antigo `JID_PERMITIDO=...@g.us`) → [JID]. Sem isso, `.env`/compose com valor cru viram
        SettingsError."""
        if v is None:
            return []
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                return json.loads(s)
            return [s]
        return v

    reset_teste_instances: list[str] = Field(
        default_factory=list,
        description=(
            "Allowlist de evolution_instance_id que aceitam o comando de TESTE `#reset` no grupo "
            "(zera todo o estado transacional da modelo p/ recomeçar um teste E2E do zero). "
            "Default vazio = desligado. Ferramenta de teste — nunca inclua a instância de uma "
            "modelo real em produção."
        ),
    )

    sentry_dsn: str | None = None

    @property
    def cache_control_anthropic(self) -> bool:
        """True quando o chat #1 roda em Anthropic — único caso em que o `cache_control` ephemeral
        vale. No OpenRouter/DeepSeek ele quebraria o roteamento e é inútil (cache automático do
        provider). Fonte única do predicado: consumido pelo nó llm (bind de tools), pelo
        prepare_context (system/BP_MODELO/BP_JANELA) e pelo preaquecimento do worker."""
        return self.llm_chat_provider == "anthropic"

    @model_validator(mode="after")
    def _validar_providers_llm(self) -> "Settings":
        """Falha cedo (no boot) quando uma chamada aponta p/ OpenRouter sem o id do modelo/chave, ou
        p/ DeepSeek-direct sem a chave — em vez de estourar 500 no meio do turno. Cobre #1 (chat),
        #2 (extracao) e #3 (judge)."""
        alvos = [
            ("llm_chat_provider", "openrouter_model_chat", self.openrouter_model_chat),
            ("extracao_provider", "openrouter_model_extracao", self.openrouter_model_extracao),
            ("output_guard_provider", "openrouter_model_judge", self.openrouter_model_judge),
        ]
        for campo_provider, campo_modelo, valor_modelo in alvos:
            if getattr(self, campo_provider) == "openrouter":
                if not valor_modelo:
                    raise ValueError(f"{campo_provider}=openrouter exige {campo_modelo} setado")
                if not self.openrouter_api_key:
                    raise ValueError(f"{campo_provider}=openrouter exige openrouter_api_key setado")
        for campo_provider in ("llm_chat_provider", "extracao_provider", "output_guard_provider"):
            if getattr(self, campo_provider) == "deepseek" and not self.deepseek_api_key:
                raise ValueError(f"{campo_provider}=deepseek exige deepseek_api_key setado")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
