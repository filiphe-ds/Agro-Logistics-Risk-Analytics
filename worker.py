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
    print(f"🚀 Iniciando captura direta (Correção de Tipos Pyarrow): {datetime.now()}")
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
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [' '.join(col).lower() for col in df_temp.columns.values]
            else:
                df_temp.columns = [str(c).lower() for c in df_temp.columns]

            for _, row in df_temp.iterrows():
                item = {}
                for campo, keyword in mapeamento.items():
                    col_alvo = next((c for c in df_temp.columns if keyword in c), None)
                    item[campo] = row[col_alvo] if col_alvo else None
                
                if pd.notnull(item['ship_id']):
                    registros_limpos.append(item)

        if not registros_limpos:
            print("⚠️ Nenhum dado encontrado.")
            return

        # Montamos o DataFrame base
        df_final = pd.DataFrame(registros_limpos).drop_duplicates()

        # --- CORREÇÃO DE TIPOS PARA O PYARROW ---

        # 1. ship_id: Converte para string, remove o '.0' e filtra 'nan'
        # Usamos uma função anônima para garantir que '9292577.0' vire '9292577'
        df_final['ship_id'] = df_final['ship_id'].astype(str).apply(lambda x: x.split('.')[0] if '.' in x else x)
        df_final = df_final[df_final['ship_id'] != 'nan'].copy()
        
        # 2. Datas: Garantir formato datetime64[ns]
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        df_final['data_atracacao_prevista'] = df_final['data_chegada_prevista']
        
        # 3. Quantidade: Garantir float real
        df_final['quantidade_estimada'] = pd.to_numeric(
            df_final['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0.0).astype(float)
        
        # 4. Metadados
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        df_final['status_atual'] = 'Esperado'
        df_final['inserido_em'] = datetime.utcnow()

        # Filtro de sanidade
        df_final = df_final.dropna(subset=['data_chegada_prevista', 'ship_id']).copy()

        if not df_final.empty:
            # --- UPLOAD PARA DIM_NAVIO ---
            df_dim = df_final[['ship_id', 'nome_navio']].drop_duplicates().copy()
            # Forçamos o tipo object (string) no pandas antes do upload
            df_dim['ship_id'] = df_dim['ship_id'].astype(str)
            df_dim['nome_navio'] = df_dim['nome_navio'].astype(str)
            
            print(f"📦 Subindo {len(df_dim)} navios para dim_navio...")
            safe_load_to_bq(df_dim, "dim_navio")

            # --- UPLOAD PARA FATO_LINEUP ---
            colunas_fato = [
                'lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista', 
                'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
            ]
            df_fato = df_final[colunas_fato].copy()
            
            # Garantia final de conversão para o fiscal de tipos do BigQuery
            df_fato['ship_id'] = df_fato['ship_id'].astype(str)
            df_fato['terminal'] = df_fato['terminal'].astype(str).fillna('N/A')
            df_fato['commodity'] = df_fato['commodity'].astype(str).fillna('N/A')
            
            print(f"📦 Subindo {len(df_fato)} registros para fato_lineup...")
            safe_load_to_bq(df_fato, "fato_lineup")
        else:
            print("⚠️ Sem dados válidos após tratamento de tipos.")

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