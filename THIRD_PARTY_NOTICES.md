# Autoria e dependências

O código e a documentação originais de EPUB Navigation Audit usam a [licença MIT](LICENSE), com `Copyright (c) 2026 Contribuidores da LOFRANO TECNOLOGIA`. Dependências e projetos reutilizados mantêm seus próprios avisos.

## Código da família LOFRANO

O tratamento limitado de arquivos ZIP e a infraestrutura de publicação de arquivos novos podem reutilizar algoritmos dos projetos [Wheel Record Audit](https://github.com/martinlofranodeoliveira/wheel-record-audit) e [SQLite Catalog Report](https://github.com/martinlofranodeoliveira/sqlite-catalog-report), ambos sob MIT.

- Wheel Record Audit: `Copyright (c) 2026 Contribuidores LOFRANO`.
- SQLite Catalog Report: `Copyright (c) 2026 Contribuidores da LOFRANO TECNOLOGIA`.

As adaptações aplicam esses mecanismos ao contêiner EPUB e aos relatórios deste perfil; regras específicas de wheels não definem conformidade EPUB. O texto de permissão MIT está preservado em [LICENSE](LICENSE). Mantenha os avisos ao reutilizar as partes correspondentes.

## Dependência de execução

| Pacote | Versão | Licença | Uso |
| --- | --- | --- | --- |
| [defusedxml](https://pypi.org/project/defusedxml/0.7.1/) | `0.7.1` | Python Software Foundation License Version 2 (`PSF-2.0`) | Parser XML com as restrições declaradas pelo perfil. |

`defusedxml` é instalado como dependência separada e não é vendorizado no código desta biblioteca. Sua distribuição identifica Christian Heimes como autor e inclui o texto integral da licença em `defusedxml-0.7.1.dist-info/LICENSE`. A licença MIT deste repositório não substitui esses termos. Consulte também o [projeto original](https://github.com/tiran/defusedxml).

O runtime Python e suas bibliotecas nativas, incluindo Expat e zlib, são fornecidos pela instalação do usuário. Seus termos próprios permanecem aplicáveis; este pacote não distribui uma cópia do runtime.

## Construção e desenvolvimento

- [build](https://github.com/pypa/build), versão `1.6.1`, licença MIT.
- [setuptools](https://github.com/pypa/setuptools), versão `84.2.1`, licença MIT.

Esses pacotes e suas dependências transitivas são ferramentas de desenvolvimento/construção, não código incluído no runtime da aplicação. Consulte os avisos das distribuições instaladas caso redistribua essas ferramentas.

EPUBCheck e Node.js são ferramentas externas opcionais de desenvolvimento, utilizadas apenas quando uma verificação independente é executada. Não são iniciados pela auditoria, não integram o wheel e não são exigidos para usar o pacote. Seus projetos e licenças devem ser consultados separadamente: [EPUBCheck](https://www.w3.org/publishing/epubcheck/) e [licença do Node.js](https://github.com/nodejs/node/blob/main/LICENSE).

## Especificação e exemplos

O perfil referencia a [Recomendação EPUB 3.3 de 13 de janeiro de 2026](https://www.w3.org/TR/2026/REC-epub-33-20260113/). Não inclui uma cópia da especificação nem afirma aprovação ou certificação pelo W3C.

Os EPUBs e relatórios de demonstração são construídos com dados originais e fictícios. Não incluem texto, imagens ou estrutura extraída de um livro de terceiros.
