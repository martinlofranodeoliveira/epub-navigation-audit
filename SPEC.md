# Contrato público · EPUB Navigation Audit 1

Biblioteca e CLI Python3.11+ para auditar navegação EPUB3 local sem renderizar, extrair membros ou executar conteúdo. Perfil próprio baseado na Recomendação EPUB3.3 de13/01/2026: https://www.w3.org/TR/2026/REC-epub-33-20260113/. Não substitui EPUBCheck nem valida integralmente EPUB, acessibilidade, CSS, scripts, metadados editoriais ou a integridade de todos os recursos binários.

Dependência de runtime: defusedxml0.7.1. Sem rede, subprocessos ou Java durante auditoria. Java/EPUBCheck e Node são apenas oráculos independentes de desenvolvimento, nunca dependências de execução.

## Organização dos módulos

- model.py: limites, estados e diagnósticos compartilhados.
- archive.py: captura privada, inventário ZIP e leitura limitada de membros selecionados.
- semantic.py, urls.py e xmlsafe.py: resolução de referências e análise estrutural XML.
- api.py, cli.py e report.py: composição da auditoria, interface de terminal e relatórios.
- scripts/, tests/, examples/ e docs/: verificação da distribuição, oráculos independentes, exemplos originais e documentação.

Os algoritmos de ZIP e publicação exclusiva adaptados de projetos anteriores da LOFRANO TECNOLOGIA mantêm as atribuições em THIRD_PARTY_NOTICES.md.

## API pública

`from epub_navigation_audit import AuditError, AuditLimits, audit_epub, to_json, to_markdown`

`audit_epub(path, *, rootfile=None, include_hrefs=False, limits=AuditLimits()) -> dict`

Argumentos inválidos -> ValueError (tipos exatos de bool/inteiros). AuditError(code,message) para origem ausente/não regular/ilegível, seleção de rootfile inexistente e saída impossível; mensagens constantes PT-BR sem caminho absoluto, texto do livro ou erro cru de bibliotecas. Falha de estrutura ZIP/XML da entrada é achado, não traceback.

`rootfile` é caminho de membro decodificado, não URL, para selecionar uma rendição declarada. Com uma rootfile, escolha automática; com várias e sem seleção explícita, `incomplete/rootfile_selection_required`, sem adivinhar. Seleção explícita que não consta do container -> AuditError(rootfile_not_listed). Outra rendição não é auditada nem alegada como coberta.

## Resultado

```json
{
 "schema_version":1,"profile":"epub-navigation-audit-v1","filename":"exemplo.epub",
 "status":"consistent","complete":true,
 "options":{"rootfile":null,"include_hrefs":false},"limits":{},
 "archive":{"bytes":null,"sha256":null,"entries":null,"selected_member_reads":0,"read_bytes":0},
 "package":{"path":null,"version":null,"rootfiles":[],"manifest":[],"spine":[],"nav_path":null},
 "navigation":{"path":null,"toc_count":0,"links":[]},
 "documents":[],"summary":{"manifest_items":0,"spine_items":0,"nav_links":0,"resolved_links":0,"xml_documents":0,"xml_nodes":0},
 "issues":[]
}
```

`status`: invalid se houve erro comprovado, mesmo com captura incompleta; senão incomplete se algo do perfil não pôde ser concluído; senão consistent. `complete` indica completude apenas dos checks deste perfil e independe do status invalid. Recursos declarados fora de checks (ex.: imagem não ligada à navegação) não são verificados nem contam como checks incompletos por si só. Não há data de geração ou caminho absoluto da origem. SHA256 identifica bytes do snapshot capturado, não autenticidade. Campos bytes/entries null significam que a abertura foi interrompida antes de disponibilizar o inventário.

Achado `{severity:error|incomplete|warning,code,message,path:null|string,location:null|int}`. path é membro EPUB; location pode ser ordinal1-based de link/item. Mensagens estáticas; nomes técnicos/IDs/fragmentos podem ser sensíveis, portanto relatório não é anônimo. Não copiar labels, título, autores, texto de capítulos nem metadados DC. Por padrão não inclui href original: grava href_sha256. `include_hrefs=True` acrescenta href literal aos registros manifest/nav, inclusive URLs que podem conter credenciais/query; opção explícita e aviso na documentação. Não incluir valor bruto de URL em mensagens de erro.

Manifest: `{id,media_type,properties:[tokens ordenados],fallback:null|string,path:null|string,href_sha256,resolution:local|remote|unsupported,href?:str}`. Ordem original preservada.

Spine: `{index:1,idref,linear:bool,path:null|string,media_type:null|string}`. Ordem original preservada; não ordenar pelo manifest. Defaults linear=yes; valor diferente de yes/no é erro. idref deve identificar item único, sem duplicação de itemref, ao menos um linear. Core content XHTML/SVG é lido para IDs; foreign content/fallback chain relevante fora do perfil -> incomplete, não erro inventado. Destinos TOC precisam ser top-level content documents, isto é, spine direto ou fallback (esta última forma é incompleta neste perfil).

Navigation link: `{index:1,href_sha256,target:null|string,fragment:null|string,resolution:resolved|missing_member|missing_fragment|not_manifested|not_spine|not_content|unsupported|target_unavailable,href?:str}`. Somente links do nav toc; todos em ordem de documento. Não avaliar landmarks/page-list/outras navs neste perfil. Ordens TOC versus spine divergentes são no máximo warning, nunca erro obrigatório. Sem labels textuais no relatório.

Document: `{path,media_type,ids:int,complete:bool}` para XHTML/SVG selecionados (nav, spine e alvos locais). Não listar valores dos IDs exceto fragmentos de links. Ordenar documents por path. Capturar cada documento uma vez. IDs são atributos id e xml:id, exatos e case-sensitive; aliases iguais no mesmo elemento contam uma vez; o mesmo valor em elementos diferentes é erro duplicate_id. Não interpretar a/name, #top nem renderização HTML. Fragmento vazio indica documento inteiro; ausência ou # vazio não exige ID. EPUB CFI/XPointer/svgView e outras microssintaxes reconhecíveis -> incomplete, nunca missing_fragment por ignorá-las.

## Limites e coletor compartilhados (model.py)

AuditLimits congelado, tipo exato int positivo (bool rejeitado); tetos explícitos em model. Padrões:

max_archive_bytes=33554432; max_members=4096; max_xml_bytes=2097152; max_total_read_bytes=16777216; max_name_bytes=1024; max_xml_nodes=100000 (global); max_xml_depth=128; max_links=20000 (global links/manifest/spine/rootfiles); max_issues=1000.

Coletor `Issues(limit)` com `.items` (Issue dataclass), `.error` bool, `.partial` bool. `.add(severity,code,message,path=None,location=None)` registra e atualiza flags; incomplete torna partial. `.stop(...)` marca partial, registra e levanta StopAudit. Limite reserva issue_limit e levanta StopAudit; erro já comprovado nunca deve perder prioridade invalid, mesmo quando diagnóstico é resumido. `_Stop` de arquivo e XML devem virar achados ou StopAudit, não ser engolidos como sucesso.

O contador read_bytes pode usar um byte-testemunha adicional para comprovar excesso efetivo e então parar a fila. Orçamentos limitam resultados/leitura. Não são sandbox, deadline ou teto rígido para memória nativa/preparação/árvore; o snapshot pode usar disco temporário. Após orçamento global esgotado, não repetir leitura/análise para contornar limite. Textos XML contam em bytes físicos inclusive UTF16. Limitar nós/profundidade enquanto constrói árvore; não só depois de materializá-la.

## ArchiveSnapshot (arquivo)

`with open_snapshot(path, *, limits, issues) as archive:`; contexto garante fechamento também em StopAudit. Origem existente regular, symlink regular pode ser seguido; usar descriptor próprio e confirmar fstat. Não modificar/extrair origem. Snapshot para TemporaryFile limitado em blocos; calcular SHA256 e detectar mudança de identidade/tamanho/mtime/ctime entre início e fim. Mudança detectada -> incomplete e parar; não prometer snapshot transacional contra escritor malicioso que preserve metadados.

Antes de ZipFile criar ZipInfo, conte/valide diretório central com orçamento max_members; não confiar só no contador EOCD. Reutilizar prova contra EOCD ambíguo, prefixos, bytes após trailer, ZIP64 e extensões: fora do perfil => incomplete. Estrutura contraditória/truncada -> error. ZIP64 é permitido por EPUB, não rotular invalid só por não suportar. Não oferecer perfil geral de arquivos arbitrários.

Interface archive: `.entries` dict nome->Entry com campos `name,size,compressed_size,crc32,compression,header_offset,flags,directory,local_extra_size`; `.archive_bytes`, `.sha256`, `.read_bytes`, `.selected_member_reads`; `.read(name, *, max_bytes=None)->bytes|None` (defaultmax_xml_bytes). None indica membro ausente/ilegível/incompleto e coletor já contém diagnóstico quando falha de leitura. Ausência simples pode ser detectada pelo chamador antes de read. Cache inclui falhas para não repetir; global max_total_read_bytes conta somente bytes efetivamente produzidos de leituras únicas. Root coleta os contadores depois da semântica.

Inventário de nomes únicos (inclusive comparação de caminhos completos por normalização canônica e fullcasefold), relativos/canônicos, sem NUL, backslash, colon, segmentos vazios/dot/dotdot ou arquivos usados como diretórios; caminhos fora do perfil de nomes -> incomplete, não alegar conformance OCF completa. Não confundir diretório com arquivo. Usar nomes UTF8 quando sinalizados; nomes nãoASCII sem flagUTF8 fora do perfil. Não seguir links/tipos especiais dentro ZIP. Métodos store/deflate. ZIP encryption é proibida por OCF e pode ser error; compressões/flags fora do perfil são incomplete sem descompressão.

Leituras selecionadas verificam cabeçalho local vs central, limites físicos, descompressão bounded inclusive tamanho efetivo além de declaração, EOF deflate, CRC, tamanho real e data descriptor (com/sem assinatura). Não usar apenas ZipExtFile truncado por file_size para esconder dados. Nunca ler XML de outro membro automaticamente nem abrir caminhos de host a partir de href. Alvos binários não selecionados não são descomprimidos/CRC-checked.

Arquivo mimetype deve ser primeiro fisicamente (offset0), stored, não encrypted, sem extra local e bytes exatos20 `application/epub+zip`. Contradições de mimetype são erro de perfil OCF; pode continuar com container se leitura estrutural permitir. Nomes/ordem do diretório central não substituem ordem física de cabeçalhos.

## XML seguro

Usar DefusedXMLParser com forbid_dtd=True, forbid_entities=True, forbid_external=True, target TreeBuilder com orçamento compartilhado de nós/profundidade enquanto parseia. UTF8/UTF16 aceitos pelo parser. DOCTYPE, mesmo legal/inofensivo, é fora do perfil -> incomplete, não XMLinvalid. XML malformado -> error; XML limit -> incomplete. Não carregar DTD/XInclude, executar CSS/JS, expandir entidades ou usar rede. Não buscar texto para labels.

Namespaces por URI, não prefixo: container urn:oasis:names:tc:opendocument:xmlns:container; OPF http://www.idpf.org/2007/opf; XHTML http://www.w3.org/1999/xhtml; SVG http://www.w3.org/2000/svg; epub:type http://www.idpf.org/2007/ops; xml:id/base http://www.w3.org/XML/1998/namespace. Prefixos arbitrários equivalentes devem funcionar.

`xml:base` ou XHTML base em documento relevante -> incomplete; não resolver refs ignorando base e inventar missing_member. `META-INF/encryption.xml` presente -> incomplete/ocf_encryption_unsupported e não tentar descriptografar nem parsear capítulos criptografados. Container pode ser inventariado, mas semântica da rendição para antes de conteúdo protegido.

## Container, package, nav

container.xml raiz/namespace corretos, version1.0 e rootfiles/rootfile(s) com media-type application/oebps-package+xml. full-path é URL path-relative-scheme-less relativa à raiz do EPUB; resolver percent-encoding pelo mesmo perfil, sem query/fragment. Expor rootfiles como caminhos decodificados ou null se fora perfil. OPF selecionado deve existir como arquivo e raiz package namespaceOPF. package@version3.0 é o suportado; outras versões => incomplete/version_unsupported, não classificar EPUB2 válido como inválido.

Manifest e spine containers únicos; item tem id/href/media-type necessários não vazios. IDs de manifest repetidos erro; paths locais equivalentes repetidos erro. Manifest href com fragment/query fora perfil; referências remotas inventariadas sem contato externo e sem incluir URL literal por padrão. Manifest assets locais fora da navegação só têm presença conferida, sem XML/CRC integral. Falha de recurso local ausente é error; href fora perfil gera incomplete sem fabricar path. Exatamente um item nav e media-type XHTML. Campos editoriais/DC, fallback completo, semântica CSS/JS fora checks.

Nav XHTML raiz correta; exatamente um nav cujo epub:type token contém toc. Verificar estrutura básica de ol/li aninhados: nav toc tem ol primário, li começa com a[href] ou span, seguido no máximo por ol; span exige sublista. Não exigir texto direto como label: imagens/alt/title são legais e a qualidade dos labels não é validada aqui. Links dentro dos itens são auditados em ordem; evitar confundir links de outrasnavs. Iteração/budget sem recursão ilimitada.

TOC link local deve identificar item manifest único XHTML/SVG e top-level via spine, ou caminho de fallback não suportado => incomplete. Falhas de path ausente, alvo não manifestado, fora spine quando não há ambiguidade de fallback, fragmento inexistente e ID duplicado são errors. Não afirmar que documento sem link no TOC é inválido. Comparação simples da primeira ocorrência de alvos TOC diretos com posições lineares do spine pode gerar warning toc_order, nunca error.

## Perfil de URLs

`urls.py` exporta `resolve_reference(base_path, reference)->dict {kind:local|remote|unsupported,path:null|string,fragment:null|string,reason:null|string}`. Pure sem coletor; base_path é membro físico já canônico; para URLs relativasàraiz use base_path=''. Parse com bibliotecas padrão e regras explícitas compatíveis com WHATWG no subconjunto aceito. Sem query, controles, backslash, credenciais/autoridade, scheme local/file/data/js nem acesso ao host. Scheme/authority remotos => kindremote sem ecoar URL; o chamador decide se recurso remoto participa de checks e portanto incomplete.

Suportar nomes Unicode, espaços, UTF8 percent-encoding, fragmentos simples decodificados, caminho vazio/#fragment, ./ e ../ no interior da raiz e segmentos percent-encoded dot `%2e`, `.%2e`, `%2e.` e `%2e%2e` case-insensitive. Reconhecer segmentos ponto antes de percent-decodificar nomes; não tratar %2F/%5C como separador. Essas formas codificadas, query, parentacimaraiz, rootedpath, fragmentos nãoID e URLs ambíguas ficam unsupported, não missing_member. Decodificar UTF8 estrito uma vez; %25 não vira dupla decodificação. O resolvedor preserva Unicode/spelling e case. No lookup do inventário, usar equivalência NFC para caminhos e devolver o nome físico real; nomes ZIP canon-equivalentes ou iguais após normalização canônica/fullcasefold são ambíguos e geram erro. Não fazer lookup caseless nem normalizar IDs/fragmentos; equivalência apenas canônica de um ID ausente fica incomplete em vez de adivinhar resolução. Bytes inválidos/percentescapes malformados -> unsupported. Base paths com % literal devem ser escapados ao comparar com Node oracle, evitando dupla interpretação.

Não implementar WHATWG universal por aproximação. Oráculo de desenvolvimento Node newURL com origem sintética https://publication.invalid/ confirma casos aceitos; não fazer chamadas a esse domínio. Tiposunsupported honestos não invalidam o livro por si só.

## CLI e entrega

`epub-navigation-audit FILE [--rootfile MEMBER] [--include-hrefs] [--format json|markdown] [--output NEW] [--max-...]`; `python -m epub_navigation_audit` equivalente. Exit0 consistent,1 invalid,2 incomplete,3 operacional/uso/saída, help/version0. JSON determinístico ASCII-safe com LF, sem relógio. Markdown escapa valores HTML/Markdown/controles. Publicação --output cria novo com temp+fsync+link exclusivo, sem sobrescrever concorrente/entrada. Diretório pai existente; sem fallback inseguro nem promessa de durabilidade física. Stdout flush protegido contra pipefechado e código120.

README PT-BR orientado a uso, MIT, avisos de reutilização/runtime, exemplos originais gerados por script (não usar livro real), wheel/sdist/sourceZIP+checksums em release GitHub; não PyPI. CI Linux Python3.11–3.14 e Windows3.14 com instalação forafontes. Oráculo EPUBCheck5.3.0 fora runtime (recomendação3.3), fixtures originalválida e inválidas benignas; registrar resultados efetivos sem fingir certificação. Sem depender do oráculo Java para operar o pacote.
