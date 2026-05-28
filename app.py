import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração C-Level
st.set_page_config(page_title="CETCOM | Operações", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .destaque-nome {color: #EE4D2D; font-weight: 700; font-size: 1rem;}
    .assinatura-lideranca {text-align: right; color: #f8f9fa; font-size: 0.9rem; margin-top: 1.5rem;}
    </style>
""", unsafe_allow_html=True)

# Cabeçalho
col_titulo, col_assinatura = st.columns([3.5, 1.5])
with col_titulo:
    st.title("⚡ CETCOM: Inteligência de Throughput & SLA")
with col_assinatura:
    st.markdown("<div class='assinatura-lideranca'>Responsável:<br><span class='destaque-nome'>Jonathas Louback Pereira Silva</span></div>", unsafe_allow_html=True)

# 2. Conexão via Secrets
try:
    csv_url = st.secrets["CSV_URL"]
    api_key = st.secrets["API_KEY"]
    df = pd.read_csv(csv_url, on_bad_lines='skip')
except Exception as e:
    st.error(f"Erro de configuração ou conexão: {e}")
    st.stop()

# 3. Painel de Filtros Avançados (RESTAURADO)
with st.sidebar:
    st.header("⚙️ Filtros Táticos")
    colunas = df.columns.tolist()
    eixo_x = st.selectbox("Operador (Eixo X):", colunas, index=0)
    eixo_y = st.selectbox("Volume (Eixo Y):", colunas, index=1)
    coluna_hora = st.selectbox("Coluna de Hora/Data:", colunas, index=2)
    
    st.markdown("---")
    hora_sel = st.selectbox("Hora:", ["Visão Completa"] + sorted(df[coluna_hora].unique().astype(str).tolist()))
    modo_tempo = st.radio("Modo de Visão:", ["Hora Isolada", "Acumulado"])
    
    st.markdown("---")
    esteira = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])
    visual = st.radio("Desempenho:", ["Total", "Top 5 Performers", "Bottom 5 Ofensores"])
    
    meta_indiv = st.number_input("Corte Individual (SLA):", value=157)
    meta_esteira = st.number_input("Meta Total Esteira (h):", value=2560)

# 4. Processamento da Base
df_f = df.copy()
if esteira != "Visão Global":
    df_f = df_f[df_f.apply(lambda row: row.astype(str).str.contains(esteira, case=False).any(), axis=1)]

if hora_sel != "Visão Completa":
    if modo_tempo == "Hora Isolada":
        df_f = df_f[df_f[coluna_hora].astype(str) == hora_sel]
    else:
        df_f = df_f[df_f[coluna_hora].astype(str) <= hora_sel]

df_f = df_f.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

if visual == "Top 5 Performers": df_f = df_f.head(5)
elif visual == "Bottom 5 Ofensores": df_f = df_f.tail(5)

# 5. KPIs e Gráficos
vol_real = df_f[eixo_y].sum()
st.metric("Volume Total Filtrado", f"{vol_real:,.0f}")

c1, c2 = st.columns([2, 1])
with c1:
    cores = ['#00B46E' if val >= meta_indiv else '#EE4D2D' for val in df_f[eixo_y]]
    fig = go.Figure(go.Bar(x=df_f[eixo_x], y=df_f[eixo_y], marker_color=cores))
    fig.update_layout(template="plotly_dark", height=400)
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.dataframe(df_f, use_container_width=True)

# 6. IA Diretiva
if st.button("Gerar Análise de Liderança"):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    st.markdown(model.generate_content(f"Analise a produtividade: {df_f.to_string()}").text)
