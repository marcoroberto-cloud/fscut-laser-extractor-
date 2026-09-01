import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

st.set_page_config(page_title="Gestão de Corte Laser FSCut", layout="wide", page_icon="⚙️")

# Controle de estado para limpar uploads
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

def limpar_arquivos():
    st.session_state.uploader_key += 1
    st.rerun()

st.title("⚙️ Gestão de Programação FSCut Laser")

# Upload e Botão Limpar
col_upload, col_btn = st.columns([5, 1])
with col_upload:
    uploaded_files = st.file_uploader(
        "Arraste ou selecione os relatórios PDF (.pdf)", 
        type=["pdf"], 
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}"
    )
with col_btn:
    st.write(" ")
    st.write(" ")
    if st.button("🗑️ Limpar Arquivos", use_container_width=True, on_click=limpar_arquivos):
        pass

def converter_tempo_para_segundos(tempo_str):
    try:
        partes = tempo_str.split(":")
        if len(partes) == 3:
            return int(partes[0]) * 3600 + int(partes[1]) * 60 + int(partes[2])
    except:
        pass
    return 0

def formatar_segundos_para_tempo(segundos):
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = int(segundos % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def processar_fscut_pdf(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        primeira_pagina = pdf.pages[0]
        texto = primeira_pagina.extract_text() or ""
        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        texto_unificado = " ".join(linhas)

    # 1. Programa CNC
    cnc_match = re.search(r"CNC\s*(\d{5,6})", texto_unificado) or re.search(r"\b(\d{5,6})\b", texto_unificado)
    cnc = cnc_match.group(1) if cnc_match else ""

    # 2. Projeto
    projeto = ""
    for i, linha in enumerate(linhas):
        if "Trabalho" in linha:
            resto = re.sub(r"^.*?Trabalho\s*", "", linha).strip()
            if resto and not any(k in resto for k in ["CNC", "Ref", "Qtde", "Obs:"]):
                projeto = resto
            elif i + 1 < len(linhas):
                projeto = linhas[i + 1].strip()
            break
    projeto = re.sub(r"^(CNC|Ref|Qtde\.|Obs:)\s*", "", projeto).strip()

    # 3. Quantidade de Chapas / Repetições
    qtd_match = re.search(r"Qtde\.\s*(\d+)", texto_unificado)
    qtd_chapas = int(qtd_match.group(1)) if qtd_match else 1

    # 4. Dimensões e Espessura
    dim_match = re.search(r"(\d+)\s*x\s*(\d+)\s*x\s*([\d\.,]+)", texto_unificado)
    comp_chapa = float(dim_match.group(1)) if dim_match else 0.0
    larg_chapa = float(dim_match.group(2)) if dim_match else 0.0
    espessura = float(dim_match.group(3).replace(",", ".")) if dim_match else 0.0

    # 5. Material com regra: SAE -> AÇO CARBONO
    mat_match = re.search(r"Material\s+([A-Za-z0-9\sÁ-Úá-ú]+?)(?=\s+Tempo|\s+X\b|\s+Y\b|\s+Aprov|$)", texto_unificado, re.IGNORECASE)
    material_raw = mat_match.group(1).strip() if mat_match else "SAE 1020"
    
    if "SAE" in material_raw.upper():
        material = "AÇO CARBONO"
    elif "ALUM" in material_raw.upper():
        material = "ALUMÍNIO"
    elif "INOX" in material_raw.upper():
        material = "AÇO INOX"
    else:
        material = material_raw.upper()

    # 6. Tempo de Corte
    tempo_match = re.search(r"Tempo total\s*[:\|]?\s*([\d:\.]+)", texto_unificado)
    tempo_unit_str = "00:00:00"
    if tempo_match:
        bruto = tempo_match.group(1).replace("::", ":").strip(":")
        partes = bruto.split(":")
        if len(partes) >= 3:
            hh = partes[0][-2:] if len(partes[0]) >= 2 else partes[0].zfill(2)
            mm = partes[1].zfill(2)
            ss = partes[2].split(".")[0].zfill(2)
            tempo_unit_str = f"{hh}:{mm}:{ss}"

    segundos_unit = converter_tempo_para_segundos(tempo_unit_str)
    segundos_totais = segundos_unit * qtd_chapas
    tempo_total_repeticoes_str = formatar_segundos_para_tempo(segundos_totais)

    # 7. Porcentagens
    aprov_match = re.search(r"Aprov\.\s*\(%\)\s*([\d\.,]+)", texto_unificado)
    ret_match = re.search(r"Ret\.\s*\(%\)\s*([\d\.,]+)", texto_unificado)
    perda_match = re.search(r"Perda\s*\(%\)\s*([\d\.,]+)", texto_unificado)

    aprov_pct = float(aprov_match.group(1).replace(",", ".")) if aprov_match else 0.0
    ret_pct = float(ret_match.group(1).replace(",", ".")) if ret_match else 0.0
    perda_pct = float(perda_match.group(1).replace(",", ".")) if perda_match else 0.0

    # 8. Pesos e Sucata
    peso_match = re.search(r"Peso Total Chapa\s*([\d\.,]+)\s*kg", texto_unificado)
    peso_unit = float(peso_match.group(1).replace(",", ".")) if peso_match else 0.0
    peso_lote = peso_unit * qtd_chapas
    sucata_kg = round(peso_lote * (perda_pct / 100.0), 3)

    # Linha Operacional
    linha_op = {
        "#CNC": cnc,
        "QUANT. REP. (CH)": qtd_chapas,
        "HORAS DE CORTE REAL": "00:00:00",
        "QUANT. FINALIZADA(CH)": "",
        "TEMPO ESTIMADO CORTE": tempo_unit_str,
        "TEMPO TOTAL (REP)": tempo_total_repeticoes_str,
        "ESPESSURA (mm)": espessura,
        "MATERIAL": material,
        "PROJETO": projeto
    }

    # Linha Analítica
    linha_metricas = {
        "CNC": cnc,
        "PROJETO": projeto,
        "Material": material,
        "Espessura (mm)": espessura,
        "Dimensões": f"{int(comp_chapa)} x {int(larg_chapa)}",
        "Qtd Chapas": qtd_chapas,
        "Tempo Unitário": tempo_unit_str,
        "Tempo Total Lote": tempo_total_repeticoes_str,
        "Segundos Totais": segundos_totais,
        "Peso Total (kg)": round(peso_lote, 3),
        "Aprov (%)": aprov_pct,
        "Retalho (%)": ret_pct,
        "Perda (%)": perda_pct,
        "Sucata (kg)": sucata_kg
    }

    return linha_op, linha_metricas

if uploaded_files:
    dados_op = []
    dados_metricas = []

    for f in uploaded_files:
        op, met = processar_fscut_pdf(f)
        dados_op.append(op)
        dados_metricas.append(met)

    df_op = pd.DataFrame(dados_op)
    df_met = pd.DataFrame(dados_metricas)

    # Seletor de Projeto
    st.markdown("---")
    projetos_unicos = ["TODOS OS PROJETOS"] + sorted(list(df_met["PROJETO"].unique()))
    projeto_selecionado = st.selectbox("🎯 Filtrar Visão do Dashboard e Relatórios:", projetos_unicos)

    if projeto_selecionado == "TODOS OS PROJETOS":
        df_met_filtrado = df_met.copy()
        df_op_filtrado = df_op.copy()
    else:
        df_met_filtrado = df_met[df_met["PROJETO"] == projeto_selecionado].copy()
        df_op_filtrado = df_op[df_op["PROJETO"] == projeto_selecionado].copy()

    # Dashboard
    st.subheader(f"📊 Indicadores de Produção — {projeto_selecionado}")

    total_chapas = int(df_met_filtrado["Qtd Chapas"].sum())
    segundos_totais_filtro = df_met_filtrado["Segundos Totais"].sum()
    tempo_formatado_total = formatar_segundos_para_tempo(segundos_totais_filtro)
    
    peso_bruto_total = df_met_filtrado["Peso Total (kg)"].sum()
    sucata_gerada_total = df_met_filtrado["Sucata (kg)"].sum()
    aprov_medio = df_met_filtrado["Aprov (%)"].mean() if not df_met_filtrado.empty else 0.0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total de Chapas", f"{total_chapas} un")
    m2.metric("Tempo Total Corte", tempo_formatado_total)
    m3.metric("Matéria-Prima Bruta", f"{peso_bruto_total:,.2f} kg")
    m4.metric("Volume Sucata", f"{sucata_gerada_total:,.2f} kg")
    m5.metric("Aproveitamento Médio", f"{aprov_medio:.1f}%")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.caption("Consumo Bruto por Material (kg)")
        resumo_peso_mat = df_met_filtrado.groupby("Material")["Peso Total (kg)"].sum()
        st.bar_chart(resumo_peso_mat)

    with col_g2:
        st.caption("Índice de Perda (%) por Programa CNC")
        chart_perda = df_met_filtrado.set_index("CNC")["Perda (%)"]
        st.bar_chart(chart_perda)

    # Tabelas e Exportação
    st.markdown("---")
    st.subheader("📋 Tabela Operacional de Fábrica")
    st.dataframe(df_op_filtrado, use_container_width=True)

    st.subheader("⚖️ Volume Consolidado por Material e Espessura")
    resumo_material = df_met_filtrado.groupby(["Material", "Espessura (mm)"]).agg({
        "Qtd Chapas": "sum",
        "Segundos Totais": "sum",
        "Peso Total (kg)": "sum",
        "Sucata (kg)": "sum",
        "Aprov (%)": "mean",
        "Perda (%)": "mean"
    }).reset_index()

    resumo_material["Tempo Total Corte"] = resumo_material["Segundos Totais"].apply(formatar_segundos_para_tempo)
    resumo_material = resumo_material.drop(columns=["Segundos Totais"])
    resumo_material = resumo_material.rename(columns={"Aprov (%)": "Aprov Médio (%)", "Perda (%)": "Perda Média (%)"})
    
    st.dataframe(resumo_material, use_container_width=True)

    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df_op_filtrado.to_excel(writer, sheet_name="Programacao_Operacional", index=False)
        df_met_filtrado.drop(columns=["Segundos Totais"]).to_excel(writer, sheet_name="Metricas_Detalhadas", index=False)
        resumo_material.to_excel(writer, sheet_name="Consumo_Material", index=False)

    st.download_button(
        label="📥 Baixar Planilha Consolidada (.xlsx)",
        data=excel_buffer.getvalue(),
        file_name=f"corte_laser_{projeto_selecionado.replace(' ', '_').lower()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
