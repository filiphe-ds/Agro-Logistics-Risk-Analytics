Agro-Logistics Risk Analytics (v2.0) 🚢🌾
Inteligência Preditiva para mitigação de riscos de demurrage no Porto de Santos.

📌 1. Visão Geral
O Agro-Logistics Risk Analytics antecipa gargalos logísticos críticos no escoamento de commodities agrícolas. Através da integração de dados meteorológicos reais, monitoramento de embarcações e processamento de linguagem natural (NLP), o sistema gera um Delay Risk Score para apoiar a tomada de decisão e evitar multas de demurrage.

🏗️ 2. Arquitetura Tecnológica Atualizada
Data Warehouse: Google BigQuery (Arquitetura Star Schema).

Data Engineering: Python, Pandas e extração via APIs (OpenWeather e Visual Crossing para histórico).

Web Scraping: Captura automatizada do line-up de navios esperados no Porto de Santos.

AI & NLP: Google Gemini API para extração estruturada de entidades em boletins logísticos.

Machine Learning: Scikit-Learn (Random Forest Classifier) com técnicas de balanceamento de classe e alvos probabilísticos.

🗺️ 3. Roadmap de Desenvolvimento (Status Atual)
Fase 1: Fundação & Modelagem 🏗️
[x] Definição do Escopo e PRD.

[x] Desenho do Modelo de Dados (Star Schema: fato_clima, fato_lineup, fato_contingencias_nlp).

[x] Configuração do ambiente GCP (BigQuery Sandbox e autenticação via Service Account).

Fase 2: Pipelines de Ingestão (Data Engineering) ⚙️
[x] Pipeline para API de Clima (Ingestão em tempo real e Backfilling histórico de 15 dias).

[x] Web Scraping para monitoramento do line-up de navios (Terminais: Alamoa, Ilha, etc.).

[x] Carga automatizada via Python (método WRITE_TRUNCATE para gestão de dados no Sandbox).

Fase 3: Motor de NLP & Inteligência Artificial 🤖
[x] Integração funcional com Gemini 2.0 Flash para extração de JSON estruturado.

[ ] (Em progresso) Automação da varredura de notícias e boletins de tráfego/porto.

[x] Engenharia de Prompt para extração de: entidade_evento, score_risco, impacto_estimado_horas e local_foco.

Fase 4: Modelagem de Machine Learning (Data Science) 🧠
[x] Construção de Feature Store unificada via SQL Views no BigQuery.

[x] Treinamento de modelo Random Forest.

[x] Tratamento de Overfitting e Desbalanceamento de Classe (class_weight='balanced').

[x] Implementação de Target Probabilístico para simulação de cenários reais.

Fase 5: Serving & Analytics 📊
[ ] Dashboard interativo em Streamlit.

[ ] Povoamento das tabelas dimensionais (dim_navio e dim_geografia_rota).

[ ] Deploy final e documentação de uso.

🚀 Como Executar o MVP
Configurar GCP: Garanta acesso ao BigQuery e crie o dataset logisticsdata.

Variáveis de Ambiente: Configure suas chaves de API (Gemini, Visual Crossing).

Processamento: Execute os notebooks de extração para popular as tabelas fato.

Treinamento: Rode o script de ML para gerar o arquivo .pkl do modelo preditivo.

🛠️ Como Executar (Em breve)
(Nota: Este projeto está em fase ativa de desenvolvimento. Instruções de configuração de ambiente e requisitos de bibliotecas serão adicionados conforme as fases forem concluídas.)

Desenvolvido por [Filiphe]
