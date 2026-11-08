# EPUB Navigation Audit

Confira a estrutura de navegação de um EPUB local: a rendição selecionada, os documentos declarados, a ordem de leitura, os destinos do sumário e os fragmentos referenciados. A biblioteca e a CLI Python produzem relatórios **JSON ou Markdown**, sem renderizar o livro, extrair membros para uma pasta ou executar seu conteúdo.

Útil para investigar um sumário quebrado ou registrar os checks de navegação antes de entregar uma publicação. O resultado distingue erro comprovado de verificação incompleta por limite ou recurso fora do perfil.

Projeto da [LOFRANO TECNOLOGIA](https://lofranotecnologia.com.br), com [licença MIT](LICENSE). O perfil é próprio e documentado; **não substitui o EPUBCheck nem certifica a conformidade integral do livro**.

## Instalação

Requer **Python 3.11 ou superior**. A dependência de execução é `defusedxml==0.7.1`, instalada junto do pacote. Java, Node.js e EPUBCheck não são necessários para usar a biblioteca ou a CLI.

Os comandos usam `python`. Se seu sistema disponibiliza apenas `python3`, use esse nome até ativar o ambiente virtual.

```bash
git clone https://github.com/martinlofranodeoliveira/epub-navigation-audit.git
cd epub-navigation-audit
python -m venv .venv
```

Ative o ambiente com `source .venv/bin/activate` no Linux/macOS ou `.venv\Scripts\Activate.ps1` no PowerShell. Depois:

```bash
python -m pip install .
epub-navigation-audit --version
```

Para instalar um wheel baixado de [Releases](https://github.com/martinlofranodeoliveira/epub-navigation-audit/releases):

```bash
python -m pip install ./epub_navigation_audit-1.0.0-py3-none-any.whl
```

O projeto não é publicado no PyPI.

## Comece com um exemplo fictício

Na cópia do repositório, gere os arquivos de demonstração:

```bash
python scripts/make_samples.py --directory .samples
epub-navigation-audit .samples/valido.epub
epub-navigation-audit .samples/fragmento-ausente.epub --format markdown
```

O segundo arquivo demonstra um destino de fragmento ausente e, por isso, deve produzir `invalid`, com código de saída `1`. Os EPUBs são sintéticos e gerados localmente; não contêm um livro de terceiros. Consulte o [gerador](scripts/make_samples.py) para ver como os casos são construídos.

Veja as saídas registradas em [JSON](examples/valido.json), [Markdown](examples/valido.md) e no [caso com fragmento ausente](examples/fragmento-ausente.json).

## Audite seu arquivo

```bash
epub-navigation-audit livro.epub
epub-navigation-audit livro.epub --format markdown --output navegacao.md
python -m epub_navigation_audit livro.epub --format json
```

JSON é o formato padrão. `python -m epub_navigation_audit` aceita os mesmos argumentos da CLI.

`--output` exige um arquivo **novo** e um diretório pai existente. A publicação não sobrescreve um destino existente, inclusive se outro processo criá-lo durante a execução. Sem essa opção, a saída vai para stdout; redirecionamentos feitos pelo shell seguem as regras de sobrescrita do próprio shell.

### Escolha uma rendição quando necessário

Se `container.xml` declarar uma única rootfile, ela é selecionada automaticamente. Com várias, o relatório fica `incomplete` até você escolher uma delas:

```bash
epub-navigation-audit livro.epub --rootfile "EPUB/package.opf"
```

Substitua o caminho pelo membro decodificado mostrado em `package.rootfiles`. Esse argumento é um caminho interno do EPUB, não uma URL ou um caminho do computador. A auditoria cobre a rendição selecionada; não presume que as demais foram verificadas.

### Entenda o resultado

| Estado | Saída | Significado |
| --- | ---: | --- |
| `consistent` | `0` | Os checks deste perfil terminaram sem erro comprovado. Avisos ainda podem existir. |
| `invalid` | `1` | Foi encontrado ao menos um erro comprovado; outros checks podem ter ficado incompletos. |
| `incomplete` | `2` | Não há erro comprovado, mas parte do perfil não pôde ser concluída. |
| Erro operacional ou de uso | `3` | Falha de abertura, seleção, argumentos ou saída. |

`--help` e `--version` retornam `0`. Ao automatizar, examine também `complete` e `issues`: um relatório `invalid` pode ter `complete: false`. Os [campos e as regras de precedência](docs/FORMATO.md) estão documentados.

## O que é conferido

- Estrutura ZIP do perfil, posição física e conteúdo de `mimetype`, e leituras selecionadas com tamanho real e CRC.
- `container.xml`, seleção de rootfile e package OPF com manifest e spine.
- Presença dos recursos locais declarados, referências de leitura e identificação do documento de navegação.
- Estrutura básica do sumário `toc`, seus destinos locais e os fragmentos simples nos documentos XHTML/SVG selecionados.
- IDs duplicados nos documentos analisados e distinção entre caminhos ausentes e referências não suportadas.

A ordem do spine é preservada. Uma diferença simples entre a primeira aparição dos destinos no sumário e a ordem linear do spine pode gerar um aviso, sem ser tratada como erro obrigatório.

Na resolução de caminhos, nomes Unicode canonicamente equivalentes, como formas NFC e NFD, apontam para o mesmo membro e o relatório preserva seu nome físico no ZIP. Não há busca sem distinguir maiúsculas de minúsculas. Nomes ambíguos no inventário são erros; IDs e fragmentos não recebem essa normalização. Se a única diferença de um fragmento for a normalização Unicode, a resolução fica incompleta em vez de ser presumida.

O perfil se baseia na [Recomendação EPUB 3.3 de 13 de janeiro de 2026](https://www.w3.org/TR/2026/REC-epub-33-20260113/). Não avalia integralmente CSS, scripts, acessibilidade, qualidade de rótulos, metadados editoriais, fallback de recursos ou todos os conteúdos binários. Imagens e outros recursos fora das leituras selecionadas não recebem verificação integral de conteúdo/CRC. `consistent` não autentica a origem nem comprova que o arquivo é seguro para ser aberto por outro programa.

Recursos como ZIP64, DOCTYPE, `xml:base`, criptografia de conteúdo, fallback relevante ou microssintaxes de fragmento podem deixar os checks incompletos. Eles não são rotulados como livro inválido apenas por estarem fora deste perfil. Veja [SECURITY.md](SECURITY.md) e [SPEC.md](SPEC.md) para o alcance exato.

## Relatórios e privacidade

O relatório não exporta rótulos do sumário, título, autores ou texto dos capítulos. Por padrão, os hrefs originais são substituídos por `href_sha256`.

**A saída não é anônima.** Nome do arquivo, caminhos internos, identificadores e fragmentos podem ser sensíveis; hashes também permitem correlação. Para incluir os hrefs literais, use explicitamente:

```bash
epub-navigation-audit livro.epub --include-hrefs
```

Essa opção também pode expor URLs com parâmetros ou credenciais presentes no próprio livro. Revise o relatório antes de compartilhá-lo. Mensagens de erro não repetem URLs, conteúdo do livro ou caminhos absolutos da origem.

## Use como biblioteca

```python
from epub_navigation_audit import AuditLimits, audit_epub, to_markdown

report = audit_epub(
    "livro.epub",
    include_hrefs=False,
    limits=AuditLimits(max_xml_nodes=200_000),
)
print(report["status"], report["complete"])
print(to_markdown(report))
```

A API também exporta `AuditError` e `to_json`. `AuditError` possui um atributo `code` para falhas operacionais; argumentos inválidos levantam `ValueError`. Erros estruturais da entrada são registrados em `issues`. A auditoria não consulta a rede nem inicia subprocessos.

## Limites

| Opção | Padrão | O que limita |
| --- | ---: | --- |
| `--max-archive-bytes` | 32 MiB | Bytes do arquivo de origem capturado |
| `--max-members` | 4.096 | Entradas ZIP |
| `--max-xml-bytes` | 2 MiB | Bytes físicos por leitura selecionada |
| `--max-total-read-bytes` | 16 MiB | Bytes produzidos nas leituras selecionadas únicas |
| `--max-name-bytes` | 1.024 | Bytes UTF-8 por nome interno |
| `--max-xml-nodes` | 100.000 | Nós XML, compartilhados pelos documentos |
| `--max-xml-depth` | 128 | Profundidade XML |
| `--max-links` | 20.000 | Entradas de rootfiles, manifest, spine e links de navegação |
| `--max-issues` | 1.000 | Achados registrados |

Os limites são inteiros positivos, com tetos definidos no [contrato](docs/FORMATO.md#limites). Atingir um orçamento não produz sucesso silencioso. Eles não são uma sandbox, um prazo máximo nem uma garantia rígida de memória; o snapshot pode usar armazenamento temporário.

Uma leitura pode contabilizar um byte-testemunha adicional para comprovar que um limite ou tamanho declarado foi excedido. Quando o orçamento global é esgotado, a fila de leituras para; isso não autoriza produzir conteúdo arbitrário além dele.

## Desenvolvimento

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m build
python scripts/check_installed.py --wheel dist/epub_navigation_audit-1.0.0-py3-none-any.whl
```

O último comando verifica o wheel instalado fora da árvore de fontes. Ferramentas de construção: `build==1.6.1` e `setuptools==84.2.1`. EPUBCheck e Node.js podem ser usados como oráculos independentes de desenvolvimento; não participam da execução do pacote.

### Reproduza o confronto independente

Com Java 17 e Node.js 22 ou superior disponíveis no PATH:

```bash
python scripts/fetch_epubcheck.py --directory .tools
python scripts/check_oracles.py --jar .tools/epubcheck-5.3.0/epubcheck.jar --output .tools/oracle.json
```

O primeiro comando baixa o EPUBCheck 5.3.0 oficial e confere seu SHA-256 fixado. O segundo gera os próprios exemplos, executa o verificador e compara referências aceitas com o resolvedor URL do Node. Escolha um arquivo de saída novo. Os [resultados registrados](examples/oraculos.json) incluem recursos válidos que ficam incompletos neste perfil, como DOCTYPE e a seleção ainda não informada entre várias rendições.

[Contribuir](CONTRIBUTING.md) · [Formato e perfil](docs/FORMATO.md) · [Segurança](SECURITY.md) · [Avisos de terceiros](THIRD_PARTY_NOTICES.md)
