# Liara — snapshot sanitizado do runtime

Este arquivo descreve somente a referência local do runtime, sem segredos, tokens ou estado live.
O runtime deve ser verificado antes de afirmar disponibilidade de scheduler, workers ou conectores.

Componentes esperados: serviço de aplicação, jobs agendados e adapters de plataformas.
Estado confirmado nesta etapa: existência deste snapshot versionado; execução real permanece não confirmada.
