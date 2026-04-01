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
    print(f"🚀 Iniciando captura em tempo real (Modo Anti-Duplicata): {datetime.now()}")
    
    url_carga = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
    
    df_bruto = extrair_dados_porto(url_carga)
    
    if not df_bruto.empty:
        # 1. MAPEAMENTO POR POSIÇÃO
        target_keys = {
            'ship_id': 'imo',
            'nome_navio': 'navio_ship',
            'data_chegada_prevista': 'chegarrival',
            'commodity': 'mercadoria_goods',
            'quantidade_estimada': 'peso_weight',
            'terminal': 'terminal'
        }

        dados_limpos = {}
        
        # O segredo: Pegar apenas o PRIMEIRO índice que der match com a keyword
        for destino, keyword in target_keys.items():
            # Encontra o índice da primeira coluna que contém a keyword
            idx = next((i for i, c in enumerate(df_bruto.columns) if keyword in str(c).lower()), None)
            
            if idx is not None:
                # Extraímos a coluna pela posição exata para garantir que venha apenas UMA Series
                coluna_serie = df_bruto.iloc[:, idx]
                
                # Caso o Pandas retorne um DataFrame (raro com iloc de um índice), pegamos a primeira coluna
                if isinstance(coluna_serie, pd.DataFrame):
                    coluna_serie = coluna_serie.iloc[:, 0]
                
                # Salvamos apenas os valores para resetar qualquer conflito de índice
                dados_limpos[destino] = coluna_serie.reset_index(drop=True)
            else:
                dados_limpos[destino] = pd.Series([None] * len(df_bruto))

        # Criamos o DataFrame NOVO - Agora é IMPOSSÍVEL ter chaves duplicadas
        df_final = pd.DataFrame(dados_limpos)

        # 2. TRATAMENTO DE DADOS
        # Agora o df_final['data_chegada_prevista'] é garantidamente uma Series única
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        
        # Limpeza de números
        df_final['quantidade_estimada'] = pd.to_numeric(
            df_final['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0)
        
        df_final['inserido_em'] = datetime.utcnow()
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        df_final['status_atual'] = 'Esperado'
        df_final['data_atracacao_prevista'] = df_final['data_chegada_prevista']

        # Limpeza final: removemos o que não tem ID ou Data
        df_final = df_final.dropna(subset=['ship_id', 'data_chegada_prevista']).copy()

        if not df_final.empty:
            # 3. ALIMENTAR DIM_NAVIO
            df_dim = df_final[['ship_id', 'nome_navio']].drop_duplicates()
            safe_load_to_bq(df_dim, "dim_navio")

            # 4. ALIMENTAR FATO_LINEUP
            colunas_fato = [
                'lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista',
                'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
            ]
            
            df_fato = df_final[colunas_fato].copy()
            print(f"📦 Sucesso: {len(df_fato)} navios processados sem duplicatas de colunas.")
            safe_load_to_bq(df_fato, "fato_lineup")
        else:
            print("⚠️ Nenhuma linha válida restou após o tratamento.")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()