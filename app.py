import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração de Alta Densidade
st.set_page_config(page_title="CETCOM | Operações", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .destaque-nome {color: #EE4D2D; font-weight: 700; font-size: 1rem;}
    .assinatura-lideranca {text-align: right; color: #f8f9fa; font-size: 0.85rem; margin-top: 1rem;}
    </style>
""", unsafe_allow_html=True)

# Cabeçalho
col_titulo, col_assinatura = st.columns([3.5, 1.5])
with col_titulo:
    st.title("⚡ CETCOM: Inteligência de Throughput & SLA")
with col_assinatura:
    st.markdown("<div class='assinatura-lideranca'>Floor Lead:<br><span class='destaque-nome'>Jonathas Louback Pereira Silva</span></div>", unsafe_allow_html=True)

# 2. Conexão via Secrets
try:
    csv_url = st.secrets["CSV_URL"]
    api_key = st.secrets["API_KEY"]
    df = pd.read_csv(csv_url, on_bad_lines='skip')
except Exception as e:
    st.error(f"Erro de conexão: {e}")
    st.stop()

# 3. PAINEL DE FILTROS INTEGRAL (RESTAURADO)
with st.sidebar:
    st.header("⚙️ Centro de Comando")
    colunas = df.columns.tolist()
    
    st.subheader("📊 Eixos")
    eixo_x = st.selectbox("Operador/ID (X):", colunas, index=0)
    eixo_y = st.selectbox("Volume (Y):", colunas, index=1)
    col_hora = st.selectbox("Coluna Referência de Tempo:", colunas, index=2)
    
    st.markdown("---")
    st.subheader("⏱️ Filtros Temporais")
    lista_horas = ["Visão Completa"] + sorted(df[col_hora].unique().astype(str).tolist())
    hora_sel = st.selectbox("Hora:", lista_horas)
    modo_tempo = st.radio("Modo de Visão:", ["Hora Isolada", "Acumulado"])
    
    st.markdown("---")
    st.subheader("🔍 Filtros Táticos")
    esteira = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])
    visual = st.radio("Desempenho:", ["Total", "Top 5 Performers", "Bottom 5 Ofensores"])
    
    st.markdown("---")
    st.subheader("🎯 Metas & Turno")
    meta_indiv = st.number_input("SLA Indiv (Corte):", value=157)
    meta_total = st.number_input("Meta Coletiva (h):", value=2560)
    horas_turno = st.number_input("Duração Turno (H):", value=9)
    horas_dec = st.number_input("Horas Decorridas:", value=4)

# 4. Processamento Lógico (Engine)
df_f = df.copy()
df_f[col_hora] = df_f[col_hora].astype(str)

if esteira != "Visão Global":
    df_f = df_f[df_f.apply(lambda row: row.astype(str).str.contains(esteira, case=False).any(), axis=1)]

if hora_sel != "Visão Completa":
    if modo_tempo == "Hora Isolada":
        df_f = df_f[df_f[col_hora] == hora_sel]
    else:
        df_f = df_f[df_f[col_hora] <= hora_sel]

df_f = df_f.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

if visual == "Top 5 Performers": df_f = df_f.head(5)
elif visual == "Bottom 5 Ofensores": df_f = df_f.tail(5)

# 5. KPIs e Visualização
vol_real = df_f[eixo_y].sum()
meta_prop = meta_total * horas_dec
pace = (vol_real / meta_prop) * 100 if meta_prop > 0 else 0
run_rate = ((meta_total * horas_turno) - vol_real) / (horas_turno - horas_dec) if (horas_turno - horas_dec) > 0 else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vol. Produzido", f"{vol_real:,.0f}")
c2.metric("Meta Proporcional", f"{meta_prop:,.0f}")
c3.metric("Pace da Esteira", f"{pace:.1f}%")
c4.metric("Run Rate p/ Salvar", f"{run_rate:,.0f} unid/h")

# 6. Gráfico e Tabela
cg, ct = st.columns([2, 1])
with cg:
    cores = ['#00B46E' if v >= meta_indiv else '#EE4D2D' for v in df_f[eixo_y]]
    fig = go.Figure(go.Bar(x=df_f[eixo_x], y=df_f[eixo_y], marker_color=cores, text=df_f[eixo_y]))
    fig.update_layout(template="plotly_dark", height=450)
    st.plotly_chart(fig, use_container_width=True)

with ct:
    st.subheader("Matriz de Ofensores")
    st.dataframe(df_f.style.map(lambda v: f'color: {"#00B46E" if v >= meta_indiv else "#EE4D2D"}', subset=[eixo_y]), use_container_width=True, height=450)

# 7. IA
if st.button("Gerar Análise de Liderança"):
    genai.configure(api_key=api_key)
    st.markdown(genai.GenerativeModel("gemini-1.5-flash").generate_content(f"Analise: {df_f.to_string()}").text)
