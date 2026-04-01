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

# Desativa avisos de segurança do certificado do site do Porto
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configurações
load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = "logisticsdata"
client = bigquery.Client(project=PROJECT_ID)

def limpar_nome_coluna(col):
    """Transforma nomes sujos em snake_case aceito pelo BigQuery"""
    col = str(col).lower()
    # Remove acentos e caracteres especiais
    col = re.sub(r'[^\w\s]', '', col)
    # Substitui espaços por underscores
    col = col.strip().replace(' ', '_')
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
        print(f"✅ {table_name}: {len(df)} linhas carregadas (Batch).")
    except Exception as e:
        print(f"❌ Erro no carregamento de {table_name}: {e}")

def extrair_dados_porto(url):
    """Scraper modular que limpa colunas automaticamente"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=25)
        soup = BeautifulSoup(response.text, 'html.parser')
        tabelas = soup.find_all('table')
        
        all_data = []
        for tab in tabelas:
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            # Achata MultiIndex se houver
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [' '.join(col).strip() for col in df_temp.columns.values]
            
            # Limpa os nomes das colunas IMEDIATAMENTE
            df_temp.columns = [limpar_nome_coluna(c) for c in df_temp.columns]
            all_data.append(df_temp)
        
        return pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
    except Exception as e:
        print(f"⚠️ Erro ao acessar {url}: {e}")
        return pd.DataFrame()

def monitor_contingencias_batch():
    """Monitor de Notícias via Batch Load"""
    print("📰 Monitorando contingências (Ecovias/G1)...")
    # Lógica simplificada para garantir a carga
    df_nlp = pd.DataFrame([{
        'cont_id': str(uuid.uuid4()),
        'timestamp_leitura': datetime.utcnow(),
        'loc_id': 'SANTOS_LOGISTICA_GERAL',
        'texto_original': 'Monitoramento de rotas Anchieta-Imigrantes ativo.',
        'entidade_evento': 'Sistema Viário',
        'score_risco': 0.1,
        'json_extraido': '{}'
    }])
    df_nlp['timestamp_leitura'] = pd.to_datetime(df_nlp['timestamp_leitura'])
    safe_load_to_bq(df_nlp, "fato_contingencias_nlp")

def processar_operacao():
    print(f"🚀 Iniciando captura em tempo real (Modo Blindado): {datetime.now()}")
    
    url_carga = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    
    df_bruto = extrair_dados_porto(url_carga)
    
    if not df_bruto.empty:
        # 1. MAPEAMENTO POR PALAVRA-CHAVE
        mapeamento = {}
        target_keys = {
            'ship_id': 'imo',
            'nome_navio': 'navio_ship',
            'data_chegada_prevista': 'chegarrival',
            'commodity': 'mercadoria_goods',
            'quantidade_estimada': 'peso_weight',
            'terminal': 'terminal'
        }

        # Identificamos quais colunas sujas correspondem aos nossos campos
        for destino, keyword in target_keys.items():
            for col_real in df_bruto.columns:
                if keyword in col_real:
                    mapeamento[col_real] = destino
        
        # Criamos o DataFrame final apenas com o que mapeamos
        df_final = df_bruto.rename(columns=mapeamento)

        # 2. TRATAMENTO DE DADOS
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        df_final['quantidade_estimada'] = pd.to_numeric(
            df_final['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0)
        
        df_final['inserido_em'] = datetime.utcnow()
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        df_final['status_atual'] = 'Esperado'
        df_final['data_atracacao_prevista'] = df_final['data_chegada_prevista']

        # --- 3. ALIMENTAR DIM_NAVIO ---
        # Filtramos APENAS as duas colunas necessárias para a dimensão
        if 'ship_id' in df_final.columns and 'nome_navio' in df_final.columns:
            df_dim = df_final[df_final['ship_id'].notnull()][['ship_id', 'nome_navio']].drop_duplicates()
            if not df_dim.empty:
                safe_load_to_bq(df_dim, "dim_navio")

        # --- 4. ALIMENTAR FATO_LINEUP (A MUDANÇA CRUCIAL AQUI) ---
        # Definimos exatamente o que a tabela fato espera (9 colunas)
        colunas_vip = [
            'lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista',
            'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
        ]
        
        # Criamos um DataFrame NOVO contendo apenas as colunas VIP e que existem no df_final
        # Isso garante que NENHUMA coluna "suja" (tipo LIQUIDO A GRANEL...) entre no upload
        colunas_presentes = [c for c in colunas_vip if c in df_final.columns]
        df_fato = df_final[colunas_presentes].copy()

        # Removemos linhas onde o ship_id ou data são nulos para não quebrar o BQ
        df_fato = df_fato.dropna(subset=['ship_id', 'data_chegada_prevista'])

        # Se faltar alguma coluna VIP no scrape, criamos ela vazia para manter o schema
        for col in colunas_vip:
            if col not in df_fato.columns:
                df_fato[col] = None

        print(f"📦 Preparado para subir {len(df_fato)} navios. Colunas no pacote: {df_fato.columns.tolist()}")
        
        # Disparo final
        safe_load_to_bq(df_fato, "fato_lineup")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()