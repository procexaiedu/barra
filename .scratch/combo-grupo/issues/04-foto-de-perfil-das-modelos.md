# 04 — Foto de perfil das modelos ativas

**O que construir:** cada modelo precisa ter uma foto de perfil cadastrada (`foto_perfil_object_key`), porque é ela que a **Modelo do canal** mostra ao apresentar uma **Modelo convidada**. Hoje **nenhuma** das duas modelos não-inativas tem foto.

A escolha de mostrar foto na oferta não é estética: o cliente **nunca viu** a convidada — não viu anúncio dela, não a escolheu. Diferente da modelo do canal, sobre quem a persona assume que *"quem te chama já te escolheu: viu seu anúncio, viu suas fotos e veio"*. O corpus do vendedor confirma que ele pede (*"você atende com amiga? tem link dela"*, *"e sua amiga / vc conseguiu as fotos?"*) e que avalia (*"não curti sua amiga não"*).

É uma foto por modelo, distinta do **book** (2-3 fotos + vídeo) que continua exclusivo do canal.

**Bloqueado por:** nenhum — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] `foto_perfil_object_key` populado para todas as modelos não-inativas
- [ ] A foto é recuperável pelo caminho de envio de mídia já existente
- [ ] Definido e documentado o critério da foto (enquadramento de vitrine, não de book)
- [ ] Modelo sem foto não quebra nada — degrada para nome e preço
