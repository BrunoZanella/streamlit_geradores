import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import random
import json
from datetime import datetime, timedelta
import os
import aiomysql
import asyncio

# Ocultar o cabeçalho e o rodapé padrão do Streamlit
st.set_page_config(
    page_title="Monitoramento de Equipamentos",
    page_icon="🏭",
    layout="wide",
)

# CSS para remover o cabeçalho, rodapé e padding padrão do Streamlit
hide_streamlit_style = """
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {
        padding-top: 0px;
        padding-bottom: 0px;
        padding-left: 0px;
        padding-right: 0px;
    }
    .stApp {
        margin-top: -80px;
    }
    .appview-container .main .block-container {
        max-width: 100%;
        padding-top: 0rem;
        padding-right: 0rem;
        padding-left: 0rem;
        padding-bottom: 0rem;
    }
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Função para criar o gauge como HTML
def create_gauge_html(value, max_value):
    import plotly
    
    # Garantir que max_value seja pelo menos 1 para evitar divisão por zero
    max_value = max(max_value, 1)
    
    # Calcular a porcentagem
    percentage = min(100, (value / max_value) * 100)
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=value,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Equipamentos com Alerta", 'font': {'color': 'white', 'size': 14}},
        gauge={
            'axis': {'range': [None, max_value], 'tickwidth': 1, 'tickcolor': "white"},
            'bar': {'color': "#FF0000"},  # Barra de valores em vermelho
            'bgcolor': "rgba(255, 255, 255, 0.1)",
            'borderwidth': 2,
            'bordercolor': "white",
            'steps': [
                {'range': [0, max_value], 'color': 'white'}  # Fundo do gauge 100% branco

            ],
        },
        number={'font': {'color': 'white', 'size': 20}, 'suffix': f"/{max_value}"}
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=150,
        margin=dict(l=10, r=10, t=50, b=20),
    )
    
    # Converter o gráfico para HTML
    gauge_html = plotly.io.to_html(fig, include_plotlyjs=True, full_html=False)
    return gauge_html

# Função para consultar dados do MySQL
async def fetch_data_from_mysql():
    try:
        # Criar pool de conexões
        pool = await aiomysql.create_pool(
            host=st.secrets["mysql"]["host"],
            port=int(st.secrets["mysql"]["port"]),
            user=st.secrets["mysql"]["user"],
            password=st.secrets["mysql"]["password"],
            db=st.secrets["mysql"]["database"],
            minsize=int(st.secrets["mysql"]["minsize"]),
            maxsize=int(st.secrets["mysql"]["maxsize"])
        )

        # Consulta para o gauge - contagem de equipamentos com alerta=1 e cod_campo=114
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Consulta para obter a contagem de equipamentos com alerta
                query_alerta = """
                SELECT COUNT(DISTINCT cod_equipamento) as count_equipamentos_alerta
                FROM machine_learning.leituras_consecutivas 
                WHERE alerta = 1 AND cod_campo = 114
                """
                await cursor.execute(query_alerta)
                result_alerta = await cursor.fetchone()
                count_equipamentos_alerta = result_alerta[0] if result_alerta and result_alerta[0] else 0
                
                # Consulta para obter o total de equipamentos ativos (valor máximo do gauge)
                query_ativos = """
                SELECT COUNT(DISTINCT cod_equipamento) as count_equipamentos_ativos
                FROM machine_learning.leituras_consecutivas 
                WHERE cod_campo = 114 
                AND valor_5 > 0 
                AND data_cadastro >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
                """
                await cursor.execute(query_ativos)
                result_ativos = await cursor.fetchone()
                count_equipamentos_ativos = result_ativos[0] if result_ativos and result_ativos[0] else 0

                # Consulta para obter dados dos equipamentos
                query_equipamentos = """
                    SELECT 
                        lrq.cod_equipamento,
                        lrq.cod_usina,
                        lrq.data_cadastro_quebra,
                        eq.nome AS nome_equipamento,
                        us.nome AS nome_usina
                    FROM machine_learning.log_relatorio_quebras lrq
                    JOIN sup_geral.equipamentos eq ON lrq.cod_equipamento = eq.codigo
                    JOIN sup_geral.usinas us ON lrq.cod_usina = us.codigo
                    WHERE lrq.data_cadastro_previsto IS NOT NULL
                    AND DATE(lrq.data_cadastro_previsto) = CURDATE()
                    ORDER BY lrq.data_cadastro_previsto ASC;
                """
                await cursor.execute(query_equipamentos)
                equipamentos_quebras = await cursor.fetchall()

                # Consulta para obter equipamentos com alerta
                query_alertas = """
                SELECT DISTINCT lc.cod_equipamento
                FROM machine_learning.leituras_consecutivas lc
                WHERE lc.alerta = 1 AND lc.cod_campo = 114
                """
                await cursor.execute(query_alertas)
                equipamentos_alerta = [row[0] for row in await cursor.fetchall()]

                # Consulta para obter todos os equipamentos ativos
                query_todos_equipamentos = """
                SELECT DISTINCT lc.cod_equipamento, eq.nome as nome_equipamento, 
                       eq.cod_usina, us.nome as nome_usina
                FROM machine_learning.leituras_consecutivas lc
                JOIN sup_geral.equipamentos eq ON lc.cod_equipamento = eq.codigo
                JOIN sup_geral.usinas us ON eq.cod_usina = us.codigo
                WHERE lc.cod_campo = 114 
                AND lc.valor_5 > 0 
                AND lc.data_cadastro >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
                """
                await cursor.execute(query_todos_equipamentos)
                todos_equipamentos = await cursor.fetchall()

        # Fechar a pool
        pool.close()
        await pool.wait_closed()
        
        # Processar os dados dos equipamentos
        equipamentos_processados = []
        
        # Dicionário para mapear equipamentos com quebras
        equipamentos_com_quebras = {}
        for eq in equipamentos_quebras:
            equipamentos_com_quebras[eq[0]] = {
                'cod_equipamento': eq[0],
                'cod_usina': eq[1],
                'data_cadastro_quebra': eq[2],
                'nome_equipamento': eq[3],
                'nome_usina': eq[4]
            }

        # Processar todos os equipamentos ativos
        # for eq in todos_equipamentos:
        #     cod_equipamento = eq[0]
        #     nome_equipamento = eq[1]
        #     cod_usina = eq[2]
        #     nome_usina = eq[3]

        for eq in equipamentos_quebras:
            cod_equipamento = eq[0]
            cod_usina = eq[1]
            nome_usina = eq[4]
            nome_equipamento = eq[3]
            print('nome_usina',nome_usina)
                        
            # Verificar status do equipamento
            if cod_equipamento in equipamentos_com_quebras and equipamentos_com_quebras[cod_equipamento]['data_cadastro_quebra']:
                status = "Desligado com falha"
                status_class = "status-error"
            elif cod_equipamento in equipamentos_alerta:
                status = "Funcionando"
                status_class = "status-ok"
            else:
                status = "Desligado sem falha"
                status_class = "status-warning"
            
            equipamentos_processados.append({
                'cod_equipamento': cod_equipamento,
                'nome_equipamento': nome_equipamento,
                'cod_usina': cod_usina,
                'nome_usina': nome_usina,
                'status': status,
                'status_class': status_class
            })

        return {
            "count_equipamentos_alerta": count_equipamentos_alerta,
            "count_equipamentos_ativos": count_equipamentos_ativos,
            "equipamentos": equipamentos_processados
        }
    except Exception as e:
        st.error(f"Erro ao consultar o banco de dados: {e}")
        return {
            "count_equipamentos_alerta": 0,
            "count_equipamentos_ativos": 0,
            "equipamentos": []
        }

# Função para executar consultas assíncronas
def run_async(coroutine):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()

def generate_sample_data(num_rows):
    data = {
        "Código do Equipamento": [i for i in range(1, num_rows + 1)],
        "Nome do Equipamento": [f"Equipamento {i}" for i in range(1, num_rows + 1)],
        "Código da Usina": [random.randint(1, 3) for _ in range(num_rows)],
        "Nome da Usina": [f"Usina {random.randint(1, 3)}" for _ in range(num_rows)],
        "Tipo do Alerta": [random.choice(["Temperatura", "Pressão", "Vibração", "Nenhum"]) for _ in range(num_rows)],
        "Status": [random.choice(["Funcionando", "Desligado com falha", "Desligado sem falha"]) for _ in range(num_rows)],
    }
    return pd.DataFrame(data)

def generate_alarms(equipment_code, equipment_name):
    num_alarms = random.randint(0, 3)
    alarms = []
    for i in range(num_alarms):
        alarms.append(f"Alerta {i+1} para {equipment_name} ({equipment_code})")
    return alarms

def get_status_class(status):
    if status == "Funcionando":
        return "status-ok"
    elif status == "Desligado com falha":
        return "status-error"
    else:
        return "status-warning"


# Buscar dados do MySQL
mysql_data = run_async(fetch_data_from_mysql())

# Valores para o gauge (agora vem do banco de dados)
efficiency_value = mysql_data["count_equipamentos_alerta"]
max_efficiency_value = mysql_data["count_equipamentos_ativos"]

# Gerar o HTML do gauge
gauge_html = create_gauge_html(efficiency_value, max_efficiency_value)

# Preparar dados para o HTML
equipment_data = []
for eq in mysql_data["equipamentos"]:
    equipment_data.append({
        "codigo": eq["cod_equipamento"],
        "nome": eq["nome_equipamento"],
        "codigoUsina": eq["cod_usina"],
        "nomeUsina": eq["nome_usina"],
        "tipoAlerta": "Temperatura" if eq["status"] == "Funcionando" else "Nenhum",
        "status": eq["status"],
        "statusClass": eq["status_class"],
        "alarmes": generate_alarms(eq["cod_equipamento"], eq["nome_equipamento"])
    })

# # Se não houver dados reais, usar dados de exemplo
# if not equipment_data:
#     df = generate_sample_data(12)
#     for _, row in df.iterrows():
#         equipment_data.append({
#             "codigo": row["Código do Equipamento"],
#             "nome": row["Nome do Equipamento"],
#             "codigoUsina": row["Código da Usina"],
#             "nomeUsina": row["Nome da Usina"],
#             "tipoAlerta": row["Tipo do Alerta"],
#             "status": row["Status"],
#             "statusClass": get_status_class(row["Status"]),
#             "alarmes": generate_alarms(row["Código do Equipamento"], row["Nome do Equipamento"])
#         })

# Se não houver dados reais, adicionar apenas um item com traços
if not equipment_data:
    equipment_data.append({
        "codigo": "-",
        "nome": "-",
        "codigoUsina": "-",
        "nomeUsina": "-",
        "tipoAlerta": "-",
        "status": "-",
        "statusClass": "-",
        "alarmes": "-"
    })


# Ler o arquivo HTML externo
def read_html_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

# Verificar se o arquivo HTML existe
if not os.path.exists('index.html'):
    st.error("Arquivo index.html não encontrado. Por favor, crie o arquivo conforme as instruções.")
else:
    # Ler o HTML
    html_content = read_html_file('index.html')
    
    # Substituir os placeholders pelos dados reais
    html_content = html_content.replace('EQUIPMENT_DATA_PLACEHOLDER', json.dumps(equipment_data))
    html_content = html_content.replace('GAUGE_PLACEHOLDER', gauge_html)
    
    # Renderizar o HTML
    st.components.v1.html(html_content, height=1000, scrolling=True)

