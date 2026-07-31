"""`ContextoDoTurno`: o dicionário de propósito do turno, declarado uma vez e tipado.

É o contrato da cauda volátil — o MESMO conjunto de campos alimenta os dois blocos que saem dele:
`contexto_dinamico.md.j2` (o que a IA lê) e `ja_registrado.md.j2` (o que o EXTRATOR lê, via
`PecasDoTurno` no State). Era um `dict[str, Any]` montado num `return` de 70 linhas: um rename de
chave não quebrava nada — o Jinja renderiza variável desconhecida como VAZIA, então o bloco sumia
do prompt em silêncio e a IA perdia a instrução em produção.

Aqui o rename vira erro de mypy no ponto de construção, e o que amarra a outra ponta (as
variáveis que os templates de fato leem, mais o espelho da bancada offline) é
`tests/unit/test_contrato_variaveis_contexto.py`.

`frozen=True` de propósito: as duas correções que rodam DEPOIS de resolver o contexto (o A2 do dia
e o OR da sondagem, em `_anexar_contexto_dinamico`) passam a ser `replace(...)` explícito, com o
campo nomeado no diff, em vez de mutação in-place de um dicionário anônimo — a ordem entre elas e
o render do bloco de estado é semântica (ver `_anexar_contexto_dinamico`).
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any


@dataclass(frozen=True)
class ContextoDoTurno:
    """Variáveis do turno resolvidas por `_resolver_variaveis` (02 §5). Ver o módulo."""

    # Âncora de tempo. `agora` é a âncora CRUA (BRT naive) — os templates não a leem, ela viaja
    # para a janela dedicada da extração (`PecasDoTurno`); `data_atual`/`hora_atual` são as
    # DERIVADAS que a IA lê no `<agenda>`. Sair da mesma fonte é o que impede divergência.
    agora: datetime | None
    data_atual: date | None
    hora_atual: str | None

    # Atendimento e belief-state (derivado da MESMA FSM da extração).
    numero_curto: int | None
    estado: str | None
    slots_faltantes: list[str]
    proximo_passo: str
    # A `intencao` crua não é renderizada no contexto dinâmico (vira <ainda_falta>/<proximo_passo>);
    # está aqui porque o <ja_registrado> precisa dela p/ o extrator saber que já está registrada.
    intencao: str | None
    tipo_atendimento: str | None
    urgencia: str | None
    pix_status: str
    data_desejada: date | None
    horario_desejado: time | None
    horario_ja_combinado: bool
    horario_evidenciado: bool
    endereco: str | None
    bairro: str | None
    valor_fechado: str | None
    valor_aceito: bool
    duracao_fechada: str | None

    # Flags de disciplina materializadas no write-time (padrão A2 — agente/CLAUDE.md).
    # `dia_ja_sondado_hist` é a coluna crua; quem os templates leem é `dia_ja_sondado`, o OR dela
    # com o window-scan do turno (aplicado em `_anexar_contexto_dinamico`).
    n_contrapropostas: int
    n_perguntas_de_horario: int
    dia_ja_sondado_hist: bool
    book_ja_enviado: bool
    endereco_ja_enviado: bool
    amiga_ja_ofertada: bool
    foto_portaria_ja_pedida: bool
    motivo_resgate_ja_perguntado: bool

    # Ponto de encontro, já gated por estado/tipo (`_libera_local_de_encontro`). `local_endereco`
    # chega no degrau do estado — SEM o número da rua antes de o encontro estar de pé.
    local_endereco: str | None
    local_nome: str | None
    # Degrau do número, por ESTADO só (`_libera_numero_do_endereco`) — vale mesmo onde não há local
    # (externo/remoto); os templates só o leem dentro do `{% if local_endereco %}`. É o que faz a
    # instrução do bloco acompanhar o degrau em vez de mandar esconder um dado que ela tem.
    numero_liberado: bool

    # Cardápio e cliente.
    tabela_max_horas: float
    sem_periodo_longo: bool
    # Gate do cardápio de ATOS, da mesma leitura de fetiches do BP_MODELO: sem nenhum vínculo em
    # `modelo_fetiches` o <fetiches> dela sai "(sem fetiches cadastrados)" — não há extra a cotar
    # nem linha "Inclusos", e a cauda injeta o <sem_fetiches>. Mesma família derivada do cardápio.
    sem_fetiches: bool
    # Gate do <menage>, derivado do cardápio dela (mesma leitura de fetiches do BP_MODELO): sem a
    # seção "Por pessoa" no <fetiches>, menage/casal não existe pra ela e a cauda injeta o
    # <sem_menage>. É o padrão do `sem_periodo_longo` — a condição vira dado, não prosa.
    sem_menage: bool
    # Mesmo trilho para a vídeo chamada (ADR-0021/0029): sem o programa na tabela dela (as mesmas
    # linhas de `modelo_programas` que o <programas> do BP_MODELO renderiza), a chamada não é dela
    # e a cauda injeta o <sem_video_chamada> — a prosa que negava isso em quatro sites do BP_GERAL
    # sai. Default conservador `False` (não injeta) igual aos dois acima.
    sem_video_chamada: bool
    recorrente: bool
    observacoes_internas: str | None
    ultimo_motivo_perda: str | None
    cliente_nome: str | None
    historico_anteriores: str | None

    # Agenda das próximas 48h, com a aritmética já feita em Python (a IA só verbaliza).
    bloqueios: list[dict[str, Any]]
    disponibilidade: list[dict[str, Any]]
    horario_minimo: datetime | None
    proximo_horario: datetime | None
    janelas_livres: list[tuple[datetime, datetime]]

    # Percepção de tempo na cauda (emenda ADR 0025).
    min_desde_ultima_msg_cliente: int | None
    combinado_hora: str | None
    min_para_combinado: int | None

    # Resolvidos depois das queries, sobre a janela do turno — default para a construção não
    # precisar antecipá-los (ver `_anexar_contexto_dinamico`).
    dia_ja_sondado: bool = False
    # Ela já falou nesta parte da conversa? Gate do "não recumprimente" do `<antes_de_perguntar>`:
    # sem ele a cauda proibia, no ponto de recency máxima, a abertura que a `<abertura>` prescreve.
    conversa_em_andamento: bool = False

    def como_variaveis(self) -> dict[str, Any]:
        """Dicionário para o `render(**variaveis)` dos templates. Raso de propósito: os valores
        (datetimes, listas de bloqueio) vão por referência, como iam quando isto era um dict."""
        return dict(vars(self))
