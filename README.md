# 🚢 Agro-Logistics Risk Analytics v2.0

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://agro-logistics-risk-analytics-km6au6byuklbh79jujlxjf.streamlit.app/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![BigQuery](https://img.shields.io/badge/Google_BigQuery-Data_Warehouse-blue)](https://cloud.google.com/bigquery)

**Monitoramento de Risco de Demurrage e Condições Logísticas em Tempo Real para o Porto de Santos.**
[Link do app](https://agro-logistics-risk-analytics-km6au6byuklbh79jujlxjf.streamlit.app/)

---

## 🎯 Sobre o Projeto

O **Agro-Logistics Risk Analytics** é uma plataforma de inteligência de dados desenvolvida para mitigar custos de **Demurrage** no setor de agronegócio. O sistema monitora o line-up de navios, condições meteorológicas e eventos logísticos críticos (bloqueios em rodovias e paralisações), utilizando **Machine Learning** para prever a probabilidade de atrasos.

### 🚀 Funcionalidades Principais

- **Monitor de Navios (Line-up):** Raspagem automática de dados do Porto de Santos, processando o fluxo de embarcações esperadas.
- **Inteligência de Notícias (NLP):** Motor de scraping que monitora **Ecovias** (Sistema Anchieta-Imigrantes) e **G1 Santos**, convertendo notícias em um **Score de Risco Logístico** automatizado.
- **Previsão de Risco com ML:** Modelo de classificação (Random Forest) que integra volume de carga, condições climáticas e risco de acesso para prever atrasos operacionais.
- **Radar Geográfico:** Visualização espacial em tempo real utilizando **Folium**, mapeando pontos críticos de tráfego e terminais sob alerta climático.

---

## 🏗️ Arquitetura Técnica

O projeto utiliza uma estrutura moderna de **Modern Data Stack**:

1.  **Ingestão:** Robô autônomo (`worker.py`) rodando via **GitHub Actions** a cada hora.
2.  **Processamento:** Limpeza e transformação de dados com **Pandas** e Python.
3.  **Storage:** Data Warehouse escalável no **Google BigQuery**.
4.  **Interface:** Dashboard interativo desenvolvido em **Streamlit**.
5.  **Geospatial:** Dados geográficos armazenados como `GEOGRAPHY` no BigQuery e renderizados com Folium.

---

## 🛠️ Tecnologias Utilizadas

- **Linguagem:** Python 3.9+
- **Bibliotecas de Dados:** Pandas, Numpy, Scikit-learn
- **Cloud/Infra:** Google Cloud Platform (BigQuery), GitHub Actions
- **Visualização:** Streamlit, Plotly, Folium
- **Scraping:** BeautifulSoup4, Requests

---

## 🏁 Como Executar o Projeto

### Pré-requisitos
- Conta no **Google Cloud Platform** (com projeto e BigQuery configurados).
- Chave de API da **Visual Crossing** para dados climáticos.

### Instalação Local
1. Clone o repositório:
   git clone [https://github.com/seu-usuario/agro-logistics-risk-analytics.git](https://github.com/seu-usuario/agro-logistics-risk-analytics.git)

2. Instale as dependências:

  pip install -r requirements.txt

3. Configure o arquivo .env com suas credenciais:

  Code snippet
  PROJECT_ID="seu-projeto-gcp"
  VC_API_KEY="sua-chave-weather"

4. Execute o app:
  streamlit run app.py

## 📈 Próximos Passos (Roadmap)
[ ] Implementação de Deep Learning para análise de sentimento mais refinada das notícias.

[ ] Criação de alertas automáticos via Telegram/E-mail para riscos acima de 80%.

[ ] Inclusão de dados históricos de safras para análise de sazonalidade.

Desenvolvido por Filiphe – [LinkedIn](https://www.linkedin.com/in/filipheassuncao/)


