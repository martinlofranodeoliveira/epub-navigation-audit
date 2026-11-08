# Segurança e tratamento de arquivos

EPUB Navigation Audit lê arquivos EPUB locais e trata seus nomes, XML e referências como dados não confiáveis. O programa não renderiza páginas, executa scripts, extrai membros para uma árvore de arquivos ou acessa hrefs pela rede.

## Controles do perfil

A origem é capturada em um arquivo temporário limitado. As leituras selecionadas conferem estrutura, tamanho efetivo e CRC; o parser XML usa `defusedxml` com DTD, entidades e referências externas proibidas. Nós e profundidade são contados durante a construção da árvore. XInclude e folhas de estilo não são executados.

Um DOCTYPE, mesmo inofensivo ou permitido em EPUB, fica fora deste perfil e gera check incompleto. O mesmo cuidado vale para bases de URL, conteúdo protegido, extensões de ZIP e outras construções que não possam ser interpretadas fielmente. A ferramenta não tenta resolver essas limitações executando outro leitor ou consultando serviços externos.

O snapshot não é uma transação do filesystem: a auditoria detecta certas mudanças de identidade, tamanho e tempos do descritor, mas isso não protege contra um escritor que consiga alterar bytes preservando os metadados observados. Disponibilize a origem sem escrita concorrente quando precisar conferir um artefato específico.

Os limites de resultados e leitura não constituem uma sandbox ou garantia rígida de memória e duração. Python, Expat e zlib continuam sendo parte do ambiente de execução. O programa também não valida o conteúdo/CRC de todos os recursos binários que não foram selecionados para leitura.

## Compartilhar um relatório

O relatório omite texto do livro e hrefs literais por padrão, mas nomes de arquivos, caminhos internos, IDs e fragmentos podem identificar a publicação. Hashes não tornam os dados anônimos nem autenticam sua procedência.

`--include-hrefs` inclui valores originais, inclusive parâmetros e credenciais que possam existir nas URLs da entrada. Use essa opção somente quando precisar desses valores e confira a saída antes de publicá-la.

`--output` exige um diretório pai existente sob seu controle e publica somente um arquivo novo. Não há fallback que sobrescreva um destino em caso de falha de publicação. O uso de redirecionamento pelo shell permanece sob as regras do shell.

## Relatar um problema

Para um defeito comum, abra uma issue com versão, comportamento e um caso mínimo sintético. Não anexe um livro comercial, material privado, credenciais ou relatório sensível.

Para uma vulnerabilidade que não deve ser descrita publicamente, use os canais publicados no [site da LOFRANO TECNOLOGIA](https://lofranotecnologia.com.br) para combinar o envio dos detalhes. A existência deste documento não estabelece prazo de resposta ou suporte contratado.
