import os
import re
import unicodedata
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ==========================================================
# CETCOM | Operações - Versão v3
# Correções centrais:
# 1) Filtro de esteira compatível com base longa e base larga.
# 2) Top/Bottom não contamina cards executivos.
# 3) Filtro temporal usa chave ordenável, não comparação textual.
# 4) IA migrada para Google GenAI SDK via secrets/env.
# 5) Prompt de parecer mais operacional, menos genérico.
# ==========================================================

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
    [data-testid="stMetricValue"] {font-size: 2.35rem; font-weight: 800; color: #f8f9fa;}
    [data-testid="stMetricDelta"] {font-size: 1.05rem; font-weight: 600;}
    h1, h2, h3 {font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;}
    .assinatura-lideranca {text-align: right; color: #f8f9fa; font-size: 0.9rem; font-weight: 500; margin-top: 1.5rem; line-height: 1.4;}
    .destaque-nome {color: #EE4D2D; font-weight: 700; font-size: 1rem;}
    .nota-tecnica {font-size: 0.84rem; opacity: 0.72;}
    .alerta-filtro {border-left: 4px solid #EE4D2D; padding-left: 0.8rem; opacity: 0.92;}
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================
# Funções utilitárias
# =============================
def normalizar_texto(valor: Any) -> str:
    """Normaliza texto para comparação robusta: sem acento, caixa alta, espaço limpo."""
    if pd.isna(valor):
        return ""
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"\s+", " ", texto)
    return texto


def limpar_nome_coluna(coluna: Any) -> str:
    texto = normalizar_texto(coluna)
    return re.sub(r"[^A-Z0-9]", "", texto)


def obter_segredo(nome: str, padrao: str = "") -> str:
    """Busca segredo no Streamlit Cloud, no secrets.toml local ou em variável de ambiente."""
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

    def parse_valor(valor: Any) -> Any:
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
            # Último separador tende a representar decimal.
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif tem_virgula:
            parte_decimal = s.split(",")[-1]
            s = s.replace(",", "") if len(parte_decimal) == 3 else s.replace(",", ".")
        elif tem_ponto:
            parte_decimal = s.split(".")[-1]
            # Em bases operacionais brasileiras, 1.234 costuma ser milhar.
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
    """Cria chave ordenável para horas/datas sem depender de ordem alfabética."""
    bruto = serie.astype(str).str.strip()

    # 14:00, 14h00, 14H, 14 h 30 etc.
    partes_hora = bruto.str.extract(r"(?P<hora>\d{1,2})\s*[:hH]\s*(?P<minuto>\d{0,2})")
    hora_num = pd.to_numeric(partes_hora["hora"], errors="coerce")
    minuto_num = pd.to_numeric(partes_hora["minuto"].replace("", "0"), errors="coerce").fillna(0)
    chave_hora = hora_num * 60 + minuto_num
    if chave_hora.notna().sum() >= max(1, int(len(bruto) * 0.5)):
        return chave_hora.astype("Float64")

    # Data ou data/hora.
    data = pd.to_datetime(bruto, errors="coerce", dayfirst=True)
    if data.notna().sum() >= max(1, int(len(bruto) * 0.5)):
        return data

    # Valores 1, 2, 3 ou 1.0, 2.0 etc.
    numerico = pd.to_numeric(bruto.str.replace(",", ".", regex=False), errors="coerce")
    if numerico.notna().sum() > 0:
        return numerico.astype("Float64")

    # Último recurso: ordem categórica estável.
    ordem = {valor: idx for idx, valor in enumerate(sorted(bruto.dropna().unique()))}
    return bruto.map(ordem).astype("Float64")


def detectar_indice(colunas: list[str], palavras: list[str], padrao: int = 0) -> int:
    return next((i for i, c in enumerate(colunas) if any(p in normalizar_texto(c).lower() for p in palavras)), padrao)


def encontrar_indice(colunas: list[str], palavras: list[str]) -> int | None:
    return next((i for i, c in enumerate(colunas) if any(p in normalizar_texto(c).lower() for p in palavras)), None)


def encontrar_coluna_volume_esteira(colunas_volume: list[str], esteira: str) -> str | None:
    """Detecta coluna de volume por esteira em base larga: P4, VOL P4, ESTEIRA 4, PISTA 4 etc."""
    numero = esteira.upper().replace("P", "")
    melhor: tuple[int, str] | None = None

    for coluna in colunas_volume:
        norm_col = limpar_nome_coluna(coluna)
        texto = normalizar_texto(coluna)
        score = 0

        if norm_col in {f"P{numero}", f"P0{numero}"}:
            score = 100
        elif re.search(rf"(^|[^A-Z0-9])P\s*[-_/]?\s*0?{numero}($|[^A-Z0-9])", texto):
            score = 95
        elif any(prefixo in norm_col for prefixo in ["ESTEIRA", "PISTA", "LINHA", "PROCESSO", "STAGE"]) and re.search(rf"0?{numero}", norm_col):
            score = 82
        elif f"P{numero}" in norm_col and any(k in norm_col for k in ["VOL", "VOLUME", "QTD", "PACOTE", "BIP", "TOTAL"]):
            score = 78

        if score and (melhor is None or score > melhor[0]):
            melhor = (score, coluna)

    return melhor[1] if melhor else None


def valor_corresponde_esteira(valor: Any, esteira: str, aceitar_numero_puro: bool = False) -> bool:
    """Compara valores de uma coluna de esteira sem capturar P40/P14 etc."""
    numero = esteira.upper().replace("P", "").strip()
    texto = normalizar_texto(valor)
    if not texto:
        return False

    texto_sem_ponto_zero = re.sub(r"\.0$", "", texto)
    if aceitar_numero_puro and texto_sem_ponto_zero == numero:
        return True

    padroes = [
        rf"(^|[^A-Z0-9])P\s*[-_/]?\s*0*{re.escape(numero)}($|[^A-Z0-9])",
        rf"(^|[^A-Z0-9])PISTA\s*[-_/]?\s*0*{re.escape(numero)}($|[^A-Z0-9])",
        rf"(^|[^A-Z0-9])ESTEIRA\s*[-_/]?\s*0*{re.escape(numero)}($|[^A-Z0-9])",
        rf"(^|[^A-Z0-9])LINHA\s*[-_/]?\s*0*{re.escape(numero)}($|[^A-Z0-9])",
        rf"(^|[^A-Z0-9])PROCESSO\s*[-_/]?\s*0*{re.escape(numero)}($|[^A-Z0-9])",
        rf"(^|[^A-Z0-9])STAGE\s*[-_/]?\s*0*{re.escape(numero)}($|[^A-Z0-9])",
    ]
    return any(re.search(padrao, texto) for padrao in padroes)


def colunas_candidatas_esteira(df: pd.DataFrame, eixo_x: str, eixo_y: str) -> list[str]:
    palavras = ["esteira", "pista", "linha", "processo", "stage", "posto", "area", "área", "setor", "origem", "destino"]
    candidatas = []
    for coluna in df.columns:
        if coluna in {eixo_x, eixo_y}:
            continue
        nome = normalizar_texto(coluna).lower()
        if any(p in nome for p in palavras):
            candidatas.append(coluna)
    return candidatas


def filtrar_por_coluna_esteira(df: pd.DataFrame, esteira: str, coluna_esteira: str, eixo_x: str, eixo_y: str) -> tuple[pd.DataFrame, dict]:
    diagnostico = {
        "modo_filtro": "base_longa_coluna_esteira",
        "esteira": esteira,
        "coluna_esteira": coluna_esteira,
        "linhas_antes": len(df),
        "linhas_match_coluna": None,
        "linhas_match_candidatas": None,
        "fallback_candidatas_usado": False,
        "colunas_candidatas_fallback": [],
    }

    if esteira == "Visão Global":
        diagnostico["linhas_depois"] = len(df)
        return df, diagnostico

    if coluna_esteira != "Detectar automaticamente":
        mascara = df[coluna_esteira].apply(lambda valor: valor_corresponde_esteira(valor, esteira, aceitar_numero_puro=True))
        diagnostico["linhas_match_coluna"] = int(mascara.sum())
        resultado = df[mascara]
        diagnostico["linhas_depois"] = len(resultado)
        return resultado, diagnostico

    candidatas = colunas_candidatas_esteira(df, eixo_x=eixo_x, eixo_y=eixo_y)
    diagnostico["colunas_candidatas_fallback"] = candidatas
    diagnostico["fallback_candidatas_usado"] = True

    if not candidatas:
        diagnostico["linhas_match_candidatas"] = 0
        diagnostico["linhas_depois"] = 0
        return df.iloc[0:0].copy(), diagnostico

    mascara_final = pd.Series(False, index=df.index)
    for coluna in candidatas:
        mascara_final = mascara_final | df[coluna].apply(lambda valor: valor_corresponde_esteira(valor, esteira, aceitar_numero_puro=True))

    diagnostico["linhas_match_candidatas"] = int(mascara_final.sum())
    resultado = df[mascara_final]
    diagnostico["linhas_depois"] = len(resultado)
    return resultado, diagnostico


def aplicar_filtro_temporal(df: pd.DataFrame, hora_selecionada: str, modo_tempo: str, mapa_horas: dict) -> pd.DataFrame:
    if hora_selecionada == "Visão Completa do Turno" or hora_selecionada not in mapa_horas:
        return df

    if modo_tempo == "Hora Isolada (Apenas esta hora)":
        return df[df["_tempo_rotulo"] == hora_selecionada]

    chave_selecionada = mapa_horas[hora_selecionada]
    return df[df["_tempo_chave"] <= chave_selecionada]


def montar_prompt_parecer(
    *,
    esteira_filtro: str,
    hora_selecionada: str,
    referencia_visao: str,
    meta_coletiva_proporcional: float,
    vol_realizado: float,
    delta_proporcional: float,
    pace_percentual: float,
    meta_coletiva_final: float,
    gap_fim_turno: float,
    run_rate_exigido: float,
    horas_restantes: float,
    meta_individual_aplicada: float,
    headcount_total: int,
    media_individual: float,
    mediana_individual: float,
    qtd_acima_corte: int,
    qtd_abaixo_corte: int,
    top_df: pd.DataFrame,
    bottom_df: pd.DataFrame,
    eixo_x: str,
) -> str:
    top_txt = top_df[[eixo_x, "_volume_num"]].rename(columns={"_volume_num": "volume"}).to_string(index=False)
    bottom_txt = bottom_df[[eixo_x, "_volume_num"]].rename(columns={"_volume_num": "volume"}).to_string(index=False)

    sinal = "acima" if delta_proporcional >= 0 else "abaixo"

    return f"""
Você é o Diretor do CETCOM (Centro de Controle Operacional) em uma operação logística de alto volume.
Seu papel é entregar um parecer executivo para liderança operacional, sem floreio e sem inventar fatos fora dos dados.

REGRAS DE SAÍDA:
- Responda em português do Brasil.
- Sem saudação.
- Máximo de 170 palavras.
- Use tom executivo, firme e operacional.
- Diferencie claramente desempenho coletivo da esteira e desempenho individual.
- Não invente causa operacional que não esteja nos dados. Se precisar inferir, use a palavra "sugere".
- Cite nomes/IDs exatamente como aparecem nas tabelas.
- Se o coletivo estiver abaixo de 100%, trate como risco de SLA. Se estiver acima, trate como sustentação de ritmo.
- Não use termos infantis. Não use motivacional genérico.

CENÁRIO COLETIVO:
- Esteira analisada: {esteira_filtro}
- Recorte temporal: {hora_selecionada} | {referencia_visao}
- Meta proporcional da esteira: {meta_coletiva_proporcional:.0f} unidades
- Volume realizado: {vol_realizado:.0f} unidades
- Delta vs meta proporcional: {delta_proporcional:.0f} unidades {sinal} da exigência
- Pace coletivo: {pace_percentual:.1f}%
- Meta final do turno: {meta_coletiva_final:.0f} unidades
- Gap para fim do turno: {gap_fim_turno:.0f} unidades
- Horas restantes consideradas: {horas_restantes:.1f}
- Run rate exigido para salvar o turno: {run_rate_exigido:.1f} unid/h

CENÁRIO INDIVIDUAL:
- Headcount filtrado: {headcount_total}
- Corte individual aplicado: {meta_individual_aplicada:.0f} unidades
- Média individual: {media_individual:.1f} unidades
- Mediana individual: {mediana_individual:.1f} unidades
- Acima do corte: {qtd_acima_corte}
- Abaixo do corte: {qtd_abaixo_corte}

TOP SUSTENTADORES:
{top_txt}

BOTTOM OFENSORES:
{bottom_txt}

FORMATO OBRIGATÓRIO:
1. **Diagnóstico coletivo:** uma frase objetiva sobre o pace e risco de SLA.
2. **Mapa individual:** destaque quem sustenta e quem compromete o resultado.
3. **Ordem tática:** ação imediata em campo, com foco em remanejamento, coaching de ofensores ou preservação dos sustentadores.
""".strip()


def gerar_parecer_ia(prompt: str, api_key: str, modelo: str) -> str:
    try:
        from google import genai  # type: ignore
    except Exception as exc:
        raise RuntimeError("Biblioteca google-genai não instalada. Inclua google-genai no requirements.txt.") from exc

    client = genai.Client(api_key=api_key)
    resposta = client.models.generate_content(model=modelo, contents=prompt)
    texto = getattr(resposta, "text", None)
    if not texto:
        raise RuntimeError("A IA respondeu sem texto. Verifique modelo, chave e cota da API.")
    return texto


def exibir_diagnostico_filtros(
    *,
    df_original: pd.DataFrame,
    df_base: pd.DataFrame,
    df_pos_esteira: pd.DataFrame,
    df_pos_tempo: pd.DataFrame,
    diagnostico_esteira: dict,
    eixo_x: str,
    eixo_y: str,
    coluna_hora: str,
    coluna_esteira: str,
    volume_ativo_label: str,
):
    with st.expander("Diagnóstico técnico dos filtros", expanded=False):
        st.write(
            {
                "linhas_base_original": len(df_original),
                "linhas_com_volume_valido": len(df_base),
                "linhas_apos_filtro_esteira": len(df_pos_esteira),
                "linhas_apos_filtro_tempo": len(df_pos_tempo),
                "eixo_x": eixo_x,
                "volume_ativo": volume_ativo_label,
                "coluna_volume_original": eixo_y,
                "coluna_hora": coluna_hora,
                "coluna_esteira": coluna_esteira,
                "diagnostico_esteira": diagnostico_esteira,
            }
        )

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown("**Amostra do eixo X**")
            st.dataframe(df_original[[eixo_x]].drop_duplicates().head(30), use_container_width=True, hide_index=True)
        with col_b:
            st.markdown("**Amostra do tempo**")
            st.dataframe(df_original[[coluna_hora]].drop_duplicates().head(30), use_container_width=True, hide_index=True)
        with col_c:
            st.markdown("**Amostra da esteira**")
            if coluna_esteira != "Detectar automaticamente":
                st.dataframe(df_original[[coluna_esteira]].drop_duplicates().head(30), use_container_width=True, hide_index=True)
            else:
                st.info("Esteira em detecção automática. O app usa apenas colunas candidatas, não nomes/IDs.")

        st.markdown("**Amostra final após filtros**")
        st.dataframe(df_pos_tempo.head(25), use_container_width=True, hide_index=True)


# =============================
# Cabeçalho
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
# Entrada de dados
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
# Sidebar: mapeamento
# =============================
with st.sidebar:
    st.markdown("---")
    st.subheader("📊 Mapeamento de Eixos")

    idx_nome = detectar_indice(colunas, ["nome", "operador", "colaborador", "id", "matricula", "matrícula"])
    idx_hora = detectar_indice(colunas, ["hora", "horario", "horário", "data", "time"])
    idx_volume = detectar_indice(colunas_volume, ["volume", "pacote", "qtd", "quantidade", "bip", "total"])
    idx_esteira_detectado = encontrar_indice(colunas, ["esteira", "pista", "linha", "processo", "stage", "posto", "setor", "area", "área"])

    eixo_x = st.selectbox("Operador/ID (Eixo X):", colunas, index=min(idx_nome, len(colunas) - 1))
    eixo_y = st.selectbox("Volume padrão (quando base longa/global):", colunas_volume, index=min(idx_volume, len(colunas_volume) - 1))
    coluna_hora = st.selectbox("Referência de Tempo (Hora):", colunas, index=min(idx_hora, len(colunas) - 1))

    st.markdown("---")
    st.subheader("🧭 Modelo da Base")
    modelo_base = st.radio(
        "Estrutura dos dados:",
        [
            "Automático",
            "Base longa: uma coluna indica P1/P2/P4",
            "Base larga: P1/P2/P4 são colunas de volume",
        ],
        help=(
            "Base longa: existe uma coluna com o valor P1/P2/P4. "
            "Base larga: existem colunas de volume separadas para P1, P2 e P4."
        ),
    )

    opcoes_coluna_esteira = ["Detectar automaticamente"] + colunas
    coluna_esteira = st.selectbox(
        "Coluna da Esteira / Pista / Processo:",
        opcoes_coluna_esteira,
        index=(idx_esteira_detectado + 1) if idx_esteira_detectado is not None else 0,
        help="Use a coluna onde aparece P1, P2 ou P4. Se não souber, deixe automático.",
    )

    auto_p1 = encontrar_coluna_volume_esteira(colunas_volume, "P1")
    auto_p2 = encontrar_coluna_volume_esteira(colunas_volume, "P2")
    auto_p4 = encontrar_coluna_volume_esteira(colunas_volume, "P4")
    opcoes_volume_esteira = ["Não usar"] + colunas_volume

    with st.expander("Mapeamento de volume por esteira (base larga)", expanded=modelo_base == "Base larga: P1/P2/P4 são colunas de volume"):
        col_volume_p1 = st.selectbox("Volume P1:", opcoes_volume_esteira, index=(opcoes_volume_esteira.index(auto_p1) if auto_p1 in opcoes_volume_esteira else 0))
        col_volume_p2 = st.selectbox("Volume P2:", opcoes_volume_esteira, index=(opcoes_volume_esteira.index(auto_p2) if auto_p2 in opcoes_volume_esteira else 0))
        col_volume_p4 = st.selectbox("Volume P4:", opcoes_volume_esteira, index=(opcoes_volume_esteira.index(auto_p4) if auto_p4 in opcoes_volume_esteira else 0))

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
    ocultar_zerados = st.checkbox("Ocultar nomes/IDs com volume zero", value=True)

    st.markdown("---")
    st.subheader("🤖 IA")
    modelo_ia = st.selectbox("Modelo Gemini:", ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"], index=0)


# =============================
# Motor de filtragem v3
# =============================
mapa_colunas_largas = {
    "P1": None if col_volume_p1 == "Não usar" else col_volume_p1,
    "P2": None if col_volume_p2 == "Não usar" else col_volume_p2,
    "P4": None if col_volume_p4 == "Não usar" else col_volume_p4,
}

# Decide automaticamente se vai usar base larga.
coluna_larga_ativa = mapa_colunas_largas.get(esteira_filtro) if esteira_filtro != "Visão Global" else None
tem_mapeamento_largo = any(mapa_colunas_largas.values())

usar_base_larga = False
if modelo_base == "Base larga: P1/P2/P4 são colunas de volume":
    usar_base_larga = True
elif modelo_base == "Automático" and ((esteira_filtro != "Visão Global" and coluna_larga_ativa) or (esteira_filtro == "Visão Global" and tem_mapeamento_largo)):
    usar_base_larga = True

# Prepara base e volume ativo.
df_base = df.copy()
df_base["_tempo_rotulo"] = df_base[coluna_hora].astype(str).str.strip()
df_base["_tempo_chave"] = chave_temporal(df_base[coluna_hora])

diagnostico_esteira: dict[str, Any]
volume_ativo_label = eixo_y

if usar_base_larga:
    diagnostico_esteira = {
        "modo_filtro": "base_larga_colunas_de_volume",
        "esteira": esteira_filtro,
        "linhas_antes": len(df_base),
        "mapa_colunas_largas": mapa_colunas_largas,
    }

    if esteira_filtro == "Visão Global":
        colunas_ativas = [c for c in mapa_colunas_largas.values() if c]
        if not colunas_ativas:
            df_base["_volume_num"] = normalizar_numero_coluna(df_base[eixo_y])
            volume_ativo_label = eixo_y
            diagnostico_esteira["fallback_volume_global"] = eixo_y
        else:
            matriz_volumes = pd.DataFrame({c: normalizar_numero_coluna(df_base[c]) for c in colunas_ativas})
            df_base["_volume_num"] = matriz_volumes.sum(axis=1, skipna=True)
            volume_ativo_label = " + ".join(colunas_ativas)
            diagnostico_esteira["colunas_volume_global"] = colunas_ativas
        df_pos_esteira = df_base
    else:
        if not coluna_larga_ativa:
            st.error(f"A esteira {esteira_filtro} está em modo base larga, mas nenhuma coluna de volume foi mapeada para ela.")
            exibir_diagnostico_filtros(
                df_original=df,
                df_base=df_base,
                df_pos_esteira=df_base.iloc[0:0].copy(),
                df_pos_tempo=df_base.iloc[0:0].copy(),
                diagnostico_esteira=diagnostico_esteira,
                eixo_x=eixo_x,
                eixo_y=eixo_y,
                coluna_hora=coluna_hora,
                coluna_esteira=coluna_esteira,
                volume_ativo_label=volume_ativo_label,
            )
            st.stop()
        df_base["_volume_num"] = normalizar_numero_coluna(df_base[coluna_larga_ativa])
        volume_ativo_label = coluna_larga_ativa
        df_pos_esteira = df_base
        diagnostico_esteira["coluna_volume_ativa"] = coluna_larga_ativa
else:
    df_base["_volume_num"] = normalizar_numero_coluna(df_base[eixo_y])
    df_pos_esteira, diagnostico_esteira = filtrar_por_coluna_esteira(
        df_base,
        esteira=esteira_filtro,
        coluna_esteira=coluna_esteira,
        eixo_x=eixo_x,
        eixo_y=eixo_y,
    )

# Remove linhas sem volume válido; opcionalmente remove volume zerado.
df_pos_esteira = df_pos_esteira.dropna(subset=["_volume_num"])
if ocultar_zerados:
    df_pos_esteira = df_pos_esteira[df_pos_esteira["_volume_num"] != 0]

diagnostico_esteira["linhas_depois_volume_valido"] = len(df_pos_esteira)

if df_pos_esteira.empty:
    st.error("Nenhum volume encontrado após o filtro de esteira/volume.")
    st.markdown(
        "<div class='alerta-filtro'>Se você selecionou P4 e aparecer vazio, verifique se a base é larga e se a coluna de volume P4 foi mapeada corretamente.</div>",
        unsafe_allow_html=True,
    )
    exibir_diagnostico_filtros(
        df_original=df,
        df_base=df_base,
        df_pos_esteira=df_pos_esteira,
        df_pos_tempo=df_pos_esteira,
        diagnostico_esteira=diagnostico_esteira,
        eixo_x=eixo_x,
        eixo_y=eixo_y,
        coluna_hora=coluna_hora,
        coluna_esteira=coluna_esteira,
        volume_ativo_label=volume_ativo_label,
    )
    st.stop()

# Filtro temporal.
df_filtrado_linhas = aplicar_filtro_temporal(df_pos_esteira.copy(), hora_selecionada, modo_tempo, mapa_horas)

if df_filtrado_linhas.empty:
    st.error("Nenhum volume encontrado após o filtro temporal.")
    exibir_diagnostico_filtros(
        df_original=df,
        df_base=df_base,
        df_pos_esteira=df_pos_esteira,
        df_pos_tempo=df_filtrado_linhas,
        diagnostico_esteira=diagnostico_esteira,
        eixo_x=eixo_x,
        eixo_y=eixo_y,
        coluna_hora=coluna_hora,
        coluna_esteira=coluna_esteira,
        volume_ativo_label=volume_ativo_label,
    )
    st.stop()

# Agregado completo: cards, SLA, IA e base estratégica.
df_agregado_total = (
    df_filtrado_linhas.groupby(eixo_x, dropna=False, as_index=False)["_volume_num"]
    .sum()
    .sort_values(by="_volume_num", ascending=False)
)
df_agregado_total[eixo_x] = df_agregado_total[eixo_x].astype(str)
if ocultar_zerados:
    df_agregado_total = df_agregado_total[df_agregado_total["_volume_num"] != 0]

if df_agregado_total.empty:
    st.error("Após a agregação por Operador/ID, não restou volume válido.")
    exibir_diagnostico_filtros(
        df_original=df,
        df_base=df_base,
        df_pos_esteira=df_pos_esteira,
        df_pos_tempo=df_filtrado_linhas,
        diagnostico_esteira=diagnostico_esteira,
        eixo_x=eixo_x,
        eixo_y=eixo_y,
        coluna_hora=coluna_hora,
        coluna_esteira=coluna_esteira,
        volume_ativo_label=volume_ativo_label,
    )
    st.stop()

# Recorte visual: não mexe nos cards.
df_exibicao = df_agregado_total.copy()
if visualizacao_filtro == "Top 5 (Performers)":
    df_exibicao = df_exibicao.head(5)
elif visualizacao_filtro == "Bottom 5 (Ofensores)":
    df_exibicao = df_exibicao.tail(5).sort_values(by="_volume_num", ascending=True)


# =============================
# SLA e indicadores
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
vol_realizado = float(df_agregado_total["_volume_num"].sum())
vol_exibido = float(df_exibicao["_volume_num"].sum())

meta_coletiva_final = meta_col_ativa * horas_turno
delta_proporcional = vol_realizado - meta_coletiva_proporcional
pace_percentual = (vol_realizado / meta_coletiva_proporcional) * 100 if meta_coletiva_proporcional > 0 else 0

horas_restantes = max(float(horas_turno - horas_decorridas), 0.0)
gap_fim_turno = meta_coletiva_final - vol_realizado
run_rate_exigido = gap_fim_turno / horas_restantes if horas_restantes > 0 and gap_fim_turno > 0 else 0

media_individual = float(df_agregado_total["_volume_num"].mean()) if headcount_total else 0.0
mediana_individual = float(df_agregado_total["_volume_num"].median()) if headcount_total else 0.0
qtd_acima_corte = int((df_agregado_total["_volume_num"] >= meta_individual_aplicada).sum())
qtd_abaixo_corte = int((df_agregado_total["_volume_num"] < meta_individual_aplicada).sum())

referencia_visao = "Acumulado" if not visao_hora_isolada else "Isolado"

# =============================
# Rendering executivo
# =============================
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
    f"<div class='nota-tecnica'>Modo de filtro: <b>{diagnostico_esteira.get('modo_filtro')}</b> | Volume ativo: <b>{volume_ativo_label}</b>. Cards executivos usam todo o headcount filtrado. Top/Bottom altera apenas gráfico, tabela e recorte visual.</div>",
    unsafe_allow_html=True,
)

exibir_diagnostico_filtros(
    df_original=df,
    df_base=df_base,
    df_pos_esteira=df_pos_esteira,
    df_pos_tempo=df_filtrado_linhas,
    diagnostico_esteira=diagnostico_esteira,
    eixo_x=eixo_x,
    eixo_y=eixo_y,
    coluna_hora=coluna_hora,
    coluna_esteira=coluna_esteira,
    volume_ativo_label=volume_ativo_label,
)

st.divider()


# =============================
# Gráfico e tabela
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
    df_tabela = df_exibicao.rename(columns={"_volume_num": "Volume"}).copy()

    def colorir_tabela(val: Any) -> str:
        if isinstance(val, (int, float)):
            return f'color: {"#00B46E" if val >= meta_individual_aplicada else "#EE4D2D"}; font-weight: bold;'
        return ""

    st.dataframe(
        df_tabela.style.map(colorir_tabela, subset=["Volume"]),
        use_container_width=True,
        height=550,
        hide_index=True,
    )

st.divider()


# =============================
# Parecer AI
# =============================
st.subheader("Parecer Diretivo (AI Insights)")
api_key = obter_segredo("GEMINI_API_KEY")

top_df = df_agregado_total.head(5).copy()
bottom_df = df_agregado_total.tail(5).sort_values(by="_volume_num", ascending=True).copy()

prompt_cetcom = montar_prompt_parecer(
    esteira_filtro=esteira_filtro,
    hora_selecionada=hora_selecionada,
    referencia_visao=referencia_visao,
    meta_coletiva_proporcional=float(meta_coletiva_proporcional),
    vol_realizado=float(vol_realizado),
    delta_proporcional=float(delta_proporcional),
    pace_percentual=float(pace_percentual),
    meta_coletiva_final=float(meta_coletiva_final),
    gap_fim_turno=float(gap_fim_turno),
    run_rate_exigido=float(run_rate_exigido),
    horas_restantes=float(horas_restantes),
    meta_individual_aplicada=float(meta_individual_aplicada),
    headcount_total=int(headcount_total),
    media_individual=float(media_individual),
    mediana_individual=float(mediana_individual),
    qtd_acima_corte=int(qtd_acima_corte),
    qtd_abaixo_corte=int(qtd_abaixo_corte),
    top_df=top_df,
    bottom_df=bottom_df,
    eixo_x=eixo_x,
)

if not api_key:
    st.info("Para ativar o parecer de IA, cadastre GEMINI_API_KEY nos Secrets do Streamlit Cloud ou como variável de ambiente local.")
else:
    if st.button("Gerar Análise de Liderança", type="primary"):
        with st.spinner("Analisando gargalos do CETCOM..."):
            try:
                parecer = gerar_parecer_ia(prompt_cetcom, api_key=api_key, modelo=modelo_ia)
                st.markdown(parecer)
            except Exception as e:
                st.error(f"Erro no motor da IA: {e}")
                st.warning("Verifique: 1) GEMINI_API_KEY nos Secrets, 2) requirements.txt com google-genai, 3) cota/modelo disponível na sua conta.")

with st.expander("Ver prompt enviado para a IA", expanded=False):
    st.code(prompt_cetcom, language="markdown")
