import os
import pandas as pd
from datetime import datetime
import uuid
import requests
from bs4 import BeautifulSoup
import io
from google.cloud import bigquery
from dotenv import load_dotenv

# Configurações
load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = "logisticsdata"
client = bigquery.Client(project=PROJECT_ID)

def safe_load_to_bq(df, table_name):
    """Método Batch Load: Único aceito no Free Tier do BigQuery"""
    if df.empty: return
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    try:
        client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
        print(f"✅ {table_name}: {len(df)} linhas carregadas (Batch).")
    except Exception as e:
        print(f"❌ Erro no carregamento de {table_name}: {e}")

def extrair_dados_porto(url):
    """Scraper modular para as novas URLs do Porto"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        tabelas = soup.find_all('table')
        
        all_data = []
        for tab in tabelas:
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [' '.join(col).strip() for col in df_temp.columns.values]
            all_data.append(df_temp)
        
        return pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
    except Exception as e:
        print(f"⚠️ Erro ao acessar {url}: {e}")
        return pd.DataFrame()

def monitor_contingencias_batch():
    """Monitor de Notícias ajustado para Batch Load"""
    print("📰 Monitorando contingências...")
    # Lógica de scraping do G1/Ecovias aqui...
    df_nlp = pd.DataFrame([{
        'cont_id': str(uuid.uuid4()),
        'timestamp_leitura': datetime.utcnow(),
        'score_risco': 0.2, # Exemplo
        'texto_original': 'Condições estáveis nas rodovias.'
    }])
    # Forçamos o tipo para evitar erros de conversão no BQ
    df_nlp['timestamp_leitura'] = pd.to_datetime(df_nlp['timestamp_leitura'])
    safe_load_to_bq(df_nlp, "fato_contingencias_nlp")

def processar_operacao():
    print(f"🚀 Iniciando captura em tempo real: {datetime.now()}")
    
    # URLs sugeridas para Agro
    url_esperados = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    url_atracados = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracados-porto-terminais/"
    
    df_esperados = extrair_dados_porto(url_esperados)
    
    if not df_esperados.empty:
        # Tratamento de datas e de-duplicação
        # Foco em identificar o que é "Granel Sólido" para o Agro
        df_esperados['inserido_em'] = datetime.utcnow()
        
        # 1. Alimentar dim_navio (Cadastro)
        # O objetivo aqui é ter o histórico técnico dos navios que escalam Santos
        if 'IMO' in df_esperados.columns:
            df_dim = df_esperados[['IMO', 'Navio Ship']].drop_duplicates().rename(columns={'IMO': 'ship_id', 'Navio Ship': 'nome_navio'})
            safe_load_to_bq(df_dim, "dim_navio")
        
        # 2. Alimentar fato_lineup
        # Aqui enviamos os dados de carga e previsão de chegada
        safe_load_to_bq(df_esperados, "fato_lineup")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()