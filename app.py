import os
import re

import google.generativeai as genai
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# =============================
# 1. Configuração da página
# =============================
st.set_page_config(
    page_title="CETCOM | Operações",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
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
    .nota-tecnica {font-size: 0.85rem; opacity: 0.75;}
    </style>
    """,
    unsafe_allow_html=True,
)


def obter_segredo(nome: str, padrao: str = "") -> str:
    """Busca segredo no Streamlit Cloud ou em variável de ambiente local."""
    try:
        valor = st.secrets.get(nome, None)
        if valor:
            return str(valor)
    except Exception:
        pass
    return os.getenv(nome, padrao)


@st.cache_data(ttl=60, show_spinner=False)
def carregar_csv(url: str) -> pd.DataFrame:
    return pd.read_csv(url, on_bad_lines="skip")


def normalizar_numero_coluna(serie: pd.Series) -> pd.Series:
    """Converte números em formatos comuns: 1234, 1.234, 1,234, 1.234,56, 1,234.56."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")

    def parse_valor(valor):
        if pd.isna(valor):
            return pd.NA
        s = str(valor).strip()
        if not s:
            return pd.NA

        s = re.sub(r"[^0-9,\.\-]", "", s)
        if s in {"", "-", ",", "."}:
            return pd.NA

        tem_virgula = "," in s
        tem_ponto = "." in s

        if tem_virgula and tem_ponto:
            # O último separador costuma indicar o decimal.
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif tem_virgula:
            parte_decimal = s.split(",")[-1]
            s = s.replace(",", "") if len(parte_decimal) == 3 else s.replace(",", ".")
        elif tem_ponto:
            parte_decimal = s.split(".")[-1]
            # Em operação, 1.234 geralmente é milhar, não decimal.
            if len(parte_decimal) == 3 and s.count(".") >= 1:
                s = s.replace(".", "")

        try:
            return float(s)
        except ValueError:
            return pd.NA

    return serie.apply(parse_valor).astype("Float64")


def colunas_numericas_convertiveis(df: pd.DataFrame) -> list[str]:
    candidatas = []
    for coluna in df.columns:
        convertida = normalizar_numero_coluna(df[coluna])
        if convertida.notna().sum() > 0:
            candidatas.append(coluna)
    return candidatas


def chave_temporal(serie: pd.Series) -> pd.Series:
    """Cria uma chave ordenável para horas/datas sem depender de comparação alfabética."""
    bruto = serie.astype(str).str.strip()

    # Prioridade 1: horas no formato 14:00, 14h00, 14H00 etc.
    partes_hora = bruto.str.extract(r"(?P<hora>\d{1,2})\s*[:hH]\s*(?P<minuto>\d{0,2})")
    hora_num = pd.to_numeric(partes_hora["hora"], errors="coerce")
    minuto_num = pd.to_numeric(partes_hora["minuto"].replace("", "0"), errors="coerce").fillna(0)
    chave_hora = hora_num * 60 + minuto_num
    if chave_hora.notna().sum() >= max(1, int(len(bruto) * 0.5)):
        return chave_hora.astype("Float64")

    # Prioridade 2: data ou data/hora.
    data = pd.to_datetime(bruto, errors="coerce", dayfirst=True)
    if data.notna().sum() >= max(1, int(len(bruto) * 0.5)):
        return data

    # Prioridade 3: valores numéricos simples, como 1, 2, 3...
    numerico = pd.to_numeric(bruto.str.replace(",", ".", regex=False), errors="coerce")
    if numerico.notna().sum() > 0:
        return numerico.astype("Float64")

    # Último recurso: ordem categórica estável.
    ordem = {valor: idx for idx, valor in enumerate(sorted(bruto.dropna().unique()))}
    return bruto.map(ordem).astype("Float64")


def detectar_indice(colunas: list[str], palavras: list[str], padrao: int = 0) -> int:
    return next((i for i, c in enumerate(colunas) if any(p in c.lower() for p in palavras)), padrao)


def encontrar_indice(colunas: list[str], palavras: list[str]) -> int | None:
    return next((i for i, c in enumerate(colunas) if any(p in c.lower() for p in palavras)), None)


def mascara_esteira_em_serie(serie: pd.Series, esteira: str, aceitar_numero_puro: bool = False) -> pd.Series:
    """
    Filtro tolerante para P1/P2/P4.
    Captura P1, P 1, P-1, P_1, P01, Esteira 1 e Pista 1, sem capturar P10.
    Quando a coluna escolhida é explicitamente de esteira, aceita também valor puro 1/2/4.
    """
    numero = esteira.upper().replace("P", "").strip()
    bruto = serie.astype(str).str.upper().str.strip()

    padrao = rf"(?<![A-Z0-9])(?:P|PISTA|ESTEIRA)\s*[-_/]?\s*0*{re.escape(numero)}(?![A-Z0-9])"
    mascara = bruto.str.contains(padrao, regex=True, na=False)

    if aceitar_numero_puro:
        normalizado = bruto.str.replace(r"\.0$", "", regex=True)
        mascara = mascara | normalizado.eq(numero)

    return mascara


def filtrar_esteira(df: pd.DataFrame, esteira: str, coluna_esteira: str) -> tuple[pd.DataFrame, dict]:
    diagnostico = {
        "esteira": esteira,
        "coluna_esteira": coluna_esteira,
        "linhas_antes": len(df),
        "linhas_coluna_escolhida": None,
        "linhas_fallback_todas_colunas": None,
        "fallback_usado": False,
    }

    if esteira == "Visão Global":
        diagnostico["linhas_depois"] = len(df)
        return df, diagnostico

    if coluna_esteira != "Buscar em todas as colunas":
        mascara_coluna = mascara_esteira_em_serie(df[coluna_esteira], esteira, aceitar_numero_puro=True)
        diagnostico["linhas_coluna_escolhida"] = int(mascara_coluna.sum())
        if mascara_coluna.any():
            resultado = df[mascara_coluna]
            diagnostico["linhas_depois"] = len(resultado)
            return resultado, diagnostico

        # Blindagem: se a coluna escolhida não encontrou nada, tenta todas as colunas antes de matar a base.
        diagnostico["fallback_usado"] = True

    mascara_todas = df.apply(
        lambda linha: mascara_esteira_em_serie(linha, esteira, aceitar_numero_puro=False).any(),
        axis=1,
    )
    diagnostico["linhas_fallback_todas_colunas"] = int(mascara_todas.sum())
    resultado = df[mascara_todas]
    diagnostico["linhas_depois"] = len(resultado)
    return resultado, diagnostico


def painel_diagnostico_filtros(
    df_original: pd.DataFrame,
    df_com_volume: pd.DataFrame,
    df_pos_esteira: pd.DataFrame,
    df_pos_tempo: pd.DataFrame,
    eixo_y: str,
    coluna_hora: str,
    coluna_esteira: str,
    diagnostico_esteira: dict,
):
    with st.expander("Abrir diagnóstico técnico dos filtros", expanded=True):
        st.write(
            {
                "linhas_base_original": len(df_original),
                "linhas_com_volume_numerico": len(df_com_volume),
                "linhas_apos_filtro_esteira": len(df_pos_esteira),
                "linhas_apos_filtro_tempo": len(df_pos_tempo),
                "coluna_volume": eixo_y,
                "coluna_hora": coluna_hora,
                "coluna_esteira": coluna_esteira,
                "diagnostico_esteira": diagnostico_esteira,
            }
        )

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Amostra da coluna de tempo**")
            st.dataframe(df_original[[coluna_hora]].drop_duplicates().head(30), use_container_width=True, hide_index=True)
        with col_b:
            st.markdown("**Amostra da coluna de esteira selecionada**")
            if coluna_esteira != "Buscar em todas as colunas":
                st.dataframe(df_original[[coluna_esteira]].drop_duplicates().head(30), use_container_width=True, hide_index=True)
            else:
                st.info("Filtro de esteira configurado para buscar em todas as colunas.")

        st.markdown("**Amostra da base carregada**")
        st.dataframe(df_original.head(20), use_container_width=True, hide_index=True)


# =============================
# 2. Cabeçalho
# =============================
col_titulo, col_assinatura = st.columns([3.5, 1.5])
with col_titulo:
    st.title("⚡ CETCOM: Inteligência de Throughput & SLA")
    st.markdown("Monitoramento Ativo de Esteiras, Gargalos e Projeção de Turno")
with col_assinatura:
    st.markdown(
        """
        <div class='assinatura-lideranca'>
            Responsável Operacional:<br>
            <span class='destaque-nome'>Jonathas Louback Pereira Silva</span><br>
            <i>Gestão de Throughput & Performance</i>
        </div>
        """,
        unsafe_allow_html=True,
    )
st.divider()


# =============================
# 3. Entrada de dados
# =============================
with st.sidebar:
    st.header("⚙️ Conexão de Dados")
    csv_url = st.text_input("Link da Base (CSV):", placeholder="Cole o link publicado em CSV aqui")

if not csv_url:
    st.info("Aguardando inserção da URL CSV no painel lateral para levantar o CETCOM.")
    st.stop()

try:
    df = carregar_csv(csv_url)
except Exception as e:
    st.error(f"Falha de conexão com a base. Erro: {e}")
    st.stop()

if df.empty:
    st.error("A base carregou vazia. Verifique se o link CSV está publicado corretamente.")
    st.stop()

df.columns = [str(c).strip() for c in df.columns]
colunas = df.columns.tolist()
colunas_volume = colunas_numericas_convertiveis(df)

if not colunas or not colunas_volume:
    st.error("A base precisa ter pelo menos uma coluna válida e uma coluna de volume convertível para número.")
    st.stop()


# =============================
# 4. Sidebar: mapeamento e filtros
# =============================
with st.sidebar:
    st.markdown("---")
    st.subheader("📊 Mapeamento de Eixos")

    idx_nome = detectar_indice(colunas, ["nome", "operador", "colaborador", "id", "matricula", "matrícula"])
    idx_hora = detectar_indice(colunas, ["hora", "horário", "horario", "data", "time"])
    idx_volume = detectar_indice(colunas_volume, ["volume", "pacote", "qtd", "quantidade", "bip", "total"])
    idx_esteira_detectado = encontrar_indice(colunas, ["esteira", "pista", "linha", "posto", "processo", "stage"])

    eixo_x = st.selectbox("Operador/ID (Eixo X):", colunas, index=idx_nome)
    eixo_y = st.selectbox("Volume (Eixo Y):", colunas_volume, index=min(idx_volume, len(colunas_volume) - 1))
    coluna_hora = st.selectbox("Referência de Tempo (Hora):", colunas, index=idx_hora)

    opcoes_coluna_esteira = ["Buscar em todas as colunas"] + colunas
    coluna_esteira = st.selectbox(
        "Coluna para filtro de Esteira:",
        opcoes_coluna_esteira,
        index=(idx_esteira_detectado + 1) if idx_esteira_detectado is not None else 0,
        help="Se o filtro P1/P2/P4 zerar a base, deixe em 'Buscar em todas as colunas' ou selecione a coluna real da esteira.",
    )

    st.markdown("---")
    st.subheader("⏱️ Filtro Temporal")

    tempo_tmp = pd.DataFrame(
        {
            "rotulo": df[coluna_hora].astype(str).str.strip(),
            "chave": chave_temporal(df[coluna_hora]),
        }
    )
    tempo_tmp = tempo_tmp[(tempo_tmp["rotulo"] != "") & (tempo_tmp["rotulo"].str.lower() != "nan")]
    tempo_tmp = tempo_tmp.dropna(subset=["chave"]).drop_duplicates(subset=["rotulo"]).sort_values(["chave", "rotulo"])

    lista_horas = tempo_tmp["rotulo"].tolist()
    mapa_horas = dict(zip(tempo_tmp["rotulo"], tempo_tmp["chave"]))

    if not lista_horas:
        st.warning("A coluna de tempo selecionada não gerou valores válidos. A visão ficará sem filtro temporal.")
        hora_selecionada = "Visão Completa do Turno"
    else:
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
    visualizacao_filtro = st.radio("Desempenho:", ["Headcount Total", "Top 5 (Performers)", "Bottom 5 (Ofensores)"])


# =============================
# 5. Motor de filtragem corrigido
# =============================
df_base = df.copy()
df_base["_volume_num"] = normalizar_numero_coluna(df_base[eixo_y])
df_base["_tempo_rotulo"] = df_base[coluna_hora].astype(str).str.strip()
df_base["_tempo_chave"] = chave_temporal(df_base[coluna_hora])
df_base = df_base.dropna(subset=["_volume_num"])

# 5.1 Filtro de esteira
df_pos_esteira, diagnostico_esteira = filtrar_esteira(df_base, esteira_filtro, coluna_esteira)

if df_pos_esteira.empty:
    st.error("Nenhum volume encontrado após o filtro de esteira.")
    painel_diagnostico_filtros(
        df_original=df,
        df_com_volume=df_base,
        df_pos_esteira=df_pos_esteira,
        df_pos_tempo=df_pos_esteira,
        eixo_y=eixo_y,
        coluna_hora=coluna_hora,
        coluna_esteira=coluna_esteira,
        diagnostico_esteira=diagnostico_esteira,
    )
    st.stop()

# 5.2 Filtro temporal
df_filtrado_linhas = df_pos_esteira.copy()
if hora_selecionada != "Visão Completa do Turno" and hora_selecionada in mapa_horas:
    chave_selecionada = mapa_horas[hora_selecionada]
    if modo_tempo == "Hora Isolada (Apenas esta hora)":
        df_filtrado_linhas = df_filtrado_linhas[df_filtrado_linhas["_tempo_rotulo"] == hora_selecionada]
    else:
        df_filtrado_linhas = df_filtrado_linhas[df_filtrado_linhas["_tempo_chave"] <= chave_selecionada]

if df_filtrado_linhas.empty:
    st.error("Nenhum volume encontrado após o filtro temporal.")
    painel_diagnostico_filtros(
        df_original=df,
        df_com_volume=df_base,
        df_pos_esteira=df_pos_esteira,
        df_pos_tempo=df_filtrado_linhas,
        eixo_y=eixo_y,
        coluna_hora=coluna_hora,
        coluna_esteira=coluna_esteira,
        diagnostico_esteira=diagnostico_esteira,
    )
    st.stop()

# Agregado completo: alimenta os cards e o parecer coletivo.
df_agregado_total = (
    df_filtrado_linhas.groupby(eixo_x, dropna=False, as_index=False)["_volume_num"]
    .sum()
    .sort_values(by="_volume_num", ascending=False)
)

df_agregado_total[eixo_x] = df_agregado_total[eixo_x].astype(str)

# Recorte de exibição: alimenta gráfico e tabela. Não contamina o volume coletivo.
df_exibicao = df_agregado_total.copy()
if visualizacao_filtro == "Top 5 (Performers)":
    df_exibicao = df_exibicao.head(5)
elif visualizacao_filtro == "Bottom 5 (Ofensores)":
    df_exibicao = df_exibicao.tail(5).sort_values(by="_volume_num", ascending=True)

if df_exibicao.empty:
    st.warning("O recorte visual selecionado não possui dados.")
    st.stop()


# =============================
# 6. SLA e indicadores
# =============================
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

visao_hora_isolada = hora_selecionada != "Visão Completa do Turno" and modo_tempo == "Hora Isolada (Apenas esta hora)"
if visao_hora_isolada:
    multiplicador_meta = 1
    periodo_meta_label = "1H"
else:
    multiplicador_meta = horas_decorridas
    periodo_meta_label = f"{horas_decorridas}H"

meta_individual_aplicada = meta_ind_ativa * multiplicador_meta
meta_coletiva_proporcional = meta_col_ativa * multiplicador_meta

headcount_total = len(df_agregado_total)
headcount_exibido = len(df_exibicao)
vol_realizado = df_agregado_total["_volume_num"].sum()
vol_exibido = df_exibicao["_volume_num"].sum()

meta_coletiva_final = meta_col_ativa * horas_turno
delta_proporcional = vol_realizado - meta_coletiva_proporcional
pace_percentual = (vol_realizado / meta_coletiva_proporcional) * 100 if meta_coletiva_proporcional > 0 else 0

horas_restantes = max(horas_turno - horas_decorridas, 0)
gap_fim_turno = meta_coletiva_final - vol_realizado
run_rate_exigido = gap_fim_turno / horas_restantes if horas_restantes > 0 and gap_fim_turno > 0 else 0

referencia_visao = "Acumulado" if not visao_hora_isolada else "Isolado"
st.subheader(f"Status: {esteira_filtro} | Referência: {hora_selecionada} ({referencia_visao})")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Volume Produzido", f"{vol_realizado:,.0f}", f"{delta_proporcional:,.0f} vs Exigência")
col2.metric(f"Meta Esteira ({periodo_meta_label})", f"{meta_coletiva_proporcional:,.0f}")
col3.metric("Pace da Esteira", f"{pace_percentual:.1f}%", "Fluxo Saudável" if pace_percentual >= 100 else "Fluxo Comprometido")
col4.metric("HC Filtrado", f"{headcount_total}", f"Exibidos: {headcount_exibido}")

if gap_fim_turno <= 0:
    col5.metric("Run Rate Exigido", "SLA Garantido", "0/h")
else:
    col5.metric("Run Rate p/ Salvar Turno", f"{run_rate_exigido:,.0f} unid/h", f"Déficit: {gap_fim_turno:,.0f}")

st.markdown(
    "<div class='nota-tecnica'>Cards executivos usam todo o headcount filtrado. Top/Bottom altera apenas gráfico, tabela e recorte tático.</div>",
    unsafe_allow_html=True,
)

st.divider()


# =============================
# 7. Gráfico e tabela
# =============================
col_grafico, col_tabela = st.columns([1.8, 1])

with col_grafico:
    st.subheader(f"Throughput Individual vs Linha de Corte ({meta_individual_aplicada:,.0f} unid)")
    cores = ["#00B46E" if val >= meta_individual_aplicada else "#EE4D2D" for val in df_exibicao["_volume_num"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df_exibicao[eixo_x],
            y=df_exibicao["_volume_num"],
            marker_color=cores,
            text=df_exibicao["_volume_num"].round(0).astype(int),
            textposition="outside",
            textfont=dict(size=14, color="white"),
        )
    )
    fig.add_hline(
        y=meta_individual_aplicada,
        line_dash="dot",
        line_color="white",
        annotation_text=f"Corte Individual ({meta_individual_aplicada:,.0f})",
        annotation_position="top right",
        annotation_font=dict(color="white"),
    )
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=20, t=30, b=80),
        xaxis_title=None,
        yaxis_title="Unidades",
        showlegend=False,
        height=550,
    )
    st.plotly_chart(fig, use_container_width=True)

with col_tabela:
    st.subheader("Matriz de Performance")
    df_tabela = df_exibicao.rename(columns={"_volume_num": eixo_y}).copy()

    def colorir_tabela(val):
        if isinstance(val, (int, float)):
            return f'color: {"#00B46E" if val >= meta_individual_aplicada else "#EE4D2D"}; font-weight: bold;'
        return ""

    st.dataframe(
        df_tabela.style.map(colorir_tabela, subset=[eixo_y]),
        use_container_width=True,
        height=550,
        hide_index=True,
    )

st.divider()


# =============================
# 8. Parecer AI
# =============================
st.subheader("Parecer Diretivo (AI Insights)")
api_key = obter_segredo("GEMINI_API_KEY")

if not api_key:
    st.info("Para ativar o parecer de IA, cadastre GEMINI_API_KEY nos Secrets do Streamlit Cloud ou como variável de ambiente.")
else:
    if st.button("Gerar Análise de Liderança", type="primary"):
        with st.spinner("Analisando gargalos do CETCOM..."):
            genai.configure(api_key=api_key)
            modelo_alvo = "gemini-1.5-flash"
            try:
                modelos = genai.list_models()
                for m in modelos:
                    if "generateContent" in m.supported_generation_methods:
                        modelo_alvo = m.name
                        if "flash" in m.name:
                            break

                model = genai.GenerativeModel(modelo_alvo)
                prompt_cetcom = f"""
                Atue como Diretor do CETCOM (Centro de Controle Operacional).

                CENÁRIO COLETIVO:
                - Esteira analisada: {esteira_filtro}
                - Referência temporal: {hora_selecionada} | {referencia_visao}
                - Meta coletiva proporcional: {meta_coletiva_proporcional:.0f} unidades
                - Volume realizado total: {vol_realizado:.0f} unidades
                - Pace da esteira: {pace_percentual:.1f}%
                - Volume faltante para o turno: {gap_fim_turno:.0f}
                - Run Rate exigido para salvar turno: {run_rate_exigido:.1f}/h
                - Headcount filtrado: {headcount_total}

                CENÁRIO INDIVIDUAL:
                - Meta individual de corte: {meta_individual_aplicada:.0f}
                - Volume do recorte visual: {vol_exibido:.0f}
                - Headcount exibido no recorte: {headcount_exibido}

                DADOS INDIVIDUAIS DO RECORTE:
                {df_exibicao[[eixo_x, "_volume_num"]].to_string(index=False)}

                Gere relatório C-Level em 3 bullets curtos:
                1. Diagnóstico do pace coletivo.
                2. Avaliação individual: quem sustenta e quem compromete.
                3. Ação tática imediata.

                Tom executivo, direto e agressivo. Sem saudação.
                """
                st.markdown(model.generate_content(prompt_cetcom).text)
            except Exception as e:
                st.error(f"Erro no motor da IA: {e}")
