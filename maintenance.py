import os
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

client = bigquery.Client(project=os.getenv("PROJECT_ID"))
DATASET_FULL = "agrologisticsdata.logisticsdata"

def renovar_validade():
    # 1. Tabelas com Particionamento e Clusterização (Exigem SQL específico)
    tabelas_complexas = {
        "fato_lineup": f"""
            CREATE OR REPLACE TABLE `{DATASET_FULL}.fato_lineup`
            PARTITION BY data_chegada_prevista
            CLUSTER BY terminal, commodity
            AS SELECT * FROM `{DATASET_FULL}.fato_lineup`
        """,
        "fato_clima": f"""
            CREATE OR REPLACE TABLE `{DATASET_FULL}.fato_clima`
            PARTITION BY DATE(timestamp_leitura)
            CLUSTER BY loc_id
            AS SELECT * FROM `{DATASET_FULL}.fato_clima`
        """
    }

    # 2. Tabelas Simples (SELECT * funciona direto)
    tabelas_simples = ["dim_navio", "fato_contingencias_nlp", "dim_geografia_rota"]

    # 3. Dicionário de Views (Usando fr"" para aceitar a barra única do Regex)
    views = {
        "view_feature_store_ml": fr"""
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
        "view_performance_ml": fr"""
            CREATE OR REPLACE VIEW `{DATASET_FULL}.view_performance_ml` AS
            WITH predicoes AS (
                SELECT 
                    REGEXP_REPLACE(CAST(ship_id AS STRING), r'\.0$', '') as clean_id,
                    data_chegada_prevista,
                    nlp_risk_score as prob_atraso_prevista,
                    inserido_em as data_predicao
                FROM `{DATASET_FULL}.view_feature_store_ml`
                WHERE ship_id IS NOT NULL
                QUALIFY ROW_NUMBER() OVER (PARTITION BY REGEXP_REPLACE(CAST(ship_id AS STRING), r'\.0$', '') ORDER BY inserido_em ASC) = 1
            ),
            realidade AS (
                SELECT 
                    r.clean_id,
                    r.data_atracacao_real,
                    r.terminal,
                    c.commodity
                FROM (
                    /* 1. Captura a primeira foto do navio atracado para fixar data e terminal */
                    SELECT 
                        REGEXP_REPLACE(CAST(ship_id AS STRING), r'\.0$', '') as clean_id,
                        inserido_em as data_atracacao_real,
                        terminal
                    FROM `{DATASET_FULL}.fato_lineup`
                    WHERE status_atual = 'Atracado'
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY REGEXP_REPLACE(CAST(ship_id AS STRING), r'\.0$', '') ORDER BY inserido_em ASC) = 1
                ) r
                INNER JOIN (
                    /* 2. Agrupa de forma tradicional para consolidar as mercadorias sem duplicar texto */
                    SELECT 
                        REGEXP_REPLACE(CAST(ship_id AS STRING), r'\.0$', '') as clean_id,
                        STRING_AGG(DISTINCT commodity, ', ') as commodity
                    FROM `{DATASET_FULL}.fato_lineup`
                    WHERE status_atual = 'Atracado'
                    GROUP BY 1
                ) c ON r.clean_id = c.clean_id
            )
            SELECT 
                p.clean_id,
                d.nome_navio,
                r.terminal,
                r.commodity,
                p.data_chegada_prevista,
                r.data_atracacao_real,
                p.prob_atraso_prevista,
                CASE 
                    WHEN TIMESTAMP_DIFF(CAST(r.data_atracacao_real AS TIMESTAMP), CAST(p.data_chegada_prevista AS TIMESTAMP), HOUR) > 24 THEN 1 
                    ELSE 0 
                END as ocorreu_atraso_real,
                ABS(p.prob_atraso_prevista - CASE 
                    WHEN TIMESTAMP_DIFF(CAST(r.data_atracacao_real AS TIMESTAMP), CAST(p.data_chegada_prevista AS TIMESTAMP), HOUR) > 24 THEN 1 
                    ELSE 0 
                END) as erro_absoluto
            FROM predicoes p
            INNER JOIN realidade r ON p.clean_id = r.clean_id
            LEFT JOIN (
                SELECT ship_id, ANY_VALUE(nome_navio) as nome_navio
                FROM `{DATASET_FULL}.dim_navio`
                GROUP BY ship_id
            ) d ON p.clean_id = d.ship_id
        """
    }

    # --- EXECUÇÃO ---

    for nome, sql in tabelas_complexas.items():
        print(f"🔄 Renovando tabela complexa: {nome}")
        try:
            client.query(sql).result()
            print(f"✅ {nome} renovada com sucesso (Mantendo Particionamento).")
        except Exception as e:
            print(f"❌ Erro em {nome}: {e}")

    for tab in tabelas_simples:
        print(f"🔄 Renovando tabela simples: {tab}")
        try:
            query = f"CREATE OR REPLACE TABLE `{DATASET_FULL}.{tab}` AS SELECT * FROM `{DATASET_FULL}.{tab}`"
            client.query(query).result()
            print(f"✅ {tab} renovada.")
        except Exception as e:
            print(f"❌ Erro em {tab}: {e}")

    for v_name, v_sql in views.items():
        print(f"🔄 Renovando view: {v_name}")
        try:
            client.query(v_sql).result()
            print(f"✅ {v_name} renovada.")
        except Exception as e:
            print(f"❌ Erro em {v_name}: {e}")

if __name__ == "__main__":
    renovar_validade()