import os
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

# Inicializa o cliente
client = bigquery.Client(project=os.getenv("PROJECT_ID"))
DATASET_FULL = "agrologisticsdata.logisticsdata"

def renovar_validade():
    # 1. Lista de Tabelas Físicas (Refresh via SELECT *)
    tabelas = [
        "fato_lineup",
        "dim_navio",
        "fato_clima",
        "fato_contingencias_nlp",
        "dim_geografia_rota"
    ]

    # 2. Dicionário de Views (Refresh via SQL Original)
    views = {
        "view_feature_store_ml": f"""
            CREATE OR REPLACE VIEW `{DATASET_FULL}.view_feature_store_ml` AS
            WITH ultima_chuva AS (
                SELECT precipitacao_mm as rain_feature, velocidade_vento as wind_feature
                FROM `{DATASET_FULL}.fato_clima`
                ORDER BY timestamp_leitura DESC LIMIT 1
            ),
            ultimo_nlp AS (
                SELECT score_risco as nlp_risk_score
                FROM `{DATASET_FULL}.fato_contingencias_nlp`
                ORDER BY timestamp_leitura DESC LIMIT 1
            )
            SELECT 
                f.*,
                (SELECT rain_feature FROM ultima_chuva) as rain_feature,
                (SELECT wind_feature FROM ultima_chuva) as wind_feature,
                (SELECT nlp_risk_score FROM ultimo_nlp) as nlp_risk_score
            FROM `{DATASET_FULL}.fato_lineup` f
        """,
        "view_performance_ml": f"""
            CREATE OR REPLACE VIEW `{DATASET_FULL}.view_performance_ml` AS
            WITH predicoes AS (
                SELECT 
                    REGEXP_REPLACE(CAST(ship_id AS STRING), r'\\.0$', '') as clean_id,
                    data_chegada_prevista,
                    nlp_risk_score as prob_atraso_prevista,
                    inserido_em as data_predicao
                FROM `{DATASET_FULL}.view_feature_store_ml`
                WHERE ship_id IS NOT NULL
                QUALIFY ROW_NUMBER() OVER (PARTITION BY REGEXP_REPLACE(CAST(ship_id AS STRING), r'\\.0$', '') ORDER BY inserido_em ASC) = 1
            ),
            realidade AS (
                SELECT 
                    REGEXP_REPLACE(CAST(ship_id AS STRING), r'\\.0$', '') as clean_id,
                    inserido_em as data_atracacao_real
                FROM `{DATASET_FULL}.fato_lineup`
                WHERE status_atual = 'Atracado'
                QUALIFY ROW_NUMBER() OVER (PARTITION BY REGEXP_REPLACE(CAST(ship_id AS STRING), r'\\.0$', '') ORDER BY inserido_em ASC) = 1
            )
            SELECT 
                p.clean_id,
                d.nome_navio,
                p.data_chegada_prevista,
                r.data_atracacao_real,
                p.prob_atraso_prevista,
                CASE 
                    WHEN TIMESTAMP_DIFF(CAST(r.data_atracacao_real AS TIMESTAMP), CAST(p.data_chegada_prevista AS TIMESTAMP), HOUR) > 6 THEN 1 
                    ELSE 0 
                END as ocorreu_atraso_real,
                ABS(p.prob_atraso_prevista - CASE 
                    WHEN TIMESTAMP_DIFF(CAST(r.data_atracacao_real AS TIMESTAMP), CAST(p.data_chegada_prevista AS TIMESTAMP), HOUR) > 6 THEN 1 
                    ELSE 0 
                END) as erro_absoluto
            FROM predicoes p
            INNER JOIN realidade r ON p.clean_id = r.clean_id
            LEFT JOIN `{DATASET_FULL}.dim_navio` d ON p.clean_id = d.ship_id
        """
    }

    # Execução para Tabelas
    for tab in tabelas:
        print(f"🔄 Renovando tabela: {tab}")
        try:
            query = f"CREATE OR REPLACE TABLE `{DATASET_FULL}.{tab}` AS SELECT * FROM `{DATASET_FULL}.{tab}`"
            client.query(query).result()
            print(f"✅ Tabela {tab} renovada.")
        except Exception as e:
            print(f"❌ Erro na tabela {tab}: {e}")

    # Execução para Views
    for view_name, view_sql in views.items():
        print(f"🔄 Renovando view: {view_name}")
        try:
            client.query(view_sql).result()
            print(f"✅ View {view_name} renovada.")
        except Exception as e:
            print(f"❌ Erro na view {view_name}: {e}")

if __name__ == "__main__":
    renovar_validade()