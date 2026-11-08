# Formato e alcance dos relatórios

O formato inicial usa `schema_version: 1` e `profile: "epub-navigation-audit-v1"`. A auditoria trata uma rendição selecionada de um EPUB local. JSON é indicado para integração; Markdown apresenta os mesmos resultados para leitura.

O perfil é definido em [SPEC.md](../SPEC.md). Ele se baseia na Recomendação EPUB 3.3, mas não é um verificador integral dessa especificação ou um substituto do EPUBCheck.

## Envelope

| Campo | Significado |
| --- | --- |
| `schema_version` | Versão do formato deste relatório |
| `profile` | Identificador do perfil de checks |
| `filename` | Nome da origem, sem o caminho absoluto do host |
| `status` | `consistent`, `invalid` ou `incomplete` |
| `complete` | Se todos os checks deste perfil puderam ser concluídos |
| `options` | Seleção `rootfile` e apresentação `include_hrefs` |
| `limits` | Orçamentos aplicados à auditoria |
| `archive` | Contadores e hash do snapshot observado |
| `package` | Rootfiles, package selecionado, manifest, spine e caminho de navegação |
| `navigation` | Documento de navegação, contagem de `toc` e seus links |
| `documents` | Documentos XHTML/SVG selecionados e contagens de IDs |
| `summary` | Contagens dos metadados e links observados |
| `issues` | Erros, limitações e avisos do perfil |

Não são acrescentados relógio de geração, caminho absoluto da origem, rótulos do sumário, título, autores ou texto dos capítulos. A saída ainda contém nomes técnicos que podem ser sensíveis.

## Estados, completude e saídas

A precedência de `status` é:

1. `invalid` quando existe erro comprovado.
2. Caso contrário, `incomplete` quando algum check do perfil não pôde terminar.
3. Caso contrário, `consistent`.

Um erro comprovado não perde prioridade quando um limite posterior interrompe o trabalho. Por isso, `invalid` pode coexistir com `complete: false`. `consistent` permite avisos e significa somente que os checks deste perfil terminaram sem erro comprovado; não implica conformidade integral, segurança ou autenticidade.

| Saída CLI | Condição |
| --- | --- |
| `0` | `consistent`; também `--help` e `--version` |
| `1` | `invalid` |
| `2` | `incomplete` |
| `3` | Erro operacional, argumento inválido ou falha de saída |

Falhas de abertura e seleção são `AuditError(code, message)` na API. Argumentos inválidos levantam `ValueError`. Falhas estruturais de ZIP/XML são achados no relatório, com mensagens estáticas em português.

## Snapshot e arquivo

`archive` contém:

- `bytes`: tamanho informado para o arquivo capturado.
- `sha256`: SHA-256 dos bytes do snapshot, ou nulo quando não disponível.
- `entries`: entradas incluídas no inventário ZIP.
- `selected_member_reads`: quantidade de leituras selecionadas.
- `read_bytes`: bytes produzidos nessas leituras.

`read_bytes` pode chegar ao orçamento global mais um byte-testemunha, usado para comprovar excesso de limite ou de tamanho efetivo. Depois disso, não são iniciadas outras leituras para contornar o orçamento.

A origem regular é lida por descritor próprio e copiada de forma limitada para um arquivo temporário. Mudanças detectadas de identidade, tamanho ou tempos do descritor tornam a captura incompleta. Isso não é um snapshot transacional contra um escritor capaz de preservar os metadados observados.

O hash identifica os bytes capturados; não autentica a procedência. Membros não são extraídos para caminhos do host. Nome interno e href nunca autorizam abrir um arquivo do computador.

O perfil suporta membros armazenados ou deflate, nomes canônicos e leituras selecionadas com cabeçalho local, tamanho efetivo, CRC e descritor de dados conferidos. `mimetype` tem regras próprias de posição física e conteúdo. Alguns recursos ZIP válidos, como ZIP64, ficam fora do perfil e tornam o resultado incompleto em vez de serem chamados de corrupção sem evidência.

Recursos binários não selecionados não são descomprimidos nem recebem verificação integral de conteúdo/CRC. A existência de uma entrada no inventário não demonstra integridade de seus bytes.

## Package, manifest e spine

`package` contém `path`, `version`, `rootfiles`, `manifest`, `spine` e `nav_path`.

`rootfiles` lista os caminhos internos decodificados observados em `container.xml`, ou valores nulos quando uma referência está fora do perfil. Uma única rendição é selecionada automaticamente. Várias rendições sem `--rootfile` produzem `incomplete` com `rootfile_selection_required`. O argumento de seleção deve corresponder a um membro declarado; não deve ser uma URL ou caminho do host.

Cada entrada de `manifest` contém:

```json
{
  "id": "capitulo-1",
  "media_type": "application/xhtml+xml",
  "properties": [],
  "fallback": null,
  "path": "EPUB/capitulo-1.xhtml",
  "href_sha256": "...",
  "resolution": "local"
}
```

`resolution` é `local`, `remote` ou `unsupported`. Hrefs literais só aparecem com `include_hrefs=true`. A ordem dos itens do manifest é preservada; tokens em `properties` são ordenados. IDs repetidos e caminhos locais equivalentes repetidos são erros do perfil.

Cada entrada de `spine` contém `index`, `idref`, `linear`, `path` e `media_type`. O índice começa em 1 e a ordem declarada é preservada. O valor implícito de `linear` é verdadeiro; referências devem identificar itens únicos. Não se deduz a ordem de leitura pela ordem dos itens no manifest.

Fallback relevante ou conteúdo estrangeiro fora do alcance gera check incompleto. A presença de uma rendição selecionada não implica que outra rendição, layout, overlay ou recurso editorial tenha sido auditado.

## Navegação e referências

`navigation` contém `path`, `toc_count` e `links`. Somente os links do sumário `toc` fazem parte desta auditoria; `page-list`, `landmarks` e outras navegações não são cobertas.

Cada link contém:

| Campo | Significado |
| --- | --- |
| `index` | Ordinal a partir de 1, na ordem do documento |
| `href_sha256` | SHA-256 do href original |
| `target` | Caminho interno resolvido ou nulo |
| `fragment` | Fragmento simples decodificado ou nulo |
| `resolution` | Resultado da resolução dentro do perfil |
| `href` | Valor literal, somente com a opção explícita |

Resoluções possíveis:

| Valor | Interpretação |
| --- | --- |
| `resolved` | Destino e fragmento necessários foram resolvidos |
| `missing_member` | O destino local não existe como membro necessário |
| `missing_fragment` | O fragmento simples não identifica um ID observado |
| `not_manifested` | O alvo não possui declaração de manifest correspondente |
| `not_spine` | O alvo está fora do spine, sem ambiguidade de fallback no perfil |
| `not_content` | O alvo não possui o tipo de documento de conteúdo necessário |
| `unsupported` | A referência ou a construção está fora do perfil |
| `target_unavailable` | O documento necessário não pôde ser analisado |

Não se inventa `missing_member` ou `missing_fragment` quando a referência não pôde ser interpretada fielmente. EPUB CFI, XPointer, `svgView` e outras microssintaxes reconhecíveis ficam incompletas. Um href sem fragmento, ou com `#` vazio, aponta para o documento inteiro e não exige um ID especial.

O perfil não exige que todo documento do spine tenha um link no sumário. Uma comparação simples de ordem pode gerar `warning/toc_order`; não transforma uma diferença de ordem em erro obrigatório.

## Documentos e IDs

Cada item de `documents` contém `path`, `media_type`, `ids` e `complete`. São documentos XHTML/SVG selecionados para navegação, spine ou destinos locais, capturados uma vez e ordenados pelo caminho na apresentação.

`ids` é uma contagem; a lista de valores dos IDs não é exportada. Valores de `id` e `xml:id` são exatos e distinguem maiúsculas de minúsculas. O mesmo valor nos dois atributos de um único elemento conta uma vez; sua repetição em elementos diferentes é um erro `duplicate_id`. Fragmentos dos links permanecem visíveis no relatório.

Não são interpretados aliases de `a/name`, um suposto `#top`, layout de página ou comportamento de um leitor HTML. A ausência de rótulos de texto no relatório é intencional; a qualidade dos rótulos não é validada pelo perfil.

## URLs e XML

O resolvedor aceita um subconjunto explícito de referências locais: caminhos relativos dentro da raiz, nomes Unicode, espaços, percent-encoding UTF-8 e fragmentos simples. Na procura de um caminho no inventário, usa equivalência canônica NFC e devolve o nome físico do membro ZIP, preservando sua grafia. Não faz busca sem distinguir maiúsculas de minúsculas nem uma segunda decodificação de `%25`. Nomes equivalentes por normalização canônica ou por normalização com full case folding no inventário são rejeitados como ambíguos; isso não autoriza busca caseless.

IDs e fragmentos continuam exatos. Se um fragmento ausente diferir de um ID existente apenas na normalização Unicode, o resultado registra `fragment_normalization_unsupported` e fica incompleto, sem presumir equivalência.

Query, caminhos enraizados, escape acima da raiz, separadores codificados, controles, backslashes e URLs ambíguas ficam fora do perfil. Segmentos ponto, inclusive formas percent-encoded previstas no contrato, são tratados antes da decodificação dos nomes. A classificação remota não inicia uma requisição. Veja [SPEC.md](../SPEC.md#perfil-de-urls) para a lista completa.

Namespaces são comparados por URI, não pelo prefixo escolhido no XML. O parser usa `defusedxml` com DTD, entidades e referências externas proibidas. DOCTYPE, `xml:base`, XHTML `base` e conteúdo protegido podem impedir o check; não são tratados automaticamente como XML malformado. O programa não processa XInclude nem executa CSS, JavaScript ou transformações.

## Achados e resumo

Cada achado possui `severity`, `code`, `message`, `path` e `location`.

- `severity`: `error`, `incomplete` ou `warning`.
- `code`: identificador estável do tipo de achado.
- `message`: explicação estática em português, sem texto do livro ou URL bruta.
- `path`: membro EPUB relacionado ou nulo, não um caminho absoluto do host.
- `location`: ordinal relacionado, a partir de 1, ou nulo.

Os achados seguem ordem de gravidade, caminho, localização, código e mensagem. Ao atingir `max_issues`, um marcador `issue_limit` torna visível a interrupção e preserva a prioridade de um erro já observado.

`summary` contém `manifest_items`, `spine_items`, `nav_links`, `resolved_links`, `xml_documents` e `xml_nodes`. São contagens do conjunto observado, não páginas renderizadas, palavras, qualidade editorial ou cobertura completa da especificação.

`xml_documents` conta documentos XML únicos cuja análise começou, incluindo `container.xml` e o OPF. Já `documents` lista somente os XHTML/SVG selecionados; portanto, seu tamanho não precisa coincidir com essa contagem do resumo.

## Limites

| Campo | Padrão | Teto aceito |
| --- | ---: | ---: |
| `max_archive_bytes` | 33.554.432 | 268.435.456 |
| `max_members` | 4.096 | 20.000 |
| `max_xml_bytes` | 2.097.152 | 16.777.216 |
| `max_total_read_bytes` | 16.777.216 | 134.217.728 |
| `max_name_bytes` | 1.024 | 4.096 |
| `max_xml_nodes` | 100.000 | 1.000.000 |
| `max_xml_depth` | 128 | 512 |
| `max_links` | 20.000 | 100.000 |
| `max_issues` | 1.000 | 10.000 |

Todos exigem inteiros positivos de tipo exato; booleanos não são inteiros aceitos. Na CLI, os nomes usam hífen, como `--max-xml-nodes`.

O orçamento de links é compartilhado entre entradas relevantes de rootfiles, manifest, spine e navegação. Bytes XML contam o tamanho físico da leitura, inclusive UTF-16. Documentos e leituras são reutilizados; esgotar um orçamento global não autoriza repetir a análise para contorná-lo.

Os limites controlam resultados e leituras, sem prometer sandbox, deadline ou teto rígido de memória nativa. O snapshot pode usar disco temporário. Falha ou interrupção conserva a distinção entre erro comprovado e parte ainda não verificada.

## Apresentação e publicação de saída

JSON é determinístico, usa escapes ASCII e termina com LF. Markdown escapa HTML, Markdown e controles presentes em valores técnicos. Nenhum desses formatos é um leitor do livro ou executa seu conteúdo.

`--output` usa arquivo temporário no mesmo diretório, sincronização e publicação exclusiva por link, sem sobrescrever um destino concorrente. A origem nunca é substituída. Filesystems sem suporte geram falha em vez de fallback de sobrescrita; o diretório pai precisa existir. Isso não constitui promessa de durabilidade contra falha física.
