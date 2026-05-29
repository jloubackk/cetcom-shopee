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

# Separação inteligente de colunas (Evita selecionar texto no lugar de número)
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
    st.subheader("2. Filtros Operacionais")
    
    lista_operadores = ["Todos"] + sorted(df[eixo_x].dropna().unique().astype(str).tolist())
    colaborador_sel = st.multiselect("Filtrar Colaborador(es):", options=lista_operadores, default="Todos")
    
    esteira = st.selectbox("Filtrar Esteira:", ["Visão Global", "P1", "P2", "P4"])
    
    lista_horas = ["Visão Completa"] + sorted(df[col_hora].dropna().unique().astype(str).tolist())
    hora_sel = st.selectbox("Referência de Hora:", lista_horas)
    
    modo_tempo = "Acumulado"
    if hora_sel != "Visão Completa":
        modo_tempo = st.radio("Modo Temporal:", ["Hora Isolada", "Acumulado"])
        
    visual = st.radio("Recorte de Desempenho:", ["Visão Total", "Top 5 Performers", "Bottom 5 Ofensores"])

    st.markdown("---")
    st.subheader("3. Metas e Turno")
    meta_indiv = st.number_input("Corte SLA Indiv (unid/h):", value=157)
    meta_total = st.number_input("Meta Coletiva (unid/h):", value=2560)
    h_turno = st.number_input("Duração Turno (H):", min_value=1, value=9)
    h_dec = st.number_input("Horas Decorridas:", min_value=1, value=4)

# 4. ENGINE DE PROCESSAMENTO (Ordem Rigorosa e Blindagem Matemática)
df_f = df.copy()

# === BLINDAGEM CONTRA O VALUEERROR ===
# Força a coluna Y a ser numérica. Se vier com texto ou vírgula da planilha, ele limpa e processa.
df_f[eixo_y] = pd.to_numeric(df_f[eixo_y].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

df_f[col_hora] = df_f[col_hora].astype(str)
df_f[eixo_x] = df_f[eixo_x].astype(str)

# A. Filtro de Colaborador
if "Todos" not in colaborador_sel and len(colaborador_sel) > 0:
    df_f = df_f[df_f[eixo_x].isin(colaborador_sel)]

# B. Filtro de Esteira
if esteira != "Visão Global":
    mask = df_f.apply(lambda row: row.astype(str).str.contains(esteira, case=False).any(), axis=1)
    df_f = df_f[mask]

# C. Filtro Temporal
if hora_sel != "Visão Completa":
    if modo_tempo == "Hora Isolada":
        df_f = df_f[df_f[col_hora] == hora_sel]
    else:
        df_f = df_f[df_f[col_hora] <= hora_sel]

# D. Agrupamento (Soma os volumes baseados no que restou)
df_f = df_f.groupby(eixo_x, as_index=False)[eixo_y].sum().sort_values(by=eixo_y, ascending=False)

# E. Filtro Top/Bottom
if visual == "Top 5 Performers":
    df_f = df_f.head(5)
elif visual == "Bottom 5 Ofensores":
    df_f = df_f.tail(5)

# Proteção contra DataFrame Vazio
if df_f.empty:
    st.warning("⚠️ Nenhum dado encontrado para esta combinação de filtros.")
    st.stop()

# 5. CÁLCULOS MATEMÁTICOS SEGUROS
# Graças à blindagem no Passo 4, esta linha NUNCA mais causará ValueError
vol_real = float(df_f[eixo_y].sum())
meta_prop = float(meta_total * h_dec)

if meta_prop > 0:
    pace = (vol_real / meta_prop) * 100.0
else:
    pace = 0.0

tempo_restante = float(h_turno - h_dec)
if tempo_restante > 0:
    run_rate = ((meta_total * h_turno) - vol_real) / tempo_restante
else:
    run_rate = 0.0

# 6. RENDERIZAÇÃO DE KPIs
st.subheader(f"Status Atual: {esteira} | {visual}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vol. Produzido", f"{vol_real:,.0f}")
c2.metric("Meta Proporcional", f"{meta_prop:,.0f}")
c3.metric("Pace da Esteira", f"{pace:.1f}%")
c4.metric("Run Rate p/ Salvar", f"{run_rate:,.0f} unid/h")

st.divider()

# 7. GRÁFICOS E TABELAS
cg, ct = st.columns([2, 1])
with cg:
    meta_grafico = meta_indiv * h_dec if (modo_tempo == "Acumulado" or hora_sel == "Visão Completa") else meta_indiv
    cores = ['#00B46E' if v >= meta_grafico else '#EE4D2D' for v in df_f[eixo_y]]
    
    fig = go.Figure(go.Bar(x=df_f[eixo_x], y=df_f[eixo_y], marker_color=cores, text=df_f[eixo_y], textposition='outside'))
    fig.add_hline(y=meta_grafico, line_dash="dot", line_color="white", annotation_text=f"Corte ({meta_grafico})")
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=0, r=0, t=30, b=0), yaxis_title="Unidades")
    st.plotly_chart(fig, use_container_width=True)

with ct:
    st.subheader("Matriz Individual")
    st.dataframe(df_f.style.map(lambda v: f'color: {"#00B46E" if v >= meta_grafico else "#EE4D2D"}; font-weight: bold', subset=[eixo_y]), use_container_width=True, height=450)

# 8. IA OPERACIONAL TÁTICA
st.divider()
if st.button("Gerar Análise de Liderança", type="primary"):
    with st.spinner("Analisando gargalos táticos..."):
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt_tatico = (
            "Atue como Diretor de Logística. Esqueça variáveis de código ou software. Foque puramente no resultado operacional do chão de fábrica.\n\n"
            f"CENÁRIO:\n"
            f"- Meta Coletiva Esperada: {meta_prop:,.0f}\n"
            f"- Produção Real: {vol_real:,.0f}\n"
            f"- Pace: {pace:.1f}%\n"
            f"- Corte individual: {meta_grafico} unidades.\n\n"
            f"LISTA DE PRODUÇÃO DOS OPERADORES:\n{df_f.to_string()}\n\n"
            "Entregue um parecer de impacto em 3 tópicos curtos e agressivos:\n"
            "1. Diagnóstico do Volume Coletivo (Ganhamos ou perdemos até agora?).\n"
            "2. Destaques (Quem carrega a operação) e Ofensores (Quem derruba a linha).\n"
            "3. Ordem de Ação (O que o supervisor deve fazer agora no piso)."
        )
        
        try:
            st.markdown(model.generate_content(prompt_tatico).text)
        except Exception as e:
            st.error(f"Falha de comunicação com a inteligência: {e}")
