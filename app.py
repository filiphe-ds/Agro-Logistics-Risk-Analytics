import joblib
import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account # <--- Essencial para nuvem
import plotly.express as px
import os
from dotenv import load_dotenv

# 1. Configurações Iniciais
load_dotenv()
st.set_page_config(page_title="Agro-Logistics Risk Analytics", layout="wide")

# --- CONEXÃO BLINDADA PARA O STREAMLIT CLOUD ---
def get_bigquery_client():
    # Verifica se estamos no Streamlit Cloud (Segredos configurados)
    if "gcp_service_account" in st.secrets:
        # Pega o dicionário de segredos direto do painel do Streamlit
        info = st.secrets["gcp_service_account"]
        # Cria a chave de acesso usando o dicionário
        credentials = service_account.Credentials.from_service_account_info(info)
        # Inicia o cliente com a chave EXPLICITAMENTE
        return bigquery.Client(credentials=credentials, project=info["project_id"])
    
    # Se falhar (rodando local), tenta o .env clássico
    else:
        project_id = os.getenv("PROJECT_ID")
        return bigquery.Client(project=project_id)

# ATUALIZAÇÃO DA LINHA 15:
client = get_bigquery_client()

@st.cache_data
def load_data():
    project = client.project 
    query = f"""
        SELECT *, 
               FORMAT_TIMESTAMP('%d/%m/%Y %H:%M', inserido_em, 'America/Sao_Paulo') as data_formatada
        FROM `{project}.logisticsdata.view_feature_store_ml`
        WHERE ship_id IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ship_id ORDER BY inserido_em DESC) = 1
    """
    df = client.query(query).to_dataframe()
    return df

# --- INTERFACE ---
st.title("🚢 Agro-Logistics Risk Analytics v2.0")
st.markdown("Monitorização de Risco de Demurrage e Condições Logísticas em Tempo Real.")

try:
    # 1. Primeiro carregamos os dados
    df = load_data()

    # 2. Agora que o 'df' existe, mostramos o status do sistema no topo
    if not df.empty:
        # Pegamos a data formatada que a nossa nova Query SQL gerou
        ultima_atualizacao = df['data_formatada'].iloc[0]
        st.info(f"🤖 **Status do Sistema:** Robô operando normalmente. Última coleta: {ultima_atualizacao}")

     # 3. KPIs Principais (Métricas)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Navios", len(df))
    # ... resto das colunas e gráficos ...

except Exception as e:
    st.error(f"Erro ao carregar dados do BigQuery: {e}")
    st.info("Certifique-se de que as suas credenciais estão configuradas nos Secrets do Streamlit.")
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