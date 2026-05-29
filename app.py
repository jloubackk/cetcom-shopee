import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração de Alta Performance
st.set_page_config(page_title="CETCOM | Operações", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .destaque-nome {color: #EE4D2D; font-weight: 700; font-size: 1rem;}
    .assinatura-lideranca {text-align: right; color: #f8f9fa; font-size: 0.85rem; margin-top: 1rem;}
    </style>
""", unsafe_allow_html=True)

col_titulo, col_assinatura = st.columns([3.5, 1.5])
with col_titulo:
    st.title("⚡ CETCOM: Inteligência de Throughput & SLA")
with col_assinatura:
    st.markdown("<div class='assinatura-lideranca'>Floor Lead:<br><span class='destaque-nome'>Jonathas Louback Pereira Silva</span></div>", unsafe_allow_html=True)
st.divider()

# 2. Conexão via Secrets (Blindado)
try:
    df = pd.read_csv(st.secrets["CSV_URL"], on_bad_lines='skip')
    api_key = st.secrets["API_KEY"]
except Exception as e:
    st.error(f"Falha de conexão com a base. Verifique os Secrets no Streamlit Cloud. Erro: {e}")
    st.stop()

# Separação inteligente de colunas
colunas_texto = df.select_dtypes(include=['object', 'string']).columns.tolist()
colunas_numericas = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
if not colunas_texto: colunas_texto = df.columns.tolist()
if not colunas_numericas: colunas_numericas = df.columns.tolist()

# 3. Painel Lateral - Filtros de Precisão
with st.sidebar:
    st.header("⚙️ Centro de Comando")
    
    st.subheader("1. Eixos Base")
    idx_nome = next((i for i, c in enumerate(colunas_texto) if "nome" in c.lower() or "operador" in c.lower() or "id" in c.lower()), 0)
    idx_hora = next((i for i, c in enumerate(colunas_texto) if "hora" in c.lower() or "data" in c.lower()), 0)
    
    eixo_x = st.selectbox("Operador (X):", colunas_texto, index=idx_nome)
    eixo_y = st.selectbox("Volume (Y):", colunas_numericas)
    col_hora = st.selectbox("Coluna Hora:", colunas_texto, index=idx_hora)
    
    st.markdown("---")
    st.subheader("2. Recortes Operacionais")
    
    lista_operadores = ["Todos"] + sorted(df[eixo_x].dropna().unique().astype(str).tolist())
    colaborador_sel = st.multiselect("Filtrar Colaborador(es):", options=lista_operadores, default="Todos")
    
    esteira = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])
    
    lista_horas = ["Visão Completa"] + sorted(df[col_hora].dropna().unique().astype(str).tolist())
    hora_sel = st.selectbox("Referência de Hora:", lista_horas)
    
    modo_tempo = "Acumulado"
    if hora_sel != "Visão Completa":
        modo_tempo = st.radio("Modo Temporal:", ["Hora Isolada", "Acumulado"])
        
    visual = st.radio("Recorte de Desempenho:", ["Visão Total", "Top 5 Performers", "Bottom 5 Ofensores"])

    st.markdown("---")
    st.subheader("3. SLA Coletivo (Vazão da Esteira/h)")
    meta_total_p1 = st.number_input("Carga Horária P1:", value=2560, step=50)
    meta_total_p2 = st.number_input("Carga Horária P2:", value=2560, step=50)
    meta_total_p4 = st.number_input("Carga Horária P4:", value=1760, step=50)
    meta_total_global = st.number_input("Carga Horária Global:", value=6880, step=100)

    st.markdown("---")
    st.subheader("4. SLA Individual (Linha de Corte/h)")
    meta_p1 = st.number_input("Meta Individual P1:", value=157, step=5)
    meta_p2 = st.number_input("Meta Individual P2:", value=157, step=5)
    meta_p4 = st.number_input("Meta Individual P4:", value=157, step=5)
    meta_global = st.number_input("Meta Individual Global:", value=157, step=5)
    
    st.markdown("---")
    st.subheader("5. Controle de Turno")
    h_turno = st.number_input("Duração Turno (H):", min_value=1, value=9)
    h_dec = st.number_input("Horas Decorridas:", min_value=1, value=4)

# 4. ENGINE DE PROCESSAMENTO E BLINDAGEM MATEMÁTICA
df_f = df.copy()

# Força a coluna Y a ser numérica, limpando vírgulas
df_f[eixo_y] = pd.to_numeric(df_f[eixo_y].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

df_f[col_hora] = df_f[col_hora].astype(str)
df_f[eixo_x] = df_f[eixo_x].astype(str)

# A. Colaborador
if "Todos" not in colaborador_sel and len(colaborador_sel) > 0:
    df_f = df_f[df_f[eixo_x].isin(colaborador_sel)]

# B. Esteira
if esteira != "Visão Global":
    mask = df_f.apply(lambda row: row.astype(str).str.contains(esteira, case=False).any(), axis=1)
    df_f = df_f[mask]

# C. Temporal
if hora_sel != "Visão Completa":
    if modo_tempo == "Hora Isolada":
        df_f = df_f[df_f[col_hora] == hora_sel]
    else:
        df_f = df_f[df_f[col_hora] <= hora_sel]

# D. Agrupamento
df_f = df_f.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

# E. Desempenho
if visual == "Top 5 Performers":
    df_f = df_f.head(5)
elif visual == "Bottom 5 Ofensores":
    df_f = df_f.tail(5)

if df_f.empty:
    st.warning("⚠️ Nenhum dado encontrado para esta combinação de filtros.")
    st.stop()

# 5. ATRIBUIÇÃO DINÂMICA DE SLA (Restaurada)
if esteira == "P1":
    meta_ind_ativa = meta_p1
    meta_col_ativa = meta_total_p1
elif esteira == "P2":
    meta_ind_ativa = meta_p2
    meta_col_ativa = meta_total_p2
elif esteira == "P4":
    meta_ind_ativa = meta_p4
    meta_col_ativa = meta_total_p4
else:
    meta_ind_ativa = meta_global
    meta_col_ativa = meta_total_global

# 6. CÁLCULOS SEGUROS
vol_real = float(df_f[eixo_y].sum())
meta_prop = float(meta_col_ativa * h_dec)

if meta_prop > 0:
    pace = (vol_real / meta_prop) * 100.0
else:
    pace = 0.0

tempo_restante = float(h_turno - h_dec)
if tempo_restante > 0:
    run_rate = ((meta_col_ativa * h_turno) - vol_real) / tempo_restante
else:
    run_rate = 0.0

# 7. RENDERIZAÇÃO DE KPIs
st.subheader(f"Status Atual: {esteira} | {visual}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vol. Produzido", f"{vol_real:,.0f}")
c2.metric("Meta Proporcional", f"{meta_prop:,.0f}")
c3.metric("Pace da Esteira", f"{pace:.1f}%")
c4.metric("Run Rate p/ Salvar", f"{run_rate:,.0f} unid/h")

st.divider()

# 8. GRÁFICOS E TABELAS
cg, ct = st.columns([2, 1])
with cg:
    # Corte dinâmico baseado no modo de tempo e esteira selecionada
    meta_grafico = meta_ind_ativa * h_dec if (modo_tempo == "Acumulado" or hora_sel == "Visão Completa") else meta_ind_ativa
    cores = ['#00B46E' if v >= meta_grafico else '#EE4D2D' for v in df_f[eixo_y]]
    
    fig = go.Figure(go.Bar(x=df_f[eixo_x], y=df_f[eixo_y], marker_color=cores, text=df_f[eixo_y], textposition='outside'))
    fig.add_hline(y=meta_grafico, line_dash="dot", line_color="white", annotation_text=f"Corte ({meta_grafico})")
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=0, r=0, t=30, b=0), yaxis_title="Unidades")
    st.plotly_chart(fig, use_container_width=True)

with ct:
    st.subheader("Matriz Individual")
    st.dataframe(df_f.style.map(lambda v: f'color: {"#00B46E" if v >= meta_grafico else "#EE4D2D"}; font-weight: bold', subset=[eixo_y]), use_container_width=True, height=450)

# 9. IA OPERACIONAL TÁTICA
st.divider()
if st.button("Gerar Análise de Liderança", type="primary"):
    with st.spinner("Analisando gargalos táticos..."):
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt_tatico = (
            f"Atue como Diretor de Logística. Esqueça variáveis de software. Foque no resultado operacional da esteira {esteira}.\n\n"
            f"CENÁRIO:\n"
            f"- Meta Coletiva Proporcional: {meta_prop:,.0f}\n"
            f"- Produção Real: {vol_real:,.0f}\n"
            f"- Pace: {pace:.1f}%\n"
            f"- Corte individual na visão atual: {meta_grafico} unidades.\n\n"
            f"LISTA DE PRODUÇÃO:\n{df_f.to_string()}\n\n"
            "Entregue um parecer de impacto em 3 tópicos curtos e agressivos:\n"
            "1. Diagnóstico do Volume Coletivo (Estamos performando?).\n"
            "2. Destaques e Ofensores (Quem está fora do SLA de 157h e precisa de ação?).\n"
            "3. Ordem Tática (O que fazer agora no piso)."
        )
        
        try:
            st.markdown(model.generate_content(prompt_tatico).text)
        except Exception as e:
            st.error(f"Falha de comunicação com a inteligência: {e}")
