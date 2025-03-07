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
import pytz
import re

# Configuração do fuso horário de São Paulo
sao_paulo_tz = pytz.timezone('America/Sao_Paulo')

# Função para converter UTC para o horário de São Paulo
def utc_to_sao_paulo(dt):
    if dt is None:
        return None
    # Forçar o uso do horário de São Paulo, ignorando o timezone do servidor
    sao_paulo_now = datetime.now(sao_paulo_tz)
    server_now = datetime.now()
    # Calcular a diferença entre o horário do servidor e o horário de São Paulo
    time_diff = sao_paulo_now.replace(tzinfo=None) - server_now
    # Ajustar o datetime recebido com a diferença calculada
    adjusted_dt = dt + time_diff
    # Converter para o timezone de São Paulo
    return adjusted_dt.replace(tzinfo=pytz.UTC).astimezone(sao_paulo_tz)

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

        # Lista de códigos de alarmes desejados
        codigos_alarmes_desejados = [1, 240, 243, 244, 253, 256, 258, 259, 262, 265, 269, 272, 273, 279, 280, 281, 301, 304, 333, 350, 351, 352, 353, 356, 357, 381, 383, 384, 385, 386, 387, 388, 389, 390, 400, 401, 404, 405,411,412,413,414,415,416, 471, 472, 473,528, 590, 591, 592, 593, 594,595,596,597,598,599,600, 602, 603, 604, 611,615,616,617,631, 635, 637, 638, 657, 658,669,678, 725, 727, 728, 729, 730, 731, 732, 735]

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
                        lrq.data_cadastro_previsto,
                        eq.nome AS nome_equipamento,
                        us.nome AS nome_usina
                    FROM machine_learning.log_relatorio_quebras lrq
                    JOIN sup_geral.equipamentos eq ON lrq.cod_equipamento = eq.codigo
                    JOIN sup_geral.usinas us ON lrq.cod_usina = us.codigo
                    WHERE lrq.data_cadastro_previsto IS NOT NULL
                    AND DATE(lrq.data_cadastro_previsto) = CURDATE()
                    ORDER BY lrq.data_cadastro_previsto DESC;
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
                       eq.cod_usina, us.nome as nome_usina,
                       MAX(lc.data_cadastro) as ultima_atualizacao
                FROM machine_learning.leituras_consecutivas lc
                JOIN sup_geral.equipamentos eq ON lc.cod_equipamento = eq.codigo
                JOIN sup_geral.usinas us ON eq.cod_usina = us.codigo
                WHERE lc.cod_campo = 114 
                AND lc.valor_5 > 0 
                AND lc.data_cadastro >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
                GROUP BY lc.cod_equipamento, eq.nome, eq.cod_usina, us.nome
                ORDER BY ultima_atualizacao DESC
                """
                await cursor.execute(query_todos_equipamentos)
                todos_equipamentos = await cursor.fetchall()
                
                # Dicionário para armazenar alarmes por equipamento
                alarmes_por_equipamento = {}
                
                # Processar cada equipamento para obter seus alarmes
                for eq in equipamentos_quebras:
                    cod_equipamento = eq[0]
                    data_cadastro_previsto = eq[3]
                    
                    if data_cadastro_previsto:
                        # Consulta para obter alarmes para este equipamento
                        query_alarmes = """
                        SELECT la.cod_alarme, la.data_cadastro 
                        FROM sup_geral.log_alarmes la
                        WHERE la.cod_equipamento = %s
                        AND la.data_cadastro BETWEEN DATE_SUB(%s, INTERVAL 10 MINUTE) AND NOW()
                        """
                        await cursor.execute(query_alarmes, (cod_equipamento, data_cadastro_previsto))
                        alarmes = await cursor.fetchall()
                        
                        alarmes_equipamento = []
                        tem_alarme_desejado = False
                        tem_alarme_qualquer = False
                        
                        for alarme in alarmes:
                            cod_alarme = alarme[0]
                            data_cadastro = alarme[1]
                            
                            # Verificar se é um alarme desejado
                            if cod_alarme in codigos_alarmes_desejados:
                                tem_alarme_desejado = True
                            
                            tem_alarme_qualquer = True
                            
                            # Obter descrição do alarme
                            query_descricao = """
                            SELECT descricao FROM sup_geral.lista_alarmes
                            WHERE codigo = %s
                            """
                            await cursor.execute(query_descricao, (cod_alarme,))
                            result_descricao = await cursor.fetchone()
                            descricao = result_descricao[0] if result_descricao else "Descrição não disponível"
                            
                            # Determinar severidade
                            if "id" in descricao.lower():
                                severidade = "Baixa"  # Verde para alarmes com "id" no nome
                            else:
                                # Verificar se o alarme termina com um número 3 ou maior
                                # Extrair o último caractere da descrição e verificar se é um dígito
                                ultimo_char = descricao.strip()[-1] if descricao.strip() else ""
                                if ultimo_char.isdigit() and int(ultimo_char) >= 3:
                                    severidade = "Crítica"  # Vermelho para alarmes que terminam com 3 ou maior
                                elif cod_alarme in codigos_alarmes_desejados:
                                    severidade = "Alta"  # Laranja para alarmes na lista de desejados
                                else:
                                    severidade = "Baixa"  # Verde para os demais alarmes
                            
                            # Converter UTC para horário de São Paulo
                            data_cadastro_sp = utc_to_sao_paulo(data_cadastro)
                            
                            alarmes_equipamento.append({
                                "cod_alarme": cod_alarme,
                                "data_cadastro": data_cadastro_sp.strftime("%d/%m/%Y %H:%M:%S") if data_cadastro_sp else None,
                                "descricao": descricao,
                                "severidade": severidade
                            })
                        
                        # Determinar o emoji de alerta
                        if tem_alarme_desejado:
                            emoji_alerta = "❗ ⚠️"
                        elif tem_alarme_qualquer:
                            emoji_alerta = "❗"
                        else:
                            emoji_alerta = "-"
                        
                        if not alarmes_equipamento:
                            alarmes_equipamento = [{"mensagem": "Sem alarmes"}]
                            emoji_alerta = "-"
                            
                        alarmes_por_equipamento[cod_equipamento] = {
                            "alarmes": alarmes_equipamento,
                            "emoji_alerta": emoji_alerta
                        }
                    else:
                        alarmes_por_equipamento[cod_equipamento] = {
                            "alarmes": [{"mensagem": "Sem alarmes"}],
                            "emoji_alerta": "-"
                        }

        # Fechar a pool
        pool.close()
        await pool.wait_closed()
        
        # Processar os dados dos equipamentos
        equipamentos_processados = []
        
        # Dicionário para mapear equipamentos com quebras
        equipamentos_com_quebras = {}
        for eq in equipamentos_quebras:
            cod_equipamento = eq[0]
            data_cadastro_quebra = eq[2]
            data_cadastro_previsto = eq[3]
            
            # Converter horários para o fuso horário de São Paulo
            data_cadastro_quebra_sp = utc_to_sao_paulo(data_cadastro_quebra) if data_cadastro_quebra else None
            data_cadastro_previsto_sp = utc_to_sao_paulo(data_cadastro_previsto) if data_cadastro_previsto else None
            
            if cod_equipamento in equipamentos_com_quebras:
                # Se este equipamento já existe, manter o que tem quebra
                # Se ambos têm quebra ou nenhum tem quebra, manter o mais antigo
                existing_eq = equipamentos_com_quebras[cod_equipamento]
                existing_has_breakdown = existing_eq.get('data_cadastro_quebra') is not None
                current_has_breakdown = data_cadastro_quebra is not None
                
                if current_has_breakdown and not existing_has_breakdown:
                    # Atual tem quebra mas o existente não, substituir
                    equipamentos_com_quebras[cod_equipamento] = {
                        'cod_equipamento': eq[0],
                        'cod_usina': eq[1],
                        'data_cadastro_quebra': data_cadastro_quebra_sp,
                        'data_cadastro_previsto': data_cadastro_previsto_sp,
                        'nome_equipamento': eq[4],
                        'nome_usina': eq[5]
                    }
                elif not current_has_breakdown and not existing_has_breakdown:
                    # Nenhum tem quebra, manter o mais novo (já ordenado DESC)
                    if existing_eq.get('data_cadastro_previsto') < data_cadastro_previsto_sp:
                        equipamentos_com_quebras[cod_equipamento] = {
                            'cod_equipamento': eq[0],
                            'cod_usina': eq[1],
                            'data_cadastro_quebra': data_cadastro_quebra_sp,
                            'data_cadastro_previsto': data_cadastro_previsto_sp,
                            'nome_equipamento': eq[4],
                            'nome_usina': eq[5]
                        }
            else:
                equipamentos_com_quebras[cod_equipamento] = {
                    'cod_equipamento': eq[0],
                    'cod_usina': eq[1],
                    'data_cadastro_quebra': data_cadastro_quebra_sp,
                    'data_cadastro_previsto': data_cadastro_previsto_sp,
                    'nome_equipamento': eq[4],
                    'nome_usina': eq[5]
                }

        # Processar todos os equipamentos
        for eq in equipamentos_com_quebras.values():
            cod_equipamento = eq['cod_equipamento']
            cod_usina = eq['cod_usina']
            nome_usina = eq['nome_usina']
            nome_equipamento = eq['nome_equipamento']
            data_cadastro_quebra = eq['data_cadastro_quebra']
            data_cadastro_previsto = eq['data_cadastro_previsto']
            
            # Verificar status do equipamento
            is_active = cod_equipamento in [e[0] for e in todos_equipamentos]
            has_breakdown = data_cadastro_quebra is not None
            has_alert = cod_equipamento in equipamentos_alerta
            
            if has_breakdown:
                status = "Desligado com falha"
                status_class = "status-error"
            elif not is_active:
                status = "Desligado sem falha"
                status_class = "status-warning"
            elif has_alert:
                status = "Funcionando"
                status_class = "status-ok"
            else:
                status = "Funcionando"
                status_class = "status-ok"
            
            # Formatar datas para exibição
            data_cadastro_previsto_str = data_cadastro_previsto.strftime("%d/%m/%Y %H:%M:%S") if data_cadastro_previsto else None
            data_cadastro_quebra_str = data_cadastro_quebra.strftime("%d/%m/%Y %H:%M:%S") if data_cadastro_quebra else None
            
            # Obter alarmes e emoji para este equipamento
            info_alarmes = alarmes_por_equipamento.get(cod_equipamento, {"alarmes": [{"mensagem": "Sem alarmes"}], "emoji_alerta": "-"})
            alarmes = info_alarmes["alarmes"]
            emoji_alerta = info_alarmes["emoji_alerta"]
            
            equipamentos_processados.append({
                'cod_equipamento': cod_equipamento,
                'nome_equipamento': nome_equipamento,
                'cod_usina': cod_usina,
                'nome_usina': nome_usina,
                'status': status,
                'status_class': status_class,
                'data_cadastro_previsto': data_cadastro_previsto_str,
                'data_cadastro_quebra': data_cadastro_quebra_str,
                'alarmes': alarmes,
                'emoji_alerta': emoji_alerta
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
        "dataPrevisto": eq["data_cadastro_previsto"],
        "dataQuebra": eq["data_cadastro_quebra"],
        "alarmes": eq["alarmes"],
        "emojiAlerta": eq["emoji_alerta"]
    })

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
        "dataPrevisto": "-",
        "dataQuebra": "-",
        "alarmes": [{"mensagem": "Sem alarmes"}],
        "emojiAlerta": "-"
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

