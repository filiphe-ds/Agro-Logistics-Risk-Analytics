import joblib
import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
import plotly.express as px
import os
from dotenv import load_dotenv

# 1. Configurações Iniciais
load_dotenv()
st.set_page_config(page_title="Agro-Logistics Risk Analytics", layout="wide")

# --- CONEXÃO ---
def get_bigquery_client():
    if "gcp_service_account" in st.secrets:
        info = st.secrets["gcp_service_account"]
        credentials = service_account.Credentials.from_service_account_info(info)
        return bigquery.Client(credentials=credentials, project=info["project_id"])
    else:
        project_id = os.getenv("PROJECT_ID")
        return bigquery.Client(project=project_id)

client = get_bigquery_client()

# --- CARREGAMENTO DE DADOS ---

@st.cache_data(ttl=600) # Atualiza o cache a cada 10 minutos
def load_ship_data():
    project = client.project 
    query = f"""
        SELECT *, 
               FORMAT_TIMESTAMP('%d/%m/%Y %H:%M', inserido_em, 'America/Sao_Paulo') as data_formatada
        FROM `{project}.logisticsdata.view_feature_store_ml`
        WHERE ship_id IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ship_id ORDER BY inserido_em DESC) = 1
    """
    return client.query(query).to_dataframe()

@st.cache_data(ttl=600)
def load_nlp_data():
    project = client.project
    query = f"""
        SELECT texto_original, score_risco, timestamp_leitura
        FROM `{project}.logisticsdata.fato_contingencias_nlp`
        ORDER BY timestamp_leitura DESC
        LIMIT 1
    """
    df = client.query(query).to_dataframe()
    return df.iloc[0] if not df.empty else None

# --- INTERFACE PRINCIPAL ---
st.title("🚢 Agro-Logistics Risk Analytics v2.0")
st.markdown("Monitorização de Risco de Demurrage e Condições Logísticas em Tempo Real.")

try:
    # Busca dados de Navios e NLP
    df_ships = load_ship_data()
    nlp_event = load_nlp_data()

    # 1. Status do Robô e Clima Logístico
    col_status_1, col_status_2 = st.columns(2)
    
    with col_status_1:
        if not df_ships.empty:
            ultima_coleta = df_ships['data_formatada'].iloc[0]
            st.info(f"🤖 **Monitor de Navios:** Atualizado em {ultima_coleta}")

    with col_status_2:
        if nlp_event is not None:
            score = nlp_event['score_risco']
            texto = nlp_event['texto_original']
            if score > 0.4:
                st.error(f"⚠️ **Alerta Logístico:** {texto}")
            elif score > 0:
                st.warning(f"🟡 **Atenção Logística:** {texto}")
            else:
                st.success("🟢 **Acessos Normais:** Ecovias e Porto operando sem alertas.")

    # 2. KPIs Principais
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Navios", len(df_ships))
    with col2:
        st.metric("Chuva Média (Porto)", f"{df_ships['rain_feature'].mean():.1f} mm")
    with col3:
        # Usamos o score real do NLP no KPI de Risco
        risco_logistico = nlp_event['score_risco'] * 100 if nlp_event is not None else 0
        st.metric("Risco Logístico (NLP)", f"{risco_logistico:.0f}%")
    with col4:
        st.metric("Prob. Média Atraso", f"{df_ships['nlp_risk_score'].mean()*100:.1f}%")

    # 3. Gráficos
    st.subheader("📊 Análise de Volume por Terminal")
    fig = px.bar(df_ships, x='terminal', y='quantidade_estimada', color='rain_feature',
                 color_continuous_scale="Reds", labels={'quantidade_estimada': 'Volume (Ton)'})
    st.plotly_chart(fig, use_container_width=True)

    # 4. Tabela
    st.subheader("🔍 Monitor de Embarcações")
    st.dataframe(df_ships.style.highlight_max(axis=0, subset=['rain_feature'], color='#ff4b4b'), use_container_width=True)

except Exception as e:
    st.error(f"Erro na interface: {e}")

# --- SIDEBAR: SIMULADOR DE IA ---
st.sidebar.header("🧠 Inteligência Artificial")
try:
    model = joblib.load('models/modelo_risco_demurrage_v1.pkl')
    
    # Pegamos o score real para usar como base no simulador
    current_nlp_score = float(nlp_event['score_risco']) if nlp_event is not None else 0.0
    
    st.sidebar.markdown(f"**Score NLP Atual (Real):** `{current_nlp_score:.2f}`")
    st.sidebar.divider()
    
    sim_carga = st.sidebar.slider("Volume do Navio (Toneladas)", 5000, 150000, 50000)
    sim_chuva = st.sidebar.slider("Previsão de Chuva (mm)", 0, 100, 10)
    sim_vento = st.sidebar.slider("Velocidade do Vento (km/h)", 0, 50, 15)
    
    # O Score NLP não é mais slider, é um valor fixo injetado do BigQuery
    if st.sidebar.button("Calcular Risco Real"):
        input_data = pd.DataFrame(
            [[sim_chuva, sim_vento, current_nlp_score, sim_carga]], 
            columns=['rain_feature', 'wind_feature', 'nlp_risk_score', 'quantidade_estimada']
        )
        prob = model.predict_proba(input_data)[0][1]
        
        st.sidebar.metric("Probabilidade de Demurrage", f"{prob:.1%}")
        if prob > 0.7: st.sidebar.error("⚠️ ALTO RISCO")
        elif prob > 0.4: st.sidebar.warning("🟡 RISCO MODERADO")
        else: st.sidebar.success("✅ OPERAÇÃO SEGURA")

except Exception as e:
    st.sidebar.error(f"Erro no modelo: {e}")