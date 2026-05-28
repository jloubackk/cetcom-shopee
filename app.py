import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração Widescreen (Densidade Máxima)
st.set_page_config(page_title="CETCOM | Operações", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 0rem; max-width: 98%;}
    [data-testid="stMetricValue"] {font-size: 1.8rem; font-weight: 800;}
    .destaque-nome {color: #EE4D2D; font-weight: 700; font-size: 1rem;}
    .assinatura-lideranca {text-align: right; color: #f8f9fa; font-size: 0.85rem; margin-top: 1rem;}
    </style>
""", unsafe_allow_html=True)

# 2. Cabeçalho Executivo
col_t, col_a = st.columns([3.5, 1.5])
with col_t:
    st.title("⚡ CETCOM: Inteligência de Throughput & SLA")
    st.markdown("Monitoramento Ativo de Esteiras, Gargalos e Projeção de Turno")
with col_a:
    st.markdown(f"<div class='assinatura-lideranca'>Floor Lead:<br><span class='destaque-nome'>Jonathas Louback Pereira Silva</span></div>", unsafe_allow_html=True)
st.divider()

# 3. Conexão Segura
api_key = st.secrets["API_KEY"]
csv_url = st.secrets.get("CSV_URL", "")

try:
    df = pd.read_csv(csv_url, on_bad_lines='skip')
except:
    st.error("Erro na carga de dados.")
    st.stop()

# 4. Painel Lateral (Filtros Táticos Restados)
with st.sidebar:
    st.header("⚙️ Centro de Comando")
    colunas = df.columns.tolist()
    eixo_x = st.selectbox("Operador (X):", colunas, index=0)
    eixo_y = st.selectbox("Volume (Y):", colunas, index=1)
    col_hora = st.selectbox("Hora:", colunas, index=2)
    
    st.markdown("---")
    esteira = st.selectbox("Esteira:", ["Visão Global", "P1", "P2", "P4"])
    meta_indiv = st.number_input("Corte Individual:", value=157)
    meta_total = st.number_input("Meta Esteira (h):", value=2560)
    horas_turno = st.number_input("Turno (H):", value=9)
    horas_dec = st.number_input("Horas Decorridas:", value=4)

# 5. Processamento
df_f = df.copy()
if esteira != "Visão Global":
    df_f = df_f[df_f.apply(lambda row: row.astype(str).str.contains(esteira, case=False).any(), axis=1)]

df_f = df_f.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

# 6. KPIs de Torre (Restaurados)
vol_real = df_f[eixo_y].sum()
meta_prop = meta_total * horas_dec
pace = (vol_real / meta_prop) * 100
run_rate = ((meta_total * horas_turno) - vol_real) / (horas_turno - horas_dec)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Volume Produzido", f"{vol_real:,.0f}")
c2.metric("Meta Proporcional", f"{meta_prop:,.0f}")
c3.metric("Pace da Esteira", f"{pace:.1f}%")
c4.metric("Run Rate p/ Salvar", f"{run_rate:,.0f} unid/h")

# 7. Gráfico e Tabela (Layout Denso)
cg, ct = st.columns([2, 1])
with cg:
    cores = ['#00B46E' if v >= meta_indiv else '#EE4D2D' for v in df_f[eixo_y]]
    fig = go.Figure(go.Bar(x=df_f[eixo_x], y=df_f[eixo_y], marker_color=cores, text=df_f[eixo_y]))
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=0,r=0,t=20,b=0))
    st.plotly_chart(fig, use_container_width=True)

with ct:
    st.subheader("Matriz de Ofensores")
    st.dataframe(df_f.style.map(lambda v: f'color: {"#00B46E" if v >= meta_indiv else "#EE4D2D"}', subset=[eixo_y]), use_container_width=True, height=450)

# 8. IA
if st.button("Gerar Análise de Liderança"):
    genai.configure(api_key=api_key)
    st.markdown(genai.GenerativeModel("gemini-1.5-flash").generate_content(f"Analise: {df_f.to_string()}").text)
