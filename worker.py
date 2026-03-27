import os
import pandas as pd
import numpy as np
from datetime import datetime
from google.cloud import bigquery
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import io
import uuid
import urllib3

# Desativa avisos de segurança
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Configurações Globais
load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
VC_API_KEY = os.getenv("VC_API_KEY")
DATASET_ID = "logisticsdata"

client = bigquery.Client(project=PROJECT_ID)

# --- FUNÇÃO 1: CLIMA (Inalterada) ---
def coletar_clima():
    TABLE_ID_CLIMA = f"{PROJECT_ID}.{DATASET_ID}.fato_clima"
    pontos_monitoramento = [
        {"loc_id": "PORTO_SANTOS_CANAL", "nome": "Canal de Acesso / Porto", "lat": -23.9608, "lon": -46.3339},
        {"loc_id": "SERRA_ANCHIETA_IMIGRANTES", "nome": "Sistema Anchieta-Imigrantes", "lat": -23.8919, "lon": -46.4961},
        {"loc_id": "AREA_FUNDEIO_SANTOS", "nome": "Área de Fundeio", "lat": -24.0150, "lon": -46.3000}
    ]
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    lista_dfs = []
    print(f"🛰️ [CLIMA] Iniciando coleta...")
    for ponto in pontos_monitoramento:
        lat, lon = ponto['lat'], ponto['lon']
        url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}/last15days?unitGroup=metric&include=days&key={VC_API_KEY}&contentType=csv"
        try:
            df_hist = pd.read_csv(url)
            df_ponto = pd.DataFrame({
                'loc_id': ponto['loc_id'],
                'timestamp_leitura': pd.to_datetime(df_hist['datetime']),
                'precipitacao_mm': df_hist['precip'].fillna(0),
                'velocidade_vento': df_hist['windspeed'],
                'umidade': df_hist['humidity'],
                'alerta_critico': (df_hist['precip'] > 5) | (df_hist['windspeed'] > 15)
            })
            lista_dfs.append(df_ponto)
        except Exception as e:
            print(f"❌ Erro clima {ponto['loc_id']}: {e}")
    if lista_dfs:
        df_final = pd.concat(lista_dfs, ignore_index=True)
        client.load_table_from_dataframe(df_final, TABLE_ID_CLIMA, job_config=job_config).result()
        print(f"🚀 [CLIMA] {len(df_final)} linhas enviadas.")

# --- FUNÇÃO 2 & 3: LINE-UP (Inalteradas) ---
def extrair_lineup():
    url = "https://www.portodesantos.com.br/informacoes-operacionais/operacao-portuaria/navegacao-e-movimentacao-de-navios/navios-esperados/"
    headers = {"User-Agent": "Mozilla/5.0"}
    print("🚢 [LINE-UP] Acessando site do Porto...")
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code != 200: return None
    soup = BeautifulSoup(response.text, 'html.parser')
    tabelas = soup.find_all('table')
    return pd.read_html(io.StringIO(str(tabelas[0])))[0] if tabelas else None

def processar_e_subir_lineup(df_bruto):
    if df_bruto is None: return
    df_clean = df_bruto.copy()
    if isinstance(df_clean.columns, pd.MultiIndex):
        df_clean.columns = [' '.join(col).strip() for col in df_clean.columns.values]
    mapeamento = {'Navio Ship': 'nome_navio', 'Cheg/Arrival d/m/y': 'data_chegada_prevista', 'Mercadoria Goods': 'commodity', 'Peso Weight': 'quantidade_estimada', 'Terminal': 'terminal', 'IMO': 'ship_id'}
    real_rename = {col: value for col in df_clean.columns for key, value in mapeamento.items() if key in col}
    df_clean = df_clean.rename(columns=real_rename)
    df_clean['data_chegada_prevista'] = pd.to_datetime(df_clean['data_chegada_prevista'], dayfirst=True, errors='coerce')
    df_clean['quantidade_estimada'] = pd.to_numeric(df_clean['quantidade_estimada'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
    df_clean['status_atual'] = 'Esperado'
    df_clean['data_atracacao_prevista'] = df_clean['data_chegada_prevista']
    df_clean['lineup_id'] = [str(uuid.uuid4()) for _ in range(len(df_clean))]
    df_clean['inserido_em'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    colunas_permitidas = ['lineup_id', 'ship_id', 'data_chegada_prevista', 'data_atracacao_prevista', 'status_atual', 'terminal', 'commodity', 'quantidade_estimada', 'inserido_em']
    df_upload = df_clean[colunas_permitidas].copy()
    TABLE_ID_LINEUP = f"{PROJECT_ID}.{DATASET_ID}.fato_lineup"
    try:
        df_upload['data_chegada_prevista'] = pd.to_datetime(df_upload['data_chegada_prevista']).dt.strftime('%Y-%m-%d')
        df_upload['data_atracacao_prevista'] = pd.to_datetime(df_upload['data_atracacao_prevista']).dt.strftime('%Y-%m-%d %H:%M:%S')
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON)
        json_data = df_upload.to_json(orient='records', lines=True)
        client.load_table_from_file(io.StringIO(json_data), TABLE_ID_LINEUP, job_config=job_config).result()
        print(f"✅ [LINE-UP] {len(df_upload)} navios atualizados!")
    except Exception as e: print(f"❌ Erro Line-up: {e}")

# --- NOVO! FUNÇÃO 4: MONITOR DE CONTINGÊNCIAS (NLP) ---
def monitor_contingencias():
    print("📰 [NLP] Monitorando Ecovias e G1 Santos...")
    TABLE_ID_NLP = f"{PROJECT_ID}.{DATASET_ID}.fato_contingencias_nlp"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    score_final = 0.0
    textos = []

    # 1. Scrapers (Ecovias e G1)
    try:
        res_eco = requests.get("https://www.ecoviasimigrantes.com.br/", headers=headers, timeout=15, verify=False)
        if res_eco.status_code == 200:
            status_texto = BeautifulSoup(res_eco.text, 'html.parser').get_text().lower()
            if any(x in status_texto for x in ["bloqueio", "interdição", "fechada", "pare e siga"]):
                score_final += 0.5
                textos.append("Ecovias: Bloqueio detectado no SAI.")
            elif any(x in status_texto for x in ["lentidão", "congestionamento", "tráfego intenso"]):
                score_final += 0.2
                textos.append("Ecovias: Tráfego lento.")
    except: print("⚠️ Erro Ecovias")

    try:
        res_g1 = requests.get("https://g1.globo.com/sp/santos-regiao/", headers=headers, timeout=15)
        noticias = BeautifulSoup(res_g1.text, 'html.parser').find_all('a', class_='feed-post-link')
        for n in noticias[:5]:
            t = n.get_text().lower()
            if any(x in t for x in ["greve", "paralisação", "protesto", "manifestação"]):
                score_final += 0.5
                textos.append(f"G1: {n.get_text()[:40]}...")
    except: print("⚠️ Erro G1")

    # 2. Criação do DataFrame
    resumo = " | ".join(textos) if textos else "Condições normais."
    
    # Criamos o dado com a data em formato ISO STRING (O BigQuery entende perfeitamente)
    df_nlp = pd.DataFrame([{
        'cont_id': str(uuid.uuid4()),
        'loc_id': 'SANTOS_LOGISTICA_GERAL',
        'timestamp_leitura': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'), # Formato ISO
        'texto_original': resumo,
        'entidade_evento': 'Sistema Anchieta-Imigrantes / Porto',
        'score_risco': float(min(score_final, 1.0)),
        'json_extraido': f'{{"total_alertas": {len(textos)}}}'
    }])

    # 3. ENVIO VIA JSON (O Pulo do Gato para evitar erro de Pyarrow)
    try:
        # Transformamos o DataFrame em uma string JSON (Newline Delimited)
        json_data = df_nlp.to_json(orient='records', lines=True)
        
        # Configuramos o job para ler JSON em vez de tentar adivinhar pelo DataFrame
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition="WRITE_APPEND",
        )

        # Enviamos como se fosse um arquivo de texto (extremamente estável)
        client.load_table_from_file(io.StringIO(json_data), TABLE_ID_NLP, job_config=job_config).result()
        print(f"✅ [NLP] Score {df_nlp['score_risco'][0]} registrado com sucesso via JSON!")
        
    except Exception as e:
        print(f"❌ Erro fatal no envio NLP: {e}")

# --- EXECUÇÃO PRINCIPAL ---
if __name__ == "__main__":
    print(f"🤖 Invocando o Robô de Dados ({datetime.now().strftime('%d/%m %H:%M')})")
    
    coletar_clima()
    
    dados_brutos = extrair_lineup()
    processar_e_subir_lineup(dados_brutos)
    
    # Executa o novo monitor de notícias
    monitor_contingencias()
    
    print("🏁 Robô finalizou a rodada com sucesso!")