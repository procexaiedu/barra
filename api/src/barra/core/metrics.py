"""Metricas Prometheus minimas."""

from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram
    from prometheus_client import generate_latest as _prometheus_generate_latest
except ModuleNotFoundError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    class _Metric:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def labels(self, *_: object) -> "_Metric":
            return self

        def inc(self, *_: object) -> None:
            return None

        def observe(self, *_: object) -> None:
            return None

        def set(self, *_: object) -> None:
            return None

    Counter = Gauge = Histogram = _Metric  # type: ignore[misc,assignment]

    def _generate_latest() -> bytes:
        return b""
else:

    def _generate_latest() -> bytes:
        return _prometheus_generate_latest()


# Observabilidade da observabilidade (piloto de producao assistida): 1 = handler Langfuse ligado,
# 0 = tracing off (chave ausente/auth falhou — provavel Env do stack zerado por redeploy git).
# Alertavel no dashboard; o grito duro no boot e o `langfuse_obrigatorio` (settings).
TRACING_LANGFUSE_LIGADO = Gauge(
    "barra_tracing_langfuse_ligado",
    "Tracing Langfuse ativo neste processo (1=handler ligado, 0=off)",
)

HTTP_REQUESTS = Counter(
    "barra_http_requests_total", "Total de requests", ["route", "method", "status"]
)
HTTP_DURATION = Histogram(
    "barra_http_request_duration_seconds", "Duracao por rota", ["route", "method"]
)
JOBS = Counter("barra_jobs_total", "Jobs executados", ["tipo", "resultado"])
COMANDOS_GRUPO = Counter("barra_comandos_grupo_total", "Comandos do grupo", ["resultado"])
PIX = Counter("barra_pix_total", "Decisoes Pix", ["resultado"])
ENVIOS_EVOLUTION = Counter("barra_envios_evolution_total", "Envios Evolution", ["resultado"])
WEBHOOK_ERRORS = Counter("barra_webhook_errors_total", "Erros de webhook", ["tipo"])
WEBHOOK_DESCARTES = Counter(
    "barra_webhook_descartes_total",
    "Mensagens descartadas de proposito na borda, antes de virar conversa",
    # nome do campo *Message que o parser nao reconheceu (locationMessage, contactMessage, ...)
    # OU o motivo do descarte deliberado: `grupo_nao_coordenacao`.
    ["tipo"],
)
TIMEOUTS = Counter("barra_timeouts_total", "Timeouts aplicados", ["tipo"])
LEMBRETE_VALOR = Counter(
    "barra_lembrete_valor_total",
    "Lembrete de fechamento (ADR-0009): cobranca do valor_final",
    ["acao"],  # enviado | reenviado | escalado | falha
)
REENGAJAMENTO = Counter(
    "barra_reengajamento_total",
    "Reengajamento proativo do cliente apos a cotacao (07 §4.5)",
    ["resultado"],  # enviado | flag_off | sem_alvo
)
FLUXO_DRIFT = Counter(
    "barra_fluxo_drift_total",
    "Sensor de deriva de fluxo conversacional (contabilidade da corrida; JSD vai pro Langfuse)",
    ["origem", "resultado"],  # resultado: ok | flag_off | sem_dado
)

# Metricas do agente LangGraph (ver docs/agente/08-evals.md)

# Buckets de latencia dos caminhos LENTOS do agente (turno, no do grafo, chamada de LLM). Sao
# EXPLICITOS porque o default do prometheus_client termina em 10s: com todo turno acima disso
# caindo no +Inf, `histogram_quantile` devolve o ultimo bucket FINITO e o p95/p99 saturava em 10s.
# Na pratica isso tornava os dois alertas de latencia (`AgenteLatenciaTurnoP95Alta` > 20s e
# `AgenteLatenciaTurnoP99Alta` > 40s, infra/monitoring/alert.rules.yml) impossiveis de disparar --
# um turno de 41,7s (pior caso medido no roteiro de 12/08) era reportado como 10s. O topo vai a
# 120s de proposito: o teto de 60s do `asyncio.wait_for` cobre so o `graph.ainvoke`, e o turno
# medido aqui inclui transcricao de audio e drain, que passam disso.
_BUCKETS_LATENCIA_TURNO = (0.5, 1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, float("inf"))

AGENTE_TURNO_DURACAO = Histogram(
    "agente_turno_duracao_seconds",
    "Duracao por turno (p50/p95/p99); split por tipo_turno p/ nao misturar texto e audio-Whisper (E5)",
    ["modelo", "tipo_turno"],
    buckets=_BUCKETS_LATENCIA_TURNO,
)
# Latencia POR NO do grafo. O turno inteiro ja era medido; o que faltava era saber ONDE o tempo
# vai -- se os 41,7s do pior caso foram prepare_context, um round-trip llm<->tools, a extracao
# forcada ou o judge de AUP. Sem este corte, a unica alavanca contra o teto de 60s e adivinhacao.
AGENTE_NO_DURACAO = Histogram(
    "agente_no_duracao_seconds",
    "Duracao de cada no do grafo LangGraph (prepare_context|intercept_disclosure|llm|tools|"
    "extrair|post_process|output_guard)",
    ["no"],
    buckets=_BUCKETS_LATENCIA_TURNO,
)
# Latencia por CAMINHO de LLM. Os tres caminhos (chat #1, extracao forcada barata, judge de AUP)
# rodam o MESMO modelo -- entao a label `modelo` de AGENTE_TURNO_TOKENS nao os separa e o custo de
# cada um era indistinguivel em Prometheus (so no Langfuse, via `nomear_run`). Isto e o que permite
# responder "o thinking=low se paga?" sem abrir trace a trace: o p95 do chat e o que o cliente
# espera; o do judge e imposto fixo sobre TODA bolha.
AGENTE_LLM_DURACAO = Histogram(
    "agente_llm_duracao_seconds",
    "Duracao de UMA chamada de LLM, por caminho "
    "(chat|extracao|extracao_retry|judge_aup|judge_pos_envio|regen)",
    ["caminho"],
    buckets=_BUCKETS_LATENCIA_TURNO,
)
# Fingerprint do build que de fato respondeu. O DeepSeek NAO oferece snapshot pinavel -- a API
# aceita so os aliases moveis `deepseek-v4-flash`/`-pro` (sondado em 12/08: `-0731` e `-latest`
# sao rejeitados), e o provider ja trocou os pesos atras do mesmo id em 31/07. Como prevenir e
# impossivel, resta DETECTAR: o `system_fingerprint` da resposta carrega build, quantizacao e data
# (`fp_a18b46594c_prod0820_fp8_kvcache_20260402`). Gauge sempre em 1, com o valor na label: uma
# troca de pesos faz nascer uma serie nova, e `count by (fingerprint)` > 1 e o alerta.
AGENTE_MODELO_FINGERPRINT = Gauge(
    "agente_modelo_fingerprint",
    "Sempre 1; a informacao esta nas labels. Serie nova = o provider trocou o build sob o alias",
    ["modelo", "fingerprint"],
)
AGENTE_TURNO_RESULTADO = Counter(
    "agente_turno_resultado_total",
    "Resultado do turno: ok|escalado|exaustao|ia_pausada_skip|lock_busy|transcricao_timeout",
    ["resultado"],
)
# E3 (grilling 2026-05-23): dashboard de tendencia, NAO gate de qualidade.
# bucket=defesa (ataque ativo, desejavel; spike -> alerta) | capacidade (cego a
# alucinacao-sem-escalada, por isso nao gateia o cutover). mapa motivo->bucket vive
# em codigo (deterministico) e o enum de motivo aceito por `escalar` e restrito.
#
# `fase` (ciclo 8) = o ESTADO do atendimento no momento em que o handoff abriu
# (`Novo|Triagem|Qualificado|Aguardando_confirmacao|Confirmado|Em_execucao|Fechado|Perdido`, mais
# `desconhecida` quando o atendimento sumiu entre a decisao e a contagem). Sem ela a serie diz
# quantas escaladas houve e nao diz se elas sao SAUDAVEIS: escalada em `Novo`/`Triagem` e a
# assinatura do handoff indevido — a conversa morre no turno em que ainda era duvida, antes de
# existir venda para proteger (os 4 handoffs do ciclo 7; o caso 1 abriu no turno 1, em `Novo`).
# Escalada em `Aguardando_confirmacao`/`Em_execucao` e o oposto: ha encontro marcado e acordar a
# modelo e o comportamento certo. Alerta proposto:
# `increase(agente_escalada_total{fase=~"Novo|Triagem"}[1h]) > 0` como warning.
# Cardinalidade fechada por enum nos tres eixos (bucket x motivo x fase).
AGENTE_ESCALADA = Counter(
    "agente_escalada_total",
    "Escaladas por bucket/motivo/fase do atendimento (ver docs/agente/08-evals.md 3.2)",
    ["bucket", "motivo", "fase"],
)
# Porta B da escalada: a guarda DETERMINISTICA da extracao (`dominio/atendimentos/service.py`,
# `_escalar_modelo`) abrindo handoff e pausando a IA sem o LLM ter decidido nada. Serie IRMA de
# `agente_escalada_total`, nao a mesma: aquela significa "o LLM chamou `escalar`" e a distincao
# vale dinheiro na leitura — 3 dos 4 handoffs indevidos do ciclo 7 nasceram AQUI e eram invisiveis
# em Prometheus (a metrica sempre viveu na camada do agente e ninguem a espelhou no dominio).
# `motivo` e fechado pelo mapping local de `_escalar_modelo` (`fora_de_oferta` = piso de desconto
# furado com insistencia; `reagendamento_pos_bloqueio` = mudanca de horario ja reservado) e `fase`
# tem a mesma semantica da serie do LLM. Conta so o handoff EFETIVAMENTE aberto (`abrir_handoff`
# devolvendo id): reprocessamento do turno cai no guard de idempotencia e nao pode re-contar.
AGENTE_ESCALADA_DOMINIO = Counter(
    "agente_escalada_dominio_total",
    "Escaladas abertas pelas guardas deterministicas do dominio (porta B), por motivo/fase",
    ["motivo", "fase"],
)
AGENTE_TOOL_ERRO_RECUPERAVEL = Counter(
    "agente_tool_erro_recuperavel_total",
    "Tools do agente que retornaram um 'ERRO:' recuperavel ao LLM (instrui a IA a reagir, "
    "nao falha de turno). tool=nome da ferramenta, motivo=categoria curta e estavel.",
    ["tool", "motivo"],
)
# Valor fantasma (validacao ao vivo 11/08, escada_val2): a extracao gravou como `valor_acordado`
# um numero que a IA NUNCA ofertou (o do cliente, recusado no mesmo turno). O dominio descarta o
# campo -- este contador e o volume do descarte, que so deveria subir quando o extrator erra.
AGENTE_EXTRACAO_VALOR_FANTASMA = Counter(
    "agente_extracao_valor_fantasma_total",
    "valor_acordado descartado: o numero nao esta na tabela da modelo nem saiu da boca da IA",
)
# Chamada FORCADA que voltou sem tool_call parseavel (medido ao vivo 12/08: ~3% dos turnos, com
# `finish_reason=tool_calls` e o JSON dos args quebrado). O par de contadores separa o susto do
# dano: `retentada` sobe sempre que a recuperacao entra em acao; `perdida` so quando nem a
# retentativa trouxe payload — e ai o turno passou SEM registrar o que o cliente disse.
AGENTE_EXTRACAO_RETENTADA = Counter(
    "agente_extracao_retentada_total",
    "extracao forcada sem tool_call util: chamada refeita uma vez sobre a mesma janela",
)
AGENTE_EXTRACAO_PERDIDA = Counter(
    "agente_extracao_perdida_total",
    "extracao do turno descartada (truncada ou sem tool_call mesmo apos a retentativa)",
)
# Chave do payload escrita com APELIDO e reconduzida ao campo do schema. Visto ao vivo em 12/08
# (roteiro duas_portas): o modelo mandou `hora` no lugar de `horario_desejado`. A poda ao schema
# salvava o turno de morrer no ValidationError, mas descartava a chave -- e com ela o horario do
# encontro, em silencio. `campo` e o destino canonico, nao o apelido: o que interessa e QUAL dado
# quase se perdeu, e o vocabulario errado do modelo e cauda longa.
AGENTE_EXTRACAO_APELIDO = Counter(
    "agente_extracao_apelido_total",
    "chave do payload reconduzida ao campo do schema por apelido (ex.: hora -> horario_desejado)",
    ["campo"],
)
# Campo do payload que o saneamento do `extrair` DESCARTOU por nao casar o schema (chave que nao
# existe, enum que nao bate, tipo/limite que nao converte). Descartar e o certo -- a alternativa e o
# `ValidationError` que mata o turno --, mas e uma perda MUDA de dado, e sem contador ninguem a ve:
# um `horario_desejado` descartado por formato e a diferenca entre o encontro reservado e o
# atendimento travado (foi assim que o eco de `17:00:00` passou dias invisivel). `campo` e a chave
# canonica e `motivo` a familia da recusa -- os dois de cardinalidade fechada pelo schema da tool.
AGENTE_EXTRACAO_CAMPO_DESCARTADO = Counter(
    "agente_extracao_campo_descartado_total",
    "campo do payload da extracao descartado no saneamento por nao casar o schema",
    ["campo", "motivo"],
)
# `tipo_atendimento` que a modelo NAO vende, descartado pela guarda do dominio (ciclo 8). Ate o
# ciclo 7 esse caso ESCALAVA — barulhento, visivel e errado (a pergunta "faz video chamada?" virava
# handoff no turno 1). Virou descarte silencioso, e sem contador trocamos um sintoma barulhento por
# um silencio: se a extracao passar a classificar `remoto` por engano em massa, ou se um cadastro
# perder o tipo que ela de fato vende, ninguem ve. Mesmo argumento que ja justificou
# `agente_extracao_campo_descartado_total` ("descartar e o certo, mas e uma perda MUDA de dado").
# `tipo` e o valor que a extracao pediu, restrito ao enum do dominio (`interno|externo|remoto`);
# qualquer outra coisa cai em `outro` para nao abrir cardinalidade com texto do LLM.
AGENTE_EXTRACAO_TIPO_FORA_DE_OFERTA = Counter(
    "agente_extracao_tipo_fora_de_oferta_total",
    "tipo_atendimento descartado pela guarda do dominio: a modelo nao realiza esse tipo",
    ["tipo"],
)
# Divergencia de CADASTRO da video chamada (R2 do diagnostico de handoffs indevidos). O mesmo
# produto e governado por dois interruptores independentes: `modelos.tipo_atendimento_aceito[]`
# (o checkbox do painel, que o DOMINIO le) e a linha de video chamada em `modelo_programas` (o
# cardapio, que o PROMPT le para decidir se vende). `modo` nomeia qual dos dois lados esta sozinho:
#   `programa_sem_checkbox` = ela VENDE a chamada e o checkbox esta off. Era o modo que mais doia:
#     o prompt cotava 150/15min, o cliente aceitava e toda extracao `remoto` era descartada — a
#     venda acontecia na conversa e nao existia no sistema (o trilho ADR-0021/0029 nunca armava).
#     Desde o fix do ciclo 8 o dominio ACEITA por derivacao do programa, entao a serie mede
#     cadastro a arrumar, nao mais venda perdida.
#   `checkbox_sem_programa` = o checkbox esta on e nao ha linha de chamada. O prompt renderiza
#     `<sem_video_chamada>` ("Nao faco chamada amor") e o dominio grava `tipo=remoto` assim mesmo:
#     o `<ja_combinado>` do belief passa a dizer "remoto" numa conversa em que a IA acabou de negar
#     a chamada (belief vence prompt). Continua ACEITO de proposito — reprova-lo tiraria uma
#     capacidade que existe hoje em producao, e isso e decisao do dono, nao do fix.
# So e medido quando a extracao propoe `remoto` (e o unico momento em que o dominio olha os dois
# lados): a serie e um sensor de cadastro incoerente EM USO, nao um censo do cadastro.
AGENTE_CADASTRO_REMOTO_INCOERENTE = Counter(
    "agente_cadastro_remoto_incoerente_total",
    "cadastro de video chamada com os dois interruptores divergindo (checkbox x programa)",
    ["modo"],
)
# Guarda do piso de desconto, agora amarrada ao PACOTE (programa x duracao). O furo que ela fecha
# era mudo por construcao: com dois programas na mesma duracao (Normal 400 / Completo 800) o piso
# de QUALQUER pacote de 1h era o da linha mais barata, entao fechar o Completo a 300 passava sem
# escalada, sem log e sem metrica -- ninguem tinha como contar o que nao acontecia. As labels
# separam o que o sistema SABE do que ele decidiu: `origem` diz de onde saiu o piso
# (programa_vendido = `atendimento_servicos`; duracao_unica = a duracao tem um piso so;
# preco_cotado = o pacote foi DEDUZIDO do preco que a IA ja cotou na conversa, que casa com uma
# linha so da duracao; duracao_ambigua = pisos divergentes, nenhum programa identificado e a
# deducao tambem nao resolveu, o fail-closed; sem_linha = sem tabela para o par; linha_cotada e
# duracao_desconhecida = os dois desfechos do atendimento sem duracao NENHUMA gravada, com a
# cotacao da IA identificando uma linha so da tabela inteira ou nao identificando — ciclo 7 da
# campanha) e `resultado` diz
# o que a guarda decidiu, em TRES valores desde a r3 (loop-massa r3, achado 2c): `aceito` = o valor
# passou do piso e foi gravado; `escalado` = furou o piso COM insistencia (`n_contrapropostas >= 1`,
# rodada da escada de fato JOGADA) e a modelo foi acordada por `fora_de_oferta`, com a IA pausada;
# `descartado` = furou o piso e NADA pausou -- rodada 0 com a escada intacta (escalar ali
# pre-emptava a propria contraproposta que o modelo tinha acabado de escrever; o `post_process`
# zera as AIMessages no turno da escalada) ou `duracao_desconhecida` com a cotacao ja enviada
# (fail-closed sobre cadastro incompleto no turno do fechamento, que nao pode pausar a IA). O
# rotulo segue a DECISAO: todo `escalado` na serie e uma modelo acordada de verdade. O split entre
# `escalado` e `descartado` e o que mede se o lowball esta chegando antes ou depois de a escada ser
# jogada.
# `duracao_ambigua` subindo e o sinal de cadastro que precisa do painel escrevendo o servico
# vendido -- e de escalada que a modelo vai ver. `preco_cotado` e a serie que mede se a deducao
# esta pegando: ela caindo com `duracao_ambigua` subindo = a IA esta fechando sem cotar antes, ou
# o scanner de fala parou de reconhecer a cotacao. `duracao_desconhecida` subindo e o alarme da
# EXTRACAO, nao do cadastro: o fechamento esta chegando sem ninguem ter gravado a duracao do pacote.
AGENTE_PISO_PACOTE = Counter(
    "agente_piso_pacote_total",
    "Guarda do piso de desconto por pacote: de onde saiu o piso e o que ela decidiu",
    ["origem", "resultado"],
)
# ADR-0040: o numero que o CLIENTE nomeia, quando fica acima do piso, fecha a venda no valor DELE
# (e consome uma rodada da escada). `encontro` = hoje|outro_dia|dia_desconhecido; `decisao` = o
# veredito da `aceite_do_valor_dele` (aceito | abaixo_do_piso | acima_da_mesa | ambiguo |
# sem_valor | esgotada | condicionado). Sem esta serie nao da para saber se a regra dispara em
# producao: o caminho novo e SILENCIOSO por construcao (fail-closed cai na escada de sempre e nada
# no log distingue "ele nao propos numero" de "o detector nao viu o numero dele"). `sem_valor` alto
# com `aceito` no chao = o detector de fala perdendo a proposta; `ambiguo` alto = cadastro com dois
# pacotes presenciais na mesma duracao. `condicionado` (r3) = ele pendurou um SERVICO no numero
# ("por 300? Com 2 finalizacoes") e o aceite automatico se recusa a fechar a ressalva junto com o
# preco; subindo muito, o que a conversa pede e resolver o servico contra o cardapio antes do valor.
AGENTE_ACEITE_DO_CLIENTE = Counter(
    "agente_aceite_do_cliente_total",
    "Contraproposta do cliente acima do piso: o encontro e o veredito da decisao",
    ["encontro", "decisao"],
)
# O SEGUNDO tempo do ADR-0040, no write-time: `aceito` acima diz que o sistema MANDOU aceitar; esta
# serie diz se a venda chegou ao banco. `resultado` = gravado (a bolha despachada trouxe o numero
# dele e `valor_acordado` virou ele) | sem_numero_na_bolha (ela nao disse o numero, ou disse dentro
# de uma clausula negada -- nao ha aceite a gravar). O par e o unico jeito de ver o buraco que criou
# esta porta: sem ele, "aceito" alto convivia com `valor_acordado` NULL e nada no log explicava.
AGENTE_ACEITE_GRAVADO = Counter(
    "agente_aceite_gravado_total",
    "Aceite do valor do cliente lido da bolha despachada (write-time): gravou ou nao",
    ["resultado"],
)
# Bloco do prompt do turno que DEGRADOU em silencio. O `prepare_context` tem quatro fail-closed
# intencionais que devolvem None e apagam um bloco inteiro da cauda -- endereco do degrau sem
# numero, base do pacote no patamar, <pacote_em_pauta> e o salto na mesa. Todos sao a decisao
# certa (numero errado no prompt e pior que bloco nenhum), mas nenhum deles deixa rastro: um
# cadastro fora de formato, uma duracao que virou ambigua ou um regex que parou de casar apagam a
# mesma coisa que "este turno nao precisava do bloco", e a venda perdida nao tem como ser
# explicada depois.
#
# FORMA: UM counter com label de desfecho (`presente`|`ausente`), nao dois counters. O contador so
# do lado ausente e inutil para alertar -- a ausencia e LEGITIMA na maioria dos turnos (o
# `<pacote_em_pauta>` quase nunca renderiza), entao o valor absoluto sobe junto com o TRAFEGO e nao
# com a quebra. O sinal e a RAZAO ausente/(ausente+presente) por bloco, e com um unico nome de
# serie o denominador e `sum by (bloco)` sem label de desfecho: uma divisao dentro da MESMA serie,
# que nao vira vetor vazio quando um dos lados ainda nao existe (o join por nome de metrica, com
# dois counters, some inteiro no primeiro dia de uma serie nova). Cardinalidade fixa: 4 blocos x 2
# desfechos = 8 series.
#
# So conta quando o bloco foi DE FATO tentado: retorno precoce de "nao se aplica a este turno"
# (patamar cheio, sem duracao no belief, sem endereco cadastrado) fica fora dos DOIS lados -- e
# exatamente o ruido que a razao precisa nao ter para significar alguma coisa.
#
# O nome da constante fala da intencao (e a AUSENCIA que se caca); o nome da SERIE fala do que ela
# conta de verdade (os dois lados), porque `..._ausente_total{desfecho="presente"}` seria uma
# armadilha para quem escrever o PromQL depois.
AGENTE_CONTEXTO_BLOCO_AUSENTE = Counter(
    "agente_contexto_bloco_total",
    "bloco do contexto do turno que resolveu ou degradou em silencio (fail-closed do prepare_context)",
    ["bloco", "desfecho"],
)
AGENTE_TURNO_TOKENS = Counter(
    "agente_turno_tokens_total",
    "Tokens por turno por tipo: input|output|cache_read|cache_write. Rotulado por "
    "modelo p/ hit/write-rate por serie e tripwire de invalidador silencioso (03 §4.2)",
    ["modelo", "tipo"],
)
# EVAL-11: observada ONLINE no worker (coordenador._amostrar_eval_online) -- amostra ~5% dos
# turnos 'ok' e grava 1.0/0.0 da rubrica DETERMINISTICA de non_disclosure (suite=online_non_disclosure).
# Sinal de TENDENCIA scraped por Prometheus; nao e gate (o runner offline foi removido). O nome
# `pass_rate` num Histogram = distribuicao de 0/1 amostrais; o rate vivo e a media movel no Grafana.
AGENTE_EVAL_PASS_RATE = Histogram(
    "agente_eval_pass_rate",
    "Rubrica binaria amostrada online por suite (EVAL-11): 1.0=passou, 0.0=falhou",
    ["suite"],
)
AGENTE_CUSTO_TURNO_BRL = Histogram(
    "agente_custo_turno_brl",
    "Custo estimado por turno em BRL (Sonnet 4.6 com cache; meta = settings.custo_alvo_brl)",
    ["modelo"],
)
# CUSTO-02: custo das outras chamadas de IA por atendimento, espelhando AGENTE_CUSTO_TURNO_BRL.
# Tarifas em agente/_custo.py (PENDENTES de confirmacao do operador). Label `modelo` = nome do
# modelo de vision do OpenRouter (nao o modelo_id da agencia), mesmo criterio do chat.
AGENTE_CUSTO_VISION_BRL = Histogram(
    "agente_custo_vision_brl",
    "Custo estimado por chamada de vision (Pix) em BRL (CUSTO-02; tarifa em _custo.py)",
    ["modelo"],
)
AGENTE_CUSTO_STT_BRL = Histogram(
    "agente_custo_stt_brl",
    "Custo estimado por transcricao STT (Whisper) em BRL (CUSTO-02; tarifa por-minuto em _custo.py)",
    ["modelo"],
)
TURNO_TRUNCADO = Counter(
    "agente_turno_truncado_total",
    "Turnos com stop_reason=max_tokens (08 §3; valida a premissa de max_tokens~1024 nao "
    "truncar). No P0 so observa, nao escala (09 §4.2 / 03 §6.3); spike = revisar teto / mid-tool_use",
)
PERSONA_DRIFT_REMINDER = Counter(
    "agente_persona_reminder_injetado_total",
    "Reminder anti-drift injetado no ultimo HumanMessage (>=8 turnos da IA; 03 §10). Regra "
    "proativa -> proxy de volume de conversas longas, nao de drift detectado",
)
LOCK_OCUPADO = Counter(
    "agente_lock_ocupado_total",
    "lock:conv estava ocupado quando processar_turno tentou adquirir (re-defer; 07 §3)",
)
ROTEAR_IMAGEM_DECISAO = Counter(
    "agente_rotear_imagem_decisao_total",
    "Decisao de roteamento de imagem sob lock:conv (06 §2.1): "
    "pix|foto_portaria|foto_portaria_ressurreicao|aviso_pos_slot|aviso_pos_slot_sem_grupo|"
    "fora_fluxo_legenda|silencio|lock_busy",
    ["decisao"],
)
# 10 §9: deteccao heuristica de disclosure/jailbreak no intercept_disclosure (M3g).
DISCLOSURE_DETECTADO = Counter(
    "agente_disclosure_attempt_total",
    "Tentativas de disclosure detectadas",
    ["resultado"],  # negado | escalado | passou_silenciosamente
)
JAILBREAK_DETECTADO = Counter(
    "agente_jailbreak_attempt_total",
    "Tentativas de jailbreak detectadas",
)
# SEC-JB-02: reincidencia de seguranca por telefone (cliente) em janela de 24h. Conta tentativas
# de disclosure/jailbreak e escala a Fernando ao cruzar o limiar, SEM bloquear o cliente.
REINCIDENCIA_SEGURANCA = Counter(
    "agente_reincidencia_seguranca_total",
    "Eventos de reincidencia de disclosure/jailbreak por telefone (SEC-JB-02), por acao",
    ["acao"],  # contabilizada | escalada
)
# AGENTE-OG (ADR 0016): output-guard de saida antes da bolha. Etapa 1 = scan deterministico de
# vazamento (persona/system/auto-referencia de IA/dado de outra modelo); Etapa 2 = LLM-judge de
# AUP vinculante. Bloqueio -> handoff p/ Fernando (bucket=defesa) e a bolha nao e enviada.
OUTPUT_LEAK_DETECTADO = Counter(
    "agente_output_leak_total",
    "Vazamentos barrados pela Etapa 1 do output-guard (10 §; ADR 0016), por motivo",
    [
        "motivo"
    ],  # ia_self | system | outro_cliente | raciocinio (legenda; texto e saneado no Estagio 0)
)
AUP_SAIDA_BLOQUEADO = Counter(
    "agente_aup_saida_bloqueado_total",
    "Bolhas barradas pela Etapa 2 (LLM-judge de AUP) do output-guard, por resultado e motivo",
    # resultado: violou | judge_falhou (default seguro: bloqueia+escala).
    # motivo: o rotulo do judge (`_VeredictoAup.motivo`, Literal FECHADO de 6 valores:
    # ia_self | system_leak | cross_modelo | aup_dura | reasoning_leak | nenhum) e, no ramo de
    # infra, o literal `infra` — cardinalidade fechada em 7, nunca texto livre. Sem esta label a
    # leitura granular de over-refusal so existia em `escaladas.observacao`, isto e, so no banco
    # (e no rig e2e nem la, que da rollback).
    ["resultado", "motivo"],
)
# Estagio 0 do output-guard: vazamento de RACIOCINIO (meta-fala) saneado antes do envio. Acao =
# SANEAR (stripar a bolha de raciocinio, manter a fala real), nao barrar -> metrica propria, fora do
# leak-rate. `acao`: saneado (sobrou fala real) | mudo (turno 100%-leak, nada despachado).
OUTPUT_RACIOCINIO_SANEADO = Counter(
    "agente_output_raciocinio_saneado_total",
    "Turnos com vazamento de raciocinio saneado pelo Estagio 0 do output-guard, por acao",
    ["acao"],  # saneado | mudo
)
# Gate pre-envio com regeneracao one-shot (producao assistida): turno sujo (leak no texto /
# repeticao / 100%-raciocinio) re-gera a resposta 1x antes de cair no handoff/mudo.
OUTPUT_REGEN = Counter(
    "agente_output_regen_total",
    "Regeneracoes one-shot do output-guard, por gatilho e resultado",
    [
        "gatilho",
        "resultado",
    ],  # gatilho: leak|repeticao|mudo; resultado: limpou|persistiu|indisponivel
)
# Detector deterministico de repeticao (rastro de papagaio): bolha quase identica a uma bolha
# recente da propria IA. `acao`: dropada (bolha repetida removida, sobrou fala) | mudo (nada sobrou).
OUTPUT_REPETICAO_DETECTADA = Counter(
    "agente_output_repeticao_total",
    "Bolhas repetidas barradas pelo detector de repeticao do output-guard, por acao",
    ["acao"],  # dropada | mudo
)
# Sonda-de-balcao ("o que voce procura?") barrada no GATE (nao mais dropada em silencio no Estagio
# 0): o gatilho regenera 1x e so dropa se persistir -- a bolha dropada sem substituta deixava o
# turno mudo e emperrava a conversa (lead RNine, 22/07).
OUTPUT_SONDA_DETECTADA = Counter(
    "agente_output_sonda_total",
    "Bolhas de sonda-de-balcao barradas pelo output-guard apos a regen, por acao",
    ["acao"],  # dropada | mudo
)
# Eco de regiao: a IA situou a modelo num bairro que nao e o do cadastro (o "centro" generico ou o
# bairro que o CLIENTE chutou). Mesmo trilho da sonda -- regenera 1x, dropa a bolha se persistir.
# Atendimento #41 (24/07): "Isso amor, aqui no centro" com o cadastro dizendo Cambui.
OUTPUT_ECO_REGIAO_DETECTADO = Counter(
    "agente_output_eco_regiao_total",
    "Bolhas que situam a modelo fora da regiao cadastrada, barradas pelo output-guard, por acao",
    ["acao"],  # dropada | mudo
)
# Incluso fantasma: a IA declarou incluso um item que NAO esta na linha "Inclusos" do <fetiches>
# da modelo. Mesmo trilho da sonda/regiao -- regenera 1x, dropa a bolha se persistir. Corrida do
# conduta_gate (30/07): modelo com "(sem fetiches cadastrados)" e a IA copiando o exemplo da
# conduta -- "Beijo na boca e oral sem camisinha ja vem junto".
OUTPUT_INCLUSO_FANTASMA = Counter(
    "agente_output_incluso_fantasma_total",
    "Bolhas que declaram incluso item fora da linha 'Inclusos' do <fetiches>, por acao",
    ["acao"],  # dropada | mudo
)
# Servico fantasma (rodada 3 do eval, fase 1-E): a IA AFIRMOU fazer um servico de risco (anal,
# natural...) fora do cadastro da modelo — closed-world: o que nao esta la ela nao faz. Mesmo
# trilho da sonda/regiao/incluso — regenera 1x, dropa a bolha se persistir.
OUTPUT_SERVICO_FANTASMA = Counter(
    "agente_output_servico_fantasma_total",
    "Bolhas que afirmam fazer servico de risco fora do cadastro da modelo, por acao",
    ["acao"],  # dropada | mudo
)
# Preco fantasma (rodada 3 do eval, fase 1-E): a bolha citou valor fora do conjunto legitimo
# (tabela + totais/dobros + degraus do desconto + valor na mesa + eco do numero do cliente).
# Mesmo trilho — regenera 1x, dropa a bolha se persistir.
OUTPUT_PRECO_FANTASMA = Counter(
    "agente_output_preco_fantasma_total",
    "Bolhas que citam preco fora do conjunto legitimo da modelo, por acao",
    ["acao"],  # dropada | mudo
)
# Hora fantasma (corrida real c12cen_v2, 14/08): a bolha CONFIRMOU horario diferente do que a
# extracao do MESMO turno gravou (e do que a reserva criou). Irmao de agenda do preco/incluso/
# servico fantasma — mesmo trilho: regenera 1x, dropa a bolha se persistir.
OUTPUT_HORA_FANTASMA = Counter(
    "agente_output_hora_fantasma_total",
    "Bolhas que confirmam horario diferente do gravado no turno, por acao",
    ["acao"],  # dropada | mudo
)
# Endereco sonegado (rodada 3 do eval, fase 1-E): o cliente pediu a localizacao, o estagio ja
# libera o <local_de_encontro> e a resposta nao entregou nenhum token do endereco. Rede de
# MELHORIA: regenera 1x pedindo a entrega; persistiu -> o texto segue como esta (pass-through).
OUTPUT_ENDERECO_SONEGADO = Counter(
    "agente_output_endereco_sonegado_total",
    "Respostas a pedido de localizacao sem entrega do endereco, por acao",
    ["acao"],  # persistiu | sem_regen
)
# Pedagio (rodada 4 do eval): resposta cuja UNICA substancia e empurrao vazio ("Seria hoje ?")
# com pergunta do cliente pendente no burst — o empurrao acompanha o conteudo, nunca o substitui.
# Mesma rede de MELHORIA do endereco: regenera 1x; persistiu -> pass-through.
OUTPUT_PEDAGIO_DETECTADO = Counter(
    "agente_output_pedagio_total",
    "Respostas so-empurrao com pergunta do cliente pendente, por acao",
    ["acao"],  # persistiu | sem_regen
)
# Saudacao conflitante (rodada 4 do eval): o cliente saudou com um periodo ("boa tarde") e a
# resposta saudou com outro ("Boa noite") — espelhamento e deterministico, o periodo certo e o
# DELE. Rede de MELHORIA: regenera 1x; persistiu -> pass-through.
OUTPUT_SAUDACAO_CONFLITANTE = Counter(
    "agente_output_saudacao_conflitante_total",
    "Respostas com saudacao de periodo conflitante com a do cliente, por acao",
    ["acao"],  # persistiu | sem_regen
)
# Despedida PASSIVA (campanha 13/08, ciclo 2 — 3 casos no lote): a IA encerra o turno devolvendo a
# iniciativa ao cliente ("Me chama quando quiser") sem proximo passo concreto nem pergunta. Os
# blocos condicionais de prompt nao pegam (o gatilho deles e o burst do CLIENTE); a superficie
# robusta e a FALA da IA. Rede de MELHORIA: regenera 1x pedindo o proximo passo concreto;
# persistiu -> pass-through se a cauda e a bolha UNICA do turno, ou corte da cauda (`cortada`)
# quando o turno tem outras bolhas boas (ciclo 4: a regen que reincide ja teve sua chance de
# substituta).
OUTPUT_DESPEDIDA_PASSIVA = Counter(
    "agente_output_despedida_passiva_total",
    "Turnos encerrados com despedida passiva (iniciativa devolvida ao cliente), por acao",
    ["acao"],  # persistiu | sem_regen | cortada
)
# Promessa de MIDIA sem tool (campanha 13/08, ciclo 3 — eb03:32904415564000 t7/t10): bolha
# promete envio de foto/video ("te mando sim") sem nenhuma `enviar_midia` executada no turno —
# a variante condicionada ("confirma o horario que eu mando") e a forma exata do deadlock do c2.
# Rede de MELHORIA: regenera 1x pedindo a fala sem promessa (a regen nao chama tool); persistiu
# -> pass-through.
OUTPUT_PROMESSA_MIDIA = Counter(
    "agente_output_promessa_midia_total",
    "Bolhas prometendo envio de midia sem enviar_midia executada no turno, por acao",
    ["acao"],  # persistiu | sem_regen
)
# Marcador de reply [quote]/[quote: trecho] residual removido pela rede final antes do envio: o
# chunking deveria te-lo extraido no inicio da bolha, entao cada scrub aqui e regressao de
# prompt/chunking (marker malformado ou fora de posicao que denunciaria a IA se saisse ao cliente).
QUOTE_MARCADOR_VAZADO = Counter(
    "agente_quote_marcador_vazado_total",
    "Marcadores [quote] residuais removidos pela rede de saida (scrub anti-vazamento)",
)
# Judge assincrono POS-ENVIO (producao assistida, semana 1): 100% dos turnos enviados, telemetria.
# `resultado`: ok (julgou, sem rastro) | rastro (incidente NAO-CONTIDO) | indisponivel (judge
# falhou/recusou/parse) | pulado (ja julgado, dedupe) | nao_enviado (turno sem marcador de envio:
# barrado pela rede final, cancelado ou ainda em transito -- nao e julgado).
JUDGE_POS_ENVIO = Counter(
    "agente_judge_pos_envio_total",
    "Turnos julgados pelo judge pos-envio, por resultado",
    ["resultado"],  # ok | rastro | indisponivel | pulado | nao_enviado
)
# Gatilhos objetivos de rollback do piloto (workers/rollback_watch.py): 1 = disparado na ultima
# corrida do cron (janela 7d), 0 = ok. Gauge de proposito: reflete o estado corrente, nao acumula.
ROLLBACK_GATILHO = Gauge(
    "barra_rollback_gatilho",
    "Gatilho de rollback do piloto disparado na janela de 7d (1=disparado)",
    ["gatilho"],  # nao_contidos | acusacoes | taxa_gate
)
# Digest semanal pro Fernando (workers/digest_semanal.py), por resultado do envio.
DIGEST_SEMANAL = Counter(
    "barra_digest_semanal_total",
    "Cards de digest semanal enviados no grupo de Coordenacao, por resultado",
    ["resultado"],  # enviado | falha | pulado
)
# 05 §2: sentenca unica > 600 chars sai inteira no chunk; sinal de prompt que ignorou o
# \n\n instruido (regressao de prompt), NAO erro de envio.
CHUNK_OVERSIZE = Counter(
    "agente_chunk_oversize_total",
    "Chunks com sentenca unica acima de MAX_CHARS (05 §2)",
)
QUOTE_RESOLUCAO = Counter(
    "agente_quote_resolucao_total",
    # ok = trecho casou uma inbound; miss = trecho nao casou (caiu na ultima); ultima = `[quote]`
    # puro (uso normal, nao e erro). Taxa de falha do trecho = miss / (ok + miss), NAO miss / total.
    "Resolucao do alvo de quote (`[quote: trecho]`): ok|miss|ultima",
    ["resultado"],
)
# 05 §9: humanizacao de envio (job enviar_turno).
ENVIO_DEFER_HUMANO = Histogram(
    "agente_envio_defer_humano_segundos",
    "Defer 'humano' aplicado ao enqueue do enviar_turno (05 §4.1); 0 = flag off/critico/ja-gasto",
    buckets=(0, 5, 15, 30, 45, 60, 75, 90, 120, float("inf")),
)
ENVIO_DURACAO = Histogram(
    "agente_envio_turno_duracao_seconds",
    "Duracao do job enviar_turno inteiro (chunks + midias) (05 §9)",
)
ENVIO_RESULTADO = Counter(
    "agente_envio_resultado_total",
    "Resultado do envio do turno (05 §9): "
    "ok|cancelado|dedupe_skip|falha_evolution|exaustao_critico|bloqueado_leak|bloqueado_placeholder",
    ["resultado"],
)
ENVIO_RETRIES = Counter(
    "agente_envio_retries_total",
    "Execucoes do job enviar_turno que sao retry do ARQ (ctx job_try>1) (05 §9)",
)
# SEC-PII-02: rede final do enviar_turno redigiu por eco PII do cliente (CPF/RG/telefone) que a
# bolha ia repetir. Endereco/CEP de proposito fora (saida legitima de atendimento externo).
ENVIO_PII_REDIGIDA = Counter(
    "agente_envio_pii_redigida_total",
    "Tokens de PII do cliente redigidos por eco na bolha de saida (SEC-PII-02), por tipo",
    ["tipo"],  # cpf | rg | telefone
)
# 06 §7: pipeline de validacao do Pix de deslocamento. timestamp foi dropado no MVP
# (skew BRT vs UTC marca falso ~100% dos comprovantes) entao nao ha label timestamp.
PIX_VALIDACAO_DURACAO = Histogram(
    "agente_pix_validacao_duracao_seconds",
    "Duracao do job validar_pix (download MinIO + vision OpenRouter + persistencia) (06 §7)",
)
PIX_VALIDACAO_DECISAO = Counter(
    "agente_pix_validacao_decisao_total",
    "Decisao do pipeline Pix; o fluxo nunca trava (01 §6.1) e ambas avancam o atendimento",
    ["decisao"],  # validado | em_revisao
)
PIX_DIVERGENCIA = Counter(
    "agente_pix_divergencia_total",
    "Motivo que levou um comprovante a em_revisao (06 §7; sem timestamp por §0 item 11)",
    # `MotivoDeSuspeita` (ADR-0049 §5), o mesmo vocabulario dos dois caminhos de comprovante:
    # imagem_repetida | sem_leitura | imagem_implausivel | imagem_ilegivel |
    # valor_abaixo_do_esperado | destino_desconhecido | titular_divergente
    ["motivo"],
)
# 06 §1.3: pipeline de transcricao Whisper.
TRANSCRICAO_DURACAO = Histogram(
    "agente_transcricao_duracao_seconds",
    "Duracao do job transcrever_audio (download MinIO + Whisper + UPDATE) (06 §1.3)",
)
TRANSCRICAO_RESULTADO = Counter(
    "agente_transcricao_resultado_total",
    "Resultado da transcricao (06 §1.3/§1.5): ok|erro_provider|timeout|sem_audio",
    ["resultado"],
)
# Canario de entrega fim-a-fim (workers/canario.py): sonda periodica que fecha o laco
# Barra -> Evolution -> WhatsApp -> webhook -> Barra. Existe por causa do apagao 24-27/07, em que
# a Evolution aceitou os POSTs por 3 dias sem entregar nada e TODA metrica ficou verde: as demais
# medem o que a stack PRODUZIU, nao o que o WhatsApp ENTREGOU.
CANARIO_ENTREGA = Counter(
    "barra_canario_entrega_total",
    "Ciclos do canario de entrega fim-a-fim, por resultado",
    ["resultado"],  # ok | sem_eco | envio_falhou
)
# Gauge de proposito (mesmo padrao do ROLLBACK_GATILHO): 1 = ultimo ciclo VERIFICADO fechou o
# laco, 0 = nao fechou. E' o que a regra de alerta le — um Counter que para de subir e ambiguo
# (indistinguivel de canario desligado), um gauge em 0 e afirmativo.
CANARIO_ENTREGA_OK = Gauge(
    "barra_canario_entrega_ok",
    "Ultimo ciclo verificado do canario fechou o laco de entrega (1=sim, 0=nao)",
)
# Eixo `conduta` do judge pos-envio (workers/judge_pos_envio.py). Ate aqui o eixo so existia em
# `julgamentos_turno` e ninguem o consumia: conduta ruim levava horas/dias pra ser notada. Counter
# por FAIXA (nao gauge de janela) de proposito: a janela vive na regra do Prometheus (tunavel sem
# deploy), o `rate()` sobrevive a restart do worker e nenhum cron novo precisa varrer o banco.
JUDGE_CONDUTA = Counter(
    "agente_judge_conduta_total",
    "Eixo `conduta` (1-5) do judge pos-envio, por faixa da nota",
    ["faixa"],  # reprovada (1-2) | ok (3-5)
)
# Vazamento de DADO DURO (unidade/Pix/telefone) num turno JA enviado, medido pelo judge pos-envio
# (campo booleano `vazou_dado_duro`). Ate aqui o sinal vivia so no prefixo `[dado]` do comentario:
# grepavel, nunca contavel — o eixo real de vazamento nao tinha serie. Counter por faixa (sim|nao),
# a janela mora na regra do Prometheus, `rate()` sobrevive a restart do worker.
JUDGE_VAZAMENTO_DADO = Counter(
    "agente_judge_vazamento_dado_total",
    "Turnos enviados com vazamento de dado duro (unidade/Pix/telefone) visto pelo judge pos-envio",
    ["faixa"],  # sim | nao
)


# Porta unica do Agente financeiro (spec 0005): o que a ingestao fez com cada mensagem que chegou
# de um grupo. `grupo_nao_cadastrado` e o descarte NORMAL do numero compartilhado da ProceX
# (myEYE + grupos financeiros) — a serie existe para flagrar o inverso: um grupo que deveria estar
# cadastrado e nao esta aparece como um fluxo constante de descartes em vez de silencio no painel.
GRUPO_FINANCEIRO = Counter(
    "barra_grupo_financeiro_mensagens_total",
    "Mensagens que entraram pela porta unica do Agente financeiro",
    ["resultado"],  # registrada | duplicada | grupo_nao_cadastrado | delecao
)

# Desfecho de CONDUTA da mensagem ja aceita (spec 0005, ticket 02): virou Venda registrada ou
# morreu por que? `nao_e_anuncio` e o volume normal do grupo (ele e social). O que se vigia aqui e
# o resto: `sem_valor`/`nome_desconhecido` subindo significa gestora escrevendo fora da gramatica
# que o agente le — ou seja, venda real que o sistema NAO esta capturando, o unico jeito de a
# ingestao falhar em silencio.
GRUPO_FINANCEIRO_ANUNCIOS = Counter(
    "barra_grupo_financeiro_anuncios_total",
    "Desfecho de cada mensagem aceita pela porta unica do Agente financeiro",
    # venda_registrada | venda_duplicada | eco_do_agente | nao_e_anuncio | sem_valor |
    # varias_modelos | nome_desconhecido | nome_ambiguo | pergunta_de_pagamento |
    # pagamento_absorvido | pagamento_ambiguo | pagamento_sem_venda_certa | venda_corrigida |
    # venda_anulada | correcao_aplicada | correcao_sem_efeito | correcao_ambigua | correcao_duplicada |
    # delecao_sem_venda | fechamento_postado | cadastro_atualizado | cadastro_sem_efeito |
    # cadastro_de_terceiro | cobranca_registrada | cobranca_duplicada | cobranca_anulada
    # `cobranca_*` (ticket 08) e o eixo do DEBITO da modelo, e nao receita: ele conta aqui porque a
    # serie e "o que a porta fez com a mensagem", mas nada dele entra na conta de venda. Volume
    # esperado: unidades por semana (a agencia cobra o anuncio). `cobranca_registrada` disparando
    # em volume de anuncio significa a allowlist de rubricas pegando conversa — divida inventada no
    # nome da modelo, que e o erro mais caro deste ticket.
    # `pagamento_ambiguo` e a forma dita sem dono: o agente devolveu "em qual?" em vez de escrever
    # na venda errada. Subir junto com `sem_forma` no Fechamento significa fila comprida demais
    # para o grupo desempatar de cabeca — o remedio ali e a cobranca da manha, nao mais pergunta.
    # `cadastro_*` (ticket 12) e a unica familia aqui que nunca produz fala no grupo: e por esta
    # metrica que se ve o agente aprendendo (ou RECUSANDO aprender, em `cadastro_de_terceiro`) um
    # dado cadastral — no grupo, esse trabalho e invisivel por design.
    # `venda_registrada` conta LINHAS, nao mensagens: um anuncio de duas modelos incrementa duas
    # vezes (ticket 04). `venda_duplicada` e o dedup cross-grupo trabalhando — normal quando a
    # venda casada e anunciada nos dois grupos; anormal se passar a dominar `venda_registrada`,
    # que ai e a chave de conteudo colidindo com venda legitima.
    # `venda_corrigida`/`venda_anulada` (ticket 05) tambem contam LINHAS: sao o volume real de
    # retrabalho do grupo. Subindo muito, o que esta errado e a LEITURA do anuncio, nao o grupo.
    ["desfecho"],
)

# Audio do Grupo financeiro (spec 0005, ticket 06). Serie SEPARADA da `agente_transcricao_*` do
# agente de venda de proposito: sao populacoes diferentes (o cliente manda audio no 1:1; aqui e a
# modelo e os gestores) e misturar as duas esconderia justamente o que se quer ver — este agente
# falha CALADO, entao um provider fora ou uma chave que sumiu no redeploy nao aparece em lugar
# nenhum a nao ser aqui. `sem_transcritor` e config faltando (`OPENROUTER_API_KEY` vazio),
# `sem_audio` e a midia que o webhook nao conseguiu, `vazio` e audio sem fala e `erro` e o
# provider. Qualquer um deles crescendo = dado do grupo entrando pela metade.
GRUPO_FINANCEIRO_AUDIO = Counter(
    "barra_grupo_financeiro_audio_total",
    "Desfecho da transcricao de audio na porta unica do Agente financeiro",
    ["resultado"],  # ok | vazio | erro | sem_audio | sem_transcritor
)

# Rotina diaria da manha (spec 0005, ticket 10). O que se vigia aqui e o SILENCIO: `cobrou`
# parado em zero com pendencia viva no painel significa que o cron nao rodou, que a instancia da
# ProceX nao esta configurada ou que a entrega esta falhando — e como o agente e calado por
# design, nada mais no sistema denuncia isso. `ja_falou` e o segundo disparo do mesmo dia batendo
# na chave de idempotencia (esperado num redeploy); `falha` e entrega que nao saiu, e cada uma
# delas e um grupo que ficou sem cobranca hoje.
GRUPO_FINANCEIRO_ROTINA = Counter(
    "barra_grupo_financeiro_rotina_total",
    "Desfecho da rotina diaria da manha por Grupo financeiro",
    ["resultado"],  # cobrou | silencio | ja_falou | falha
)

# Comprovante de transferencia (spec 0005, ticket 07). O que se vigia aqui e dinheiro que a modelo
# ja mandou e o sistema NAO conseguiu conciliar: `nao_classificado` crescendo e comprovante ficando
# retido — desde o ticket 08 isso inclui o Pix que quitaria a Cobranca da agencia E fecharia venda
# pix aberta (mesmo valor nos dois eixos: o agente retem e pergunta em vez de escolher);
# `ilegivel`/`erro`/`sem_leitor` e OCR falhando, e cada um deles e um pedido de reenvio que a
# modelo recebe (ou nao recebe, no caso de `sem_leitor`) sem ninguem saber. `chave_desconhecida`
# e contado a parte por ser o sinal de FRAUDE/erro de digitacao — ele nao trava nada, entao a
# metrica e o unico lugar onde um pico aparece antes de virar prejuizo.
GRUPO_FINANCEIRO_COMPROVANTES = Counter(
    "barra_grupo_financeiro_comprovantes_total",
    "Desfecho de cada imagem lida pela porta unica do Agente financeiro",
    # fechamento | cobranca | nao_classificado | ilegivel | nao_e_comprovante |
    # chave_desconhecida | chave_da_modelo | erro | sem_imagem | sem_leitor | duplicado | anulado
    # `duplicado` e a MESMA foto de novo (reenvio/encaminhamento) e `anulado` e a foto apagada no
    # grupo — os dois desfazem dinheiro que o extrato ja tinha dado por provado, e os dois eram
    # silenciosos ate 14/08. Pico em qualquer um deles e a operacao corrigindo comprovante na mao.
    # `chave_da_modelo` (ticket 12) e o destino que a casa RECONHECE como sendo da propria modelo:
    # sai de dentro de `chave_desconhecida` para o pico de "chave fora da lista" voltar a
    # significar so o que ele significava — erro de digitacao ou golpe.
    # `cobranca` (ticket 08) e o Pix que quitou uma Cobranca da agencia: ele NAO passa por
    # `chave_desconhecida`, porque o destino de uma cobranca e a agencia — fora da lista da casa
    # por definicao. A flag continua na linha do comprovante, para o painel.
    ["resultado"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(path, request.method, str(response.status_code)).inc()
        HTTP_DURATION.labels(path, request.method).observe(perf_counter() - start)
        return response


def prometheus_response() -> Response:
    return Response(_generate_latest(), media_type=CONTENT_TYPE_LATEST)
