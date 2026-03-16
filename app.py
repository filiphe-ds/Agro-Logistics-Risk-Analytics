import joblib
import streamlit as st
import pandas as pd
from google.cloud import bigquery
import plotly.express as px
import os
from dotenv import load_dotenv
from google.oauth2 import service_account

# 1. Configurações Iniciais e Carregamento de Env
load_dotenv()
st.set_page_config(page_title="Agro-Logistics Risk Analytics", layout="wide")

# 2. Autenticação Inteligente (O segredo do Deploy)
if "gcp_service_account" in st.secrets:
    # No Cloud: usa os Secrets do Streamlit
    info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(credentials=credentials, project=info["project_id"])
else:
    # Local: usa o seu .env ou o login do gcloud no seu PC
    PROJECT_ID = os.getenv("PROJECT_ID")
    client = bigquery.Client(project=PROJECT_ID)

# --- REMOVI A SEGUNDA DEFINIÇÃO DE CLIENT QUE ESTAVA AQUI ---

@st.cache_data
def load_data():
    # Certifique-se de que o nome da tabela está correto conforme seu dataset
    query = "SELECT * FROM `agrologisticsdata.logisticsdata.view_feature_store_ml`"
    return client.query(query).to_dataframe()

# --- INTERFACE ---
st.title("🚢 Agro-Logistics Risk Analytics v2.0")
st.markdown("Monitorização de Risco de Demurrage e Condições Logísticas em Tempo Real.")

try:
    df = load_data()

    # 3. KPIs Principais
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Navios", len(df))
    with col2:
        st.metric("Chuva Média (Santos)", f"{df['rain_feature'].mean():.1f} mm")
    with col3:
        st.metric("Vento Médio", f"{df['wind_feature'].mean():.1f} km/h")
    with col4:
        st.metric("Risco Médio de Atraso", f"{df['nlp_risk_score'].mean()*100:.1f}%")

    # 4. Visualização de Risco
    st.subheader("📊 Análise de Risco por Terminal")
    fig = px.bar(df, x='terminal', y='quantidade_estimada', color='rain_feature',
                 title="Volume por Terminal vs. Intensidade de Chuva",
                 labels={'quantidade_estimada': 'Volume (Toneladas)', 'terminal': 'Terminal'})
    st.plotly_chart(fig, use_container_width=True)

    # 5. Tabela de Monitorização
    st.subheader("🔍 Monitor de Embarcações e Alertas")
    st.dataframe(df.style.highlight_max(axis=0, subset=['rain_feature'], color='#ff4b4b'), use_container_width=True)

except Exception as e:
    st.error(f"Erro ao carregar dados do BigQuery: {e}")

# 6. Simulador de Risco (ML Side)
st.sidebar.header("🧠 Inteligência Artificial")
try:
    model = joblib.load('models/modelo_risco_demurrage_v1.pkl')
    
    st.sidebar.markdown("Ajuste as condições para previsão real.")
    
    sim_carga = st.sidebar.slider("Volume do Navio (Toneladas)", 5000, 150000, 50000)
    sim_chuva = st.sidebar.slider("Previsão de Chuva (mm)", 0, 100, 10)
    sim_vento = st.sidebar.slider("Velocidade do Vento (km/h)", 0, 50, 15)
    sim_nlp = st.sidebar.slider("Score de Risco NLP (IA)", 0.0, 1.0, 0.5)

    if st.sidebar.button("Prever Risco Real"):
        # ORDEM E NOMES EXATOS EXIGIDOS PELO MODELO:
        # O erro indicou: rain_feature, wind_feature, nlp_risk_score, quantidade_estimada
        input_data = pd.DataFrame([[sim_chuva, sim_vento, sim_nlp, sim_carga]], 
                                   columns=['rain_feature', 'wind_feature', 'nlp_risk_score', 'quantidade_estimada'])
        
        prob = model.predict_proba(input_data)[0][1]
        
        if prob > 0.7:
            st.sidebar.error(f"⚠️ RISCO ALTO: {prob:.1%}")
        elif prob > 0.4:
            st.sidebar.warning(f"🟡 RISCO MÉDIO: {prob:.1%}")
        else:
            st.sidebar.success(f"✅ RISCO BAIXO: {prob:.1%}")

except Exception as e:
    st.sidebar.error(f"Erro ao carregar modelo: {e}")
