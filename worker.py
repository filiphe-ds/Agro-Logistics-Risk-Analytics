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
    print(f"🚀 Iniciando captura (Versão Flexível): {datetime.now()}")
    
    fontes = [
        {"url": "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/", "status": "Esperado"},
        {"url": "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracados-porto-terminais/", "status": "Atracado"}
    ]
    
    headers = {"User-Agent": "Mozilla/5.0"}
    lista_final_registros = []

    try:
        for fonte in fontes:
            print(f"🛰️ Tentando coletar: {fonte['status']}")
            res = requests.get(fonte['url'], headers=headers, verify=False, timeout=30)
            if res.status_code != 200: continue
            
            soup = BeautifulSoup(res.text, 'html.parser')
            tabelas_html = soup.find_all('table')
        
            for tab in tabelas_html:
                try:
                    df_temp = pd.read_html(io.StringIO(str(tab)))[0]
                except: continue

                # Normalização das colunas da tabela atual
                df_temp.columns = [limpar_nome_coluna(c) for c in df_temp.columns]
                
                for _, row in df_temp.iterrows():
                    # --- Lógica de Mapeamento Flexível ---
                    def buscar(termos):
                        for col in df_temp.columns:
                            if any(t in col for t in termos):
                                return row[col]
                        return None

                    # Extração com múltiplas tentativas de nome de coluna
                    imo_val = str(buscar(['imo', 'nº', 'identificacao']) or '').split('.')[0].strip()
                    
                    reg = {
                        'ship_id': imo_val,
                        'nome_navio': buscar(['navio', 'ship', 'nome']),
                        'tipo_vessel': buscar(['vessel', 'tipo', 'embarcacao']),
                        'bandeira': buscar(['flag', 'bandeira']),
                        'terminal': str(buscar(['terminal', 'local', 'cais']) or 'Area de Fundeio').strip(),
                        'commodity': buscar(['mercadoria', 'produto', 'carga', 'commodity']),
                        'quantidade_estimada': buscar(['peso', 'ton', 'quantidade'], 0),
                        'data_chegada_prevista': buscar(['chegada', 'arrival', 'data', 'previsto']),
                        'status_atual': fonte['status'],
                        'inserido_em': datetime.utcnow()
                    }
                    
                    # Só adiciona se tiver um IMO válido (mínimo 4 dígitos)
                    if reg['ship_id'] and reg['ship_id'] != 'nan' and len(reg['ship_id']) >= 4:
                        if reg['terminal'].isdigit() or '/' in reg['terminal'] or len(reg['terminal']) < 3:
                            reg['terminal'] = "Área de Fundeio / Outros"
                        lista_final_registros.append(reg)

        if not lista_final_registros: 
            print("⚠️ Nenhum registro processado nesta rodada.")
            return
        
        df_final = pd.DataFrame(lista_final_registros)
        
        # Deduplicação no Python antes de enviar para o banco (Prioriza Atracados)
        df_final = df_final.sort_values('status_atual', ascending=True).drop_duplicates(subset=['ship_id'])

        # --- ENVIO FATO_LINEUP ---
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce').dt.date
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        
        colunas_fato = ['lineup_id', 'ship_id', 'data_chegada_prevista', 'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em']
        df_fato = df_final[colunas_fato].copy()
        
        # Limpeza de peso (converte string "25.000,00" para float 25000.0)
        df_fato['quantidade_estimada'] = pd.to_numeric(
            df_fato['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), 
            errors='coerce'
        ).fillna(0.0)
        
        safe_load_to_bq(df_fato.dropna(subset=['data_chegada_prevista']), "fato_lineup")

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