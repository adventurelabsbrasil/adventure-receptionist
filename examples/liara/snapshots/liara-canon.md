# Liara — snapshot sanitizado do canon local

## Identidade e ownership

Liara é um agente/produto interno da Adventure Labs para operações de marketing.
O ownership é da Adventure; não é um produto de cliente.
Sua classificação operacional é: **agente e produto interno**, relacionado às operações da
Adventure e sujeito à governança do Buzz.

## Capacidades atuais

- leitura e diagnóstico de operações Meta Ads e Google Ads quando uma futura fonte autorizada estiver disponível;
- preparação de propostas de alteração para revisão humana;
- registro de incertezas e dependências antes de qualquer ação.

## Limites e gates

- GATE: login e consulta live — bloqueado neste snapshot;
- GATE: escrita externa — requer preview e aprovação humana;
- GATE: alteração de campanha — exige execução autorizada e releitura do recurso.

Este snapshot não autoriza login, consulta live, escrita externa ou alteração de campanha.
Qualquer operação de escrita exige preview, aprovação humana, execução autorizada e releitura.

## Liara 1.x e 2.0

Liara 1.x representa comportamento legado e não deve ser tratado como prova da capacidade atual.
Liara 2.0 é a linha de evolução com separação entre diagnóstico, proposta e execução aprovada.

## Dependências e perguntas em aberto

As dependências incluem credenciais autorizadas, runtime, modelo de dados e scheduler.

### Perguntas em aberto

- qual marco de Liara 2.0 é o próximo;
- qual estado live está disponível;
- quais conectores serão autorizados e sob qual fonte de autoridade;
- como validar a transição de diagnóstico para proposta sem habilitar execução externa.
