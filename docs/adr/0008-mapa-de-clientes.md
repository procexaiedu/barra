# Mapa de clientes

Na reunião, o cliente (Rossi) pediu um mapa com todos os clientes plotados como pins
(estilo Google Maps) para ler a concentração geográfica da demanda e direcionar marketing e
operação — um mapa **agregado**, não um mapa por cliente. A localização geográfica já é
persistida por atendimento (`latitude`/`longitude`/`endereco_formatado`/`place_id`, migration
0041, via autocomplete Google Places); o **cliente** não tem endereço próprio. Ver termo em
`CONTEXT.md`.

## Decisões

- **Um pin por cliente, só atendimentos externos.** O pin fica na coordenada do **atendimento
  externo** mais recente com `lat/lng` do cliente. Atendimentos **internos** ficam de fora: lá
  o endereço combinado é o ponto de encontro na modelo (o cliente vai até ela), então plotá-lo
  mediria a localização das *modelos*, não de onde os clientes estão — contaminando justamente
  o sinal que o mapa existe para mostrar. Cliente sem nenhum externo geocodificado **não some**:
  entra num contador "sem localização".
- **Reuso do dado existente, sem schema novo.** `latitude/longitude/endereco_formatado/bairro`
  já existem em `atendimentos` (0041). O mapa é só leitura; nenhuma coluna nova, nenhuma
  migration.
- **Endpoint dedicado, não paginado.** `GET /clientes/mapa`, SQL inline em
  `dominio/clientes/routes.py` (o contexto `clientes` não tem `repo.py`/`service.py` — seguimos
  o estilo existente). Retorna **todos os pontos de uma vez** (mapa agregado precisa do conjunto
  inteiro), cada um com `cliente_id, nome, lat, lng, bairro, total_atendimentos, valor_total`,
  mais `total_sem_localizacao`. Os totais agregam **todas as modelos** do cliente (reusam o
  `LEFT JOIN LATERAL` da listagem de clientes) — consistentes com os cards da Lista e com o
  caráter cross-modelo do painel.
- **Painel-only, sem mudança de auth.** O mapa é cross-modelo por natureza (agrega todos os
  pares do cliente), logo é exclusivo de Fernando, como o **Perfil físico preferido** (ADR 0006);
  a **IA por modelo** nunca o acessa. Endereços já são visíveis no painel autenticado — nada novo
  de privacidade no P0.
- **Google Maps, reusando o loader já no projeto.** `@googlemaps/js-api-loader` (já é dependência,
  usado pelo autocomplete) carrega as libs `maps`/`marker`; o mapa é montado de forma imperativa com
  `google.maps.Marker` clássico + `@googlemaps/markerclusterer` (única dependência nova), reusando a
  chave `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`. Escolhido `Marker` clássico em vez de `AdvancedMarker` para
  **não exigir um Map ID de nuvem** (sem ele o AdvancedMarker fica invisível — modo de falha que
  dependeria de setup extra); e o loader existente em vez de `@vis.gl/react-google-maps` para não rodar
  um segundo mecanismo de carregamento do Google em paralelo. Custo irrelevante (um operador, no tier
  grátis).
- **Aba dentro de Clientes.** Abas **Lista | Mapa** no topo do módulo Clientes (não rota dedicada
  nem item de menu próprio), como o cliente pediu ("dentro de clientes"); "Lista" é a tela atual
  intacta. Reaproveita os filtros da toolbar (modelo, e de graça período/arquivados).
- **Enquadra no Brasil, navegação livre.** Ao abrir, dá `fit` nos pins (ou no Brasil); zoom/pan
  livres, sem travar limites. Clustering ativo; **InfoWindow ao clicar** com nome, bairro, nº de
  atendimentos e **Valor final** somado dos `Fechado`.

## Considered Options

- **Pin por cliente sem distinguir interno/externo / um pin por atendimento / fallback
  geocodificando o bairro texto-livre on-the-fly:** dariam mais cobertura de pins, mas misturam
  localização de modelo (interno) com localização de cliente (ruído para marketing) ou adicionam
  custo de Geocoding e complexidade. Rejeitados a favor da fidelidade do sinal.
- **Mapbox / Leaflet + OpenStreetMap:** mais baratos em escala, mas exigem conta e stack nova
  (Mapbox) ou provedor de tiles próprio (os tiles públicos do OSM não são permitidos em produção
  comercial); o ganho de custo é irrelevante para um operador. Rejeitados a favor de consistência
  com o Google já integrado.
- **Rota dedicada `/clientes/mapa` ou item próprio no menu lateral:** contrariam o pedido de ficar
  "dentro de clientes". Rejeitados.
- **Dar endereço/`lat`/`lng` próprios ao cliente:** duplicaria dado que já vive no atendimento e
  exigiria uma captura nova; o externo mais recente já é o melhor proxy disponível. Rejeitado.

## Consequences

- No piloto, há poucos atendimentos externos geocodificados → o mapa nasce **esparso** e o
  contador "sem localização" carrega o peso até o uso amadurecer (espelha a linha "não
  classificadas" do ADR 0006).
- O endpoint não paginado é aceitável no volume do P0 (dezenas–centenas de clientes); se crescer
  muito, vira candidato a bounding-box / tile server.
- A exclusão dos internos é **deliberada**: se um dia a operação quiser um "mapa de onde
  acontecem os atendimentos" (internos = casa das modelos), isso é outra visão, não um bug a
  corrigir nesta.
- Sem migration: a única dependência de dado (lat/lng em `atendimentos`) já está aplicada (0041).
