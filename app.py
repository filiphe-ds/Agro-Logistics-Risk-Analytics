import joblib
import streamlit as st
import pandas as pd
from google.cloud import bigquery
import plotly.express as px
import os
from dotenv import load_dotenv

# 1. Configurações Iniciais
load_dotenv()
st.set_page_config(page_title="Agro-Logistics Risk Analytics", layout="wide")

# Conexão BigQuery
PROJECT_ID = os.getenv("PROJECT_ID")
client = bigquery.Client(project=PROJECT_ID)

@st.cache_data # Cache para não gastar quota do BigQuery a cada clique
def load_data():
    query = "SELECT * FROM `agrologisticsdata.logisticsdata.view_feature_store_ml`"
    return client.query(query).to_dataframe()

# --- INTERFACE ---
st.title("🚢 Agro-Logistics Risk Analytics v2.0")
st.markdown("Monitorização de Risco de Demurrage e Condições Logísticas em Tempo Real.")

try:
    df = load_data()

    # 2. KPIs Principais (Métricas)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Navios", len(df))
    with col2:
        st.metric("Chuva Média (Santos)", f"{df['rain_feature'].mean():.1f} mm")
    with col3:
        st.metric("Vento Médio", f"{df['wind_feature'].mean():.1f} km/h")
    with col4:
        st.metric("Risco Médio de Atraso", f"{df['nlp_risk_score'].mean()*100:.1f}%")

    # 3. Visualização de Risco
    st.subheader("📊 Análise de Risco por Terminal")
    fig = px.bar(df, x='terminal', y='quantidade_estimada', color='rain_feature',
                 title="Volume por Terminal vs. Intensidade de Chuva",
                 labels={'quantidade_estimada': 'Volume (Toneladas)', 'terminal': 'Terminal'})
    st.plotly_chart(fig, use_container_width=True)

    # 4. Tabela de Monitorização (O que o operacional vê)
    st.subheader("🔍 Monitor de Embarcações e Alertas")
    # Destacar linhas com risco alto (Simulação de Negócio)
    st.dataframe(df.style.highlight_max(axis=0, subset=['rain_feature'], color='#ff4b4b'), use_container_width=True)

except Exception as e:
    st.error(f"Erro ao carregar dados do BigQuery: {e}")
    st.info("Certifique-se de que as suas credenciais estão configuradas no .env ou Secrets do Streamlit.")

# 5. Simulador de Risco (Integração com ML)
st.sidebar.header("🧠 Inteligência Artificial")
try:
    # Carrega o modelo treinado que você subiu para a pasta models/
    model = joblib.load('models/modelo_risco_demurrage_v1.pkl')
    
    st.sidebar.markdown("Ajuste as condições para previsão via Random Forest.")
    sim_chuva = st.sidebar.slider("Previsão de Chuva (mm)", 0, 100, 10)
    sim_vento = st.sidebar.slider("Velocidade do Vento (km/h)", 0, 50, 15)
    sim_nlp = st.sidebar.slider("Score NLP (Notícias)", 0.0, 1.0, 0.5)

    if st.sidebar.button("Prever Risco Real"):
        # Prepara os dados para o modelo (precisa estar na mesma ordem das features do treino)
        # ['rain_feature', 'wind_feature', 'nlp_risk_score', 'quantidade_estimada']
        input_data = pd.DataFrame([[sim_chuva, sim_vento, sim_nlp, 50000]], 
                                   columns=['rain_feature', 'wind_feature', 'nlp_risk_score', 'quantidade_estimada'])
        
        prob = model.predict_proba(input_data)[0][1] # Pega a chance de ser classe 1 (atraso)
        
        if prob > 0.7:
            st.sidebar.error(f"⚠️ RISCO ALTO: {prob:.1%}")
        elif prob > 0.4:
            st.sidebar.warning(f"🟡 RISCO MÉDIO: {prob:.1%}")
        else:
            st.sidebar.success(f"✅ RISCO BAIXO: {prob:.1%}")

except Exception as e:
    st.sidebar.info("Aguardando carregamento do modelo .pkl...")
