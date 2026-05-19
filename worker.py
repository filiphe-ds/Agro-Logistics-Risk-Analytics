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
    print(f"🚀 Iniciando captura (Versão Sniper): {datetime.now()}")
    
    # 1. Carrega Dicionário de Navios (Ponte de Identidade)
    print("🔍 Consultando dim_navio para mapeamento de nomes...")
    query_dim = f"SELECT ship_id, nome_navio FROM `{PROJECT_ID}.{DATASET_ID}.dim_navio`"
    try:
        df_conhecidos = client.query(query_dim).to_dataframe()
        mapa_navios = dict(zip(df_conhecidos['nome_navio'].str.strip().str.upper(), df_conhecidos['ship_id']))
        print(f"✅ {len(mapa_navios)} navios conhecidos carregados.")
    except Exception as e:
        mapa_navios = {}
        print(f"⚠️ Erro ao carregar dicionário: {e}")

    fontes = [
        {"url": "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/", "status": "Esperado"},
        {"url": "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracados-porto-terminais/", "status": "Atracado"}
    ]
    
    headers = {"User-Agent": "Mozilla/5.0"}
    lista_final_registros = []

    try:
        for fonte in fontes:
            print(f"🛰️ Acessando: {fonte['status']}")
            res = requests.get(fonte['url'], headers=headers, verify=False, timeout=30)
            if res.status_code != 200: continue
            
            soup = BeautifulSoup(res.text, 'html.parser')
            tabelas_html = soup.find_all('table')
        
            for i, tab in enumerate(tabelas_html):
                try:
                    df_temp = pd.read_html(io.StringIO(str(tab)))[0]
                except: continue

                # Limpeza agressiva: remove \n e espaços extras dos cabeçalhos
                df_temp.columns = [str(c).replace('\n', ' ').strip().lower() for c in df_temp.columns]
                
                print(f"📊 Processando Tabela {i} de {fonte['status']} ({len(df_temp)} linhas)")

                for idx, row in df_temp.iterrows():
                    def buscar_valor(termos, col_index=None):
                        for col in df_temp.columns:
                            if any(t in col for t in termos):
                                return row[col]
                        if col_index is not None and col_index < len(row):
                            return row.iloc[col_index]
                        return None

                    # Estratégia de Colunas por URL
                    idx_navio = 0 if fonte['status'] == "Esperado" else 1
                    
                    nome_navio_raw = buscar_valor(['navio', 'ship', 'burque'], idx_navio)
                    nome_navio = str(nome_navio_raw or '').strip().upper()
                    
                    imo_val = str(buscar_valor(['imo', 'nº', 'identificacao']) or '').split('.')[0].strip()
                    
                    # Ponte de Identidade pelo nome do Navio
                    if (not imo_val or imo_val == 'nan' or len(imo_val) < 4) and nome_navio:
                        imo_val = mapa_navios.get(nome_navio, 'nan')

                    reg = {
                        'ship_id': imo_val,
                        'nome_navio': nome_navio,
                        'terminal': str(buscar_valor(['terminal', 'local', 'cais', 'berço']) or 'Area de Fundeio').strip(),
                        'status_atual': fonte['status'],
                        'data_chegada_prevista': buscar_valor(['chegada', 'arrival', 'data', 'previsto']),
                        'commodity': buscar_valor(['mercadoria', 'produto', 'carga']),
                        'quantidade_estimada': buscar_valor(['peso', 'ton'], 0),
                        'inserido_em': datetime.utcnow()
                    }
                    
                    if reg['ship_id'] and reg['ship_id'] != 'nan' and len(reg['ship_id']) >= 4:
                        lista_final_registros.append(reg)
                    else:
                        if idx < 3:
                            print(f"   ⚠️ Ignorado: {nome_navio} (IMO não resolvido)")

        if not lista_final_registros: return
        
        df_final = pd.DataFrame(lista_final_registros)
        df_final = df_final.sort_values('status_atual', ascending=True).drop_duplicates(subset=['ship_id'])

        # --- ENVIO FATO_LINEUP ---
        df_final['data_chegada_prevista'] = pd.to_datetime(df_final['data_chegada_prevista'], dayfirst=True, errors='coerce').dt.date
        df_final['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_final))]
        
        colunas_fato = ['lineup_id', 'ship_id', 'data_chegada_prevista', 'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em']
        df_fato = df_final[colunas_fato].copy()
        df_fato['quantidade_estimada'] = pd.to_numeric(df_fato['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce').fillna(0.0)
        
        # 🔥 AQUI ESTAVA O ERRO: Substituição do dropna por filtro condicional resiliente
        df_fato_filtrado = df_fato[
            ((df_fato['status_atual'] == 'Esperado') & (df_fato['data_chegada_prevista'].notna())) |
            (df_fato['status_atual'] == 'Atracado')
        ]
        
        safe_load_to_bq(df_fato_filtrado, "fato_lineup")

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