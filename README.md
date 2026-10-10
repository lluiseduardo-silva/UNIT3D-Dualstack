# Dual-stack no UNIT3D: código, medições e evidências

Este repositório é o pacote técnico de uma implementação experimental de **um peer lógico com um endpoint IPv4 e um IPv6 independentes**. O foco da leitura é avaliar funcionamento, consistência, custo de recursos, falhas e reversibilidade. Os fontes completos dos dois projetos acompanham as evidências; seus READMEs upstream não substituem este guia.

**Corte das evidências: 10/10/2026.** O Rust corrigido completou o ensaio de seis horas no perfil documentado. A matriz comparativa completa original/candidato e a campanha de escalabilidade não foram concluídas. O experimento de cache B não está incorporado ao produto. Não houve implantação em produção.

## Walkthrough: do resultado à evidência

1. Leia [resultados consolidados](docs/resultados-consolidados.md): números, unidades, duração, comparabilidade e limites. Para análise programática, use [métricas em JSON](docs/data/key-metrics.json).
2. Confira [método e ambiente](docs/metodologia-e-ambiente.md): hardware, carga, versões, durabilidade, amostragem e diferença entre resposta HTTP e persistência.
3. Examine [MySQL, memória e A/B de cache](docs/dualstack-capacidade-recursos.md) e [diagnóstico do escritor](docs/dualstack-writer.md). São os principais custos e limites encontrados.
4. Consulte [problemas e correções](docs/problemas-e-correcoes.md): separação entre defeitos preexistentes, regressões novas e falhas do laboratório, com links para reproduções.
5. Veja [arquitetura e contratos](docs/arquitetura-e-contratos.md), [testes e reprodução](docs/testes-e-reproducao.md) e [rollback ao legado](docs/dualstack-rollback-legado.md).
6. Abra os [fontes UNIT3D](repos/UNIT3D/) e [fontes UNIT3D-Announce](repos/UNIT3D-Announce/). Para revisar só a alteração, use os [patches contra as bases](packages/README.md); para baixar os fontes, use os arquivos do mesmo diretório.
7. Audite [resultados públicos](lab/dualstack/results/), [inventário das evidências](docs/data/evidence-index.json) e [proveniência/integridade](docs/entrega-e-proveniencia.md). A [matriz de validação](docs/data/validation-matrix.json) liga requisito, teste e resultado.

O [índice completo de documentação](docs/README.md) organiza os relatórios históricos por assunto. Esses relatórios registram etapas sucessivas; “pendente” em um checkpoint antigo não substitui o estado consolidado desta entrega.

## Números para orientar a avaliação

| Medição | Resultado observado | Leitura correta |
|---|---:|---|
| Rust dual-stack, seis horas | 171.427.236 announces; 0 erros; 0 divergências finais | 10.000 peers / 20.000 endpoints; cerca de 8.000 req/s nas janelas; houve pausas de controle |
| Rust original, seis horas | 175.346.000 announces; 0 erros; crédito exato | 10.000 peers IPv4; perfil diferente do dual-stack |
| p99 de resposta, seis horas | 0,330 ms candidato / 0,475 ms original | Medianas de percentis por janela, HTTP local; não prova ganho percentual entre versões |
| RSS Rust, medianas horárias | 32,15–33,20 MiB candidato / 26,95–27,92 MiB original | Perfis distintos; candidato teve pico transitório de 125,31 MiB |
| Bootstrap candidato | 100.000 peers / 200.000 endpoints em 2,81–3,38 s | Carregamento; não é capacidade de requests/s |
| Cache MySQL A1/B/A2 | Picos RSS 1.245,75 / 559,86 / 1.389,38 MiB | B experimental economiza 55–60% de RAM nesse controle; A é dual-stack, não original |
| Custo de CPU do cache B | MySQL +5,0–7,9 pontos de um núcleo; Rust +3,4–3,8 | Mais preparações SQL; escrita em disco praticamente igual |
| Payload compacto por peer | IPv4 6 B; IPv6 18 B; ambos até 24 B | Até 4× os bytes da lista IPv4, além do envelope |

Fontes, perfis e ressalvas de cada linha estão em [resultados consolidados](docs/resultados-consolidados.md). **Não há aprovação geral de ausência de regressão de 10%, certificação de produção ou teto universal de IOPS.**

## Conteúdo do pacote

```text
README.md                         roteiro orientado a evidências
docs/                             sínteses técnicas, relatórios e planos históricos
  data/                           métricas, matriz de validação e inventário JSON
repos/UNIT3D/                     código completo, migrações e testes
repos/UNIT3D-Announce/             código completo e testes Rust
packages/                         fontes compactados, patches e proveniência
lab/dualstack/                    geradores, auditores, supervisores e fixtures públicas
  results/                        resultados públicos, inclusive falhas preservadas
tools/verify-package.py           verificação local de integridade do pacote
tools/recheck-evidence.py         reanálise offline e conferência dos patches
```

| Projeto | Base fixa | Snapshot incluído |
|---|---|---|
| UNIT3D | 9.2.0 — `8b88f4c8182eb3d3912ffef425c3224dcfd596f4` | `7c45115fc8b7ad83d12b0a44a5e656c12240ede4` |
| UNIT3D-Announce | 0.3.1 — `fcd189e9aebf07a12a1f8cc39500819c3870925b` | `36823b5fab72940c0dcb90b0ed456b28c18160cc` |

Os diretórios `repos/` são arquivos normais deste snapshot, **não submódulos**. Um clone do pacote inclui o código sem precisar dos repositórios de desenvolvimento. As licenças e atribuições dos projetos foram preservadas. Consulte [licenças](LICENSES.md).

## Verificação sem executar carga

Com Python 3 e Git, na raiz:

```sh
python tools/verify-package.py
```

O verificador confere inventário, hashes dos arquivos empacotados, fontes, pacotes e vínculos dos documentos de entrada. Não conecta ao laboratório, não altera banco e não repete benchmarks. Instruções de análise offline e de execução em ambiente descartável estão em [testes e reprodução](docs/testes-e-reproducao.md).

Binlogs, dumps, credenciais, passkeys reais, fixtures privadas e amostras integrais dos ensaios prolongados não são distribuídos. Seus manifestos e resultados de auditoria públicos foram preservados. O [escopo da entrega](docs/entrega-e-proveniencia.md) identifica essa diferença; não se afirma que o pacote reproduz offline o replay de amostras que ficaram no laboratório.
