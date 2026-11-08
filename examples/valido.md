# Auditoria de navegação EPUB

**Estado:** consistent

**Checks do perfil completos:** sim

**Arquivo:** valido\.epub

**SHA-256 do snapshot:** f9654fba594c3b443fd5d1bcd78ab8a22dd253fa42a1d752c45def3ca87ed810

Resultado do perfil epub-navigation-audit-v1. Não é validação integral EPUB nem certificação de acessibilidade, segurança ou procedência.

## Cobertura

| Métrica | Valor |
| --- | --- |
| manifest\_items | 3 |
| spine\_items | 2 |
| nav\_links | 2 |
| resolved\_links | 2 |
| xml\_documents | 5 |
| xml\_nodes | 44 |

| Captura do arquivo | Valor |
| --- | --- |
| bytes | 2101 |
| sha256 | f9654fba594c3b443fd5d1bcd78ab8a22dd253fa42a1d752c45def3ca87ed810 |
| entries | 6 |
| selected\_member\_reads | 6 |
| read\_bytes | 2230 |

## Rendição selecionada

**Package:** EPUB/package\.opf

**Version:** 3\.0

**Nav:** EPUB/nav\.xhtml

### Rootfiles

| Caminho |
| --- |
| EPUB/package\.opf |

### Manifest

| ID | Caminho local | Media type | Propriedades | Fallback | Resolução | SHA\-256 do href |
| --- | --- | --- | --- | --- | --- | --- |
| nav | EPUB/nav\.xhtml | application/xhtml\+xml | nav | — | local | a09f11164f47d1e1d670a4ae7ca375d0ac42d55ce5c4739b83067b0075bc496d |
| intro | EPUB/text/inicio\.xhtml | application/xhtml\+xml |  | — | local | 89ff573006170fc6fadb15cfa83724fbe82412de597a7d3bbc6c1040be7ca190 |
| final | EPUB/text/café\.xhtml | application/xhtml\+xml |  | — | local | 76d58cd86053f2c150e9966b8c41fa7266ef0d08b309df9a5f7c9f5695550180 |

### Ordem de leitura

| Posição | IDref | Linear | Caminho | Media type |
| --- | --- | --- | --- | --- |
| 1 | intro | sim | EPUB/text/inicio\.xhtml | application/xhtml\+xml |
| 2 | final | sim | EPUB/text/café\.xhtml | application/xhtml\+xml |

## Links do sumário

**Navs toc encontrados:** 1

| Posição | Destino | Fragmento | Resolução | SHA\-256 do href |
| --- | --- | --- | --- | --- |
| 1 | EPUB/text/inicio\.xhtml | inicio | resolved | 8e351692b8cfa909d06dd3c58b0dbd9063639959aab8ed760f11591fd7d257cb |
| 2 | EPUB/text/café\.xhtml | fim | resolved | 499e052cd6956cc33f7620d6351ac56fdfc7357ddfe84eab0069383cb094b43a |

## Documentos selecionados

| Caminho | Media type | IDs | Completo |
| --- | --- | --- | --- |
| EPUB/nav\.xhtml | application/xhtml\+xml | 1 | sim |
| EPUB/text/café\.xhtml | application/xhtml\+xml | 1 | sim |
| EPUB/text/inicio\.xhtml | application/xhtml\+xml | 2 | sim |

## Achados

Nenhum achado neste perfil.
