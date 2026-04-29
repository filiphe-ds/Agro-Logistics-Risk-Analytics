# ⚖️ Governança e Metodologia de Dados

Este documento detalha as definições técnicas, a lógica de negócio e os critérios de qualidade aplicados ao projeto **Agro-Logistics Risk Analytics**.

## 1. Dicionário de Dados Críticos

### Tabela: `fato_lineup`
- `ship_id`: Identificador único (IMO) normalizado. Armazenado como String para garantir unicidade e evitar distorções de ponto flutuante.
- `terminal`: Campo de texto normalizado. Registros identificados como números puros ou datas são automaticamente reclassificados como 'Área de Fundeio / Outros'.
- `status_atual`: Status dinâmico (Esperado/Atracado). Em caso de conflito, a lógica de ingestão prioriza o status 'Atracado'.
- `quantidade_estimada`: Volume de carga em toneladas (Float).

## 2. Metodologia de Machine Learning

O risco de atraso é calculado através de um modelo **Random Forest Regressor**, utilizando as seguintes variáveis de entrada (features):

- **rain_feature:** Precipitação acumulada em mm (Fonte: Visual Crossing).
- **wind_feature:** Velocidade do vento em km/h.
- **nlp_risk_score:** Risco logístico derivado de análise de texto de notícias locais.
- **quantidade_estimada:** Impacto do volume de carga no tempo de operação.

### Lógica de Probabilidade
A probabilidade final exibida no dashboard representa a confiança do modelo em um cenário de atraso superior à janela operacional padrão.

$$P(\text{Risco}) = f(\text{Clima}, \text{Volume}, \text{NLP})$$

## 3. Critérios de Auditoria (Backtesting)

A acurácia do sistema é medida continuamente através da View `view_performance_ml`, que utiliza os seguintes critérios:

1.  **Confronto:** Comparamos a primeira predição feita para o navio (enquanto 'Esperado') com o momento real de atracação.
2.  **Definição de Atraso:** Um evento é classificado como "Atraso Real" se a atracação ocorrer **6 horas** após o horário previsto original.
3.  **Métrica de Erro:** Utilizamos o **MAE (Mean Absolute Error)** para medir a distância entre a probabilidade prevista e o evento binário ocorrido.

## 4. Pipeline de Qualidade (Data Quality)

- **Deduplicação:** O robô realiza o `drop_duplicates` baseado no IMO antes de cada carga.
- **Normalização:** Conversão forçada de Timestamps para garantir que o BigQuery e o Streamlit operem no fuso horário 'America/Sao_Paulo'.
- **Resiliência:** Uso de `WRITE_APPEND` para manutenção de histórico e `WRITE_TRUNCATE` para resets controlados de ambiente.
