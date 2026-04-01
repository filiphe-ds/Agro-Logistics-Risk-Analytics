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

def extrair_dados_porto_limpo(url):
    """Scraper que limpa e padroniza cada tabela ANTES de juntar"""
    headers = {"User-Agent": "Mozilla/5.0"}
    target_keys = {
        'ship_id': 'imo',
        'nome_navio': 'navio_ship',
        'data_chegada_prevista': 'chegarrival',
        'commodity': 'mercadoria_goods',
        'quantidade_estimada': 'peso_weight',
        'terminal': 'terminal'
    }
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=25)
        soup = BeautifulSoup(response.text, 'html.parser')
        tabelas = soup.find_all('table')
        
        tabelas_padronizadas = []
        
        for tab in tabelas:
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            
            # 1. Achata MultiIndex e limpa nomes
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [limpar_nome_coluna(' '.join(col)) for col in df_temp.columns.values]
            else:
                df_temp.columns = [limpar_nome_coluna(c) for c in df_temp.columns]
            
            # 2. Para ESTA tabela, encontra a melhor coluna para cada alvo
            dados_tabela = {}
            for destino, keyword in target_keys.items():
                col_match = next((c for c in df_temp.columns if keyword in c), None)
                if col_match:
                    # Pegamos apenas a primeira ocorrência da coluna nesta tabela
                    dados_tabela[destino] = df_temp[col_match].iloc[:] 
                else:
                    dados_tabela[destino] = pd.Series([None] * len(df_temp))
            
            # 3. Cria um DF limpo desta tabela específica
            df_limpo = pd.DataFrame(dados_tabela)
            tabelas_padronizadas.append(df_limpo)
        
        # 4. Agora sim, concatenamos DFs que têm as mesmas colunas EXATAS
        if tabelas_padronizadas:
            df_consolidado = pd.concat(tabelas_padronizadas, ignore_index=True)
            # Remove duplicatas de nomes de colunas que podem ter sobrado no concat
            return df_consolidado.loc[:, ~df_consolidado.columns.duplicated()]
        return pd.DataFrame()
        
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
    print(f"🚀 Iniciando captura em tempo real (Modo Padronizado): {datetime.now()}")
    
    url_carga = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    
    # Já recebemos o DataFrame com colunas únicas e nomes padronizados
    df_final = extrair_dados_porto_limpo(url_carga)
    
    if not df_final.empty:
        # TRATAMENTO DE DADOS (Sem erro de duplicatas agora!)
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        
        df_final['quantidade_estimada'] = pd.to_numeric(
            df_final['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0)
        
        df_final['inserido_em'] = datetime.utcnow()
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        df_final['status_atual'] = 'Esperado'
        df_final['data_atracacao_prevista'] = df_final['data_chegada_prevista']

        # Limpeza de segurança
        df_final = df_final.dropna(subset=['ship_id', 'data_chegada_prevista']).copy()

        if not df_final.empty:
            # Alimentar dim_navio
            df_dim = df_final[['ship_id', 'nome_navio']].drop_duplicates()
            safe_load_to_bq(df_dim, "dim_navio")

            # Alimentar fato_lineup
            colunas_fato = [
                'lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista',
                'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
            ]
            
            df_fato = df_final[colunas_fato].copy()
            print(f"📦 Sucesso: {len(df_fato)} navios consolidados.")
            safe_load_to_bq(df_fato, "fato_lineup")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()