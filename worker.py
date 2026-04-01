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
    col = re.sub(r'[^\w\s]', '', col)
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

def monitor_contingencias_batch():
    """Monitor de Notícias via Batch Load"""
    print("📰 Monitorando contingências (Ecovias/G1)...")
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
    print(f"🚀 Iniciando captura em tempo real (Modo Registro Único): {datetime.now()}")
    
    url_carga = "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"
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
        response = requests.get(url_carga, headers=headers, verify=False, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        tabelas_html = soup.find_all('table')
        
        lista_final_registros = []
        
        for tab in tabelas_html:
            # Lemos a tabela atual
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            
            # Limpamos os nomes das colunas APENAS desta tabela
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [limpar_nome_coluna(' '.join(col)) for col in df_temp.columns.values]
            else:
                df_temp.columns = [limpar_nome_coluna(c) for c in df_temp.columns]
            
            # Mapeamos quais colunas desta tabela correspondem aos nossos alvos
            mapeamento_tabela = {}
            for destino, keyword in target_keys.items():
                col_match = next((c for c in df_temp.columns if keyword in c), None)
                if col_match:
                    mapeamento_tabela[destino] = col_match

            # Extração linha a linha para evitar conflito de chaves do Pandas
            for _, row in df_temp.iterrows():
                registro = {
                    'lineup_id': str(uuid.uuid4()),
                    'status_atual': 'Esperado',
                    'inserido_em': datetime.utcnow()
                }
                
                # Preenchemos o dicionário apenas com as colunas encontradas
                for destino, col_origem in mapeamento_tabela.items():
                    registro[destino] = row[col_origem]
                
                # Filtro básico: se não tem nome ou IMO, ignoramos a linha
                if pd.notnull(registro.get('ship_id')) and pd.notnull(registro.get('nome_navio')):
                    lista_final_registros.append(registro)

        if not lista_final_registros:
            print("⚠️ Nenhum registro válido encontrado.")
            return

        # Criamos um DataFrame limpo a partir da lista de dicionários
        # Isso garante que não existam colunas duplicadas!
        df_final = pd.DataFrame(lista_final_registros)

        # Tratamento de tipos seguro
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce')
        df_final['data_atracacao_prevista'] = df_final['data_chegada_prevista']
        
        # Limpeza de peso (converte "20.000,00" para float)
        df_final['quantidade_estimada'] = pd.to_numeric(
            df_final['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0)

        # Remove o que não tem data válida
        df_final = df_final.dropna(subset=['data_chegada_prevista']).copy()

        if not df_final.empty:
            # 1. Alimentar dim_navio (Cadastro)
            df_dim = df_final[['ship_id', 'nome_navio']].drop_duplicates()
            safe_load_to_bq(df_dim, "dim_navio")

            # 2. Alimentar fato_lineup
            colunas_fato = [
                'lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista',
                'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em'
            ]
            print(f"📦 Sucesso: {len(df_final)} registros preparados para o BigQuery.")
            safe_load_to_bq(df_final[colunas_fato], "fato_lineup")
        else:
            print("⚠️ Nenhuma linha válida após conversão de datas.")

    except Exception as e:
        print(f"❌ Erro fatal no processamento: {e}")

if __name__ == "__main__":
    processar_operacao()
    monitor_contingencias_batch()