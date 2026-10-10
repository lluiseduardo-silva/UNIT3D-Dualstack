# Pacotes de fontes e alterações

Os arquivos deste diretório foram gerados dos commits indicados no [manifesto](manifest.json), sem dependências instaladas, `.git` ou configuração privada.

| Arquivo | Conteúdo |
|---|---|
| [UNIT3D-original-9.2.0.tar.gz](UNIT3D-original-9.2.0.tar.gz) | Base original intacta |
| [UNIT3D-dualstack-7c45115.tar.gz](UNIT3D-dualstack-7c45115.tar.gz) | Fontes candidatos, testes e migrações |
| [UNIT3D-dualstack.patch](UNIT3D-dualstack.patch) | Diff completo base→candidato, incluindo testes |
| [UNIT3D-Announce-original-0.3.1.tar.gz](UNIT3D-Announce-original-0.3.1.tar.gz) | Base Rust original intacta |
| [UNIT3D-Announce-dualstack-36823b5.tar.gz](UNIT3D-Announce-dualstack-36823b5.tar.gz) | Fontes Rust candidatos e testes |
| [UNIT3D-Announce-dualstack.patch](UNIT3D-Announce-dualstack.patch) | Diff completo base→candidato |
| [source-files.json](source-files.json) | SHA-256, tamanho, modo e blob de cada arquivo candidato |

Para revisão online, prefira [UNIT3D](../repos/UNIT3D/) e [UNIT3D-Announce](../repos/UNIT3D-Announce/). Os snapshots em `repos/` correspondem aos mesmos blobs dos arquivos candidatos. Nomes das versões upstream não significam versão oficial publicada com dual-stack.

O [patch B de cache](../lab/dualstack/capacity-cache-b.patch) permanece no laboratório como experimento separado; não está aplicado ao candidato. Os patches daqui incluem todas as alterações dos candidatos, inclusive correções independentes da feature, catalogadas em [problemas](../docs/problemas-e-correcoes.md).

Os arquivos `.tar.gz` podem ser extraídos com `tar -xzf <arquivo>` numa pasta vazia. O patch de cada produto deve ser aplicado na raiz da respectiva base exata, não na raiz desta coordenação. Consulte o manifesto e compare hashes antes de construir. Operação, migrações e rollback estão em [arquitetura](../docs/arquitetura-e-contratos.md) e [retorno ao legado](../docs/dualstack-rollback-legado.md).
