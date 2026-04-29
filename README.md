# 🚢 Agro-Logistics Risk Analytics v2.0

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://agro-logistics-risk-analytics-km6au6byuklbh79jujlxjf.streamlit.app/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![BigQuery](https://img.shields.io/badge/Google_BigQuery-Data_Warehouse-blue)](https://cloud.google.com/bigquery)

**Inteligência Preditiva e Monitoramento de Risco Logístico em Tempo Real para o Porto de Santos.**

---

## 🎯 Sobre o Projeto

O **Agro-Logistics Risk Analytics** é uma plataforma de inteligência de dados desenvolvida para mitigar custos de **Demurrage** no setor de agronegócio. O sistema unifica o monitoramento do line-up de navios, condições meteorológicas e eventos logísticos críticos (bloqueios em rodovias e paralisações), utilizando **Machine Learning** para prever a probabilidade de atrasos operacionais.

---

## 🏗️ Arquitetura e Governança

O projeto utiliza uma estrutura moderna de **Modern Data Stack** focada em auditabilidade e integridade:

1.  **Ingestão:** Robô autônomo (`worker.py`) com scraping resiliente e deduplicação inteligente.
2.  **Processamento:** Normalização de tipos e limpeza de dados via **Pandas**.
3.  **Storage:** Data Warehouse escalável no **Google BigQuery**.
4.  **Auditabilidade:** Camada de performance que confronta predições da IA com dados reais de atracação.
5.  **Interface:** Dashboard interativo em **Streamlit** com visualização geoespacial.

> [!IMPORTANT]
> **Consulte a [Documentação de Governança](GOVERNANCE.md)** para detalhes sobre o Dicionário de Dados, Lógica do Modelo de ML e Critérios de Auditoria.

---

## 🚀 Funcionalidades Principais

- **Monitor de Operações (Fluxo vs Volume):** Visualização de barras agrupadas que destaca terminais congestionados mesmo com dados de pesagem ausentes.
- **Inteligência de Notícias (NLP):** Motor que monitora **Ecovias** e **G1 Santos**, convertendo notícias em um **Score de Risco Logístico** matemático.
- **Auditoria de Performance:** Aba dedicada à validação da acurácia do modelo, exibindo o Erro Médio Absoluto (MAE) em tempo real.
- **Radar Geográfico:** Mapeamento espacial utilizando **Folium**, integrando alertas críticos de tráfego e clima.

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
   ```bash
   git clone [https://github.com/seu-usuario/agro-logistics-risk-analytics.git](https://github.com/seu-usuario/agro-logistics-risk-analytics.git)

## 📈 Próximos Passos (Roadmap)
[x] Engenharia de Dados e Scraping Multi-fonte.

[x] Implementação de NLP e Modelo Preditivo v1.

[x] Sistema de Auditoria de Performance e Backtesting.

[ ] Automação de Alertas proativos via Telegram/Webhooks.

[ ] Integração com dados satelitais AIS para rastreio oceânico.

Desenvolvido por Filiphe – [LinkedIn](https://www.linkedin.com/in/filipheassuncao/)


