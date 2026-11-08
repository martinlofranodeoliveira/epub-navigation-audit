# Contribuir

Contribuições devem tornar o perfil de navegação mais útil, correto ou fácil de usar. Explique o caso de publicação afetado e preserve a distinção entre erro comprovado e check incompleto.

## Preparar o ambiente

Requer Python 3.11 ou superior. Depois de criar e ativar um ambiente virtual:

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m build
python scripts/check_installed.py --wheel dist/epub_navigation_audit-1.0.0-py3-none-any.whl
```

Se o Python do sistema se chama `python3`, use esse nome antes de ativar o ambiente. A construção e os testes não exigem acesso a livros reais.

## Propor uma alteração

1. Descreva o comportamento observado e o esperado, com a versão do pacote.
2. Prepare um EPUB mínimo e inteiramente sintético que reproduza o caso.
3. Acrescente uma verificação que diferencie o defeito da implementação anterior, usando um resultado independente quando possível.
4. Atualize [SPEC.md](SPEC.md), [docs/FORMATO.md](docs/FORMATO.md) e os exemplos se o comportamento público mudar.
5. Execute a suíte, a construção e a verificação da distribuição instalada.

Não acrescente livros de terceiros, relatórios privados, tokens ou dados de uma operação real ao repositório. Reduza um caso real a uma estrutura sintética antes de abrir uma issue pública.

## Invariantes do projeto

- Não renderizar o livro, extrair membros para caminhos do host, executar CSS/JavaScript ou buscar recursos externos.
- Resolver referências somente no perfil documentado, sem converter uma URL não suportada em um suposto arquivo ausente.
- Manter namespaces por URI, a ordem original do spine e a leitura única dos documentos selecionados.
- Não tratar uma funcionalidade EPUB válida fora do perfil como erro apenas por não ser implementada.
- Aplicar limites durante leitura e construção XML; nunca apresentar resultado truncado como completo.
- Preservar erros já comprovados quando um limite posterior interromper a auditoria.
- Manter mensagens sanitizadas e a omissão de hrefs literais por padrão.
- Não sobrescrever arquivos de saída existentes ou modificar a origem.

## Oráculos independentes

Uma comparação com EPUBCheck deve registrar a versão usada, o caso sintético e seu resultado efetivo. O perfil local e o EPUBCheck têm alcances diferentes: concordância em uma amostra não comprova equivalência entre as ferramentas. O pacote deve continuar funcionando sem Java ou EPUBCheck.

Casos aceitos pelo resolvedor de URLs também podem ser comparados com `new URL` do Node.js usando uma origem sintética, sem qualquer requisição a essa origem. Diferencie regras desse subconjunto das regras gerais da plataforma Web.

## Licença

O projeto usa [MIT](LICENSE). Preserve os avisos de autoria e as licenças dos recursos reutilizados, conforme [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Alterações pequenas e completas, com comportamento demonstrável, são mais úteis que mudanças feitas apenas para aumentar a atividade do repositório.
