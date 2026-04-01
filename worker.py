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
    print(f"🚀 Iniciando captura direta (Ajuste de Tipos): {datetime.now()}")
    url = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=30)
        soup = BeautifulSoup(res.text, 'html.parser')
        tabelas = soup.find_all('table')
        
        registros_limpos = []
        mapeamento = {
            'ship_id': 'imo',
            'nome_navio': 'navio',
            'data_chegada_prevista': 'cheg',
            'commodity': 'mercadoria',
            'quantidade_estimada': 'peso',
            'terminal': 'terminal'
        }

        for tab in tabelas:
            df = pd.read_html(io.StringIO(str(tab)))[0]
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [' '.join(col).lower() for col in df.columns.values]
            else:
                df.columns = [str(c).lower() for c in df.columns]

            for _, row in df.iterrows():
                item = {}
                for campo, keyword in mapeamento.items():
                    col_alvo = next((c for c in df.columns if keyword in c), None)
                    item[campo] = row[col_alvo] if col_alvo else None
                
                # Só adiciona se tiver o IMO
                if pd.notnull(item['ship_id']):
                    registros_limpos.append(item)

        if not registros_limpos:
            print("⚠️ Nenhum dado encontrado.")
            return

        df_final = pd.DataFrame(registros_limpos).drop_duplicates()

        # --- O PULO DO GATO: CONVERSÃO DE TIPOS ---
        
        # 1. ship_id como STRING (Remove o .0 se houver)
        df_final['ship_id'] = df_final['ship_id'].astype(str).str.split('.').str[0]
        
        # 2. data_chegada como TIMESTAMP
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        df_final['data_atracacao_prevista'] = df_final['data_chegada_prevista']
        
        # 3. quantidade como FLOAT
        df_final['quantidade_estimada'] = pd.to_numeric(
            df_final['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0.0).astype(float)
        
        # 4. Outros campos como STRING
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        df_final['status_atual'] = 'Esperado'
        df_final['inserido_em'] = datetime.utcnow()

        # Limpeza final de nulos críticos
        df_final = df_final.dropna(subset=['data_chegada_prevista', 'ship_id'])

        if not df_final.empty:
            # 1. Povoar dim_navio (Apenas ship_id e nome)
            df_dim = df_final[['ship_id', 'nome_navio']].drop_duplicates().astype(str)
            safe_load_to_bq(df_dim, "dim_navio")

            # 2. Povoar fato_lineup
            colunas_fato = ['lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista', 
                            'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em']
            
            df_fato = df_final[colunas_fato].copy()
            
            # Garantia final de tipos para o Pyarrow não reclamar
            df_fato['ship_id'] = df_fato['ship_id'].astype(str)
            df_fato['terminal'] = df_fato['terminal'].astype(str)
            df_fato['commodity'] = df_fato['commodity'].astype(str)
            
            print(f"📦 Sucesso: {len(df_fato)} navios prontos para o BigQuery.")
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