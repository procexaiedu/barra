#!/usr/bin/env bash
# Builda a imagem da EvoGo com o patch de view-once (Mídia exclusiva).
#
# RODA NA VPS (manager1), que é onde há Docker. O Swarm tem 1 nó só, então a imagem local
# basta — não precisa registry. NÃO toca prod: só cria a imagem. Trocar o serviço para ela é
# passo à parte (§0), ver docs/evolution-view-once.md.
#
# Base = 0.7.1, que é a versão EXATA rodando em prod (confirmado comparando o swagger vivo de
# https://evogo.procexai.tech com o de cada tag). Buildar de `main` embutiria um upgrade de
# versão junto com o patch — não faça isso sem querer.
#
# A 0.7.1 depende do fork whatsmeow da EvolutionAPI como SUBMÓDULO (`whatsmeow-lib`, replace no
# go.mod) e o Dockerfile copia esse diretório — sem --recurse-submodules o build quebra.
#
# Uso:  ./build-evogo-viewonce.sh /caminho/para/evolution-go-view-once-0.7.1.patch
set -euo pipefail

PATCH="${1:?uso: $0 <caminho do evolution-go-view-once-0.7.1.patch>}"
BASE="${BASE:-0.7.1}"
TAG="${TAG:-evolution-go:${BASE}-viewonce1}"
WORKDIR="${WORKDIR:-/tmp/evogo-fork}"

echo "== espaço em disco (o build precisa de alguns GB; a VPS já chegou a 384G/387G) =="
df -h /

echo "== clone da tag $BASE, com submódulo whatsmeow-lib =="
rm -rf "$WORKDIR"
git clone --recurse-submodules --branch "$BASE" \
  https://github.com/evolution-foundation/evolution-go.git "$WORKDIR"
cd "$WORKDIR"
test -f whatsmeow-lib/go.mod || { echo "ERRO: submódulo whatsmeow-lib não veio"; exit 1; }

echo "== aplica o patch =="
git am <"$PATCH"
git log --oneline -1

echo "== build ($TAG) =="
docker build --build-arg VERSION="${BASE}-viewonce1" -t "$TAG" .

echo
echo "Imagem pronta: $TAG"
echo "Próximo passo (ATINGE PROD — exige autorização explícita):"
echo "  docker service update --image $TAG --force evolution-go_evolution_go"
