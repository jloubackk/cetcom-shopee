import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração de Alta Performance
st.set_page_config(page_title="CETCOM | Operações", layout="wide", initial_sidebar_state="expanded")

# 2. Conexão via Secrets
try:
    df = pd.read_csv(st.secrets["CSV_URL"], on_bad_lines='skip')
    api_key = st.secrets["API_KEY"]
except Exception as e:
    st.error(f"Erro de conexão com a base: {e}")
    st.stop()

# 3. Blindagem de Dados (Limpeza estrita para evitar distorção)
def sanitizar_numeros(coluna):
    # Converte para string, remove o que não é dígito/ponto/vírgula, substitui vírgula por ponto
    return pd.to_numeric(coluna.astype(str).str.replace(r'[^0-9,.]', '', regex=True).str.replace(',', '.'), errors='coerce').fillna(0)

# Identificação automática das colunas
colunas_texto = df.select_dtypes(include=['object', 'string']).columns.tolist()
colunas_numericas = df.select_dtypes(include=['float64', 'int64']).columns.tolist()

# 4. Painel Lateral
with st.sidebar:
    st.header("⚙️ Centro de Comando")
    eixo_x = st.selectbox("Operador (X):", colunas_texto, index=0)
    eixo_y = st.selectbox("Volume (Y):", df.columns.tolist())
    col_hora = st.selectbox("Coluna Hora:", colunas_texto, index=1 if len(colunas_texto)>1 else 0)
    
    st.markdown("---")
    esteira = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])
    hora_sel = st.selectbox("Referência de Hora:", ["Visão Completa"] + sorted(df[col_hora].unique().astype(str).tolist()))
    modo_tempo = st.radio("Modo Temporal:", ["Hora Isolada", "Acumulado"]) if hora_sel != "Visão Completa" else "Acumulado"
    visual = st.radio("Recorte:", ["Visão Total", "Top 5 Performers", "Bottom 5 Ofensores"])

    st.markdown("---")
    meta_indiv = st.number_input("Corte SLA Indiv:", value=157)
    meta_total = st.number_input("Meta Coletiva (h):", value=2560)
    h_turno = st.number_input("Duração Turno (H):", value=9)
    h_dec = st.number_input("Horas Decorridas:", value=4)

# 5. Engine de Processamento (Blindagem Aplicada)
df_f = df.copy()
df_f[eixo_y] = sanitizar_numeros(df_f[eixo_y]) # Aplica a limpeza aqui
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

# 6. Cálculos de Performance
vol_real = float(df_f[eixo_y].sum())
meta_prop = float(meta_total * h_dec)
pace = (vol_real / meta_prop) * 100 if meta_prop > 0 else 0
tempo_restante = float(h_turno - h_dec)
run_rate = ((meta_total * h_turno) - vol_real) / tempo_restante if tempo_restante > 0 else 0

# 7. Rendering
st.subheader(f"Status: {esteira} | {visual}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vol. Produzido", f"{vol_real:,.0f}")
c2.metric("Meta Proporcional", f"{meta_prop:,.0f}")
c3.metric("Pace da Esteira", f"{pace:.1f}%")
c4.metric("Run Rate p/ Salvar", f"{run_rate:,.0f} unid/h")

cg, ct = st.columns([2, 1])
with cg:
    fig = go.Figure(go.Bar(x=df_f[eixo_x], y=df_f[eixo_y], marker_color=['#00B46E' if v >= meta_indiv else '#EE4D2D' for v in df_f[eixo_y]]))
    fig.update_layout(template="plotly_dark", height=450)
    st.plotly_chart(fig, use_container_width=True)

with ct:
    st.dataframe(df_f.style.format({eixo_y: "{:,.0f}"}), use_container_width=True, height=450)

if st.button("Gerar Análise de Liderança"):
    genai.configure(api_key=api_key)
    prompt = f"Analise o pace {pace:.1f}% da esteira {esteira}. Dados: {df_f.to_string()}"
    st.markdown(genai.GenerativeModel("gemini-1.5-flash").generate_content(prompt).text)
