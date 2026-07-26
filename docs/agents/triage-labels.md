# Labels de triagem

As skills falam em cinco papéis canônicos de triagem. Esta tabela mapeia cada papel para a string usada de fato neste repo. Como o issue tracker é markdown local (ver `issue-tracker.md`), a "label" é o valor da linha `Status:` no topo do arquivo do issue.

| Label em mattpocock/skills | Label no nosso tracker | Significado                                    |
| -------------------------- | ---------------------- | ---------------------------------------------- |
| `needs-triage`             | `needs-triage`         | Precisa de avaliação antes de virar trabalho   |
| `needs-info`               | `needs-info`           | Esperando mais informação de quem reportou     |
| `ready-for-agent`          | `ready-for-agent`      | Totalmente especificado, pronto para agente AFK |
| `ready-for-human`          | `ready-for-human`      | Exige implementação humana                     |
| `wontfix`                  | `wontfix`              | Não será resolvido                             |

Quando uma skill mencionar um papel (ex.: "apply the AFK-ready triage label"), use a string correspondente da coluna da direita — escrevendo `Status: ready-for-agent` no arquivo.

Edite a coluna da direita se o vocabulário mudar.
