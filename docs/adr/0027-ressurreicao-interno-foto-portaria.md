---
status: accepted
---

# Ressurreição do atendimento interno auto-timed-out pela Foto de portaria

O timeout interno (ADR 0024) marca o atendimento `Perdido`/`sumiu` quando passa `GREATEST(aviso_saida_em, bloqueio.inicio) + 45min` sem **Foto de portaria**, e cancela o bloqueio (libera o slot). Mas o cliente pode chegar **depois** dessa desistência e mandar a **Foto de portaria** — prova física de presença no local da modelo. Hoje essa foto fica **órfã** (não casa o gate `Aguardando_confirmacao → Em_execucao`, pois o atendimento já é `Perdido`) e a volta tende a abrir um **novo #N em `Novo`** (recorrência fragmentada). Tratar como "novo atendimento" quem literalmente **chegou para o horário combinado** é errado operacionalmente.

Caso real (rig Lucia, 18/06/2026): #1 interno morreu por timeout; a Foto de portaria chegou ~10 min depois, com o cliente no local — e foi orfanada.

## Decisão

- Uma **Foto de portaria** que chega num par cujo interno mais recente é um `Perdido` por **`auto_timeout_interno`** **ressuscita** esse atendimento — volta a `Em_execucao`, `ia_pausada=true` (`modelo_em_atendimento`), reativa o bloqueio cancelado e emite o card "cliente chegou" — em vez de orfanar/fragmentar, **se e só se**:
  - a morte foi **`auto_timeout_interno`** (não `Perdido` humano/explícito — decisão humana se respeita);
  - o **slot ainda está livre** (nenhum bloqueio ativo ocupou o horário depois do cancelamento — sem sobreposição);
  - ainda **dentro do `bloqueio.fim`** (o horário reservado não acabou).

- **Fora disso → novo #N** (recorrência legítima): volta horas/dias depois (passou do `fim`), slot já realocado a outro atendimento, ou volta por **mensagem** (não foto).

- **Ressurreição é o backstop do timeout (ADR 0024).** Com o piso no horário, a maioria das fotos chega **antes** da desistência e nem precisa ressuscitar; a ressurreição cobre só as que chegam **após** `GREATEST(aviso, horário) + 45min`.

## Considered Options

- **Não ressuscitar** (`Perdido` é terminal; recorrência = novo atendimento). Rejeitado: a Foto de portaria é prova de **chegada física**; fragmentar em #1 `Perdido` + #2 órfão é errado operacionalmente.

- **Janela fixa após o timeout** (reconectar qualquer volta em até X min). Rejeitado: arbitrário e desligado do domínio; uma foto às 21h05 para um encontro de 22h cairia fora mesmo sendo a mesma visita. A âncora no `bloqueio.fim` usa o slot reservado como janela natural.

- **Foto sempre reconecta o último interno morto**, sem janela. Rejeitado: uma foto dias depois (nova visita) reviveria um #1 stale e ignora se o slot foi ocupado por outro atendimento.

## Consequences

- **Exceção explícita ao invariante "`Perdido` é terminal"** (verbete *Estados do atendimento*): um `auto_timeout_interno` `Perdido` pode voltar a `Em_execucao` por sinal forte (foto) dentro do slot livre. É auto-transição, sem humano — registrado para não surpreender quem vir um `Perdido` virar `Em_execucao`.

- **Implementado** em `dominio/atendimentos/service.py::ressuscitar_interno_foto_portaria` (candidato + 4 efeitos atômicos numa transação) e no gatilho `workers/media.py::rotear_imagem` (ramo `atendimento is None`, antes do fora-fluxo, mais o helper `_ressurreicao_foto_portaria`). Não houve colisão real com a sessão paralela: o gate da foto vive em `media.py`/`atendimentos/service.py`, fora do diff de buffer/agenda dela. Cobertura `needs_db` em `tests/integracao/test_foto_portaria.py` (happy + 3 guardas: pós-`fim`, slot ocupado, `Perdido` humano).

- **Reativar bloqueio cancelado:** o `cancel_bloqueio` do timeout (ADR 0024) põe `estado='cancelado'` (salvo `em_atendimento`/`concluido`). A ressurreição checa **não-sobreposição** (`NOT EXISTS` sobre bloqueios ativos) antes de voltar o bloqueio a `em_atendimento`; a EXCLUDE constraint da agenda é o backstop contra corrida.

- **`CONTEXT.md` (verbete Foto de portaria) atualizado** com o mecanismo de ressurreição agora que a decisão está implementada.
