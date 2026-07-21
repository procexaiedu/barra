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

    llm_vision_provider: Literal["openrouter"] = "openrouter"
    llm_audio_provider: Literal["openrouter"] = "openrouter"
    openrouter_api_key: str | None = None
    # Os 3 caminhos de TEXTO do agente (chat #1, extracao forcada #2 e judge de AUP #3) rodam SEMPRE
    # no DeepSeek V4 Flash DIRETO (api.deepseek.com) — sem alternativa de provider. Preferido em
    # escala: garante o cache automatico de prefixo (so o endpoint oficial cacheia; o prefixo global
    # byte-identico fica quente -> 98% mais barato no hit) E crava modelo/quant (sem roleta de FP4 do
    # load-balance OpenRouter). `deepseek-v4-flash` = id atual do V4 Flash (os aliases legados
    # `deepseek-chat`/`deepseek-reasoner` saem em 2026-07-24 15:59 UTC). O id cru tem thinking LIGADO
    # por default (doc oficial: "the thinking toggle defaults to enabled") -> criar_chat_deepseek
    # passa `extra_body={"thinking": {"type": "disabled"}}` p/ travar non-thinking (preserva
    # structured output #2/#3 e a temperature 1.3 do chat #1). Vision (Pix OCR) e audio (STT) seguem
    # no OpenRouter/OpenAI — o DeepSeek nao faz imagem/audio.
    deepseek_api_key: str | None = None
    deepseek_model_chat: str = "deepseek-v4-flash"
    # Temperatura do chat #1 (DeepSeek V4 Flash direct). A recomendacao oficial DeepSeek p/ chat/traducao
    # e ~1.3, mas o experimento N-1 de 30/06 (300 pts, corpus real) mostrou 1.3 como CAUSA-RAIZ do garble:
    # baixar p/ 0.7 corta as respostas problematicas 8.7%->2.7% (vazamento de raciocinio 3->0) E as perdas
    # head-to-head 24%->16.7% (win-rate 74.9%->81.7%) — dominante nos dois eixos, sem degradar a voz.
    # So e honrada em modo non-thinking (a factory trava thinking:disabled via extra_body). Escopo: SO o
    # chat #1 — extracao (#2) e judge (#3) chamam sem temperatura (determinismo).
    chat_temperature: float = Field(
        default=0.7,
        ge=0.0,
        description="Temperatura do chat #1 (DeepSeek V4 Flash). 0.7 = melhor ponto medido no exp N-1 30/06 (coerencia + head-to-head); so vale non-thinking.",
    )
    openrouter_model_vision_pix: str | None = None
    # TODO(M5-final): aposentar (sabatina 2026-05-23 §1.3 — STT migrou para OpenAI direto).
    openrouter_model_audio_transcribe: str | None = None
    # Anthropic sobrevive APENAS para o LLM-judge dos evals (EVAL-02; api/evals/) e o preaquecimento
    # dormente — os 3 caminhos de texto do agente ao vivo (chat/extracao/judge de AUP) sao DeepSeek-only.
    anthropic_api_key: str | None = None
    anthropic_modelo_principal: str = "claude-sonnet-4-6"
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

    # thinking/effort: parametros do ChatAnthropic (so os evals usam).
    anthropic_thinking: Literal["enabled", "disabled"] = "disabled"
    anthropic_effort: Literal["low", "medium", "high"] = "low"
    # Teto de tokens da resposta — compartilhado por TODAS as factories de chat (DeepSeek e o
    # Anthropic dos evals). Guard-rail (~1024): tom e tamanho vem da persona, nao deste limite.
    anthropic_max_tokens: int = 1024

    # Fonte unica do alvo de custo por turno (CUSTO-06). Antes o numero estava duplicado em
    # comentarios/help de core/metrics.py, agente/nos/llm.py e _custo.py; agora todos apontam
    # para este campo. Recalibrado p/ DeepSeek V4 Flash direto (com cache automatico): o turno custa
    # ~R$0,005-0,01; 0,03 da folga p/ turnos cold-cache (extracao+judge releem o prefixo) sem ruido,
    # ~4x mais apertado que o alvo antigo do Sonnet (0,12).
    custo_alvo_brl: float = Field(
        default=0.03,
        gt=0.0,
        description="Alvo de custo estimado por turno do agente em BRL (DeepSeek V4 Flash com cache; 03 §4.2).",
    )

    # Cotacao USD->BRL p/ a metrica AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta em settings.custo_alvo_brl).
    # Reajustar por settings em vez de hardcoded p/ nao requerer deploy a cada flutuacao cambial.
    usd_brl_cotacao: float = Field(
        default=5.50,
        gt=0.0,
        description="Cotacao USD->BRL usada p/ converter o custo estimado do turno do agente.",
    )

    forcar_extracao_por_turno: bool = Field(
        default=True,
        description="Fallback deterministico (#2): quando o LLM encerra o turno sem chamar registrar_extracao, forca 1 chamada (tool_choice) antes de fechar o turno, garantindo que a FSM nao defase. Custa 1 request extra so nos turnos onde o modelo esqueceu. False = comportamento dependente da boa vontade do LLM (kill-switch sem deploy).",
    )
    # Reducao de custo: a extracao forcada e nota interna estruturada — nao precisa da persona/regras/
    # FAQ. Quando ON, a chamada FORCADA de registrar_extracao roteia p/ uma janela MINIMA (sem o
    # SystemMessage geral), em vez do prefixo inteiro; sempre no DeepSeek V4 Flash direto (igual ao
    # chat). NAO afeta o caminho normal (quando o LLM extrai sozinho no loop). thinking travado em
    # disabled (extra_body) nao corrompe o structured output da extracao (tool_choice).
    extracao_no_modelo_barato: bool = Field(
        default=True,
        description="Roteia a chamada FORCADA de registrar_extracao p/ uma janela minima (sem o prefixo geral), em vez do prefixo inteiro. Sempre DeepSeek V4 Flash. False = usa o prefixo inteiro (kill-switch sem deploy).",
    )
    # Auto-reoferta (#1/#2 follow-up): quando a extracao (forcada/inline) erra RECUPERAVEL
    # (ConflitoAgenda/AntecedenciaInsuficiente/ForaDisponibilidade — qualquer ToolMessage status=error
    # da reserva, ver _extracao_recente_errou) ao criar o bloqueio previo, a IA reoferta UM horario
    # alternativo em vez de fechar o turno MUDO. Volta ao proprio no llm (one-shot via
    # _reoferta_tentada) p/ o modelo ver o erro no ToolMessage e reofertar; se a reoferta tambem
    # errar, fecha mudo. Default ON desde a validacao ao vivo (A/B DeepSeek 2026-06-25, caso interno
    # sub-buffer): OFF silenciava o lead no turno do fechamento; ON reoferta o horario_minimo e
    # conduz ate Aguardando_confirmacao. Kill-switch sem deploy. False = comportamento antigo (mute).
    reoferta_automatica_habilitada: bool = Field(
        default=True,
        description="Liga a auto-reoferta de horario quando a extracao erra recuperavel (ConflitoAgenda/AntecedenciaInsuficiente/ForaDisponibilidade) ao reservar o slot, em vez de fechar o turno mudo. Volta ao no llm (one-shot) p/ o modelo reofertar. Default ON (validado ao vivo 2026-06-25). False = comportamento antigo (mute).",
    )
    # Output-guard de saida antes da bolha (AGENTE-OG / ADR 0016).
    output_guard_habilitado: bool = Field(
        default=True,
        description="Liga o no output_guard (scan deterministico + LLM-judge de AUP) antes do despacho da bolha. False desliga o no inteiro (bolha sai como hoje) — kill-switch sem deploy.",
    )
    output_guard_judge_habilitado: bool = Field(
        default=True,
        description="Liga a Etapa 2 (LLM-judge de AUP vinculante) do output_guard. False roda so a Etapa 1 (scan deterministico barato), util se o judge nao-calibrado causar over-refusal. ATENCAO: a Etapa 1 so cobre ia_self/system/outro_cliente/raciocinio -- AUP DURA (ato com menor/sem consentimento/ilegal) e a promessa que revela a farsa NAO tem piso deterministico, sao 100% Etapa 2; com False essas classes ficam SEM barreira de saida (a rede final _saida_guard tambem nao cobre AUP). Desligue apenas pontualmente por over-refusal calibrado, nunca como config permanente em prod. Falha de infra do judge -> default seguro (bloqueia+escala), nunca configuravel p/ passar.",
    )
    output_guard_regen_habilitado: bool = Field(
        default=True,
        description="Liga a regeneracao one-shot do output_guard (producao assistida): leak deterministico no TEXTO, bolha repetida ou turno 100%-raciocinio -> re-gera a resposta 1x com feedback antes de cair no handoff/mudo. False = comportamento antigo (bloqueia/handoff direto) — kill-switch sem deploy.",
    )
    output_guard_repeticao_habilitada: bool = Field(
        default=True,
        description="Liga o detector deterministico de repeticao do output_guard: bolha do turno quase identica a uma bolha recente da propria IA (rastro de papagaio). Detectou -> regenera (se regen ligada); persistiu -> dropa a bolha repetida (silencio > papagaio), sem handoff.",
    )
    # O LLM-judge de AUP (#3, Etapa 2) roda SEMPRE no DeepSeek V4 Flash direto (criar_chat_deepseek):
    # cacheia o prefixo aup_saida.md (o mesmo system antes de CADA bolha) e crava modelo/quant. E
    # classificacao binaria (viola/nao), nao a voz da IA. CAMINHO DE SEGURANCA (ADR 0016): o
    # default-seguro do _julgar_aup vale em qualquer veredito inconclusivo (refusal/truncado/parse).
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
    filtro_travessao_habilitado: bool = Field(
        default=True,
        description="Normaliza o travessao da bolha de saida (camada de voz, nao seguranca): troca o em-dash '—' por virgula (persona <voz>: 'nada de travessao... use virgula'), que o DeepSeek vaza mesmo instruido. Nao toca o hifen ASCII '-' nem o en-dash. Vale para todos os caminhos do enviar_turno. False = bolha sai como o modelo gerou (kill-switch sem deploy).",
    )
    filtro_vocativo_habilitado: bool = Field(
        default=True,
        description="Afina a frequencia do vocativo 'amor/vida' trailing da bolha de saida (camada de voz, nao seguranca): o DeepSeek satura ~2x a taxa do Vendedor humano fora da venda mesmo instruido (estilometria por ato 2026-07-14); sorteio per-bolha calibrado ao corpus remove o vocativo do FIM da bolha nos atos saturados (saudacao/outro), nunca no meio da frase. Vale para todos os caminhos do enviar_turno. False = bolha sai como o modelo gerou (kill-switch sem deploy).",
    )
    envio_delay_humano_habilitado: bool = Field(
        default=False,
        description="Adia o job enviar_turno via _defer_by (camada de voz, nao seguranca) para aproximar a latencia de 1ª resposta do Vendedor humano (corpus: p25≈14s / p50≈40s, cauda log-normal) — hoje o agente responde em ≤~9s de leitura+digitacao, um tell de bot. O grafo/cards/Pix rodam sem atraso; so a bolha ao cliente espera, fora do job_timeout e sem segurar slot. Turno critico nunca adia (pula o cancel-on-new-message; adiar criaria inversao de ordem). False (default) = comportamento atual — kill-switch sem deploy.",
    )
    envio_delay_humano_mediana_s: float = Field(
        default=40.0,
        gt=0.0,
        description="Mediana (s) da latencia-alvo de 1ª resposta quando envio_delay_humano_habilitado. p50 do Vendedor no corpus (mineracao 2026-06-17).",
    )
    envio_delay_humano_sigma: float = Field(
        default=1.55,
        gt=0.0,
        description="Sigma da log-normal do delay humano. 1.55 fixa p25≈14s dada a mediana 40s (corpus).",
    )
    envio_delay_humano_teto_s: int = Field(
        default=90,
        ge=0,
        le=300,
        description="Teto operacional (s) do delay humano — trunca a cauda (p90 humano ≈8min e inviavel p/ venda). Hard bound 300: turno_atual/enviados tem EX=600 e o envio + retries (Retry defer 10*job_try, 3 tries) precisam caber dentro do TTL.",
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

    # Comportamento comercial do agente (grilling 2026-05-23; docs/agente + ADR-0004; dois degraus ADR-0031)
    desconto_degrau_pct: float = Field(
        default=0.125,
        ge=0.0,
        le=1.0,
        description="Degrau intermediário do Desconto de fechamento sobre o Preço de tabela do pacote — primeira contraproposta da escalada de 2 rodadas (ADR-0031).",
    )
    desconto_teto_pct: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Teto do Desconto de fechamento sobre o Preço de tabela do pacote — segunda e última contraproposta da escalada de 2 rodadas (ADR-0031); é o piso duro checado pela guarda de código. 0 desliga o desconto (IA escala todo pedido abaixo da tabela).",
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
    experimento_braco_ativo: bool = Field(
        default=False,
        description=(
            "Liga o trilho do A/B vivo: cada atendimento NASCE carimbado num braço determinístico "
            "e sticky por cliente (md5(cliente_id) % 2 -> 'controle'/'tratamento') em "
            "workers/coordenador.resolver_atendimento. DESLIGADO por default (net-new, sem alavanca "
            "validada): com OFF a coluna experimento_braco nem é referenciada na query, então o "
            "código roda contra o schema pré-migration. Ligar exige a migration "
            "20260623044614_atendimentos_experimento_braco aplicada em prod. Até uma alavanca ser "
            "ligada no braço 'tratamento', controle e tratamento rodam comportamento idêntico (A/A)."
        ),
    )
    agenda_buffer_min: int = Field(
        default=30,
        ge=0,
        description=(
            "Buffer em minutos de preparo/intervalo ao redor de um bloqueio (ADR 0025). Regra DURA "
            "da reservabilidade: gap entre atendimentos (>= buffer, todos os tipos) em "
            "criar_bloqueio_previo + skip de vizinho no proximo_livre; e a antecedência mínima do "
            "externo-Uber (inicio >= now + buffer). Antecedência dos tipos sem deslocamento da "
            "modelo usa agenda_antecedencia_sem_deslocamento_min (emenda ADR 0025, 2026-06-26). "
            "Global."
        ),
    )
    agenda_antecedencia_sem_deslocamento_min: int = Field(
        default=0,
        ge=0,
        description=(
            "Antecedência mínima (min) para reservar quando a modelo NÃO se desloca — interno "
            "e remoto — emenda ADR 0025 (2026-06-26). Casa o "
            "comportamento do vendedor humano (recebe agora com a modelo ociosa) em vez de adiar "
            "por preparo a frio. O gap entre atendimentos segue agenda_buffer_min; só o "
            "externo-Uber mantém a antecedência = agenda_buffer_min. Global."
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
    baixo_score_ativo: bool = Field(
        default=False,
        description="Liga o coletor diário de turnos reprovados ('ruim' no painel /observabilidade) para um dataset de regressão no Langfuse. Observacional: só lê avaliacoes_resposta_ia e escreve dataset, nunca toca o agente ao vivo. Começa OFF; ligue via BAIXO_SCORE_ATIVO=true.",
    )
    baixo_score_janela_dias: int = Field(
        default=7,
        ge=1,
        description="Janela (dias, por avaliado_em) de turnos reprovados que o coletor de baixo score agrega a cada corrida.",
    )
    judge_pos_envio_ativo: bool = Field(
        default=True,
        description="Liga o judge assíncrono PÓS-ENVIO em 100% dos turnos enviados (produção assistida, semana 1): job ARQ que pontua rastro-de-LLM/voz/conduta no DeepSeek e grava em julgamentos_turno + scores no Langfuse. Telemetria dev: nunca pausa a IA nem gera tarefa pro Fernando. Kill-switch via JUDGE_POS_ENVIO_ATIVO=false.",
    )
    digest_semanal_ativo: bool = Field(
        default=True,
        description="Liga o digest diário automático pro Fernando (cron diário de manhã): card no grupo de Coordenação de cada modelo ativa com conversas/fechados/handoffs/incidentes contidos do dia. Kill-switch via DIGEST_SEMANAL_ATIVO=false.",
    )
    rollback_watch_ativo: bool = Field(
        default=True,
        description="Liga o cron diário que monitora os gatilhos objetivos de rollback do piloto (incidentes não-contidos >=2/semana; >=3 conversas/semana com acusação-padrão; gate abortando >20% dos turnos). Só ALERTA (log ERROR + métrica + Sentry, canal dev): nunca pausa a modelo sozinho — o freio é humano. Kill-switch via ROLLBACK_WATCH_ATIVO=false.",
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
    langfuse_obrigatorio: bool = Field(
        default=False,
        description="Trava de boot da observabilidade (piloto de producao assistida): True faz setup_langfuse LEVANTAR RuntimeError quando o tracing nao sobe (chave ausente/auth falhou), derrubando o boot da API/worker em vez de rodar cego — o cenario real e o redeploy git que zera o Env do stack e some com as chaves em silencio. Ligar via Env de PROD no go-live; default False preserva dev/teste (sem chaves) e o comportamento atual.",
    )

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_webhook_token: str = ""
    evolution_instancia: str = Field(
        default="lucia",
        description="Instância Evolution usada por envios de sistema fora da operação por modelo (ex.: relay de alertas). Env EVOLUTION_INSTANCIA (já presente no compose).",
    )
    alertas_webhook_token: str = Field(
        default="",
        description="Token do relay Alertmanager→WhatsApp (POST /alertas/alertmanager?token=...). Vazio = endpoint desligado (403). Segredo: vive no Env do stack, nunca no compose versionado (repo público).",
    )
    alertas_whatsapp_jid: str = Field(
        default="",
        description="Número/JID de DEV que recebe os alertas da stack por WhatsApp (canal dev do piloto — nunca Fernando/modelo). Vazio = relay aceita e só loga. Dado pessoal: vive no Env do stack.",
    )
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
    evolution_view_once: bool = Field(
        default=False,
        description=(
            "Liga o envio de mídia como visualização única (Mídia exclusiva, 01 §6.13). Default "
            "False porque a Evolution v2 self-host oficial NÃO expõe `viewOnce` no /message/sendMedia "
            "(issue #1651 fechada sem impl.; SendMediaDto não tem o campo) — o body sairia com o "
            "campo mas a Evolution o ignoraria. Só ligar quando estiver rodando um build da Evolution "
            "que aceite `viewOnce` no sendMedia (ver docs/adr/ e o patch em docs/evolution-view-once.md)."
        ),
    )
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

    feedback_rig_grupo_jid: str | None = Field(
        default=None,
        description=(
            "JID (`...@g.us`) do grupo de feedback do rig (skill /processar-feedbacks). Quando "
            "setado, o webhook captura as mensagens NÃO-fromMe desse grupo (comentário/áudio/print "
            "do Fernando) e emite um inbox no Langfuse (`feedback_rig_inbox`), sem tocar o fluxo "
            "de cliente — é a ingestão automática. Default None = desligado. Ferramenta de DEV: "
            "aponte para o grupo de feedback numa instância de teste, nunca para um grupo real."
        ),
    )

    feedback_rig_ack: bool = Field(
        default=False,
        description=(
            "Liga o ACK de registro do rig de feedback: ao capturar uma mensagem com substância no "
            "grupo `feedback_rig_grupo_jid`, agenda (debounce ~2 min, coalesce por grupo) uma resposta "
            "curta citando a mensagem — o Fernando/Rossi vê que o feedback foi registrado. Best-effort, "
            "não persiste em envios_evolution. Default False. Só faz efeito com `feedback_rig_grupo_jid` setado."
        ),
    )

    github_webhook_secret: str | None = Field(
        default=None,
        description=(
            "Secret HMAC do webhook do GitHub (`/webhook/github`, evento `issues`). Quando setado, o "
            "fecho de uma issue que carrega o rodapé-máquina `feedback-rig` dispara o aviso de "
            "'desenvolvido' citando a mensagem original do Rossi no grupo de feedback. Default None = "
            "webhook desligado (eventos ignorados). Ferramenta de DEV, fora do fluxo de cliente."
        ),
    )

    sentry_dsn: str | None = None

    @model_validator(mode="after")
    def _validar_providers_llm(self) -> "Settings":
        """Falha cedo (no boot) quando o DeepSeek-direct (chat #1, extracao #2, judge #3 — todos
        DeepSeek-only) nao tem a chave, em vez de estourar 500 no meio do turno."""
        if not self.deepseek_api_key:
            raise ValueError(
                "os caminhos de texto do agente sao DeepSeek-only e exigem deepseek_api_key setado"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
