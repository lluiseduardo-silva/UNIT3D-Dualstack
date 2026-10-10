# Rust: queda abrupta antes e depois do commit

Controle curto com produto `9e8b546`, em continuidade ao
[bootstrap validado](dualstack-bootstrap.md). Nenhuma alteração adicional nos
produtos. Executado por HTTP real nas duas famílias, MySQL 8.0.46 e container
encerrado com SIGKILL (código 137). O teste não solicita shutdown gracioso antes
das quedas nem altera a lease para permitir o restart.

## Resultados

| Etapa | Referência de upload | Crédito confirmado | Versão |
|---|---:|---:|---:|
| Registro inicial nas duas famílias | 1.000 | 0 | 2 |
| Primeiro delta confirmado | 1.100 | 100 | 3 |
| SIGKILL e restart | 1.100 | 100 | 3 |
| Reenvio do mesmo contador nas duas famílias | 1.100 | 100 | 5 |
| Novo delta | 1.200 | 200 | 6 |
| 100 announces aceitos, escritor bloqueado | 1.200 no SQL; 11.200 anunciado | 200 | 6 no SQL |
| SIGKILL, rollback e restart | 1.200 | 200 | 6 |
| Reenvio de 11.200 nas duas famílias | 11.200 | 10.200 | 8 |
| Novo contador de 11.300 | 11.300 | 10.300 | 9 |

Os 100 announces da rajada receberam resposta HTTP válida. Uma linha de usuário
foi mantida sob lock no banco para impedir seu commit. A consulta do escritor
foi observada enquanto os valores financeiros anteriores continuavam visíveis.
Depois do SIGKILL e da liberação do lock, não restou consulta ativa. Referência,
crédito, versão e revisões dos dois endpoints preservaram o estado confirmado.

As **100 transições pendentes foram perdidas da memória**. Os 10.000 bytes
correspondentes ficaram sem crédito até o próximo announce cumulativo. Esse
announce recuperou o delta uma vez; sua repetição na outra família não acrescentou
crédito. Isso não recupera as mensagens originais nem promete reconstruir todos
os eventos transitórios ou seedtime. Se o cliente não voltar a informar esse
contador cumulativo, o teste não demonstra recuperação daquele tráfego.

A espera pela propriedade expirar foi natural; não houve UPDATE manual na
lease. O crédito já confirmado sobreviveu aos dois encerramentos. O fechamento
confere igualdade entre crédito do usuário e histórico, referência do peer,
contagem única de seeder e endpoints IPv4/IPv6; depois encerra graciosamente o
processo reiniciado e verifica ausência de consultas pendentes.

## Evidência e reprodução

Plano: `docs/plans/2026-10-08-falha-abrupta-rust.md`. Orquestração:

```text
python lab/dualstack/run-rust-crash.py --ssh-key <chave-local> --output <resultado-novo.json>
```

O runner exige as três VMs isoladas, tracker parado, mais de 3 GiB livres nos
dados e os helpers instalados. Recria somente o banco descartável. O bloqueio
SQL tem liberação por stdin/EOF e prazo máximo de dez segundos; nenhuma chave,
passkey, URL de announce ou credencial é exportada.

`controlled-v1.json` preserva a primeira execução. O runner foi ajustado para só
marcar aprovação depois de conferir o encerramento; `controlled-v2.json` é a
repetição com esse ajuste. A primeira execução já havia terminado com lease
inativa e zero consultas, portanto não foi reclassificada como falha.

Os fontes de produto, versões Cargo e testes correspondem ao checkpoint de
bootstrap. O binário de produto e os artefatos recebem hashes no diretório
`lab/dualstack/results/rust-crash/`. Nenhum produto foi modificado nesta etapa.

As duas execuções passaram: 218 announces aceitos, quatro SIGKILLs e quatro
reinicializações. A rajada de 100 requests levou 19,3–19,9 ms; o bloqueio foi
liberado depois de aproximadamente 1,02–1,05 s. A espera natural pela lease
durou 26,44–26,97 s. Esses tempos descrevem o controle provocado, sem estimar
percentis de perda ou throughput sustentado. Fechamento final: geração 1901
inativa, referência 11.300, crédito 10.300, versão 9, dois endpoints e zero
consultas ativas.

## Limites

Esse ensaio demonstra a atomicidade dos efeitos confirmados e a perda esperada
das mensagens aceitas apenas em memória. A rajada curta não é um benchmark de
throughput; a duração do lock não estima a janela normal de perda. Ainda falta
medir essa janela durante carga sustentada, comparar com a tag original e
verificar memória/cache sob rotação, proxy/TLS/probes e a matriz longa. SIGKILL
do banco/VM e interrupção de energia não foram simulados aqui.

O resultado está de acordo com o contrato que admite perda antes da persistência.
Não há evidência neste controle que exija ampliar o escopo para um journal
durável no Rust. O ensaio de seis horas permanece condicionado à capacidade
de armazenamento; não houve push ou implantação em produção.

Revisão final única: diff restrito ao harness, plano e evidências do controle.
Nenhuma divergência funcional em relação ao plano deste incremento; os cenários
sob carga sustentada permanecem explicitamente fora desta aprovação curta.
