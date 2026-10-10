# Entrega, proveniência e integridade

## Snapshot de commit único

Esta entrega consolida código, testes, documentação, scripts e resultados públicos num commit inicial sem pais. A preparação preservou as branches e os `.git` internos do ambiente de desenvolvimento. Eles não integram os arquivos versionados do pacote. Um clone da branch de entrega contém `repos/UNIT3D` e `repos/UNIT3D-Announce` como diretórios de arquivos, não como submódulos ou repositórios independentes.

Os hashes históricos referidos em relatórios identificam proveniência, não commits alcançáveis no histórico Git deste pacote. As árvores completas, arquivos compactados e patches tornam essa proveniência consultável sem adicionar milhares de commits upstream ao histórico da entrega.

## Produtos e bases

| Projeto | Base original | Candidato incluído |
|---|---|---|
| UNIT3D | `8b88f4c8182eb3d3912ffef425c3224dcfd596f4` | `7c45115fc8b7ad83d12b0a44a5e656c12240ede4` |
| UNIT3D-Announce | `fcd189e9aebf07a12a1f8cc39500819c3870925b` | `36823b5fab72940c0dcb90b0ed456b28c18160cc` |

[Manifesto de fontes](../packages/manifest.json): commits, árvore Git, upstream, caminho, tamanho e SHA-256 dos arquivos compactados/patches. [Inventário de fontes](../packages/source-files.json): blob Git e SHA-256 por arquivo do candidato. As bases originais também acompanham o pacote em arquivos compactados para comparação; não houve incorporação incidental de `main`/`development` durante o empacotamento.

O código final Rust não inclui o [patch experimental B](../lab/dualstack/capacity-cache-b.patch). Seu binário, proveniência e validação estão em [manifesto do experimento](../lab/dualstack/capacity-cache-manifest.json).

## Resultados e documentos

O [inventário das evidências](data/evidence-index.json) cobre os arquivos públicos locais de `lab/dualstack/results/`, com tamanho e SHA-256. O [inventário do pacote](data/package-files.json) cobre todos os arquivos distribuídos, exceto ele próprio e o relatório derivado de verificação. Esses arquivos são gerados a partir dos blobs que compõem o commit, sem depender dos finais de linha do Windows.

Manifestos históricos foram preservados como evidência. Alguns se referem a arquivos existentes somente na VM/ZFS ou a uma etapa anterior da coleta. Sua existência não implica que todos esses arquivos estão distribuídos. O inventário desta entrega define o conteúdo efetivamente incluído. Os relatórios históricos não foram reescritos para apagar falhas ou estados pendentes da época.

As sínteses novas estão em `docs/`, os valores extraídos em [key-metrics.json](data/key-metrics.json) e o mapa requisito/teste/artefato em [validation-matrix.json](data/validation-matrix.json). Não houve nova execução de ensaio para produzir estes documentos.

## Incluído e não incluído

Incluídos: fontes rastreados dos produtos, licenças, lockfiles, migrações, testes, bases compactadas, patches, scripts de laboratório, fixtures públicas, planos, checkpoints, resultados públicos de sucesso/falha, séries de observadores e amostras curtas públicas já coletadas.

Não incluídos: `.git` internos, dependências instaladas (`vendor`, `node_modules`, `target`), imagens/binários de execução, `.env` de operação, chaves SSH, credenciais, passkeys reais, fixtures privadas, dumps, binlogs e amostras integrais dos soaks que permaneceram no laboratório. Exemplos de configuração e constantes já presentes no código upstream não são configurações do laboratório.

Também ficam fora os arquivos `public.tar.gz` das coletas, pois duplicam os arquivos públicos extraídos já incluídos; não são as amostras integrais privadas. `.local/` é área temporária de montagem, não parte do commit.

O pacote tem tamanho de centenas de MiB por preservar séries e amostras públicas. Não há ponteiros LFS nem dependência de download externo para os arquivos versionados. Dependências de build continuam sendo resolvidas pelos lockfiles dos respectivos produtos.

## Conferência

```sh
python tools/verify-package.py
git rev-list --count HEAD
git ls-tree -r HEAD
```

O segundo comando deve retornar `1` na branch de entrega. A árvore não deve conter modo `160000` (gitlink). O verificador compara arquivos do checkout aos hashes, permitindo conversão de finais de linha somente nos arquivos textuais apropriados, confere membros dos pacotes contra o inventário de fontes e resolve links dos guias de entrada. Ele não executa scripts de carga ou comandos remotos.

O relatório de montagem em [package-validation.json](data/package-validation.json) registra o resultado dessa conferência e das reanálises offline. Nenhuma nova aprovação funcional ou de desempenho é inferida dessa conferência de empacotamento.

O comando `python tools/recheck-evidence.py` permite repetir a reanálise dos dois soaks e do A1/B/A2, além de reconstruir os candidatos aplicando os patches às bases. A árvore resultante deve coincidir exatamente com `candidate_tree` no manifesto.
