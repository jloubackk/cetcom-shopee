import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

# 1. Configuração C-Level
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

api_key = "AQ.Ab8RN6LfNEssoStFtOKKOWpFXLuRnkSzvaA5c3wNfZMlF2n-Vg"

# 2. Captura de Dados
with st.sidebar:
    st.header("⚙️ Conexão de Dados")
    csv_url = st.text_input("Link da Base (CSV):", placeholder="Cole o link publicado em CSV aqui")

if not csv_url:
    st.info("Aguardando inserção da URL (formato CSV) no painel lateral para levantar o CETCOM.")
    st.stop()

# 3. Motor de Leitura Blindado
try:
    df = pd.read_csv(csv_url, on_bad_lines='skip')
except Exception as e:
    st.error(f"Falha de conexão com a base. Erro: {e}")
    st.stop()

colunas_texto = df.select_dtypes(include=['object', 'string']).columns.tolist()
colunas_numericas = df.select_dtypes(include=['float64', 'int64']).columns.tolist()

if not colunas_texto or not colunas_numericas:
    st.error("A base precisa ter colunas de texto (Nomes) e numéricas (Volume).")
    st.stop()

# 4. Mapeamento e Filtros com DUPLO SLA
with st.sidebar:
    st.markdown("---")
    st.subheader("📊 Mapeamento de Eixos")
    idx_nome = next((i for i, c in enumerate(colunas_texto) if "nome" in c.lower() or "operador" in c.lower() or "id" in c.lower()), 0)
    idx_hora = next((i for i, c in enumerate(colunas_texto) if "hora" in c.lower() or "data" in c.lower()), 0)
    
    eixo_x = st.selectbox("Operador/ID (Eixo X):", colunas_texto, index=idx_nome)
    eixo_y = st.selectbox("Volume (Eixo Y):", colunas_numericas)
    coluna_hora = st.selectbox("Referência de Tempo (Hora):", colunas_texto, index=idx_hora)
    
    st.markdown("---")
    st.subheader("⏱️ Filtro Temporal")
    lista_horas = sorted(df[coluna_hora].dropna().astype(str).unique().tolist())
    hora_selecionada = st.selectbox("Selecionar a Hora:", ["Visão Completa do Turno"] + lista_horas)
    
    modo_tempo = "Acumulado"
    if hora_selecionada != "Visão Completa do Turno":
        modo_tempo = st.radio("Modo de Visão:", ["Hora Isolada (Apenas esta hora)", "Acumulado (Até esta hora)"])

    st.markdown("---")
    st.subheader("🎯 SLA COLETIVO (Vazão da Esteira/h)")
    meta_total_p1 = st.number_input("Carga Horária P1:", value=2560, step=50)
    meta_total_p2 = st.number_input("Carga Horária P2:", value=2560, step=50)
    meta_total_p4 = st.number_input("Carga Horária P4:", value=1760, step=50)
    meta_total_global = st.number_input("Carga Horária Global:", value=6880, step=100)

    st.markdown("---")
    st.subheader("👤 SLA INDIVIDUAL (Linha de Corte/h)")
    meta_p1 = st.number_input("Meta Individual P1:", value=157, step=5)
    meta_p2 = st.number_input("Meta Individual P2:", value=157, step=5)
    meta_p4 = st.number_input("Meta Individual P4:", value=157, step=5)
    meta_global = st.number_input("Meta Individual Global:", value=157, step=5)
    
    st.markdown("---")
    st.subheader("⏳ Controle de Turno")
    horas_turno = st.number_input("Duração Total do Turno (H):", min_value=1, value=9)
    horas_decorridas = st.number_input("Horas Trabalhadas (Cálculo de Pace):", min_value=1, max_value=24, value=4)
    
    st.markdown("---")
    st.subheader("🔍 Recortes Táticos")
    esteira_filtro = st.selectbox("Isolar Esteira:", ["Visão Global", "P1", "P2", "P4"])
    visualizacao_filtro = st.radio("Desempenho:", ["Headcount Total", "Top 5 (Performaers)", "Bottom 5 (Ofensores)"])

# 5. Motor de Filtragem Ativo
df_filtrado = df.copy()
df_filtrado[coluna_hora] = df_filtrado[coluna_hora].astype(str)

if esteira_filtro != "Visão Global":
    mask = df_filtrado.apply(lambda row: row.astype(str).str.contains(esteira_filtro, case=False).any(), axis=1)
    df_filtrado = df_filtrado[mask]

if hora_selecionada != "Visão Completa do Turno":
    if modo_tempo == "Hora Isolada (Apenas esta hora)":
        df_filtrado = df_filtrado[df_filtrado[coluna_hora] == hora_selecionada]
    else: 
        df_filtrado = df_filtrado[df_filtrado[coluna_hora] <= hora_selecionada]

df_filtrado = df_filtrado.groupby(eixo_x, as_index=False)[eixo_y].sum()
df_filtrado = df_filtrado.sort_values(by=eixo_y, ascending=False)

if visualizacao_filtro == "Top 5 (Performaers)":
    df_filtrado = df_filtrado.head(5)
elif visualizacao_filtro == "Bottom 5 (Ofensores)":
    df_filtrado = df_filtrado.tail(5)

if df_filtrado.empty:
    st.warning("Nenhum volume operado encontrado para o cruzamento destes filtros.")
    st.stop()

# 6. Duplo Cálculo: SLA Coletivo (Turno) vs SLA Individual (Gráfico)
if esteira_filtro == "P1": 
    meta_ind_ativa = meta_p1
    meta_col_ativa = meta_total_p1
elif esteira_filtro == "P2": 
    meta_ind_ativa = meta_p2
    meta_col_ativa = meta_total_p2
elif esteira_filtro == "P4": 
    meta_ind_ativa = meta_p4
    meta_col_ativa = meta_total_p4
else: 
    meta_ind_ativa = meta_global
    meta_col_ativa = meta_total_global

if hora_selecionada != "Visão Completa do Turno" and modo_tempo == "Hora Isolada (Apenas esta hora)":
    meta_individual_aplicada = meta_ind_ativa 
    meta_coletiva_proporcional = meta_col_ativa
else:
    meta_individual_aplicada = meta_ind_ativa * horas_decorridas 
    meta_coletiva_proporcional = meta_col_ativa * horas_decorridas 

headcount = len(df_filtrado)
vol_realizado = df_filtrado[eixo_y].sum()

meta_coletiva_final = meta_col_ativa * horas_turno

delta_proporcional = vol_realizado - meta_coletiva_proporcional
pace_percentual = (vol_realizado / meta_coletiva_proporcional) * 100 if meta_coletiva_proporcional > 0 else 0

horas_restantes = horas_turno - horas_decorridas
gap_fim_turno = meta_coletiva_final - vol_realizado
run_rate_exigido = gap_fim_turno / horas_restantes if horas_restantes > 0 else 0

# 7. Rendering do CETCOM Executivo (Baseado no SLA da Esteira)
st.subheader(f"Status: {esteira_filtro} | Referência: {hora_selecionada} ({'Acumulado' if 'Acumulado' in modo_tempo or hora_selecionada == 'Visão Completa do Turno' else 'Isolado'})")
col1, col2, col3, col4 = st.columns(4)

col1.metric("Volume Produzido", f"{vol_realizado:,.0f}", f"{delta_proporcional:,.0f} vs Exigência da Esteira", delta_color="normal")
col2.metric(f"Meta da Esteira ({horas_decorridas}H)", f"{meta_coletiva_proporcional:,.0f}")
col3.metric("Pace da Esteira", f"{pace_percentual:.1f}%", "Fluxo Saudável" if pace_percentual >= 100 else "Fluxo Comprometido", delta_color="normal" if pace_percentual >= 100 else "inverse")

if gap_fim_turno <= 0:
    col4.metric("Run Rate Exigido", "SLA Garantido", "0/h", delta_color="off")
else:
    col4.metric("Run Rate p/ Salvar Turno", f"{run_rate_exigido:,.0f} unid/h", f"Déficit: {gap_fim_turno:,.0f} unid.", delta_color="inverse")

st.divider()

# 8. Gráficos Táticos (Baseado no SLA Individual)
col_grafico, col_tabela = st.columns([1.8, 1])

with col_grafico:
    st.subheader(f"Throughput Individual vs Linha de Corte ({meta_individual_aplicada} unid)")
    cores = ['#00B46E' if val >= meta_individual_aplicada else '#EE4D2D' for val in df_filtrado[eixo_y]]
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df_filtrado[eixo_x],
        y=df_filtrado[eixo_y],
        marker_color=cores,
        text=df_filtrado[eixo_y],
        textposition='outside',
        textfont=dict(size=14, color='white')
    ))
    
    fig.add_hline(y=meta_individual_aplicada, line_dash="dot", line_color="white", 
                  annotation_text=f"Corte Individual ({meta_individual_aplicada})", 
                  annotation_position="top right", annotation_font=dict(color="white"))

    fig.update_layout(
        template="plotly_dark", 
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=20, t=30, b=80),
        xaxis_title=None,
        yaxis_title="Unidades",
        showlegend=False,
        height=550,
        barmode='group'
    )
    st.plotly_chart(fig, use_container_width=True)

with col_tabela:
    st.subheader("Matriz de Ofensores")
    def colorir_tabela(val):
        if isinstance(val, (int, float)):
            return f'color: {"#00B46E" if val >= meta_individual_aplicada else "#EE4D2D"}; font-weight: bold;'
        return ''
    st.dataframe(df_filtrado.style.map(colorir_tabela, subset=[eixo_y]), 
                 use_container_width=True, 
                 height=550, 
                 hide_index=True)

st.divider()

# 9. IA do CETCOM
st.subheader("Parecer Diretivo (AI Insights)")

if st.button("Gerar Análise de Liderança", type="primary"):
    with st.spinner("Analisando gargalos do CETCOM..."):
        genai.configure(api_key=api_key)
        modelo_alvo = "gemini-1.0-pro"
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                modelo_alvo = m.name
                if 'flash' in m.name: break 
        model = genai.GenerativeModel(modelo_alvo)
        
        prompt_cetcom = f"""
        Atue como o Diretor do CETCOM (Centro de Controle Operacional).
        CENÁRIO DUPLO:
        - Meta COLETIVA da Esteira: {meta_coletiva_proporcional} unidades.
        - Pace da Esteira: {pace_percentual:.1f}%
        - Volume Faltante p/ Turno: {gap_fim_turno}
        - Run Rate exigido da Esteira p/ Salvar Turno: {run_rate_exigido:.1f}/h
        
        - Meta INDIVIDUAL de Corte (para avaliar quem está puxando): {meta_individual_aplicada}
        
        DADOS DE PRODUÇÃO INDIVIDUAL: 
        {df_filtrado.to_string()}
        
        Gere relatório C-Level (3 bullet points curtos): 
        1. Diagnóstico do Pace Coletivo (Estamos atingindo a vazão exigida da esteira?). 
        2. Avaliação Individual (Quais operadores estão compensando a vazão e quais ofensores estão afundando o Run Rate). 
        3. Ação Tática Imediata (Ex: remanejamento para cobrir o Run Rate). 
        Tom executivo agressivo. Nenhuma saudação.
        """
        try:
            st.markdown(model.generate_content(prompt_cetcom).text)
        except Exception as e:
            st.error(f"Erro no motor da IA: {e}")
