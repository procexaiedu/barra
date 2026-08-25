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
    # load-balance OpenRouter). `deepseek-v4-flash` = id unico do V4 Flash (os aliases legados
    # `deepseek-chat`/`deepseek-reasoner` foram aposentados em 2026-07-24 15:59 UTC; hoje devolvem
    # HTTP 400). O id NAO fixa snapshot: em 2026-07-31 o provider promoveu o V4 Flash oficial
    # (`DeepSeek-V4-Flash-0731`, mesma arquitetura, post-training novo) atras do MESMO id — nao ha id
    # datado p/ pinar, entao troca de peso chega sem deploy nosso. RECONFIRMADO em 12/08 sondando a
    # API: `GET /models` lista SO `deepseek-v4-flash` e `deepseek-v4-pro`, e tanto `-0731` quanto
    # `-latest` sao rejeitados com HTTP 400 ("supported API model names are..."). Como pinar e
    # impossivel, a defesa e DETECTAR: a resposta traz `system_fingerprint` com build/quantizacao
    # (`fp_a18b46594c_prod0820_fp8_kvcache_20260402`), publicado em `AGENTE_MODELO_FINGERPRINT`
    # (agente/_instrumentar.registrar_fingerprint) e vigiado por `AgenteModeloTrocouDeBuild`.
    # O id cru tem thinking LIGADO
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
    # So e honrada em modo non-thinking (a factory omite a temperatura quando thinking != disabled).
    # Com o default de `deepseek_thinking_chat` em "low" (abaixo), este campo fica DORMENTE no chat #1
    # — volta a valer assim que alguem puser DEEPSEEK_THINKING_CHAT=disabled. Escopo: SO o chat #1 —
    # extracao (#2) e os judges (#3, pos-envio) leem `judge_temperature` (abaixo).
    chat_temperature: float = Field(
        default=0.7,
        ge=0.0,
        description="Temperatura do chat #1 (DeepSeek V4 Flash). 0.7 = melhor ponto medido no exp N-1 30/06 (coerencia + head-to-head); so vale non-thinking (dormente enquanto thinking != disabled).",
    )
    # Temperatura dos caminhos CLASSIFICADORES (nao a voz): extracao forcada #2, judge de AUP #3 e
    # judge pos-envio. Ate 12/08/2026 os tres chamavam a factory SEM o parametro, e o comentario
    # daqui dizia que isso era "determinismo" — era o oposto. Verificado contra a lib instalada
    # (langchain_openai 1.3.2): `ChatOpenAI(temperature=None)` NAO envia o campo, entao valia o
    # default do provider (DeepSeek ~1.0) — a temperatura MAIS ALTA, num gate vinculante que roda
    # em todo turno (loop-massa r3, achado 1: aprovacao com folga no lote e o turno vivo caindo
    # numa cauda <2%). 0.0 nao muda o comportamento pretendido; so para de sortear.
    # ATENCAO: temp 0 desloca a fronteira de decisao do judge (pode ficar sistematicamente mais
    # rigido OU mais frouxo na borda) -> rodar o set de calibracao de kappa antes de considerar
    # fechado. Knob para poder medir a fronteira sem deploy, nunca para "afrouxar o judge".
    judge_temperature: float = Field(
        default=0.0,
        ge=0.0,
        description="Temperatura da extracao forcada (#2) e dos judges (AUP #3, pos-envio). 0.0 = veredito reprodutivel; omitir o parametro (comportamento ate 12/08/2026) deixava o provider em ~1.0.",
    )
    # Teto de tempo POR CHAMADA de LLM (httpx timeout do ChatOpenAI, todas as chamadas da factory:
    # chat #1, regen do guard, extracao #2, judges). Tem de ser ESTRITAMENTE MENOR que
    # `turno_timeout_s` (o teto do grafo inteiro, abaixo): ate 12/08/2026 os dois eram literais
    # 60.0 = 60.0, entao uma chamada pendurada nunca morria DENTRO do grafo — o `asyncio.wait_for`
    # do coordenador estourava primeiro e o turno virava `timeout_grafo` -> handoff terminal, sem
    # bolha, em vez de cair no fallback deterministico que o guard ja tem pronto (loop-massa r3,
    # achado 3). O nó mais caro (output_guard: regen + judge) roda por ULTIMO e herda o que sobrou,
    # entao a folga precisa ser generosa: 40 < 60 deixa ~20s de margem para o resto do turno.
    # ATENCAO: o timeout e por TENTATIVA. A desigualdade so vale porque `max_retries` deixou de ser
    # 2 fixo e passa por `core.llm.tentativas_que_cabem_no_turno` (40/60 -> 0 retentativa); com o 2
    # fixo, um endpoint pendurado custava 3 x 40s e o turno morria por fora do grafo do mesmo jeito.
    # Quem baixar este valor devolve as retentativas automaticamente — nao mexa no par sem ler la.
    llm_timeout_s: float = Field(
        default=40.0,
        gt=0.0,
        description="Timeout HTTP por chamada de LLM (criar_chat_deepseek). DEVE ser < turno_timeout_s, senao a chamada pendurada mata o turno inteiro por fora do grafo (sem fallback).",
    )
    # Teto do TURNO (asyncio.wait_for em volta do graph.ainvoke, workers/coordenador). Estourar
    # aqui e terminal: escalada por exaustao (`timeout_grafo`) + IA pausada, sem bolha ao cliente.
    turno_timeout_s: float = Field(
        default=60.0,
        gt=0.0,
        description="Teto de tempo do grafo por turno (coordenador). Estourar = escalada timeout_grafo + IA pausada; mantenha llm_timeout_s folgadamente abaixo deste valor.",
    )
    # Thinking do DeepSeek SO no chat #1 (no llm + regen do output_guard): "low"/"high"/"max" =
    # reasoning_effort do provider (guides/thinking_mode). Em thinking a temperatura e IGNORADA pelo
    # provider (a factory a omite) e o custo dominante e latencia (tokens de raciocinio ~3x a resposta).
    # Extracao (#2) e judge (#3) NAO leem este campo: thinking corromperia o structured output.
    #
    # Default = "low" desde 11/08/2026 (decisao do dev): o raciocinio passa a fazer parte da conduta
    # de prod E dos rigs, e vira observavel no trace (`core.tracing.resumir_trace_turno` publica o
    # `reasoning_content` no root span). O sinal que embasa: `high` foi descartado 2x por fisica
    # (p95 96,6s contra teto de produto de 60s) e `low` mediu p95 18-25s com qualidade equivalente —
    # medicao PARCIAL (o grid de 50 atendimentos nao fechou o veredito). Reversivel sem deploy de
    # codigo: DEEPSEEK_THINKING_CHAT=disabled no Env volta ao regime non-thinking + temperatura.
    deepseek_thinking_chat: Literal["disabled", "low", "high", "max"] = Field(
        default="low",
        description="Thinking do chat #1 (DeepSeek direct): reasoning_effort low (prod desde 11/08/2026) / high / max, ou disabled p/ voltar ao regime non-thinking+temperatura. Extracao e judge ficam sempre disabled.",
    )
    openrouter_model_vision_pix: str | None = None
    # STT do agente (06 §1.3) — volta ao OpenRouter. O plano antigo (Whisper direto da OpenAI)
    # nunca saiu do papel em prod: o compose jamais passou OPENAI_API_KEY, entao TODO audio de
    # cliente morria em `transcricao_sem_provider` e o cliente ouvia o canned "me manda por
    # escrito" (24/07). O OpenRouter ja tem chave viva (mesma do vision do Pix) e NAO expoe
    # `/audio/transcriptions`: transcricao roda por chat completions com um content part
    # `input_audio` (base64; ogg/opus do WhatsApp aceito). O default NAO mora aqui, e sim no ponto
    # de uso (`media.py:_MODELO_STT_PADRAO`, espelhando `openrouter_model_vision_pix` no pix.py):
    # o compose passa `OPENROUTER_MODEL_AUDIO_TRANSCRIBE=${...}` e, sem a var no Env, o valor chega
    # VAZIO — um default aqui seria sobrescrito por "" e a chamada sairia sem modelo (400).
    openrouter_model_audio_transcribe: str | None = None
    # Teto de tokens da resposta do chat (DeepSeek, unica factory). Guard-rail (~1024): tom e
    # tamanho vem da persona, nao deste limite.
    llm_max_tokens: int = 1024
    # Teto usado NO LUGAR de `llm_max_tokens` quando o chat #1 roda thinking (a factory troca): em
    # thinking o `max_tokens` cobre a saida INTEIRA — os tokens de raciocinio + a fala —, entao o
    # teto de 1024 pensado so p/ a fala vira risco de `finish_reason=length` com a bolha cortada (ou
    # vazia) no meio do raciocinio. 2048 da a folga do raciocinio sem afrouxar o guard-rail de
    # tamanho da FALA, que continua vindo da persona. Nao muda nada em non-thinking.
    llm_max_tokens_thinking: int = 2048

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
    # ATENCAO (auditado 12/08): o compose de prod NAO passa USD_BRL_COTACAO, entao producao roda
    # neste default desde sempre. Toda comparacao de `AGENTE_CUSTO_TURNO_BRL` contra
    # `custo_alvo_brl` (e o alerta `AgenteCustoTurnoAcimaDoAlvo`) esta ancorada num cambio
    # congelado: o vies e silencioso e cresce com a distancia do valor real.
    usd_brl_cotacao: float = Field(
        default=5.50,
        gt=0.0,
        description="Cotacao USD->BRL usada p/ converter o custo estimado do turno do agente.",
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
    # `strict` tool use (Beta) na chamada FORCADA da extracao. Sem ele o schema so e VALIDADO depois
    # que o modelo gerou: campo inventado / enum fora do dominio viram ValidationError e o turno
    # morre no parse. Com ele a grammar do provider impede a geracao invalida.
    #
    # Default ON (decisao do usuario, 13/08/2026). Kill-switch sem deploy: env
    # `EXTRACAO_STRICT_HABILITADA=false`. Ligar troca o endpoint da EXTRACAO (so ela) por
    # `api.deepseek.com/beta`; a medicao de `prompt_cache_hit_tokens`/output tokens la fica p/ o
    # lote de validacao do ciclo 4.
    #
    # So tem efeito com `extracao_no_modelo_barato` ON (o default): e nessa configuracao que a
    # extracao tem chat PROPRIO. Com ela OFF a forcada reusa a instancia do chat #1, e ligar strict
    # arrastaria o caminho quente inteiro para o Beta — exatamente o que nao se quer.
    extracao_strict_habilitada: bool = Field(
        default=True,
        description="Liga o `strict` tool use (Beta) na extracao forcada: schema vira grammar em vez de validacao pos-hoc. Troca o endpoint da extracao p/ api.deepseek.com/beta. Exige extracao_no_modelo_barato=True.",
    )
    # Paralelismo da chamada forcada da extracao (medicao 11/08 em traces reais: extracao 2,56s +
    # chat 2,51s, hoje em SERIE = ~5s por turno). A janela da extracao e a conversa CRUA + ancora +
    # <ja_registrado> e exclui a fala do turno, entao no turno SEM tool call ela ja esta pronta antes
    # de o chat responder: o no `llm` dispara a chamada como asyncio.Task e o no `extrair` a consome.
    # NAO e "dispara e confia": a janela tambem carrega o que o TURNO produziu (`do_turno` em
    # `_janela_para_extracao`) -- ToolMessages do loop ReAct e o par [forcado, ERRO] da 1a extracao na
    # 2a passagem da auto-reoferta. Por isso o `extrair` remonta a janela real e compara com a de
    # origem: igual -> await na Task; diferente -> cancela e chama em SERIE (o comportamento de hoje).
    # Default OFF ate validacao ao vivo (ver o checklist no docstring de `DisparoExtracao`).
    extracao_paralela_habilitada: bool = Field(
        default=False,
        description="Dispara a chamada FORCADA de registrar_extracao em paralelo com o chat (asyncio.Task no no llm, consumida no no extrair) quando a janela da extracao nao depende do que o turno produziu. Divergencia de janela, excecao ou cancelamento -> fallback para a chamada em serie. False = tudo em serie, como hoje (kill-switch sem deploy).",
    )
    # Auto-reoferta (#1/#2 follow-up): quando a extracao (forcada/inline) erra RECUPERAVEL
    # (ConflitoAgenda/AntecedenciaInsuficiente/ForaDisponibilidade — qualquer ToolMessage status=error
    # da reserva, ver _extracao_errou) ao criar o bloqueio previo, a IA reoferta UM horario
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
    # cacheia o prefixo aup_saida.md (o mesmo system em toda chamada) e crava modelo/quant. E
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
    filtro_interrogacao_habilitado: bool = Field(
        default=True,
        description="Devolve o '?' a proposta de confirmacao de horario da bolha de saida (camada de voz, nao seguranca): 'Posso confirmar as 18h' sem o '?' le como promessa de retorno ('eu te confirmo as 18h') e mata o fechamento (incidente #34, 24/07) — o gatilho e estreito (molde posso/podemos/vamos confirmar + horario na bolha). Vale para todos os caminhos do enviar_turno. False = bolha sai como o modelo gerou (kill-switch sem deploy).",
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
    agenda_buffer_externo_min: int = Field(
        default=60,
        ge=0,
        description=(
            "Gap em minutos ao redor de um bloqueio EXTERNO — o compromisso que acontece fora do "
            "local dela (emenda ADR 0025, 2026-08-14). Vale dos DOIS lados do bloqueio externo: "
            "depois (ela voltando da casa do cliente) e antes (ela indo). Substitui o "
            "agenda_buffer_min só quando o tipo do VIZINHO é externo — tipo NULL/desconhecido "
            "segue no agenda_buffer_min, então nada muda para bloqueio que não declara tipo. "
            "60 = 2x o buffer padrão: é a menor folga honesta para uma volta de carro na cidade "
            "sem geocoding (não há distância medida; 45 fingiria uma mediana que ninguém mediu) e "
            "cai na grade de :00/:30 em que a oferta é arredondada. Global."
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
    grupo_financeiro_rotina_ativa: bool = Field(
        default=True,
        description="Liga a rotina diária da manhã do Agente financeiro (spec 0005): UMA mensagem consolidada por Grupo financeiro cobrando as pendências (forma de pagamento, comprovante) e postando o saldo aberto. Grupo sem pendência e sem movimento fica em silêncio. Kill-switch via GRUPO_FINANCEIRO_ROTINA_ATIVA=false.",
    )
    grupo_financeiro_instancia: str = Field(
        default="",
        description="Instância Evolution do número da ProceX — o número do Agente financeiro, o mesmo em todos os Grupos financeiros. Usada pelo cron da manhã E pelo webhook: a modelo é participante do Grupo financeiro e o WhatsApp dela é outra instância apontando para o mesmo webhook, então o evento chega duas vezes e só a entrega da ProceX vale (na entrega dela o `fromMe` se inverte e as falas da modelo virariam eco do agente). VAZIA = rotina da manhã desligada e webhook sem filtro de instância (fail-open); prod deve defini-la.",
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
    evolution_media_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Hosts extras permitidos no download anti-SSRF de mídia inbound, além do host do "
            "evolution_base_url. A Evolution GO entrega a mídia (WEBHOOK_FILES) do MinIO DELA, num "
            "host distinto do base_url (ex.: minioback.procexai.tech) — adicione-o aqui em prod. "
            "Vazio = só o host do base_url é aceito. Aceita lista JSON, CSV ou host único no env."
        ),
    )

    @field_validator("evolution_media_hosts", mode="before")
    @classmethod
    def _parse_evolution_media_hosts(cls, v: object) -> object:
        """Parser tolerante (campo `NoDecode`, recebe a string crua do env), espelhando
        `jid_permitido`: vazio → []; lista JSON (`["a","b"]`) → parseada; senão CSV/host único
        (`a.com,b.com` ou `a.com`) → lista. Sem isso, um valor cru no env viraria SettingsError."""
        if v is None:
            return []
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                return json.loads(s)
            return [h.strip() for h in s.split(",") if h.strip()]
        return v

    evogo_media_bucket: str = Field(
        default="evolution-go",
        description=(
            "Bucket do MinIO onde a Evolution GO deposita a mídia inbound JÁ DECIFRADA, com key "
            "`<evogo_media_prefix><evolution_message_id>.<ext>`. É a ÚNICA porta da mídia recebida "
            "na EvoGo: o webhook dela não traz base64 inline (WEBHOOK_BASE64 é da v2/Baileys) e a "
            "`url` do payload aponta pro CDN cifrado do WhatsApp, inútil sem a mediaKey. Vazio = "
            "fallback desligado (só base64/download, comportamento da v2)."
        ),
    )
    evogo_media_prefix: str = Field(
        default="evolution-go-medias/",
        description="Prefixo das keys de mídia inbound dentro do `evogo_media_bucket`.",
    )
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
            "False porque nenhuma das plataformas OFICIAIS expõe `viewOnce` no envio de mídia: a "
            "Evolution v2 não tem o campo no SendMediaDto (issue #1651 fechada sem impl.) e a EvoGo "
            "não tem no MediaStruct do /send/media — o body sai com o campo e a plataforma o ignora. "
            "Só ligar sobre um build patchado (ver docs/evolution-view-once.md)."
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

    # --- Canário de entrega fim-a-fim (workers/canario.py) ---------------------------------
    # Sonda periódica que fecha o laço Barra → Evolution → WhatsApp → webhook → Barra. Desligado
    # por default (JID + instância vazios): ligar manda mensagem REAL num WhatsApp real.
    canario_jid: str = Field(
        default="",
        description=(
            "Número/JID 1:1 de CONTROLE que recebe a sonda do canário de entrega (ex.: "
            "`5519999999999@s.whatsapp.net` ou só os dígitos). Vazio = canário DESLIGADO. Precisa "
            "ser um número de DEV, nunca cliente ou modelo: o canário manda uma linha inócua por "
            "ciclo e o eco `fromMe` dela vira uma Conversa cliente inerte (direcao='modelo_manual', "
            "sem atendimento, sem turno, sem crédito de LLM) — é justamente essa linha em "
            "`barravips.mensagens` que prova que o WhatsApp entregou de verdade."
        ),
    )
    canario_instance_id: str = Field(
        default="",
        description=(
            "`modelos.evolution_instance_id` de onde a sonda do canário sai (a instância cuja "
            "entrega se quer vigiar — a do piloto). Precisa estar CADASTRADA em `modelos`, senão o "
            "webhook descarta o eco com `unknown_instance` e o canário acusa falha eterna. Vazio = "
            "canário DESLIGADO."
        ),
    )
    canario_intervalo_min: int = Field(
        default=60,
        ge=1,
        le=60,
        description=(
            "Intervalo (min) entre sondas do canário; vira o set de minutos do cron ARQ "
            "(`range(0, 60, N)`), então 60 = uma vez por hora em :00. Teto 60: o canário mede "
            "apagão de dias, não soluço de rede — e cada ciclo é uma mensagem real."
        ),
    )
    canario_prazo_eco_min: int = Field(
        default=10,
        ge=1,
        description=(
            "Prazo (min) para o eco `fromMe` da sonda voltar pelo webhook. Passou disso sem eco = "
            "laço de entrega quebrado → métrica + log ERROR + Telegram. Mantenha bem abaixo do "
            "`canario_intervalo_min` para o veredito de um ciclo fechar antes do próximo."
        ),
    )
    canario_telegram_token: str = Field(
        default="",
        description=(
            "Token do bot do Telegram que recebe o alerta do canário. É o canal FORA da Evolution: "
            "o relay padrão de alerta entrega por WhatsApp via Evolution, então alerta sobre a "
            "Evolution caída não se auto-entrega (apagão 24-27/07). Vazio = só métrica + log. "
            "Segredo: vive no Env do stack, nunca no compose versionado."
        ),
    )
    canario_telegram_chat_id: str = Field(
        default="",
        description=(
            "chat_id do Telegram (DEV) que recebe o alerta do canário. Vazio = só métrica + log."
        ),
    )

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
