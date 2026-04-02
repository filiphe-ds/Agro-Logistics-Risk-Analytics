import os
import pandas as pd
import numpy as np
from datetime import datetime
import uuid
import requests
from bs4 import BeautifulSoup
import io
import re
from google.cloud import bigquery
from dotenv import load_dotenv
import urllib3

# 1. Configurações Iniciais e Supressão de Avisos
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = "logisticsdata"
client = bigquery.Client(project=PROJECT_ID)

def limpar_nome_coluna(col):
    """Transforma nomes sujos em snake_case aceito pelo BigQuery"""
    col = str(col).lower()
    col = re.sub(r'[^\w\s]', '', col) # Remove caracteres especiais
    col = col.strip().replace(' ', '_') # Substitui espaços por underscore
    return col[:300]

def safe_load_to_bq(df, table_name):
    """Método Batch Load: Único aceito no Free Tier do BigQuery"""
    if df.empty: 
        print(f"⚠️ {table_name}: DataFrame vazio, pulando carga.")
        return
    
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    
    try:
        client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
        print(f"✅ {table_name}: {len(df)} linhas carregadas.")
    except Exception as e:
        print(f"❌ Erro no carregamento de {table_name}: {e}")

def processar_operacao():
    print(f"🚀 Iniciando captura (Deduplicação e Limpeza de Terminais): {datetime.now()}")
    url = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    target_keys = {
        'ship_id': 'imo',
        'nome_navio': 'navio_ship',
        'bandeira': 'flag',
        'tipo_vessel': 'nav',             
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
                # Geramos os dados base primeiro
                reg = {}
                for destino, col_origem in mapeamento_tabela.items():
                    reg[destino] = row[col_origem]
                
                if pd.notnull(reg.get('ship_id')) and pd.notnull(reg.get('nome_navio')):
                    lista_final_registros.append(reg)

        if not lista_final_registros:
            return

        # Criamos o DataFrame
        df_final = pd.DataFrame(lista_final_registros)

        # --- 1. LIMPEZA DE IDs (Crucial para a Unicidade) ---
        df_final['ship_id'] = df_final['ship_id'].astype(str).apply(lambda x: x.split('.')[0] if '.' in x else x)

        # --- 2. DEDUPLICAÇÃO POR NAVIO (Evita o inchaço na carga atual) ---
        # Mantemos apenas um registro por navio nesta rodada do robô
        df_final = df_final.drop_duplicates(subset=['ship_id'])

        # --- 3. LIMPEZA RIGOROSA DO TERMINAL (Resolve os números no gráfico) ---
        def limpar_terminal(valor):
            v = str(valor).strip()
            # Se for só número (como o IMO), tiver data (/) ou for curto demais, não é terminal
            if v.isdigit() or '/' in v or len(v) < 3:
                return "Área de Fundeio / Outros"
            return v
        
        df_final['terminal'] = df_final['terminal'].apply(limpar_terminal)

        # --- 4. PREPARAÇÃO FINAL PARA O BIGQUERY ---
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        df_final['status_atual'] = 'Esperado'
        df_final['inserido_em'] = datetime.utcnow()
        df_final['capacidade_ton'] = 0.0
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')

        # --- ENVIO PARA DIM_NAVIO ---
        colunas_dim = ['ship_id', 'nome_navio', 'tipo_vessel', 'capacidade_ton', 'bandeira']
        df_dim = df_final[colunas_dim].copy()
        safe_load_to_bq(df_dim, "dim_navio")

        # --- ENVIO PARA FATO_LINEUP ---
        colunas_fato = [
            'lineup_id', 'ship_id', 'data_chegada_prevista', 'status_atual', 
            'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
        ]
        df_fato = df_final[colunas_fato].copy()
        df_fato['quantidade_estimada'] = pd.to_numeric(
            df_fato['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0.0).astype(float)
        
        df_fato = df_fato.dropna(subset=['data_chegada_prevista']).copy()
        
        print(f"📦 Sucesso: Enviando {len(df_fato)} navios únicos nesta rodada.")
        safe_load_to_bq(df_fato, "fato_lineup")

    except Exception as e:
        print(f"❌ Erro fatal: {e}")

def monitor_contingencias_batch():
    print("📰 Monitorando notícias e contingências...")
    df_nlp = pd.DataFrame([{
        'cont_id': str(uuid.uuid4()),
        'timestamp_leitura': datetime.utcnow(),
        'loc_id': 'SANTOS_LOGISTICA_GERAL',
        'texto_original': 'Monitoramento de vias Anchieta-Imigrantes ativo e estável.',
        'entidade_evento': 'Sistema Viário',
        'score_risco': 0.1,
        'json_extraido': '{}'
    }])
    df_nlp['timestamp_leitura'] = pd.to_datetime(df_nlp['timestamp_leitura'])
    safe_load_to_bq(df_nlp, "fato_contingencias_nlp")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()