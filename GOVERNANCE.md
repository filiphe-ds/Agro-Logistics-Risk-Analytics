# ⚖️ Governança e Metodologia de Dados

## 1. Dicionário de Dados (fato_lineup)
- `ship_id`: Identificador único (IMO) normalizado como String para evitar erros de casting.
- `terminal`: Campo normalizado. Valores numéricos ou inconsistentes são classificados como 'Fundeio/Outros'.
- `status_atual`: 'Esperado' ou 'Atracado' (Prioridade para status real em caso de duplicidade).

## 2. Metodologia do Modelo de ML
O modelo utiliza um **Random Forest Regressor** para estimar a probabilidade de atraso baseando-se em:
- **Precipitação (mm):** Impacto direto na produtividade de terminais de grãos.
- **Score NLP:** Risco derivado de notícias sobre acessos terrestres.
- **Volume Estimado:** Influência do tamanho da carga no tempo de berço.

## 3. Critérios de Auditoria (Backtesting)
A performance é calculada através da `view_performance_ml`:
- **Definição de Atraso:** Consideramos atraso real qualquer atracação ocorrida 6 horas após a janela prevista original.
- **Métrica de Sucesso:** Erro Médio Absoluto (MAE) comparando a Probabilidade Prevista vs. Evento Real (Binário 0 ou 1).

## 4. Ética e Privacidade
O projeto utiliza exclusivamente dados de fontes públicas (Porto de Santos, Ecovias, G1). Não há coleta de PII (Personally Identifiable Information).
