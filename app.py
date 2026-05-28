import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração CETCOM
st.set_page_config(
    page_title="CETCOM | Operações", 
    layout="wide", 
    initial_sidebar_state="expanded" 
)

# CSS Avançado
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 0rem; max-width: 98%;}
    [data-testid="stMetricValue"] {font-size: 2.5rem; font-weight: 800; color: #f8f9fa;}
    [data-testid="stMetricDelta"] {font-size: 1.1rem; font-weight: 600;}
    h1, h2, h3 {font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;}
    .assinatura-lideranca {text-align: right; color: #f8f9fa; font-size: 0.9rem; font-weight: 500; margin-top: 1.5rem; line-height: 1.4;}
    .destaque-nome {color: #EE4D2D; font-weight: 700; font-size: 1rem;}
    </style>
""", unsafe_allow_html=True)

# Cabeçalho com Assinatura
col_titulo, col_assinatura = st.columns([3.5, 1.5])
with col_titulo:
    st.title("⚡ CETCOM: Inteligência de Throughput & SLA")
    st.markdown("Monitoramento Ativo de Esteiras, Gargalos e Projeção de Turno")
with col_assinatura:
    st.markdown(f"""
        <div class='assinatura-lideranca'>
            Responsável Operacional:<br>
            <span class='destaque-nome'>Jonathas Louback Pereira Silva</span><br>
            <i>Gestão de Throughput & Performance</i>
        </div>
    """, unsafe_allow_html=True)
st.divider()

# Acesso seguro via secrets do Streamlit Cloud
api_key = st.secrets["API_KEY"]

# 2. Captura de Dados com Memória Persistente
with st.sidebar:
    st.header("⚙️ Conexão de Dados")
    if 'url_base' not in st.session_state: st.session_state.url_base = ""
    csv_url = st.text_input("Link da Base (CSV):", value=st.session_state.url_base, placeholder="Cole o link publicado em CSV aqui")
    if csv_url != st.session_state.url_base: st.session_state.url_base = csv_url

if not csv_url:
    st.info("Aguardando inserção da URL (formato CSV) no painel lateral.")
    st.stop()

# 3. Motor de Leitura Blindado
try:
    df = pd.read_csv(csv_url, on_bad_lines='skip')
except Exception as e:
    st.error(f"Falha de conexão: {e}")
    st.stop()

colunas_texto = df.select_dtypes(include=['object', 'string']).columns.tolist()
colunas_numericas = df.select_dtypes(include=['float64', 'int64']).columns.tolist()

# 4. Mapeamento e Filtros
with st.sidebar:
    st.markdown("---")
    st.subheader("📊 Mapeamento de Eixos")
    idx_nome = next((i for i, c in enumerate(colunas_texto) if "nome" in c.lower() or "operador" in c.lower() or "id" in c.lower()), 0)
    idx_hora = next((i for i, c in enumerate(colunas_texto) if "hora" in c.lower() or "data" in c.lower()), 0)
    
    eixo_x = st.selectbox("Operador (Eixo X):", colunas_texto, index=idx_nome)
    eixo_y = st.selectbox("Volume (Eixo Y):", colunas_numericas)
    coluna_hora = st.selectbox("Hora:", colunas_texto, index=idx_hora)
    
    st.markdown("---")
    st.subheader("🎯 SLAs (Esteira vs Indiv.)")
    meta_total_p1 = st.number_input("Vazão P1 (Total/h):", value=2560, step=50)
    meta_p1 = st.number_input("Meta Indiv. P1:", value=157, step=5)
    
    st.markdown("---")
    st.subheader("⏳ Controle de Turno")
    horas_turno = st.number_input("Duração Turno (H):", value=9)
    horas_decorridas = st.number_input("Horas Decorridas:", value=4)
    
    esteira_filtro = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])

# 5. Filtragem e Processamento
df_filtrado = df.copy()
df_filtrado[coluna_hora] = df_filtrado[coluna_hora].astype(str)
if esteira_filtro != "Visão Global":
    mask = df_filtrado.apply(lambda row: row.astype(str).str.contains(esteira_filtro, case=False).any(), axis=1)
    df_filtrado = df_filtrado[mask]

df_filtrado = df_filtrado.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

# 6. Cálculos de SLA
meta_ind = meta_p1 if esteira_filtro == "P1" else 157
meta_col_proporcional = meta_total_p1 * horas_decorridas if esteira_filtro == "P1" else 6880 * horas_decorridas
vol_realizado = df_filtrado[eixo_y].sum()
pace = (vol_realizado / meta_col_proporcional) * 100 if meta_col_proporcional > 0 else 0

# 7. Rendering dos KPIs
st.subheader(f"Status: {esteira_filtro}")
c1, c2, c3 = st.columns(3)
c1.metric("Produção Atual", f"{vol_realizado:,.0f}")
c2.metric("Pace da Esteira", f"{pace:.1f}%")
c3.metric("Meta Vigente", f"{meta_col_proporcional:,.0f}")

# 8. Gráficos e IA
st.divider()
st.subheader("Performance Individual vs Corte")
cores = ['#00B46E' if val >= meta_ind else '#EE4D2D' for val in df_filtrado[eixo_y]]
fig = go.Figure(go.Bar(x=df_filtrado[eixo_x], y=df_filtrado[eixo_y], marker_color=cores))
fig.update_layout(template="plotly_dark", height=400)
st.plotly_chart(fig, use_container_width=True)

if st.button("Gerar Análise de Liderança"):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"Analise o pace {pace:.1f}% da esteira {esteira_filtro}. Dados: {df_filtrado.to_string()}"
    st.markdown(model.generate_content(prompt).text)