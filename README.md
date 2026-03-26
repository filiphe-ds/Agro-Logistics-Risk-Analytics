🚢 Agro-Logistics Risk Analytics v2.0
Sistema inteligente de monitoramento e previsão de risco de Demurrage para operações de exportação agrícola no Porto de Santos. O projeto integra raspagem de dados em tempo real, automação em nuvem e Inteligência Artificial.

🚀 Arquitetura do Projeto
O sistema opera como um pipeline de dados ponta a ponta:

Coleta Automatizada (The Robot): Um script em Python (worker.py) realiza a extração de dados do Line-up oficial do Porto de Santos e coleta previsões climáticas via API do Visual Crossing.

Automação (CI/CD): O GitHub Actions executa o robô de hora em hora, garantindo que o banco de dados esteja sempre atualizado sem intervenção humana.

Data Warehouse: Os dados são processados, limpos e armazenados no Google BigQuery, organizados em tabelas de fatos e visões otimizadas para ML.

Inteligência Artificial: Um modelo de Random Forest (Scikit-Learn) analisa variáveis como volume de carga, precipitação e ventos para prever a probabilidade de atrasos.

Interface: Um dashboard interativo em Streamlit permite a visualização de KPIs operacionais e simulações de risco em tempo real.

🛠️ Tech Stack
Linguagem: Python 3.11

Data Prep: Pandas, NumPy, BeautifulSoup4

Cloud: Google Cloud Platform (BigQuery)

Orquestração: GitHub Actions (Cron Jobs)

Machine Learning: Scikit-Learn, Joblib

Visualização: Streamlit, Plotly

📊 Funcionalidades
✅ Monitor de Line-up: Lista atualizada de navios esperados no porto.

✅ Radar Climático: Monitoramento de precipitação e ventos em pontos estratégicos (Canal do Porto, Serra e Fundeio).

✅ Simulador de IA: Interface lateral para prever riscos baseados em cenários customizados.

✅ Alertas Críticos: Identificação automática de condições climáticas que podem paralisar a operação.

⚙️ Configuração de Segredos
O projeto utiliza Secrets do GitHub e do Streamlit para proteger credenciais sensíveis. Nunca suba arquivos .json ou .env para o repositório.

Variáveis Necessárias:
PROJECT_ID: ID do seu projeto no Google Cloud.

VC_API_KEY: Chave da API Visual Crossing.

GCP_SA_JSON: Conteúdo do JSON da sua Service Account do Google.

👨‍💻 Autor
Filiphe - Data Science & Logistics Engineering
