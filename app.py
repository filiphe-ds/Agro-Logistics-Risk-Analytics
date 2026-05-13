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
                   -- AJUSTE AQUI: Forçamos o CAST para TIMESTAMP para a função aceitar o fuso horário
                   FORMAT_TIMESTAMP('%d/%m/%Y %H:%M', CAST(inserido_em AS TIMESTAMP), 'America/Sao_Paulo') as data_formatada
            FROM `{project}.logisticsdata.view_feature_store_ml`
        )
        WHERE clean_id IS NOT NULL
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
            -- O segredo está aqui: Se for NULL, vira FALSE
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

# Usamos um try/except global para capturar erros de carregamento de dados
try:
    # 1. Busca os dados de forma independente
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
        # Pegamos a data mais recente de toda a tabela para provar que o robô passou por aqui
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
        # 1. KPIs Principais
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Navios em Santos", len(df_ships))
        with col2:
            st.metric("Chuva Média (Porto)", f"{df_ships['rain_feature'].mean():.1f} mm")
        with col3:
            risco_logistico = nlp_event['score_risco'] * 100 if nlp_event is not None else 0
            st.metric("Risco de Acessos", f"{risco_logistico:.0f}%")
        with col4:
            st.metric("Prob. Média Atraso", f"{df_ships['nlp_risk_score'].mean()*100:.1f}%")

        st.divider()

        # 2. Gráfico de Atividade (Fluxo vs Volume)
        st.subheader("📊 Atividade por Terminal: Fluxo vs. Volume")
        df_agrupado = df_ships.groupby('terminal').agg(
            qtd_navios=('ship_id', 'count'),
            volume_total=('quantidade_estimada', 'sum')
        ).reset_index().sort_values('qtd_navios', ascending=False)

        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_agrupado['terminal'], y=df_agrupado['qtd_navios'],
            name='Qtd. de Navios', marker_color='#0077b6', text=df_agrupado['qtd_navios'], textposition='auto'
        ))
        fig.add_trace(go.Bar(
            x=df_agrupado['terminal'], y=df_agrupado['volume_total'],
            name='Volume (Ton)', marker_color='#ef476f', yaxis='y2', opacity=0.7
        ))
        fig.update_layout(
            barmode='group',
            yaxis=dict(title='Quantidade de Navios'),
            yaxis2=dict(title='Volume Total (Ton)', overlaying='y', side='right'),
            legend=dict(x=0, y=1.1, orientation='h'),
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- ABA 2: RADAR GEOGRÁFICO ---
    with tab_radar:
        st.subheader("📍 Radar Geográfico de Ativos")
        try:
            df_map = load_map_data()
            
            # 1. Criamos o mapa base centrado em Santos
            m = folium.Map(location=[-23.95, -46.35], zoom_start=11, tiles="OpenStreetMap")

            # 2. Adicionamos os pontos (POIs) do seu BigQuery
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

            # 3. Exibimos o mapa no Streamlit
            st_folium(m, width=1200, height=500, returned_objects=[])
            
            st.caption("🔵 Azul: Operação Normal | 🔴 Vermelho: Condições Críticas Detectadas")

        except Exception as map_e:
            st.error(f"Erro ao renderizar o Radar: {map_e}")

    # --- ABA 3: LINE-UP DETALHADO ---
    with tab_detalhe:
        st.subheader("🔍 Consulta Detalhada de Embarcações")
        st.markdown("Lista completa de navios ativos com destaque para riscos climáticos.")
        
        # Filtro rápido na tabela
        search = st.text_input("Filtrar por Navio ou Terminal:")
        if search:
            # Filtro case-insensitive em todas as colunas
            df_filtered = df_ships[df_ships.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)]
        else:
            df_filtered = df_ships

        # Exibição com estilo
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
            # Cálculos de Performance
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

            # Gráfico de Predição vs Realidade
            st.write("### Histórico de Confronto: Predição vs Realidade")
            
            # Criando uma coluna visual para facilitar a leitura
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