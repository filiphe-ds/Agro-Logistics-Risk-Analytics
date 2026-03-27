import joblib
import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
import plotly.express as px
import folium
from streamlit_folium import st_folium
import os
from dotenv import load_dotenv

# 1. Configurações Iniciais
load_dotenv()
st.set_page_config(page_title="Agro-Logistics Risk Analytics v2.0", layout="wide")

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

# --- CARREGAMENTO DE DADOS (COM CACHE) ---

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

@st.cache_data(ttl=600)
def load_map_data():
    """Busca as coordenadas e as converte de STRING para GEOGRAPHY na query"""
    project = client.project
    # Usamos ST_GEOGFROMTEXT para que o BigQuery entenda a coluna como coordenadas
    query = f"""
        SELECT 
            g.nome_ponto, 
            ST_Y(ST_GEOGFROMTEXT(g.coordenadas)) as lat, 
            ST_X(ST_GEOGFROMTEXT(g.coordenadas)) as lon, 
            g.tipo_ponto,
            c.precipitacao_mm,
            c.velocidade_vento,
            c.alerta_critico
        FROM `{project}.logisticsdata.dim_geografia_rota` g
        LEFT JOIN `{project}.logisticsdata.fato_clima` c ON g.loc_id = c.loc_id
        QUALIFY ROW_NUMBER() OVER (PARTITION BY g.loc_id ORDER BY c.timestamp_leitura DESC) = 1
    """
    return client.query(query).to_dataframe()

# --- INTERFACE PRINCIPAL ---
st.title("🚢 Agro-Logistics Risk Analytics v2.0")
st.markdown("Monitorização de Risco de Demurrage e Condições Logísticas em Tempo Real.")

# Usamos um try/except global para capturar erros de carregamento de dados
try:
    # 1. Busca todos os dados necessários
    df_ships = load_ship_data()
    nlp_event = load_nlp_data()

    # --- Painel Superior: Status do Robô e Clima Logístico ---
    col_status_1, col_status_2 = st.columns(2)
    
    with col_status_1:
        if not df_ships.empty:
            ultima_coleta = df_ships['data_formatada'].iloc[0]
            st.info(f"🤖 **Monitor de Navios:** Atualizado em {ultima_coleta}")

    with col_status_2:
        if nlp_event is not None:
            score = nlp_event['score_risco']
            texto = nlp_event['texto_original']
            if score > 0.4: st.error(f"⚠️ **Alerta Logístico:** {texto}")
            elif score > 0: st.warning(f"🟡 **Atenção Logística:** {texto}")
            else: st.success("🟢 **Acessos Normais:** Ecovias e Porto operando sem alertas.")

    # --- Criação das Abas (Tabs) ---
    tab_monitor, tab_radar = st.tabs(["📊 Monitor de Operações", "🛰️ Radar Geográfico"])

    # --- ABA 1: MONITOR DE OPERAÇÕES ---
    with tab_monitor:
        # 1. KPIs Principais
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total de Navios", len(df_ships))
        with col2:
            st.metric("Chuva Média (Porto)", f"{df_ships['rain_feature'].mean():.1f} mm")
        with col3:
            # Score real do NLP vindo do BigQuery
            risco_logistico = nlp_event['score_risco'] * 100 if nlp_event is not None else 0
            st.metric("Risco de Acessos (NLP)", f"{risco_logistico:.0f}%")
        with col4:
            st.metric("Prob. Média Atraso (ML)", f"{df_ships['nlp_risk_score'].mean()*100:.1f}%")

        st.divider()

        # 2. Gráficos
        st.subheader("📊 Análise de Volume por Terminal")
        fig = px.bar(df_ships, x='terminal', y='quantidade_estimada', color='rain_feature',
                     color_continuous_scale="Reds", labels={'quantidade_estimada': 'Volume (Ton)', 'rain_feature': 'Chuva (mm)'})
        st.plotly_chart(fig, use_container_width=True)

        # 3. Tabela
        st.subheader("🔍 Monitor Detalhado de Embarcações")
        # Destacamos em vermelho onde a chuva está mais forte
        st.dataframe(df_ships.style.highlight_max(axis=0, subset=['rain_feature'], color='#ff4b4b'), use_container_width=True)

    # --- ABA 2: RADAR GEOGRÁFICO ---
    with tab_radar:
        st.subheader("📍 Radar Geográfico de Ativos")
        try:
            df_map = load_map_data()
            
            # 1. Criamos o mapa base centrado em Santos
            m = folium.Map(location=[-23.95, -46.35], zoom_start=11, tiles="OpenStreetMap")

            # 2. Adicionamos os pontos (POIs) do seu BigQuery
            for index, row in df_map.iterrows():
                # Define a cor: Vermelho para alerta, Azul para normal
                cor_ponto = "red" if row['alerta_critico'] else "blue"
                icone = "cloud-showers-heavy" if row['alerta_critico'] else "ship"
                
                # Criamos um balão informativo (Popup)
                popup_text = f"""
                <b>{row['nome_ponto']}</b><br>
                Tipo: {row['tipo_ponto']}<br>
                Chuva: {row['precipitacao_mm']}mm<br>
                Vento: {row['velocidade_vento']}km/h
                """
                
                # Adiciona o marcador no mapa
                folium.Marker(
                    location=[row['lat'], row['lon']],
                    popup=folium.Popup(popup_text, max_width=300),
                    tooltip=row['nome_ponto'],
                    icon=folium.Icon(color=cor_ponto, icon=icone, prefix='fa')
                ).add_to(m)

            # 3. Exibimos o mapa no Streamlit
            st_folium(m, width=1200, height=500, returned_objects=[])
            
            st.caption("🔵 Azul: Operação Normal | 🔴 Vermelho: Condições Críticas Detectadas")

        except Exception as map_e:
            st.error(f"Erro ao renderizar o Radar: {map_e}")

except Exception as e:
    st.error(f"Erro crítico na interface: {e}")
    st.info("Verifique a conexão com o BigQuery e os Secrets do Streamlit.")

# --- SIDEBAR: SIMULADOR DE IA (FICA FORA DAS TABS) ---
st.sidebar.header("🧠 Inteligência Artificial")
try:
    # Carregamento do Modelo de ML
    model = joblib.load('models/modelo_risco_demurrage_v1.pkl')
    
    # Injetamos o score real do NLP vindo do BigQuery (Fim do slider manual!)
    current_nlp_score = float(nlp_event['score_risco']) if nlp_event is not None else 0.0
    
    st.sidebar.markdown(f"📈 **Risco NLP Atual (Real):** `{current_nlp_score:.2f}`")
    st.sidebar.divider()
    
    st.sidebar.markdown("Simule as condições operacionais:")
    sim_carga = st.sidebar.slider("Volume do Navio (Toneladas)", 5000, 150000, 50000)
    sim_chuva = st.sidebar.slider("Previsão de Chuva (mm)", 0, 100, 10)
    sim_vento = st.sidebar.slider("Velocidade do Vento (km/h)", 0, 50, 15)
    
    # Botão para calcular a probabilidade baseada no modelo e no score real
    if st.sidebar.button("Calcular Risco Real"):
        # Cria o input na ordem exata que o modelo Random Forest espera
        input_data = pd.DataFrame(
            [[sim_chuva, sim_vento, current_nlp_score, sim_carga]], 
            columns=['rain_feature', 'wind_feature', 'nlp_risk_score', 'quantidade_estimada']
        )
        
        # Faz a previsão da probabilidade (classe 1 = Demurrage)
        prob = model.predict_proba(input_data)[0][1]
        
        # Exibe o resultado de forma visual
        st.sidebar.metric("Probabilidade de Demurrage", f"{prob:.1%}")
        
        if prob > 0.7: st.sidebar.error("⚠️ ALTO RISCO DE ATRASO")
        elif prob > 0.4: st.sidebar.warning("🟡 RISCO MODERADO")
        else: st.sidebar.success("✅ OPERAÇÃO SEGURA")

except Exception as e:
    st.sidebar.error(f"Erro ao carregar simulador: {e}")