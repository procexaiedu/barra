# CLAUDE.md

## 1. Pense Antes de Codificar

**Não presuma. Não esconda dúvidas. Exponha os tradeoffs.**

Antes de implementar:
- Declare suas suposições explicitamente. Se houver incerteza, pergunte.
- Se existirem múltiplas interpretações, apresente-as; não escolha uma em silêncio.
- Se houver uma abordagem mais simples, diga. Questione quando for justificável.
- Se algo estiver pouco claro, pare. Diga o que está confuso. Pergunte.

## 2. Simplicidade Primeiro

**O mínimo de código que resolve o problema. Nada especulativo.**

- Não implemente funcionalidades além do que foi pedido.
- Não crie abstrações para código de uso único.
- Não adicione "flexibilidade" ou "configurabilidade" que não foi solicitada.
- Não trate erros para cenários impossíveis.
- Se você escrever 200 linhas e poderia ser 50, reescreva.

Pergunte a si mesmo: "Um engenheiro sênior diria que isto está complexo demais?" Se sim, simplifique.

## 3. Mudanças Cirúrgicas

**Altere apenas o necessário. Limpe apenas a sujeira que você criou.**

Ao editar código existente:
- Não "melhore" código, comentários ou formatação adjacentes.
- Não refatore coisas que não estão quebradas.
- Siga o estilo existente, mesmo que você faria diferente.
- Se notar código morto não relacionado, mencione; não delete.

Quando suas mudanças criarem sobras:
- Remova imports, variáveis ou funções que AS SUAS mudanças tornaram inutilizados.
- Não remova código morto preexistente, a menos que seja solicitado.

O teste: toda linha alterada deve estar diretamente ligada ao pedido do usuário.

## 4. Execução Guiada por Objetivos

**Defina critérios de sucesso. Repita até verificar.**

Transforme tarefas em objetivos verificáveis:
- "Adicionar validação" -> "Escrever testes para entradas inválidas e depois fazê-los passar"
- "Corrigir o bug" -> "Escrever um teste que o reproduza e depois fazê-lo passar"
- "Refatorar X" -> "Garantir que os testes passem antes e depois"

Para tarefas com múltiplas etapas, declare um plano breve:
```
1. [Etapa] -> verificar: [checagem]
2. [Etapa] -> verificar: [checagem]
3. [Etapa] -> verificar: [checagem]
```

Critérios de sucesso fortes permitem que você itere de forma independente. Critérios fracos ("faça funcionar") exigem esclarecimentos constantes.

## 5. Verificação Agêntica e Skills do Claude Code

**Teste o trabalho de forma concreta. Use as ferramentas disponíveis.**

Antes de considerar uma tarefa concluída:
- Defina qual método de verificação comprova que a mudança funciona.
- Para backend, inicie o servidor e valide o fluxo de ponta a ponta quando aplicável.
- Para frontend, use o navegador controlado por automação, como Playwright ou Chromium, para verificar a interface real.
- Para aplicações desktop ou fluxos visuais, use ferramentas de controle da interface quando disponíveis.
- Para tarefas longas ou complexas, rode uma verificação completa antes de finalizar.
- Quando houver um skill apropriado, use-o para revisar, simplificar ou validar a solução.

Regra prática: toda tarefa não trivial deve terminar com uma verificação objetiva. Uma conclusão sem teste, execução ou inspeção concreta ainda é uma hipótese.
