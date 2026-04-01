import os
import pandas as pd
import numpy as np
from datetime import datetime
import uuid
import requests
from bs4 import BeautifulSoup
import io
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
VC_API_KEY = os.getenv("VC_API_KEY")
DATASET_ID = "logisticsdata"

client = bigquery.Client(project=PROJECT_ID)

# --- FUNÇÃO 1: CLIMA (REVISADA) ---
def coletar_clima():
    TABLE_ID_CLIMA = f"{PROJECT_ID}.{DATASET_ID}.fato_clima"
    pontos = [
        {"loc_id": "PORTO_SANTOS_CANAL", "lat": -23.9608, "lon": -46.3339},
        {"loc_id": "SERRA_ANCHIETA_IMIGRANTES", "lat": -23.8919, "lon": -46.4961},
        {"loc_id": "AREA_FUNDEIO_SANTOS", "lat": -24.0150, "lon": -46.3000}
    ]
    lista_dfs = []
    for p in pontos:
        url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{p['lat']},{p['lon']}/today?unitGroup=metric&key={VC_API_KEY}&contentType=csv"
        try:
            df = pd.read_csv(url)
            df_ponto = pd.DataFrame({
                'loc_id': p['loc_id'],
                'timestamp_leitura': pd.to_datetime(df['datetime']),
                'precipitacao_mm': df['precip'].fillna(0),
                'velocidade_vento': df['windspeed'],
                'umidade': df['humidity'],
                'alerta_critico': (df['precip'] > 5) | (df['windspeed'] > 15)
            })
            lista_dfs.append(df_ponto)
        except Exception as e: print(f"⚠️ Erro clima {p['loc_id']}: {e}")
    
    if lista_dfs:
        df_final = pd.concat(lista_dfs)
        client.load_table_from_dataframe(df_final, TABLE_ID_CLIMA, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")).result()
        print(f"🚀 [CLIMA] {len(df_final)} registros enviados.")

# --- FUNÇÃO 2: LINE-UP (BUSCA EM TODAS AS TABELAS) ---
def extrair_lineup_completo():
    url = "https://www.portodesantos.com.br/informacoes-operacionais/operacao-portuaria/navegacao-e-movimentacao-de-navios/navios-esperados/"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, verify=False)
    soup = BeautifulSoup(response.text, 'html.parser')
    tabelas_html = soup.find_all('table')
    
    lista_geral = []
    for tab in tabelas_html:
        try:
            df_temp = pd.read_html(io.StringIO(str(tab)))[0]
            # Limpa colunas MultiIndex
            if isinstance(df_temp.columns, pd.MultiIndex):
                df_temp.columns = [' '.join(col).strip() for col in df_temp.columns.values]
            lista_geral.append(df_temp)
        except: continue
        
    return pd.concat(lista_geral, ignore_index=True) if lista_geral else None

# --- FUNÇÃO 3: PROCESSAMENTO, DIM_NAVIO E FATO_LINEUP ---
def processar_e_subir_dados(df_bruto):
    if df_bruto is None: return
    
    df = df_bruto.copy()
    # Mapeamento robusto
    mapeamento = {'Navio Ship': 'nome_navio', 'Cheg/Arrival d/m/y': 'data_chegada', 'IMO': 'ship_id', 'Terminal': 'terminal', 'Mercadoria Goods': 'commodity', 'Peso Weight': 'quantidade'}
    real_rename = {col: v for col in df.columns for k, v in mapeamento.items() if k in col}
    df = df.rename(columns=real_rename)

    # Filtrar apenas o que tem ship_id válido
    df = df[df['ship_id'].notnull()].copy()
    df['data_chegada'] = pd.to_datetime(df['data_chegada'], dayfirst=True, errors='coerce')
    df['quantidade'] = pd.to_numeric(df['quantidade'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
    df['inserido_em'] = datetime.utcnow()

    # --- 3.1: Alimentar dim_navio (Cadastro Único) ---
    df_dim = df[['ship_id', 'nome_navio']].drop_duplicates()
    client.load_table_from_dataframe(df_dim, f"{PROJECT_ID}.{DATASET_ID}.dim_navio", 
                                     job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")).result()

    # --- 3.2: Alimentar fato_lineup ---
    df_fato = df[['ship_id', 'data_chegada', 'terminal', 'commodity', 'quantidade', 'inserido_em']].copy()
    df_fato['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_fato))]
    df_fato['status_atual'] = 'Esperado'
    df_fato['data_atracacao_prevista'] = df_fato['data_chegada']

    client.load_table_from_dataframe(df_fato, f"{PROJECT_ID}.{DATASET_ID}.fato_lineup", 
                                     job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")).result()
    print(f"✅ [LINE-UP] {len(df_fato)} navios e dim_navio atualizados!")

# --- FUNÇÃO 4: NLP (VERSÃO COMPATÍVEL COM FREE TIER) ---
def monitor_contingencias_batch():
    print("📰 [NLP] Monitorando Ecovias e G1...")
    textos = []
    score = 0.0
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # Scrapers simples (Ecovias/G1)
    try:
        res = requests.get("https://g1.globo.com/sp/santos-regiao/", headers=headers, timeout=10)
        noticias = BeautifulSoup(res.text, 'html.parser').find_all('a', class_='feed-post-link')
        for n in noticias[:3]:
            t = n.get_text().lower()
            if any(x in t for x in ["greve", "acidente", "paralisação", "bloqueio"]):
                score += 0.4
                textos.append(f"Alerta: {n.get_text()[:50]}...")
    except: pass

    resumo = " | ".join(textos) if textos else "Condições normais."
    
    # DataFrame para carregar via Batch (Load Job), não via Streaming
    df_nlp = pd.DataFrame([{
        'cont_id': str(uuid.uuid4()),
        'loc_id': 'SANTOS_LOGISTICA_GERAL',
        'timestamp_leitura': datetime.utcnow(),
        'texto_original': resumo,
        'entidade_evento': 'Sistema Anchieta-Imigrantes / Porto',
        'score_risco': float(min(score, 1.0)),
        'json_extraido': '{}'
    }])

    # Forçar tipo datetime para evitar erro de conversão
    df_nlp['timestamp_leitura'] = pd.to_datetime(df_nlp['timestamp_leitura'])

    try:
        client.load_table_from_dataframe(df_nlp, f"{PROJECT_ID}.{DATASET_ID}.fato_contingencias_nlp", 
                                         job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")).result()
        print(f"✅ [NLP] Score {df_nlp['score_risco'][0]} enviado via Batch Load.")
    except Exception as e: print(f"❌ Erro NLP Batch: {e}")

if __name__ == "__main__":
    print(f"🚀 OPERAÇÃO DE RESGATE: {datetime.now()}")
    coletar_clima()
    dados = extrair_lineup_completo()
    processar_e_subir_dados(dados)
    monitor_contingencias_batch()
    print("🏁 Sistema estabilizado e dados atualizados.")