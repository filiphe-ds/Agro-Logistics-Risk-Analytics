import os
import pandas as pd
from datetime import datetime
import uuid
import requests
from bs4 import BeautifulSoup
import io
import re
from google.cloud import bigquery
from dotenv import load_dotenv
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = "logisticsdata"
client = bigquery.Client(project=PROJECT_ID)

def safe_load_to_bq(df, table_name):
    """Batch Load: O único que funciona de graça no BigQuery."""
    if df.empty: return
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    try:
        client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
        print(f"✅ {table_name}: {len(df)} linhas enviadas.")
    except Exception as e:
        print(f"❌ Erro BQ {table_name}: {e}")

def processar_operacao():
    print(f"🚀 Iniciando captura (Alinhada com Schema dim_navio): {datetime.now()}")
    url = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # MAPEAMENTO RESTRITO AO SEU SCHEMA REAL
    target_keys = {
        'ship_id': 'imo',
        'nome_navio': 'navio_ship',
        'bandeira': 'flag',
        'tipo_vessel': 'nav',             # O campo 'Nav' no site indica o tipo/longo curso
        'data_chegada_prevista': 'chegarrival',
        'commodity': 'mercadoria',
        'quantidade_estimada': 'peso',
        'terminal': 'terminal'
    }

    try:
        res = requests.get(url, headers=headers, verify=False, timeout=30)
        soup = BeautifulSoup(res.text, 'html.parser')
        tabelas_html = soup.find_all('table')
        
        lista_final_registros = []
        
        for tab in tabelas_html:
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [limpar_nome_coluna(' '.join(col)) for col in df_temp.columns.values]
            else:
                df_temp.columns = [limpar_nome_coluna(c) for c in df_temp.columns]
            
            mapeamento_tabela = {}
            for destino, keyword in target_keys.items():
                col_match = next((c for c in df_temp.columns if keyword in c), None)
                if col_match:
                    mapeamento_tabela[destino] = col_match

            for _, row in df_temp.iterrows():
                registro = {
                    'lineup_id': str(uuid.uuid4()),
                    'status_atual': 'Esperado',
                    'inserido_em': datetime.utcnow(),
                    'capacidade_ton': 0.0 # Campo do seu schema, inicializado como float
                }
                
                for destino, col_origem in mapeamento_tabela.items():
                    registro[destino] = row[col_origem]
                
                if pd.notnull(registro.get('ship_id')) and pd.notnull(registro.get('nome_navio')):
                    lista_final_registros.append(registro)

        if not lista_final_registros:
            return

        df_final = pd.DataFrame(lista_final_registros).drop_duplicates()

        # --- TRATAMENTO DE TIPOS ---
        df_final['ship_id'] = df_final['ship_id'].astype(str).apply(lambda x: x.split('.')[0] if '.' in x else x)
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        
        # 1. ALIMENTAR DIM_NAVIO (Exatamente 5 colunas do seu schema)
        colunas_dim_reais = ['ship_id', 'nome_navio', 'tipo_vessel', 'capacidade_ton', 'bandeira']
        
        # Garantimos que todas as colunas do seu schema existam no DataFrame
        for col in colunas_dim_reais:
            if col not in df_final.columns:
                df_final[col] = None if col != 'capacidade_ton' else 0.0

        df_dim = df_final[colunas_dim_reais].drop_duplicates().copy()
        # Forçamos tipos para bater com o BigQuery
        df_dim['ship_id'] = df_dim['ship_id'].astype(str)
        df_dim['capacidade_ton'] = df_dim['capacidade_ton'].astype(float)
        
        print(f"📦 Povoando dim_navio ({len(df_dim)} linhas) com schema validado.")
        safe_load_to_bq(df_dim, "dim_navio")

        # 2. ALIMENTAR FATO_LINEUP (Mantendo o que já funciona)
        colunas_fato = [
            'lineup_id', 'ship_id', 'data_chegada_prevista', 'status_atual', 
            'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
        ]
        # Limpeza rápida de terminais que capturam datas por erro
        df_final['terminal'] = df_final['terminal'].apply(lambda x: 'Não Identificado' if '/' in str(x) else x)
        
        df_fato = df_final[colunas_fato].copy()
        df_fato['ship_id'] = df_fato['ship_id'].astype(str)
        
        safe_load_to_bq(df_fato, "fato_lineup")

    except Exception as e:
        print(f"❌ Erro fatal: {e}")

def monitor_contingencias_batch():
    print("📰 Notícias...")
    df_nlp = pd.DataFrame([{
        'cont_id': str(uuid.uuid4()),
        'timestamp_leitura': datetime.utcnow(),
        'loc_id': 'SANTOS_LOGISTICA_GERAL',
        'texto_original': 'Monitoramento ativo.',
        'entidade_evento': 'Sistema Viário',
        'score_risco': 0.1,
        'json_extraido': '{}'
    }])
    df_nlp['timestamp_leitura'] = pd.to_datetime(df_nlp['timestamp_leitura'])
    safe_load_to_bq(df_nlp, "fato_contingencias_nlp")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()