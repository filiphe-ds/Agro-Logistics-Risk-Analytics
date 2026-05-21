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
import plotly.graph_objects as go

# Inicialização de segurança
df_ships = pd.DataFrame()
nlp_event = None

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

@st.cache_data(ttl=600)
def load_ship_data():
    project = client.project 
    query = f"""
        SELECT * FROM (
            SELECT *, 
                   -- Normaliza o ID: transforma em String e remove o '.0'
                   REGEXP_REPLACE(CAST(ship_id AS STRING), r'\.0$', '') as clean_id,
                   -- Forçamos o CAST para TIMESTAMP para a função aceitar o fuso horário
                   FORMAT_TIMESTAMP('%d/%m/%Y %H:%M', CAST(inserido_em AS TIMESTAMP), 'America/Sao_Paulo') as data_formatada
            FROM `{project}.logisticsdata.view_feature_store_ml`
        )
        WHERE clean_id IS NOT NULL
        AND inserido_em >= TIMESTAMP_SUB((SELECT MAX(inserido_em) FROM `{project}.logisticsdata.view_feature_store_ml`), INTERVAL 15 MINUTE)
        QUALIFY ROW_NUMBER() OVER (PARTITION BY clean_id ORDER BY inserido_em DESC) = 1
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
    project = client.project
    query = f"""
        SELECT 
            g.nome_ponto, 
            ST_Y(ST_GEOGFROMTEXT(g.coordenadas)) as lat, 
            ST_X(ST_GEOGFROMTEXT(g.coordenadas)) as lon, 
            g.tipo_ponto,
            COALESCE(c.precipitacao_mm, 0) as precipitacao_mm,
            COALESCE(c.velocidade_vento, 0) as velocidade_vento,
            COALESCE(c.alerta_critico, FALSE) as alerta_critico
        FROM `{project}.logisticsdata.dim_geografia_rota` g
        LEFT JOIN `{project}.logisticsdata.fato_clima` c ON g.loc_id = c.loc_id
        QUALIFY ROW_NUMBER() OVER (PARTITION BY g.loc_id ORDER BY c.timestamp_leitura DESC) = 1
    """
    return client.query(query).to_dataframe()

@st.cache_data(ttl=600)
def load_performance_data():
    project = client.project
    query = f"""
        SELECT * FROM `{project}.logisticsdata.view_performance_ml` 
        ORDER BY data_atracacao_real DESC
    """
    return client.query(query).to_dataframe()

# --- INTERFACE PRINCIPAL ---
st.title("🚢 Agro-Logistics Risk Analytics v2.0")
st.markdown("Monitorização de Risco de Demurrage e Condições Logísticas em Tempo Real.")

try:
    try:
        nlp_event = load_nlp_data()
    except:
        nlp_event = None
        
    try:
        df_ships = load_ship_data()
    except Exception as e:
        st.error(f"Erro ao carregar navios: {e}")
        df_ships = pd.DataFrame()

    # --- Painel Superior: Status do Robô e Clima Logístico ---
    col_status_1, col_status_2 = st.columns(2)
    
    with col_status_1:
        if not df_ships.empty:
            ultima_atualizacao = df_ships['inserido_em'].max().strftime('%d/%m/%Y %H:%M')
            st.info(f"🤖 **Monitor de Navios:** Última varredura no Porto em {ultima_atualizacao}")

    with col_status_2:
        if nlp_event is not None:
            score = nlp_event['score_risco']
            texto = nlp_event['texto_original']
            if score > 0.4: st.error(f"⚠️ **Alerta Logístico:** {texto}")
            elif score > 0: st.warning(f"🟡 **Atenção Logística:** {texto}")
            else: st.success("🟢 **Acessos Normais:** Ecovias e Porto operando sem alertas.")

    # --- Criação das Abas (Tabs) ---
    tab_monitor, tab_radar, tab_detalhe, tab_ia = st.tabs([
        "📊 Monitor de Operações", 
        "🛰️ Radar Geográfico", 
        "🔍 Line-up Detalhado",
        "🎯 Performance da IA"
    ])

    # --- ABA 1: MONITOR DE OPERAÇÕES ---
    with tab_monitor:
        # Separação dos sub-datasets para os blocos visuais
        df_atracados = df_ships[df_ships['status_atual'] == 'Atracado'] if not df_ships.empty else pd.DataFrame()
        df_esperados = df_ships[df_ships['status_atual'] == 'Esperado'] if not df_ships.empty else pd.DataFrame()

        # 1. KPIs Principais (Expandido para 5 blocos informativos)
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Atracados Agora", len(df_atracados))
        with col2:
            st.metric("Fila (Esperados)", len(df_esperados))
        with col3:
            st.metric("Chuva Média (Porto)", f"{df_ships['rain_feature'].mean():.1f} mm" if not df_ships.empty else "0.0 mm")
        with col4:
            risco_logistico = nlp_event['score_risco'] * 100 if nlp_event is not None else 0
            st.metric("Risco de Acessos", f"{risco_logistico:.0f}%")
        with col5:
            st.metric("Prob. Média Atraso", f"{df_ships['nlp_risk_score'].mean()*100:.1f}%" if not df_ships.empty else "0.0%")

        st.divider()

        # 2. Gráficos de Atividade Isolados Lado a Lado
        col_graf_1, col_graf_2 = st.columns(2)

        with col_graf_1:
            st.markdown("### 🚢 Ocupação Atual (Navios Atracados)")
            if not df_atracados.empty:
                df_grp_atracados = df_atracados.groupby('terminal').agg(
                    qtd=('ship_id', 'count'), vol=('quantidade_estimada', 'sum')
                ).reset_index().sort_values('qtd', ascending=False)

                fig1 = go.Figure()
                fig1.add_trace(go.Bar(x=df_grp_atracados['terminal'], y=df_grp_atracados['qtd'], name='Qtd. Navios', marker_color='#023e8a', text=df_grp_atracados['qtd'], textposition='auto'))
                fig1.add_trace(go.Bar(x=df_grp_atracados['terminal'], y=df_grp_atracados['vol'], name='Volume (Ton)', marker_color='#f72585', yaxis='y2', opacity=0.6))
                fig1.update_layout(barmode='group', yaxis=dict(title='Qtd. Navios'), yaxis2=dict(title='Volume (Ton)', overlaying='y', side='right'), margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation='h', x=0, y=1.1))
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.info("Nenhum navio atracado detectado no snapshot atual.")

        with col_graf_2:
            st.markdown("### ⏳ Pipeline de Ingestão (Navios Esperados)")
            if not df_esperados.empty:
                df_grp_esperados = df_esperados.groupby('terminal').agg(
                    qtd=('ship_id', 'count'), vol=('quantidade_estimada', 'sum')
                ).reset_index().sort_values('qtd', ascending=False)

                fig2 = go.Figure()
                fig2.add_trace(go.Bar(x=df_grp_esperados['terminal'], y=df_grp_esperados['qtd'], name='Qtd. Navios', marker_color='#00b4d8', text=df_grp_esperados['qtd'], textposition='auto'))
                fig2.add_trace(go.Bar(x=df_grp_esperados['terminal'], y=df_grp_esperados['vol'], name='Volume (Ton)', marker_color='#7209b7', yaxis='y2', opacity=0.6))
                fig2.update_layout(barmode='group', yaxis=dict(title='Qtd. Navios'), yaxis2=dict(title='Volume (Ton)', overlaying='y', side='right'), margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation='h', x=0, y=1.1))
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Nenhum navio esperado na fila para os próximos dias.")

    # --- ABA 2: RADAR GEOGRÁFICO ---
    with tab_radar:
        st.subheader("📍 Radar Geográfico de Ativos")
        try:
            df_map = load_map_data()
            m = folium.Map(location=[-23.95, -46.35], zoom_start=11, tiles="OpenStreetMap")

            for index, row in df_map.iterrows():
                cor_ponto = "red" if row['alerta_critico'] else "blue"
                icone = "cloud-showers-heavy" if row['alerta_critico'] else "ship"
                
                popup_text = f"""
                <b>{row['nome_ponto']}</b><br>
                Tipo: {row['tipo_ponto']}<br>
                Chuva: {row['precipitacao_mm']}mm<br>
                Vento: {row['velocidade_vento']}km/h
                """
                
                folium.Marker(
                    location=[row['lat'], row['lon']],
                    popup=folium.Popup(popup_text, max_width=300),
                    tooltip=row['nome_ponto'],
                    icon=folium.Icon(color=cor_ponto, icon=icone, prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=500, returned_objects=[])
            st.caption("🔵 Azul: Operação Normal | 🔴 Vermelho: Condições Críticas Detectadas")

        except Exception as map_e:
            st.error(f"Erro ao renderizar o Radar: {map_e}")

    # --- ABA 3: LINE-UP DETALHADO ---
    with tab_detalhe:
        st.subheader("🔍 Consulta Detalhada de Embarcações")
        st.markdown("Lista completa de navios ativos com destaque para riscos climáticos.")
        
        search = st.text_input("Filtrar por Navio ou Terminal:")
        if search:
            df_filtered = df_ships[df_ships.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)]
        else:
            df_filtered = df_ships

        st.dataframe(
            df_filtered.style.highlight_max(axis=0, subset=['rain_feature'], color='#ff4b4b'), 
            use_container_width=True,
            hide_index=True
        )

    # --- ABA 4: PERFORMANCE DA IA ---
    with tab_ia:
        st.subheader("🎯 Auditoria de Precisão do Modelo")
        df_perf = load_performance_data()

        if not df_perf.empty:
            mae = df_perf['erro_absoluto'].mean()
            acuracia = (1 - mae) * 100
            total_validados = len(df_perf)

            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                st.metric("Acurácia Real", f"{acuracia:.1f}%", help="Percentual de acerto do modelo comparado à realidade do Porto.")
            with col_p2:
                st.metric("Erro Médio (MAE)", f"{mae:.2f}", delta_color="inverse")
            with col_p3:
                st.metric("Navios Auditados", total_validados)

            st.divider()

            st.write("### Histórico de Confronto: Predição vs Realidade")
            df_perf['Resultado'] = df_perf['ocorreu_atraso_real'].apply(lambda x: "🔴 Atrasou" if x == 1 else "🟢 No Prazo")
            
            st.dataframe(
                df_perf[['nome_navio', 'prob_atraso_prevista', 'Resultado', 'data_atracacao_real', 'erro_absoluto']],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("💡 A auditoria aparecerá assim que os primeiros navios 'Esperados' mudarem para o status 'Atracado'.")

except Exception as e:
    st.error(f"Erro crítico na interface: {e}")
    st.info("Verifique a conexão com o BigQuery e os Secrets do Streamlit.")

# --- SIDEBAR: SIMULADOR DE IA (FICA FORA DAS TABS) ---
st.sidebar.header("🧠 Inteligência Artificial")
try:
    model = joblib.load('models/modelo_risco_demurrage_v1.pkl')
    current_nlp_score = float(nlp_event['score_risco']) if nlp_event is not None else 0.0
    
    st.sidebar.markdown(f"📈 **Risco NLP Atual (Real):** `{current_nlp_score:.2f}`")
    st.sidebar.divider()
    
    st.sidebar.markdown("Simule as condições operacionais:")
    sim_carga = st.sidebar.slider("Volume do Navio (Toneladas)", 5000, 150000, 50000)
    sim_chuva = st.sidebar.slider("Previsão de Chuva (mm)", 0, 100, 10)
    sim_vento = st.sidebar.slider("Velocidade do Vento (km/h)", 0, 50, 15)
    
    if st.sidebar.button("Calcular Risco Real"):
        input_data = pd.DataFrame(
            [[sim_chuva, sim_vento, current_nlp_score, sim_carga]], 
            columns=['rain_feature', 'wind_feature', 'nlp_risk_score', 'quantidade_estimada']
        )
        
        prob = model.predict_proba(input_data)[0][1]
        st.sidebar.metric("Probabilidade de Demurrage", f"{prob:.1%}")
        
        if prob > 0.7: st.sidebar.error("⚠️ ALTO RISCO DE ATRASO")
        elif prob > 0.4: st.sidebar.warning("🟡 RISCO MODERADO")
        else: st.sidebar.success("✅ OPERAÇÃO SEGURA")

except Exception as e:
    st.sidebar.error(f"Erro ao carregar simulador: {e}")