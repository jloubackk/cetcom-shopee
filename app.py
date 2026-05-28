import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração C-Level (CETCOM)
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

# Acesso seguro via Secrets
api_key = st.secrets["API_KEY"]
csv_url = st.secrets.get("CSV_URL", "")

# 2. Motor de Leitura Blindado
if not csv_url:
    st.error("Erro: Link da base (CSV_URL) não configurado nas Secrets do Streamlit Cloud.")
    st.stop()

try:
    df = pd.read_csv(csv_url, on_bad_lines='skip')
except Exception as e:
    st.error(f"Falha de conexão: {e}")
    st.stop()

colunas_texto = df.select_dtypes(include=['object', 'string']).columns.tolist()
colunas_numericas = df.select_dtypes(include=['float64', 'int64']).columns.tolist()

# 3. Mapeamento e Filtros (Painel Lateral)
with st.sidebar:
    st.header("⚙️ Configurações Táticas")
    idx_nome = next((i for i, c in enumerate(colunas_texto) if "nome" in c.lower() or "operador" in c.lower() or "id" in c.lower()), 0)
    idx_hora = next((i for i, c in enumerate(colunas_texto) if "hora" in c.lower() or "data" in c.lower()), 0)
    
    eixo_x = st.selectbox("Operador (Eixo X):", colunas_texto, index=idx_nome)
    eixo_y = st.selectbox("Volume (Eixo Y):", colunas_numericas)
    coluna_hora = st.selectbox("Referência de Tempo (Hora):", colunas_texto, index=idx_hora)
    
    st.markdown("---")
    st.subheader("🎯 SLAs & Turno")
    meta_total_esteira = st.number_input("Meta Coletiva Esteira (unid/h):", value=2560, step=50)
    meta_indiv = st.number_input("Corte Individual (unid/h):", value=157, step=5)
    horas_turno = st.number_input("Duração Total Turno (H):", value=9)
    horas_decorridas = st.number_input("Horas Decorridas:", value=4)
    
    esteira_filtro = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])

# 4. Filtragem e Processamento
df_filtrado = df.copy()
df_filtrado[coluna_hora] = df_filtrado[coluna_hora].astype(str)

if esteira_filtro != "Visão Global":
    mask = df_filtrado.apply(lambda row: row.astype(str).str.contains(esteira_filtro, case=False).any(), axis=1)
    df_filtrado = df_filtrado[mask]

df_filtrado = df_filtrado.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

# 5. Cálculos Operacionais
vol_realizado = df_filtrado[eixo_y].sum()
meta_coletiva_proporcional = meta_total_esteira * horas_decorridas
pace = (vol_realizado / meta_coletiva_proporcional) * 100 if meta_coletiva_proporcional > 0 else 0
run_rate = ((meta_total_esteira * horas_turno) - vol_realizado) / (horas_turno - horas_decorridas)

# 6. Dashboard
col1, col2, col3, col4 = st.columns(4)
col1.metric("Produção Realizada", f"{vol_realizado:,.0f}")
col2.metric("Meta Proporcional", f"{meta_coletiva_proporcional:,.0f}")
col3.metric("Pace da Esteira", f"{pace:.1f}%")
col4.metric("Run Rate p/ Salvar Turno", f"{run_rate:,.0f} unid/h")

st.divider()

# 7. Gráfico e Tabela
c1, c2 = st.columns([1.8, 1])
with c1:
    cores = ['#00B46E' if val >= meta_indiv else '#EE4D2D' for val in df_filtrado[eixo_y]]
    fig = go.Figure(go.Bar(x=df_filtrado[eixo_x], y=df_filtrado[eixo_y], marker_color=cores))
    fig.update_layout(template="plotly_dark", height=450)
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.dataframe(df_filtrado.style.map(lambda v: f'color: {"#00B46E" if v >= meta_indiv else "#EE4D2D"}', subset=[eixo_y]), use_container_width=True)

# 8. IA Diretiva
if st.button("Gerar Análise de Liderança"):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"Diretor CETCOM, analise pace {pace:.1f}%. Metas: Coletiva {meta_total_esteira}, Indiv {meta_indiv}. Dados: {df_filtrado.to_string()}"
    st.markdown(model.generate_content(prompt).text)
