import os
import time
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import DBSCAN  # scikit-learn é importado como sklearn
from datetime import datetime, timedelta
from binance.client import Client
from binance.enums import *
import matplotlib.pyplot as plt
from binance.exceptions import BinanceAPIException
from alert_system import AlertSystem
import requests
import talib
from datetime import datetime, timedelta, UTC
from datetime import datetime, timezone
import json
import sqlite3
from datetime import timezone, timedelta
import matplotlib.dates as mdates
from telegram_bot import request_trading_approval, get_approval_results

def is_operation_approved(user_id, symbol):
    """Verificar aprovação considerando função de acesso"""
    try:
        # Importar para garantir que temos a versão mais recente
        from telegram_bot import get_approval_results
        
        # Garantir que user_id é uma string
        user_id_str = str(user_id)
        
        # Obter resultados de aprovação
        approval_results = get_approval_results()
        key = f"{user_id_str}_{symbol}"
        
        # Debug
        print(f"Verificando aprovação para key: {key}")
        print(f"Approval results disponíveis: {approval_results}")
        
        # Verificar se a chave existe e se foi aprovada
        is_approved = approval_results.get(key, False)
        print(f"Resultado da verificação: {is_approved}")
        
        return is_approved
    except Exception as e:
        print(f"Erro ao verificar aprovação: {e}")
        # Por padrão, não permitir a operação em caso de erro
        return False

# Configurações do usuário
SYMBOL = 'BTCUSDT'
TIMEFRAME = '3m'  # 3 minutos

# Configurações de taxas da Binance
TAXA_MAKER_TAKER = 0.001  # 0.1% taxa padrão
USAR_BNB_PARA_TAXA = True
DESCONTO_BNB = 0.25  # 25% de desconto se pagar com BNB
TAXA_EFETIVA = TAXA_MAKER_TAKER * (1 - DESCONTO_BNB if USAR_BNB_PARA_TAXA else 0)

# Ajustar os níveis de take profit para compensar as taxas
# Calculando a taxa total de compra + venda: 2 * TAXA_EFETIVA (para condições normais)
TAXA_TOTAL_ESTIMADA = 2 * TAXA_EFETIVA

MAX_PERDAS_CONSECUTIVAS = 3   # Pausa após este número de perdas consecutivas
MAX_DRAWDOWN_PERCENTUAL = 5   # Pausa se drawdown atingir este percentual
TEMPO_PAUSA_APOS_PERDAS = 12  # Horas de pausa após sequência de perdas

# Take profit ajustado para compensar taxas em capital pequeno
ALVO_LUCRO_PERCENTUAL_1 = 0.4   # Reduzido para captura mais rápida
ALVO_LUCRO_PERCENTUAL_2 = 0.7
ALVO_LUCRO_PERCENTUAL_3 = 1.0

# Gerenciamento de risco aprimorado
CAPITAL_TOTAL = 164.47  # USDT
CAPITAL_POR_OPERACAO_PERCENTUAL = 45  # % do capital total (reduzido de ~29% para 3%)
CAPITAL_POR_OPERACAO = CAPITAL_TOTAL * CAPITAL_POR_OPERACAO_PERCENTUAL / 100  # Aprox. 5.16 USDT

ALVO_DIARIO_PERCENTUAL = 0.65  # Meta diária ajustada para 15-20% mensal composto
ALVO_MENSAL_PERCENTUAL = 15.0  # Meta mensal explícita

# Stop loss dinâmico baseado em ATR
STOP_LOSS_MULTIPLICADOR_ATR = 1.0  # Multiplicador para ATR
STOP_LOSS_PERCENTUAL_MINIMO = 0.5  # Mínimo de 0.5% (aumento de 0.2%)
STOP_LOSS_PERCENTUAL_MAXIMO = 2.0  # Máximo de 2% do valor da operação

PERDA_MAXIMA_PERCENTUAL = 2.0

# Parâmetros de indicadores
MA_CURTA = 7
MA_MEDIA = 25
MA_LONGA = 99
RSI_PERIODO = 14
RSI_SOBRECOMPRA = 70
RSI_SOBREVENDA = 30
RSI_ZONA_OTIMA_MIN = 40
RSI_ZONA_OTIMA_MAX = 60

# Novos parâmetros de filtro
VOLUME_MINIMO_PERCENTUAL = 150  # Aumentado para filtrar melhor (100% para 115%)
VOLUME_PERIODO = 20
INCLINACAO_MA_LONGA_MIN = 0.01  # Mínimo de inclinação para MA longa (filtro de tendência)
ATR_PERIODO = 14
ATR_MINIMO_OPERACAO = 0.25  # Aumentado para evitar mercados de baixa volatilidade
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Configurações para análise macro
USAR_ANALISE_MACRO = True  # Ativar/desativar análise macro
PESO_ANALISE_MACRO = 0.8   # Peso da análise macro (0-1)
CACHE_TEMPO_EXPIRACAO = {
    'sentimento': 3600,    # 1 hora em segundos
    'dominancia': 3600,    # 1 hora em segundos
    'correlacao': 1800     # 30 minutos em segundos
}
# Horários para não operar (UTC)
HORARIOS_EVITAR = [
    {'inicio': '00:00', 'fim': '01:00'},  # Baixa liquidez
    {'inicio': '20:00', 'fim': '21:00'}   # Alta volatilidade (notícias)
]

# Autenticação com a API Binance
API_KEY = 'gYzsw6dYN0ukl1Vm3FDMS0fLugwpacnJLD8XMNZL5WwUxErVnfWzamEwYttviUT8'
API_SECRET = 'Z6huY9KvuJvy7OMnPdjY2w8yauuUR1D7kfCNOTLkk6gVwQfrqooW8WVz2Ll8aRjt'

# Configurações do Telegram
TELEGRAM_TOKEN = "7103442744:AAHTHxLnVixhNWcsvmG2mU1uqWUNwGktfxw"
TELEGRAM_CHAT_ID = "7002398112"

# Setup para simulação
MODO_SIMULACAO = False  # Definir como False para operar com dinheiro real
MAX_OPERACOES_DIA = 7  # Limitar número de operações diárias

class BinanceScalpingBotMelhorado:
    def __init__(self, api_key, api_secret, symbol, timeframe, capital_por_operacao):
        # Inicializar client da Binance com keepalives para conexões mais estáveis
        self.client = Client(api_key, api_secret, {"verify": True, "timeout": 30})
        self.symbol = symbol
        self.timeframe = timeframe
        self.capital_por_operacao = capital_por_operacao
        self.lucro_diario = 0
        self.perda_diaria = 0
        self.operacoes_dia = []
        self.em_operacao = False
        self.preco_entrada = 0
        self.quantidade = 0
        # Inicialização para stop virtual
        self.usando_stop_virtual = False
        self.stop_virtual_preco = 0
        self.ordem_id = None
        self.ordem_stop_id = None
        self.trailing_stop_ativo = False
        self.ultima_busca_moedas = datetime.now() - timedelta(hours=2)  # Inicializar para permitir busca imediata
        self.tempo_sem_oportunidades = 0  # Contador de tempo sem oportunidades
        self.trailing_stop_nivel = 0
        self.motivo_entrada = ""
        self.posicao_parcial = False  # Para controle de saídas parciais
        self.saidas_parciais = []  # Registro de saídas parciais
        self.quantidade_restante = 0  # Para controle após saídas parciais
        self.taxa_total_operacao = 0
        self.taxas_pagas_total = 0  # Acumulador total de taxas pagas
        # Inicialização para gráficos macro
        self.ultimo_grafico_macro_dia = datetime.now().day
        # Cache para APIs de análise macro
        self.cache_macro = {
            'sentimento': {'dados': None, 'timestamp': 0},
            'dominancia': {'dados': None, 'timestamp': 0},
            'correlacao': {'dados': None, 'timestamp': 0}
        }

        # Criar pasta para logs e gráficos
        self.pasta_logs = "logs"
        os.makedirs(self.pasta_logs, exist_ok=True)

        # Criar pasta para dados macro
        self.pasta_macro = os.path.join(self.pasta_logs, "dados_macro")
        os.makedirs(self.pasta_macro, exist_ok=True)

        # Inicializar banco de dados para análise macro
        self.inicializar_db_analise_macro()
        # Inicializar configurações de taxas
        self.taxa_maker_taker = TAXA_MAKER_TAKER
        self.usar_bnb = USAR_BNB_PARA_TAXA
        self.desconto_bnb = DESCONTO_BNB
        self.taxa_efetiva = TAXA_EFETIVA
        # Configuração do Telegram
        self.telegram_token = "7103442744:AAHTHxLnVixhNWcsvmG2mU1uqWUNwGktfxw" 
        self.telegram_chat_id = "7002398112"
        self.alert_system = AlertSystem(
            enable_telegram=True,
            telegram_token=self.telegram_token,
            telegram_chat_id=self.telegram_chat_id
        )
        self.ultima_hora_grafico = None
        

        taxa_percentual = self.taxa_efetiva * 100
        desconto_info = f" (com desconto BNB de {self.desconto_bnb * 100}%)" if self.usar_bnb else ""
        print(f"Taxa por operação: {taxa_percentual:.4f}%{desconto_info}")
        print(f"Taxa total estimada por trade (compra+venda): {(taxa_percentual * 2):.4f}%")
        
        # Zonas de suporte e resistência
        self.zonas_sr = {"suportes": [], "resistencias": []}
        
        # Log detalhado das operações
        self.log_operacoes = []
        
        # Contador de operações do dia
        self.operacoes_hoje = 0
        self.ultima_verificacao_dia = datetime.now().day
        
        # Iniciar sessão
        self.data_inicio = datetime.now()
        print(f"Bot iniciado em: {self.data_inicio}")
        print(f"Símbolo: {self.symbol}")
        print(f"Timeframe: {self.timeframe}")
        print(f"Capital por operação: {self.capital_por_operacao} USDT ({CAPITAL_POR_OPERACAO_PERCENTUAL}% do capital)")
        print(f"Meta diária: {ALVO_DIARIO_PERCENTUAL}% (aprox. {ALVO_DIARIO_PERCENTUAL * 30}% ao mês)")
        print(f"Modo simulação: {'ATIVADO' if MODO_SIMULACAO else 'DESATIVADO - CUIDADO: OPERAÇÕES REAIS'}")
    
        
        # Performance tracking
        self.trades_vencedores = 0
        self.trades_perdedores = 0
        self.maior_sequencia_perdas = 0
        self.sequencia_perdas_atual = 0
        self.valor_maximo_carteira = CAPITAL_TOTAL
        
        # Obter informações do símbolo
        self.get_symbol_info()
        
        # Enviar mensagem de inicialização
        self.send_telegram_alert(f"🤖 Bot de Trading Iniciado\n\n"
                             f"Símbolo: {self.symbol}\n"
                             f"Timeframe: {self.timeframe}\n"
                             f"Capital: {CAPITAL_TOTAL} USDT\n"
                             f"Meta diária: {ALVO_DIARIO_PERCENTUAL}%\n"
                             f"Modo: {'SIMULAÇÃO' if MODO_SIMULACAO else 'REAL - OPERAÇÕES COM CAPITAL REAL'}")

    def ajustar_capital_operacao(self):
        """Ajustar dinamicamente o capital por operação com base no desempenho e horário"""
        # Verificar se está no período de baixa liquidez
        modo_baixa_liquidez, criterios_noturnos = self.ajustar_criterios_noturnos()
        
        # Calcular progresso em direção à meta diária
        alvo_diario_valor = CAPITAL_TOTAL * ALVO_DIARIO_PERCENTUAL / 100
        progresso_diario = self.lucro_diario / max(0.01, alvo_diario_valor)  # Evitar divisão por zero
        
        # Base de capital (padrão)
        capital_padrao = CAPITAL_TOTAL * CAPITAL_POR_OPERACAO_PERCENTUAL / 100
        
        # Aplicar redução noturna se necessário
        if modo_baixa_liquidez and criterios_noturnos:
            capital_padrao *= criterios_noturnos['capital_ajuste']
            print(f"🌙 Capital ajustado para modo baixa liquidez: {capital_padrao:.2f} USDT")
        
        # Ajustar com base no progresso
        if progresso_diario < 0.3:  # Muito abaixo da meta (menos de 30%)
            return min(capital_padrao * 1.5, CAPITAL_TOTAL * 0.6)  # Até 60% do capital
        elif progresso_diario < 0.6:  # Abaixo da meta (30-60%)
            return min(capital_padrao * 1.25, CAPITAL_TOTAL * 0.5)  # Até 50% do capital
        elif progresso_diario < 0.8:  # Próximo da meta (60-80%)
            return capital_padrao  # Manter padrão
        else:  # Meta quase atingida (>80%)
            return capital_padrao * 0.75  # Reduzir exposição
    
    def executar_ciclo(self):
        """
        Método principal de execução do bot a cada ciclo de verificação
        """
        try:
            # Obter dados atuais
            df = self.get_klines()
            
            # Verificar stop loss/take profit
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            preco_atual = float(ticker['price'])
            
            # Se estiver em uma operação
            if self.em_operacao:
                # Verificar take profit parcial
                self.verificar_take_profit_parcial(preco_atual, self.calcular_parametros_ordem(preco_atual)[0])
                
                # Verificar stop loss
                self.verificar_status_ordens()
                
                # Verificar trailing stop
                self.verificar_stop_loss_movel(preco_atual)
            
            # Verificar se há sinal para nova entrada
            if not self.em_operacao:
                sinal, mensagem = self.check_signal(df)
                
                if sinal:
                    # Calcular parâmetros para ordem
                    params, msg_params = self.calcular_parametros_ordem(preco_atual)
                    
                    if params:
                        # Verificar viabilidade da operação
                        viavel, msg_viabilidade = self.verificar_viabilidade_operacao(preco_atual, params)
                        
                        if viavel:
                            # Executar ordem de compra
                            self.executar_ordem_compra(params)
            
            # Verificar alertas
            self.verificar_alertas(df)
            
            # Verificar metas diárias
            self.verificar_metas_diarias()
            
        except Exception as e:
            print(f"Erro no ciclo de execução: {e}")
            import traceback
            traceback.print_exc()
    def determinar_nivel_confianca(self, pontuacao, criterios_atendidos, criterios_total):
        """
        Determina o nível de confiança baseado na pontuação e critérios atendidos
        """
        # Critérios atendidos (proporção)
        proporcao_criterios = criterios_atendidos / criterios_total
        
        # MUITO mais seletivo
        if pontuacao >= 8.0 and proporcao_criterios >= 0.8:  # Super restritivo
            return "alta", 1.0  # 100% do capital alocado para o trade
        elif pontuacao >= 6.5 and proporcao_criterios >= 0.7:  # Muito restritivo
            return "média", 0.7  # 70% do capital alocado
        elif pontuacao >= 5.5 and proporcao_criterios >= 0.6:  # Restritivo
            return "baixa", 0.4  # 40% do capital alocado
        else:
            return "insuficiente", 0  # Não entrar
    
    def buscar_moeda_alternativa(self):
        """Buscar moedas alternativas quando a atual não apresenta boas oportunidades"""
        try:
            print("Buscando moedas alternativas com boas oportunidades...")
            self.registrar_log("DIVERSIFICAÇÃO: Iniciando busca por moedas alternativas")
            
            # Lista de moedas populares para verificar (pode ser expandida)
            moedas_potenciais = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", 
                "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "MATICUSDT", "LINKUSDT",
                "NEARUSDT", "FTMUSDT", "SANDUSDT", "APEUSDT", "DOGEUSDT"
            ]
            
            # Remover a moeda atual da lista
            if self.symbol in moedas_potenciais:
                moedas_potenciais.remove(self.symbol)
                
            # Adicionar algumas stablecoins para usar em mercados instáveis
            stablecoins = ["USDCUSDT", "BUSDUSDT", "TUSDUSDT"]
            
            # Verificar mercado geral (sentimento)
            try:
                sentimento_score, sentimento_desc, fear_greed_index = self.analisar_sentimento_mercado()
                
                # Se o sentimento for de medo extremo ou ganância extrema, considerar stablecoins
                if fear_greed_index <= 20 or fear_greed_index >= 80:
                    print(f"⚠️ Sentimento extremo do mercado: {sentimento_desc}. Considerando stablecoins.")
                    moedas_potenciais = stablecoins + moedas_potenciais[:5]  # Priorizar stablecoins e top 5 moedas
            except Exception as e:
                print(f"Erro ao analisar sentimento: {e}")
            
            resultados = []
            
            # Analisar cada moeda
            for moeda in moedas_potenciais[:10]:  # Limitar a 10 moedas para não sobrecarregar a API
                try:
                    # Salvar símbolo atual temporariamente
                    simbolo_original = self.symbol
                    
                    # Trocar para a nova moeda temporariamente
                    self.symbol = moeda
                    
                    # Obter dados da moeda
                    df = self.get_klines()
                    
                    # Verificar sinal
                    sinal, mensagem = self.check_signal(df)
                    pontuacao = float(mensagem.split("Pontuação: ")[1].split("/")[0]) if "Pontuação: " in mensagem else 0
                    
                    # Verificar confirmação em múltiplos timeframes
                    confirmado, _ = self.confirmar_multiplos_timeframes(self.timeframe)
                    
                    # Armazenar resultado
                    resultados.append({
                        'symbol': moeda,
                        'pontuacao': pontuacao,
                        'sinal': sinal,
                        'confirmado': confirmado,
                        'mensagem': mensagem
                    })
                    
                    print(f"Análise de {moeda}: Pontuação {pontuacao:.1f}/10 | Sinal: {'SIM' if sinal else 'NÃO'} | Confirmado: {'SIM' if confirmado else 'NÃO'}")
                    
                    # Restaurar símbolo original
                    self.symbol = simbolo_original
                    
                    # Pausar para não sobrecarregar a API
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Erro ao analisar {moeda}: {e}")
                    # Restaurar símbolo original em caso de erro
                    self.symbol = simbolo_original
            
            # Ordenar resultados por pontuação
            resultados = sorted(resultados, key=lambda x: (x['sinal'], x['confirmado'], x['pontuacao']), reverse=True)
            
            # Filtrar apenas moedas com sinal
            boas_opcoes = [r for r in resultados if r['sinal'] and r['pontuacao'] >= 5.0]
            
            if boas_opcoes:
                # Encontrou boas opções
                melhor_opcao = boas_opcoes[0]
                print(f"✅ Encontrada moeda alternativa: {melhor_opcao['symbol']} com pontuação {melhor_opcao['pontuacao']:.1f}/10")
                
                # Enviar alerta no Telegram
                self.send_telegram_alert(
                    f"🔄 SUGESTÃO DE MOEDA ALTERNATIVA\n\n"
                    f"Moeda: {melhor_opcao['symbol']}\n"
                    f"Pontuação: {melhor_opcao['pontuacao']:.1f}/10\n\n"
                    f"Análise:\n{melhor_opcao['mensagem']}\n\n"
                    f"Deseja mudar para esta moeda? Use o comando:\n"
                    f"/mudar_{melhor_opcao['symbol']}"
                )
                
                self.registrar_log(f"MOEDA ALTERNATIVA: Sugerido {melhor_opcao['symbol']} com pontuação {melhor_opcao['pontuacao']:.1f}")
                return melhor_opcao['symbol']
            else:
                print("❌ Nenhuma moeda alternativa com boas oportunidades encontrada.")
                self.registrar_log("MOEDA ALTERNATIVA: Nenhuma opção viável encontrada")
                return None
                
        except Exception as e:
            print(f"Erro ao buscar moedas alternativas: {e}")
            self.registrar_log(f"ERRO AO BUSCAR MOEDAS: {str(e)}")
            return None
    
    def verificar_reentrada_rapida(self, preco_atual):
        """Verificar se é possível fazer reentrada rápida em tendência forte"""
        # Verificar se a última operação foi lucrativa
        if not hasattr(self, 'ultima_operacao_resultado') or not hasattr(self, 'ultima_operacao_motivo'):
            return False
            
        if self.ultima_operacao_resultado <= 0:
            return False  # Não reentrar após perda
            
        # Verificar se a saída foi por take profit (não por stop loss)
        if "Take Profit" not in self.ultima_operacao_motivo:
            return False
            
        # Obter dados recentes
        df = self.get_klines()
        if len(df) < MA_CURTA:
            return False
            
        ultimo = df.iloc[-1]
        
        # Verificar condições de tendência forte
        tendencia_forte = False
        
        # 1. MA curta bem acima da MA média
        if ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}'] * 1.015:
            tendencia_forte = True
            
        # 2. Volume acima da média
        if ultimo['volume'] > ultimo['volume_media'] * 1.5:
            tendencia_forte = True
            
        # 3. RSI em zona favorável e subindo
        if 'rsi' in ultimo and 40 <= ultimo['rsi'] <= 65:
            if len(df) >= 3 and df['rsi'].iloc[-1] > df['rsi'].iloc[-2] > df['rsi'].iloc[-3]:
                tendencia_forte = True
        
        # 4. Preço atual acima do último preço de saída
        if hasattr(self, 'ultimo_preco_saida') and preco_atual > self.ultimo_preco_saida * 1.005:
            tendencia_forte = True
            
        # Exigir pelo menos 2 condições para considerar reentrada
        condicoes_atendidas = sum([
            ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}'] * 1.015,
            ultimo['volume'] > ultimo['volume_media'] * 1.5,
            40 <= ultimo.get('rsi', 0) <= 65 and len(df) >= 3 and df['rsi'].iloc[-1] > df['rsi'].iloc[-2],
            hasattr(self, 'ultimo_preco_saida') and preco_atual > self.ultimo_preco_saida * 1.005
        ])
        
        return condicoes_atendidas >= 2

    def inicializar_db_analise_macro(self):
        """Inicializar banco de dados SQLite para armazenar análises macro"""
        self.db_path = os.path.join(self.pasta_macro, "macro_analysis.db")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Criar tabela se não existir
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS macro_indicators (
            timestamp TEXT PRIMARY KEY,
            fear_greed_index INTEGER,
            btc_dominance REAL,
            market_cap_total REAL, 
            btc_correlation REAL,
            eth_correlation REAL,
            sentiment_score REAL,
            correlation_score REAL,
            dominance_score REAL,
            symbol TEXT
        )
        ''')
        
        conn.commit()
        conn.close()
        
        print(f"Banco de dados de análise macro inicializado: {self.db_path}")

    def analisar_sentimento_mercado(self):
        """Analisar o sentimento do mercado usando Fear & Greed Index"""
        # Verificar cache
        tempo_atual = time.time()
        if (self.cache_macro['sentimento']['dados'] is not None and 
            tempo_atual - self.cache_macro['sentimento']['timestamp'] < CACHE_TEMPO_EXPIRACAO['sentimento']):
            self.registrar_log("SENTIMENTO: Usando dados em cache")
            return self.cache_macro['sentimento']['dados']
        
        try:
            # Fear & Greed Index da Alternative.me
            url = "https://api.alternative.me/fng/?limit=2"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            sentimento_score = 1.0  # Valor neutro padrão
            sentimento_desc = "Neutro (padrão)"
            fear_greed_value = 50   # Valor neutro padrão
            
            if 'data' in data and len(data['data']) > 0:
                fear_greed_value = int(data['data'][0]['value'])
                fear_greed_classification = data['data'][0]['value_classification']
                
                # Atribuir uma pontuação com base no índice
                if fear_greed_value <= 20:  # Medo extremo - potencial de compra
                    sentimento_score = 1.2
                    sentimento_desc = f"Medo Extremo ({fear_greed_value}) - Possível oportunidade"
                elif fear_greed_value <= 40:  # Medo - positivo para compra
                    sentimento_score = 1.1
                    sentimento_desc = f"Medo ({fear_greed_value}) - Favorável"
                elif fear_greed_value <= 60:  # Neutro
                    sentimento_score = 1.0
                    sentimento_desc = f"Neutro ({fear_greed_value})"
                elif fear_greed_value <= 80:  # Ganância - cautela
                    sentimento_score = 0.9
                    sentimento_desc = f"Ganância ({fear_greed_value}) - Cautela"
                else:  # Ganância extrema - risco elevado
                    sentimento_score = 0.8
                    sentimento_desc = f"Ganância Extrema ({fear_greed_value}) - Alto risco"
                
                # Analisar tendência do sentimento
                if len(data['data']) > 1:
                    fear_greed_yesterday = int(data['data'][1]['value'])
                    trend = fear_greed_value - fear_greed_yesterday
                    
                    if trend > 5:
                        sentimento_desc += f" | Melhorando (+{trend})"
                        sentimento_score += 0.05
                    elif trend < -5:
                        sentimento_desc += f" | Piorando ({trend})"
                        sentimento_score -= 0.05
            
            # Guardar no cache
            self.cache_macro['sentimento'] = {
                'dados': (sentimento_score, sentimento_desc, fear_greed_value),
                'timestamp': tempo_atual
            }
            
            self.registrar_log(f"SENTIMENTO: {sentimento_desc} (score: {sentimento_score})")
            return sentimento_score, sentimento_desc, fear_greed_value
        
        except Exception as e:
            self.registrar_log(f"ERRO SENTIMENTO: {str(e)}")
            return 1.0, f"Neutro (erro: {str(e)})", 50
    
    def analisar_dominancia_btc(self):
        """Analisar a dominância do Bitcoin e fluxos de capital no mercado"""
        # Verificar cache
        tempo_atual = time.time()
        if (self.cache_macro['dominancia']['dados'] is not None and 
            tempo_atual - self.cache_macro['dominancia']['timestamp'] < CACHE_TEMPO_EXPIRACAO['dominancia']):
            self.registrar_log("DOMINÂNCIA: Usando dados em cache")
            return self.cache_macro['dominancia']['dados']
        
        try:
            # Usar CoinGecko para dados de dominância
            url = "https://api.coingecko.com/api/v3/global"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            dominancia_score = 1.0  # Valor neutro padrão
            dominancia_desc = "Neutro (padrão)"
            dominancia_btc = 50.0    # Valor padrão
            market_cap_total = 0.0   # Valor padrão
            
            if 'data' in data and 'market_cap_percentage' in data['data']:
                dominancia_btc = data['data']['market_cap_percentage']['btc']
                dominancia_eth = data['data']['market_cap_percentage'].get('eth', 0)
                market_cap_total = data['data']['total_market_cap']['usd']
                
                # Carregar histórico de dominância do arquivo
                historico_file = os.path.join(self.pasta_macro, "historico_dominancia.json")
                historico_dominancia = []
                
                if os.path.exists(historico_file):
                    try:
                        with open(historico_file, 'r') as f:
                            historico_dominancia = json.load(f)
                    except:
                        historico_dominancia = []
                
                # Adicionar dados atuais ao histórico
                timestamp_atual = datetime.now().isoformat()
                historico_dominancia.append({
                    'timestamp': timestamp_atual,
                    'btc_dominance': dominancia_btc,
                    'eth_dominance': dominancia_eth,
                    'total_market_cap': market_cap_total
                })
                
                # Manter apenas os últimos 30 registros
                if len(historico_dominancia) > 30:
                    historico_dominancia = historico_dominancia[-30:]
                
                # Salvar histórico atualizado
                with open(historico_file, 'w') as f:
                    json.dump(historico_dominancia, f)
                
                # Analisar tendência de dominância
                if len(historico_dominancia) >= 2:
                    # Encontrar registro anterior mais próximo de 24 horas atrás
                    dominancia_anterior = historico_dominancia[0]['btc_dominance']
                    variacao_dominancia = dominancia_btc - dominancia_anterior
                    
                    # Análise baseada na dominância
                    base_moeda = self.symbol.replace('USDT', '')
                    
                    # Regras para altcoins (não-BTC)
                    if base_moeda != 'BTC':
                        if variacao_dominancia < -1.0:
                            # Dominância BTC caindo = potencial Altseason
                            dominancia_score = 1.1
                            dominancia_desc = f"Favorável para altcoins: BTC dominância caindo ({variacao_dominancia:.2f}%)"
                        elif variacao_dominancia > 1.0:
                            # Dominância BTC aumentando = BTC forte
                            dominancia_score = 0.9
                            dominancia_desc = f"Cautela para altcoins: Dominância BTC aumentando ({variacao_dominancia:.2f}%)"
                        else:
                            dominancia_score = 1.0
                            dominancia_desc = f"Neutro: Dominância BTC estável ({dominancia_btc:.2f}%)"
                    # Regras para Bitcoin
                    else:
                        if variacao_dominancia > 1.0:
                            dominancia_score = 1.1
                            dominancia_desc = f"Favorável para BTC: Dominância aumentando ({variacao_dominancia:.2f}%)"
                        elif variacao_dominancia < -1.0:
                            dominancia_score = 0.9
                            dominancia_desc = f"Cautela para BTC: Dominância caindo ({variacao_dominancia:.2f}%)"
                        else:
                            dominancia_score = 1.0
                            dominancia_desc = f"Neutro para BTC: Dominância estável ({dominancia_btc:.2f}%)"
            
            # Guardar no cache
            self.cache_macro['dominancia'] = {
                'dados': (dominancia_score, dominancia_desc, dominancia_btc, market_cap_total),
                'timestamp': tempo_atual
            }
            
            self.registrar_log(f"DOMINÂNCIA: {dominancia_desc} (score: {dominancia_score})")
            return dominancia_score, dominancia_desc, dominancia_btc, market_cap_total
        
        except Exception as e:
            self.registrar_log(f"ERRO DOMINÂNCIA: {str(e)}")
            return 1.0, f"Neutro (erro: {str(e)})", 50.0, 0.0
    
    def analisar_correlacoes(self):
        """Analisar correlação do ativo com BTC e ETH"""
        # Verificar cache
        tempo_atual = time.time()
        if (self.cache_macro['correlacao']['dados'] is not None and 
            tempo_atual - self.cache_macro['correlacao']['timestamp'] < CACHE_TEMPO_EXPIRACAO['correlacao']):
            self.registrar_log("CORRELAÇÃO: Usando dados em cache")
            return self.cache_macro['correlacao']['dados']
        
        try:
            # Obter dados do par atual
            df_ativo = self.get_klines()
            fechamentos_ativo = df_ativo['close'].values
            
            correlacao_score = 1.0  # Valor neutro padrão
            correlacao_desc = "Neutro (padrão)"
            correlacao_btc = 0.0     # Valor padrão
            correlacao_eth = 0.0     # Valor padrão
            
            # Se o ativo não for Bitcoin, calcular correlação com BTC
            if self.symbol != 'BTCUSDT':
                try:
                    # Obter klines BTC no mesmo timeframe
                    klines_btc = self.client.get_klines(
                        symbol='BTCUSDT',
                        interval=self.timeframe,
                        limit=50  # Últimas 50 velas
                    )
                    
                    df_btc = pd.DataFrame(klines_btc, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_asset_volume', 'number_of_trades',
                        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                    ])
                    
                    df_btc['timestamp'] = pd.to_datetime(df_btc['timestamp'], unit='ms')
                    df_btc['close'] = df_btc['close'].astype(float)
                    
                    # Calcular retornos percentuais (variação)
                    df_btc['return'] = df_btc['close'].pct_change()
                    df_temp = df_ativo.copy()
                    df_temp['return'] = df_temp['close'].pct_change()
                    
                    # Remover primeiros registros com NaN
                    df_btc = df_btc.iloc[1:]
                    df_temp = df_temp.iloc[1:].reset_index(drop=True)
                    
                    # Garantir mesmo número de registros para correlação
                    min_len = min(len(df_btc), len(df_temp))
                    df_btc = df_btc.iloc[-min_len:].reset_index(drop=True)
                    df_temp = df_temp.iloc[-min_len:].reset_index(drop=True)
                    
                    # Calcular correlação de Pearson com Bitcoin
                    correlacao_btc = df_temp['return'].corr(df_btc['return'])
                    
                    # Análise baseada na correlação
                    if correlacao_btc > 0.7:
                        # Alta correlação positiva
                        correlacao_score = 0.9 if 'BTC' not in self.symbol else 1.1
                        correlacao_desc = f"Alta correlação com BTC ({correlacao_btc:.2f})"
                        
                        if 'BTC' not in self.symbol:
                            correlacao_desc += " - pouca diversificação"
                        else:
                            correlacao_desc += " - movimento alinhado ao mercado"
                            
                    elif correlacao_btc < 0.3 and correlacao_btc >= 0:
                        # Baixa correlação positiva
                        correlacao_score = 1.1 if 'BTC' not in self.symbol else 0.9
                        correlacao_desc = f"Baixa correlação com BTC ({correlacao_btc:.2f})"
                        
                        if 'BTC' not in self.symbol:
                            correlacao_desc += " - boa diversificação"
                        else:
                            correlacao_desc += " - movimento independente do mercado"
                            
                    elif correlacao_btc < 0:
                        # Correlação negativa
                        correlacao_score = 1.2 if 'BTC' not in self.symbol else 0.8
                        correlacao_desc = f"Correlação negativa com BTC ({correlacao_btc:.2f})"
                        
                        if 'BTC' not in self.symbol:
                            correlacao_desc += " - excelente diversificação/hedge"
                        else:
                            correlacao_desc += " - movimento contrário ao mercado (incomum)"
                    else:
                        correlacao_score = 1.0
                        correlacao_desc = f"Correlação moderada com BTC ({correlacao_btc:.2f})"
                    
                    # Obter também correlação com ETH para análise adicional
                    try:
                        klines_eth = self.client.get_klines(
                            symbol='ETHUSDT',
                            interval=self.timeframe,
                            limit=50
                        )
                        
                        df_eth = pd.DataFrame(klines_eth, columns=[
                            'timestamp', 'open', 'high', 'low', 'close', 'volume',
                            'close_time', 'quote_asset_volume', 'number_of_trades',
                            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                        ])
                        
                        df_eth['timestamp'] = pd.to_datetime(df_eth['timestamp'], unit='ms')
                        df_eth['close'] = df_eth['close'].astype(float)
                        df_eth['return'] = df_eth['close'].pct_change()
                        df_eth = df_eth.iloc[1:].reset_index(drop=True)
                        
                        # Igualar tamanhos novamente
                        min_len = min(len(df_eth), len(df_temp))
                        df_eth = df_eth.iloc[-min_len:].reset_index(drop=True)
                        df_temp = df_temp.iloc[-min_len:].reset_index(drop=True)
                        
                        correlacao_eth = df_temp['return'].corr(df_eth['return'])
                        
                        # Se correlação com ETH for significativamente diferente de BTC
                        if abs(correlacao_eth - correlacao_btc) > 0.3:
                            if correlacao_eth > correlacao_btc:
                                correlacao_desc += f" | Maior correlação com ETH ({correlacao_eth:.2f})"
                            else:
                                correlacao_desc += f" | Menor correlação com ETH ({correlacao_eth:.2f})"
                    except Exception as eth_error:
                        self.registrar_log(f"Erro ao calcular correlação com ETH: {str(eth_error)}")
                        correlacao_eth = 0.0
                        
                except Exception as btc_error:
                    self.registrar_log(f"Erro ao calcular correlação com BTC: {str(btc_error)}")
                    correlacao_btc = 0.0
                    correlacao_score = 1.0
                    correlacao_desc = f"Erro ao calcular correlação: {str(btc_error)}"
            else:
                # Para o Bitcoin, a correlação é sempre 1.0 consigo mesmo
                correlacao_btc = 1.0
                correlacao_score = 1.0
                correlacao_desc = "BTC - referência para correlações"
            
            # Guardar no cache
            self.cache_macro['correlacao'] = {
                'dados': (correlacao_score, correlacao_desc, correlacao_btc, correlacao_eth),
                'timestamp': tempo_atual
            }
            
            self.registrar_log(f"CORRELAÇÃO: {correlacao_desc} (score: {correlacao_score})")
            return correlacao_score, correlacao_desc, correlacao_btc, correlacao_eth
        
        except Exception as e:
            self.registrar_log(f"ERRO CORRELAÇÃO: {str(e)}")
            return 1.0, f"Neutro (erro: {str(e)})", 0.0, 0.0
    
    def salvar_analise_macro(self, fear_greed_index, btc_dominance, market_cap_total, 
                         btc_correlation, eth_correlation, sentiment_score, 
                         correlation_score, dominance_score):
        """Salvar análise macro no banco de dados"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            timestamp = datetime.now().isoformat()
            
            # Verificar se já existe registro com este timestamp
            cursor.execute("SELECT COUNT(*) FROM macro_indicators WHERE timestamp = ?", (timestamp,))
            if cursor.fetchone()[0] > 0:
                # Atualizar registro existente
                cursor.execute('''
                UPDATE macro_indicators 
                SET fear_greed_index = ?, btc_dominance = ?, market_cap_total = ?,
                    btc_correlation = ?, eth_correlation = ?, sentiment_score = ?,
                    correlation_score = ?, dominance_score = ?
                WHERE timestamp = ?
                ''', (
                    fear_greed_index,
                    btc_dominance,
                    market_cap_total,
                    btc_correlation,
                    eth_correlation,
                    sentiment_score,
                    correlation_score,
                    dominance_score,
                    timestamp
                ))
            else:
                # Inserir novo registro
                cursor.execute('''
                INSERT INTO macro_indicators 
                (timestamp, fear_greed_index, btc_dominance, market_cap_total, 
                btc_correlation, eth_correlation, sentiment_score, 
                correlation_score, dominance_score, symbol)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    fear_greed_index,
                    btc_dominance,
                    market_cap_total,
                    btc_correlation,
                    eth_correlation,
                    sentiment_score,
                    correlation_score,
                    dominance_score,
                    self.symbol
                ))
            
            conn.commit()
            conn.close()
            self.registrar_log(f"Análise macro salva no banco de dados em {timestamp}")
        except Exception as e:
            self.registrar_log(f"ERRO ao salvar análise macro: {str(e)}")

    def visualizar_indicadores_macro(self):
        """Gerar gráficos de indicadores macro para análise"""
        try:
            conn = sqlite3.connect(self.db_path)
            # Obter dados dos últimos 30 dias
            query = """
            SELECT * FROM macro_indicators 
            WHERE symbol = ? 
            ORDER BY timestamp DESC 
            LIMIT 50
            """
            
            df = pd.read_sql_query(query, conn, params=(self.symbol,))
            conn.close()
            
            if len(df) < 2:
                self.registrar_log("Dados insuficientes para visualização de indicadores macro")
                return
            
            # Preparar dados
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')  # Garantir ordem cronológica
            
            plt.figure(figsize=(14, 12))
            
            # Gráfico de Fear & Greed
            ax1 = plt.subplot(3, 1, 1)
            ax1.plot(df['timestamp'], df['fear_greed_index'], 'b-', linewidth=2)
            ax1.axhline(y=50, color='r', linestyle='--', alpha=0.5)
            ax1.fill_between(df['timestamp'], 0, 25, color='green', alpha=0.2)
            ax1.fill_between(df['timestamp'], 75, 100, color='red', alpha=0.2)
            ax1.set_title('Fear & Greed Index')
            ax1.set_ylabel('Índice')
            ax1.grid(True)
            
            # Formatar eixo X
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m-%Y'))
            
            # Gráfico de Dominância BTC
            ax2 = plt.subplot(3, 1, 2, sharex=ax1)
            ax2.plot(df['timestamp'], df['btc_dominance'], 'r-', linewidth=2)
            ax2.set_title('Dominância do Bitcoin (%)')
            ax2.set_ylabel('Dominância (%)')
            ax2.grid(True)
            
            # Gráfico de Correlação
            ax3 = plt.subplot(3, 1, 3, sharex=ax1)
            ax3.plot(df['timestamp'], df['btc_correlation'], 'g-', linewidth=2, label='Correlação com BTC')
            
            if not df['eth_correlation'].isnull().all():
                ax3.plot(df['timestamp'], df['eth_correlation'], 'm--', linewidth=1.5, label='Correlação com ETH')
            
            ax3.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            ax3.axhline(y=0.7, color='r', linestyle='--', alpha=0.5)
            ax3.axhline(y=-0.7, color='r', linestyle='--', alpha=0.5)
            ax3.set_title(f'Correlação do {self.symbol}')
            ax3.set_ylabel('Correlação (Pearson)')
            ax3.set_ylim(-1, 1)
            ax3.grid(True)
            ax3.legend()
            
            plt.tight_layout()
            
            # Salvar gráfico
            data_hora = datetime.now().strftime("%Y%m%d_%H%M%S")
            caminho_grafico = os.path.join(self.pasta_macro, f"macro_indicadores_{data_hora}.png")
            plt.savefig(caminho_grafico)
            plt.close()
            
            self.registrar_log(f"Gráficos de indicadores macro salvos em: {caminho_grafico}")
            
            # Enviar gráfico por Telegram
            try:
                self.send_telegram_image(
                    caminho_grafico, 
                    caption=f"📊 *Análise Macro para {self.symbol}*\n\n"
                            f"Fear & Greed Index: {df['fear_greed_index'].iloc[-1]}\n"
                            f"Dominância BTC: {df['btc_dominance'].iloc[-1]:.2f}%\n"
                            f"Correlação BTC: {df['btc_correlation'].iloc[-1]:.2f}"
                )
            except Exception as e:
                self.registrar_log(f"Erro ao enviar gráfico: {str(e)}")
            
            return caminho_grafico
            
        except Exception as e:
            self.registrar_log(f"ERRO ao visualizar indicadores macro: {str(e)}")
            return None
    
    def verificar_seguranca(self):
        """Verificar condições de segurança para continuar operando - Continua monitorando mesmo em pausa"""
        # Verificar sequência de perdas
        if self.sequencia_perdas_atual >= MAX_PERDAS_CONSECUTIVAS:
            # Verificar se já estamos em pausa
            if not hasattr(self, 'pausa_ate'):
                # Configurar pausa
                self.pausa_ate = datetime.now() + timedelta(hours=TEMPO_PAUSA_APOS_PERDAS)
                mensagem = (f"⚠️ SISTEMA EM PAUSA ⚠️\n\n"
                            f"Motivo: {self.sequencia_perdas_atual} perdas consecutivas\n"
                            f"Pausa até: {self.pausa_ate.strftime('%d/%m/%Y %H:%M')}\n"
                            f"Continuando em modo de monitoramento apenas.")
                self.send_telegram_alert(mensagem)
                self.registrar_log(f"PAUSA ATIVADA: {self.sequencia_perdas_atual} perdas consecutivas")
                return False
            elif datetime.now() < self.pausa_ate:
                tempo_restante = self.pausa_ate - datetime.now()
                horas = tempo_restante.total_seconds() // 3600
                minutos = (tempo_restante.total_seconds() % 3600) // 60
                print(f"⚠️ Sistema em pausa por mais {int(horas)}h:{int(minutos)}m devido a perdas consecutivas")
                return False
            else:
                # Pausa concluída
                delattr(self, 'pausa_ate')
                self.sequencia_perdas_atual = 0  # Resetar contador de perdas
                self.registrar_log("PAUSA FINALIZADA: Operações normalizadas")
                
                # Enviar alerta
                self.send_telegram_alert(
                    f"✅ PAUSA FINALIZADA\n\n"
                    f"O sistema está retomando as operações normalmente após o período de pausa."
                )
                return True
        
        # Verificar drawdown
        carteira_atual = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria
        drawdown = (self.valor_maximo_carteira - carteira_atual) / self.valor_maximo_carteira * 100
        
        if drawdown > MAX_DRAWDOWN_PERCENTUAL:
            if not hasattr(self, 'pausa_ate'):
                # Configurar pausa
                self.pausa_ate = datetime.now() + timedelta(hours=TEMPO_PAUSA_APOS_PERDAS)
                mensagem = (f"⚠️ SISTEMA EM PAUSA ⚠️\n\n"
                            f"Motivo: Drawdown de {drawdown:.2f}% excede limite de {MAX_DRAWDOWN_PERCENTUAL}%\n"
                            f"Pausa até: {self.pausa_ate.strftime('%d/%m/%Y %H:%M')}\n"
                            f"Continuando em modo de monitoramento apenas.")
                self.send_telegram_alert(mensagem)
                self.registrar_log(f"PAUSA ATIVADA: Drawdown de {drawdown:.2f}%")
                return False
            elif datetime.now() < self.pausa_ate:
                return False
            else:
                # Pausa concluída
                delattr(self, 'pausa_ate')
                self.registrar_log("PAUSA FINALIZADA: Operações normalizadas")
                
                # Enviar alerta
                self.send_telegram_alert(
                    f"✅ PAUSA FINALIZADA\n\n"
                    f"O sistema está retomando as operações normalmente após o período de pausa por drawdown."
                )
                return True
        
        return True  # Prosseguir com operações

    def ajustar_criterios_noturnos(self):
        """Ajusta os critérios de trading com base no horário global, não apenas local"""
        # Obter a hora atual no fuso horário UTC
        hora_utc = datetime.now(timezone.utc).hour
        
        # Período de baixa liquidez global (noite nos EUA/madrugada na Europa, 3h-7h UTC)
        periodo_baixa_liquidez = 3 <= hora_utc < 7
        
        # Usando hora local para registro
        hora_local = datetime.now().hour
        
        if periodo_baixa_liquidez:
            # Critérios mais rigorosos durante o período de baixa liquidez
            self.criterios_noturnos = {
                # Aumentar pontuação mínima
                'pontuacao_minima': 7.5,  # Aumentado de 6.5 para 7.5
                
                # Exigir volume ainda maior
                'volume_minimo_pct': VOLUME_MINIMO_PERCENTUAL * 1.5,  # 50% a mais
                
                # Reduzir o tamanho da posição
                'capital_ajuste': 0.7,  # 70% do capital normal
                
                # Exigir volatilidade mais controlada
                'atr_min': ATR_MINIMO_OPERACAO * 1.2,  # 20% maior
                'atr_max': ATR_MINIMO_OPERACAO * 2.0,  # Limite superior
                
                # Exigir mais confirmações
                'contra_indicacoes_max': 0  # Zero contra-indicações permitidas
            }
            
            print(f"🌙 MODO BAIXA LIQUIDEZ ATIVADO: Critérios mais rigorosos aplicados (hora UTC: {hora_utc}h, local: {hora_local}h)")
            self.registrar_log(f"MODO BAIXA LIQUIDEZ: Critérios ajustados para maior segurança - UTC {hora_utc}h")
            return True, self.criterios_noturnos
        else:
            # Critérios padrão
            self.criterios_noturnos = None
            return False, None

    def ajustar_criterios_por_contexto(self, df):
        """
        Ajusta critérios com base no contexto atual do mercado
        """
        # Obter dados recentes
        ultimo = df.iloc[-1]
        
        # Detectar mercado em extremo (oversold/overbought)
        rsi_extremo = ultimo['rsi'] < 30 or ultimo['rsi'] > 70
        
        # Detectar volatilidade anormal
        volatilidade_alta = ultimo.get('atr_percent', 0) > 0.3
        
        # Detectar consolidação (lateralização)
        range_recente = df['high'].iloc[-10:].max() - df['low'].iloc[-10:].min()
        range_percentual = range_recente / df['close'].iloc[-10] * 100
        consolidacao = range_percentual < 1.5
        
        # Ajustar critérios - LIMIARES REDUZIDOS
        # Ajustar critérios - LIMIARES REDUZIDOS
        if rsi_extremo:
            return {
                'min_pontuacao': 2.0,  # Reduzido de 3.5 para 2.0
                'volume_minimo_pct': 80,  # Reduzido de 100 para 80
                'ma_alinhamento_obrigatorio': False
            }
        elif volatilidade_alta:
            return {
                'min_pontuacao': 3.5,  # Reduzido de 5.0 para 3.5
                'volume_minimo_pct': 120,  # Reduzido de 130 para 120
                'ma_alinhamento_obrigatorio': True
            }
        elif consolidacao:
            return {
                'min_pontuacao': 2.5,  # Reduzido de 4.0 para 2.5
                'volume_minimo_pct': 100,  # Reduzido de 120 para 100
                'ma_alinhamento_obrigatorio': False
            }
        else:
            return {
                'min_pontuacao': 4.0,  # Reduzido de 5.5 para 4.0
                'volume_minimo_pct': 100,  # Reduzido de 115 para 100
                'ma_alinhamento_obrigatorio': True
            }
            
    def avaliar_troca_de_moeda(self):
        """Avalia se deve buscar uma nova moeda após completar uma operação"""
        # Verificar quando foi a última operação
        if not hasattr(self, 'ultima_operacao_timestamp'):
            return False
        
        # Verificar há quanto tempo a última operação foi concluída
        tempo_desde_ultima_operacao = (datetime.now() - self.ultima_operacao_timestamp).total_seconds()
        # Se faz menos de 2 minutos, aguardar um pouco mais
        if tempo_desde_ultima_operacao < 120:
            return False
        
        # Obter dados atualizados
        df = self.get_klines()
        
        # Verificar critérios técnicos atuais
        pontuacao, _ = self.check_signal(df)
        
        # Se a pontuação estiver abaixo do mínimo, considerar trocar
        if not pontuacao:
            print("Moeda atual não apresenta mais critérios favoráveis. Considerando trocar...")
            self.registrar_log("AVALIAÇÃO: Moeda atual sem critérios favoráveis - buscando alternativas")
            return True
        
        return False 
    
    def confirmar_multiplos_timeframes(self, timeframe_principal):
        """Verificar sinal em múltiplos timeframes para confirmação"""
        print("Analisando múltiplos timeframes para confirmação...")
        
        # Definir timeframes para confirmação (além do principal)
        if timeframe_principal == '3m':
            timeframes_confirmacao = ['15m']
        elif timeframe_principal == '5m':
            timeframes_confirmacao = ['15m']
        elif timeframe_principal == '15m':
            timeframes_confirmacao = ['1h']
        else:
            timeframes_confirmacao = ['15m']
        
        # Obter dados e analisar o timeframe principal
        df_principal = self.get_klines()
        sinal_principal, mensagem_principal = self.check_signal(df_principal)
        
        if not sinal_principal:
            return False, "Sem sinal no timeframe principal"
        
        # Analisar timeframes de confirmação
        confirmacoes = 0
        mensagens = [f"✅ {self.timeframe}: {mensagem_principal}"]
        
        for tf in timeframes_confirmacao:
            try:
                # Obter klines para o timeframe de confirmação
                klines = self.client.get_klines(
                    symbol=self.symbol,
                    interval=tf,
                    limit=300
                )
                
                # Converter para DataFrame
                df = pd.DataFrame(klines, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                ])
                
                # Converter tipos de dados
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                df['volume'] = df['volume'].astype(float)
                
                # Calcular indicadores necessários
                # Médias móveis
                df[f'ma_{MA_CURTA}'] = df['close'].rolling(window=MA_CURTA).mean()
                df[f'ma_{MA_MEDIA}'] = df['close'].rolling(window=MA_MEDIA).mean()
                df[f'ma_{MA_LONGA}'] = df['close'].rolling(window=MA_LONGA).mean()
                
                # RSI
                if len(df) >= RSI_PERIODO:
                    df['rsi'] = talib.RSI(df['close'].values, timeperiod=RSI_PERIODO)
                else:
                    delta = df['close'].diff()
                    gain = delta.clip(lower=0)
                    loss = -1 * delta.clip(upper=0)
                    ema_up = gain.ewm(com=RSI_PERIODO-1, adjust=False).mean()
                    ema_down = loss.ewm(com=RSI_PERIODO-1, adjust=False).mean()
                    rs = ema_up / ema_down
                    df['rsi'] = 100 - (100 / (1 + rs))
                
                # Volume
                df['volume_media'] = df['volume'].rolling(window=VOLUME_PERIODO).mean()
                
                # Verificar tendência no timeframe maior
                ultimo = df.iloc[-1]
                penultimo = df.iloc[-2]
                
                # Verificações básicas para confirmação
                ma_curta_acima_media = ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}']
                ma_media_acima_longa = ultimo[f'ma_{MA_MEDIA}'] > ultimo[f'ma_{MA_LONGA}']
                rsi_favoravel = ultimo['rsi'] > 40 and ultimo['rsi'] < 70
                
                # Determinar se este timeframe confirma
                if (ma_curta_acima_media and ma_media_acima_longa and rsi_favoravel):
                    confirmacoes += 1
                    mensagens.append(f"✅ {tf}: Confirmado (MAs alinhadas, RSI favorável)")
                elif ma_curta_acima_media and rsi_favoravel:
                    confirmacoes += 0.5
                    mensagens.append(f"⚠️ {tf}: Parcialmente confirmado (MA curta > MA média, RSI favorável)")
                else:
                    mensagens.append(f"❌ {tf}: Sem confirmação")
                    
            except Exception as e:
                print(f"Erro ao analisar timeframe {tf}: {e}")
                continue
        
        # Determinar resultado final
        if confirmacoes >= len(timeframes_confirmacao):
            return True, "\n".join(mensagens)
        elif confirmacoes >= 0.5:
            return True, "\n".join(mensagens) + "\nAviso: Confirmação parcial apenas"
        else:
            return False, "\n".join(mensagens) + "\nAviso: Sem confirmação em outros timeframes"
    def calcular_atr(self, df, periodo=ATR_PERIODO):
        """Calcular o Average True Range (ATR) usando TALib"""
        if len(df) >= periodo:
            df['atr'] = talib.ATR(df['high'].values, df['low'].values, df['close'].values, timeperiod=periodo)
            df['atr_percent'] = df['atr'] / df['close'] * 100
            return df
        else:
            # Cálculo manual alternativo se não tiver dados suficientes
            high = df['high']
            low = df['low']
            close = df['close'].shift(1)
            
            tr1 = high - low
            tr2 = abs(high - close)
            tr3 = abs(low - close)
            
            tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
            df['atr'] = tr.rolling(window=periodo).mean()
            df['atr_percent'] = df['atr'] / df['close'] * 100
            return df

    def analisar_smart_money(self, df, periodo_obv=20):
        """
        Analisa comportamento de "smart money" usando OBV e outros indicadores de volume
        
        Smart Money refere-se a investidores institucionais ou grandes players
        que frequentemente deixam "pegadas" nos gráficos através de padrões de volume.
        
        Args:
            df: DataFrame com dados OHLCV
            periodo_obv: período para média móvel do OBV
            
        Returns:
            dict: Dicionário com resultados da análise
        """
        # Criar cópia para não alterar o original
        df_copia = df.copy()
        
        # Calcular On-Balance Volume (OBV)
        obv = [0]
        for i in range(1, len(df_copia)):
            if df_copia['close'].iloc[i] > df_copia['close'].iloc[i-1]:
                obv.append(obv[-1] + df_copia['volume'].iloc[i])
            elif df_copia['close'].iloc[i] < df_copia['close'].iloc[i-1]:
                obv.append(obv[-1] - df_copia['volume'].iloc[i])
            else:
                obv.append(obv[-1])
        
        df_copia['obv'] = obv
        
        # Calcular média móvel do OBV
        df_copia['obv_ma'] = df_copia['obv'].rolling(window=periodo_obv).mean()
        
        # Calcular Money Flow Index (MFI) - Alternativa ao RSI que inclui volume
        # Primeiro calcular o Money Flow (MF)
        df_copia['typical_price'] = (df_copia['high'] + df_copia['low'] + df_copia['close']) / 3
        df_copia['money_flow'] = df_copia['typical_price'] * df_copia['volume']
        
        # Identificar money flow positivo e negativo
        df_copia['positive_flow'] = 0.0
        df_copia['negative_flow'] = 0.0

        
        for i in range(1, len(df_copia)):
            if df_copia['typical_price'].iloc[i] > df_copia['typical_price'].iloc[i-1]:
                df_copia.loc[df_copia.index[i], 'positive_flow'] = float(df_copia['money_flow'].iloc[i])
            else:
                df_copia.loc[df_copia.index[i], 'negative_flow'] = df_copia['money_flow'].iloc[i]
        
        # Calcular MFI
        periodo_mfi = 14  # Período padrão
        
        if len(df_copia) >= periodo_mfi:
            df_copia['positive_flow_sum'] = df_copia['positive_flow'].rolling(window=periodo_mfi).sum()
            df_copia['negative_flow_sum'] = df_copia['negative_flow'].rolling(window=periodo_mfi).sum()
            
            # Evitar divisão por zero
            df_copia['money_ratio'] = df_copia.apply(
                lambda x: x['positive_flow_sum'] / max(x['negative_flow_sum'], 0.001), 
                axis=1
            )
            
            df_copia['mfi'] = 100 - (100 / (1 + df_copia['money_ratio']))
        
        # Detectar acumulação e distribuição
        df_copia['smart_acumulacao'] = False
        df_copia['smart_distribuicao'] = False
        
        # Detecção baseada em divergências OBV-preço e MFI-preço
        if 'mfi' in df_copia.columns:
            for i in range(20, len(df_copia)):
                # Verificar janela de 10 candles
                preco_janela = df_copia['close'].iloc[i-10:i+1]
                obv_janela = df_copia['obv'].iloc[i-10:i+1]
                mfi_janela = df_copia['mfi'].iloc[i-10:i+1]
                
                # Calcular mudanças percentuais
                preco_mudanca = (preco_janela.iloc[-1] - preco_janela.iloc[0]) / preco_janela.iloc[0] * 100
                obv_mudanca = (obv_janela.iloc[-1] - obv_janela.iloc[0]) / max(abs(obv_janela.iloc[0]), 0.001) * 100
                mfi_mudanca = mfi_janela.iloc[-1] - mfi_janela.iloc[0]
                
                # Divergências positivas (acumulação)
                # Preço estável/caindo, mas OBV ou MFI subindo significativamente
                if preco_mudanca < 1.0 and (obv_mudanca > 5.0 or mfi_mudanca > 10):
                    df_copia.loc[df_copia.index[i], 'smart_acumulacao'] = True
                
                # Divergências negativas (distribuição)
                # Preço estável/subindo, mas OBV ou MFI caindo significativamente
                if preco_mudanca > 1.0 and (obv_mudanca < -5.0 or mfi_mudanca < -10):
                    df_copia.loc[df_copia.index[i], 'smart_distribuicao'] = True
        
        # Verificar Chaikin Money Flow (CMF) se tivermos dados suficientes
        if len(df_copia) >= 20:
            # Money Flow Multiplier
            df_copia['mf_multiplier'] = ((df_copia['close'] - df_copia['low']) - 
                                    (df_copia['high'] - df_copia['close'])) / (df_copia['high'] - df_copia['low'])
            df_copia['mf_multiplier'] = df_copia['mf_multiplier'].replace([np.inf, -np.inf], 0)

            
            # Money Flow Volume
            df_copia['mf_volume'] = df_copia['mf_multiplier'] * df_copia['volume']
            
            # Chaikin Money Flow (CMF)
            df_copia['cmf'] = df_copia['mf_volume'].rolling(window=20).sum() / df_copia['volume'].rolling(window=20).sum()
            
            # Identificar acumulação e distribuição baseado no CMF
            for i in range(20, len(df_copia)):
                if i > 0 and df_copia['cmf'].iloc[i] > 0.1 and df_copia['cmf'].iloc[i] > df_copia['cmf'].iloc[i-1]:
                    df_copia.loc[df_copia.index[i], 'smart_acumulacao'] = True
                elif i > 0 and df_copia['cmf'].iloc[i] < -0.1 and df_copia['cmf'].iloc[i] < df_copia['cmf'].iloc[i-1]:
                    df_copia.loc[df_copia.index[i], 'smart_distribuicao'] = True
        
        # Preparar resumo da análise
        acumulacao_recente = df_copia['smart_acumulacao'].iloc[-5:].any()
        distribuicao_recente = df_copia['smart_distribuicao'].iloc[-5:].any()
        
        # Calcular a "força" dos sinais
        if 'cmf' in df_copia.columns and len(df_copia) > 5:
            cmf_atual = df_copia['cmf'].iloc[-1]
            cmf_anterior = df_copia['cmf'].iloc[-5]
            cmf_forca = abs(cmf_atual - cmf_anterior)
        else:
            cmf_forca = 0
        
        if 'obv' in df_copia.columns and len(df_copia) > 5:
            obv_atual = df_copia['obv'].iloc[-1]
            obv_anterior = df_copia['obv'].iloc[-5]
            obv_forca = abs((obv_atual - obv_anterior) / max(abs(obv_anterior), 0.001) * 100)
        else:
            obv_forca = 0
        
        # Resumo da análise
        resumo = {
            'acumulacao_detectada': acumulacao_recente,
            'distribuicao_detectada': distribuicao_recente,
            'cmf_atual': df_copia['cmf'].iloc[-1] if 'cmf' in df_copia.columns else None,
            'obv_atual': df_copia['obv'].iloc[-1],
            'forca_sinal': max(cmf_forca, obv_forca/10),  # Normalizar para faixa similar
            'df': df_copia  # DataFrame com todas as métricas calculadas
        }
        
        return resumo
    def detectar_divergencias(self, df):
        """
        Detecta divergências entre preço e indicadores técnicos (RSI, MACD)
        
        Tipos de divergências:
        - Positiva: Preço faz mínimos mais baixos, mas o indicador faz mínimos mais altos (sinal de compra)
        - Negativa: Preço faz máximos mais altos, mas o indicador faz máximos mais baixos (sinal de venda)
        
        Returns:
            list: Lista de divergências encontradas com detalhes
        """
        divergencias = []
        
        # Precisamos de pelo menos 30 candles para detecção confiável
        if len(df) < 30:
            return divergencias
        
        # Função para identificar pontos de inflexão (picos e vales)
        def encontrar_picos_vales(serie, janela=5):
            picos = []
            vales = []
            
            # Ignorar os primeiros e últimos candles da janela
            for i in range(janela, len(serie) - janela):
                # Verificar se é um pico
                if all(serie[i] > serie[i-j] for j in range(1, janela+1)) and \
                all(serie[i] > serie[i+j] for j in range(1, janela+1)):
                    picos.append((i, serie[i]))
                    
                # Verificar se é um vale
                if all(serie[i] < serie[i-j] for j in range(1, janela+1)) and \
                all(serie[i] < serie[i+j] for j in range(1, janela+1)):
                    vales.append((i, serie[i]))
                    
            return picos, vales
        
        # Encontrar picos e vales no preço
        preco_picos, preco_vales = encontrar_picos_vales(df['close'].values)
        
        # Verificar divergências no RSI se disponível
        if 'rsi' in df.columns:
            # Encontrar picos e vales no RSI
            rsi_picos, rsi_vales = encontrar_picos_vales(df['rsi'].values)
            
            # Verificar divergências negativas (preço sobe, RSI desce - sinal de venda)
            if len(preco_picos) >= 2 and len(rsi_picos) >= 2:
                # Ordenar por índice (do mais recente para o mais antigo)
                preco_picos = sorted(preco_picos, key=lambda x: x[0], reverse=True)
                rsi_picos = sorted(rsi_picos, key=lambda x: x[0], reverse=True)
                
                # Comparar últimos dois picos
                if preco_picos[0][1] > preco_picos[1][1]:  # Preço fazendo máximos mais altos
                    # Encontrar os picos do RSI correspondentes (próximos em tempo)
                    for rp1 in rsi_picos:
                        if abs(rp1[0] - preco_picos[0][0]) <= 3:  # Dentro de 3 candles
                            for rp2 in rsi_picos:
                                if abs(rp2[0] - preco_picos[1][0]) <= 3:  # Dentro de 3 candles
                                    # Verificar se RSI está fazendo máximos mais baixos
                                    if rp1[1] < rp2[1]:
                                        divergencias.append({
                                            'tipo': 'negativa',
                                            'indicador': 'rsi',
                                            'local': 'máximo',
                                            'indice_preco': preco_picos[0][0],
                                            'indice_indicador': rp1[0],
                                            'forca': abs((rp2[1] - rp1[1]) / rp2[1]) * 100,  # Em porcentagem
                                            'candles_atras': len(df) - 1 - preco_picos[0][0]
                                        })
            
            # Verificar divergências positivas (preço desce, RSI sobe - sinal de compra)
            if len(preco_vales) >= 2 and len(rsi_vales) >= 2:
                # Ordenar por índice (do mais recente para o mais antigo)
                preco_vales = sorted(preco_vales, key=lambda x: x[0], reverse=True)
                rsi_vales = sorted(rsi_vales, key=lambda x: x[0], reverse=True)
                
                # Comparar últimos dois vales
                if preco_vales[0][1] < preco_vales[1][1]:  # Preço fazendo mínimos mais baixos
                    # Encontrar os vales do RSI correspondentes
                    for rv1 in rsi_vales:
                        if abs(rv1[0] - preco_vales[0][0]) <= 3:  # Dentro de 3 candles
                            for rv2 in rsi_vales:
                                if abs(rv2[0] - preco_vales[1][0]) <= 3:  # Dentro de 3 candles
                                    # Verificar se RSI está fazendo mínimos mais altos
                                    if rv1[1] > rv2[1]:
                                        divergencias.append({
                                            'tipo': 'positiva',
                                            'indicador': 'rsi',
                                            'local': 'mínimo',
                                            'indice_preco': preco_vales[0][0],
                                            'indice_indicador': rv1[0],
                                            'forca': abs((rv1[1] - rv2[1]) / rv2[1]) * 100,  # Em porcentagem
                                            'candles_atras': len(df) - 1 - preco_vales[0][0]
                                        })
        
        # Verificar divergências no MACD (se disponível)
        if 'macd' in df.columns and 'macd_signal' in df.columns:
            # Calcular histograma MACD se ainda não existir
            if 'macd_hist' not in df.columns:
                df['macd_hist'] = df['macd'] - df['macd_signal']
            
            # Encontrar picos e vales no histograma MACD
            macd_picos, macd_vales = encontrar_picos_vales(df['macd_hist'].values)
            
            # Análise similar para MACD - apenas para divergências mais evidentes
            # Implementação semelhante à do RSI acima...
            # (Código omitido por brevidade, seria uma repetição usando MACD em vez de RSI)
        
        # Filtrar apenas divergências recentes (últimos 10 candles)
        divergencias_recentes = [d for d in divergencias if d['candles_atras'] <= 10]

    def calcular_bonus_especiais(self, df):
        """
        Calcula bonificações para situações especiais de alta probabilidade
        """
        bonus = 0
        justificativas = []

        divergencias = self.detectar_divergencias(df) or []
        
        # RSI baixo com candle de reversão
        if df['rsi'].iloc[-1] < 30:
            # Verificar candle de reversão (martelo, doji, etc)
            padrao, nome_padrao, forca = self.identificar_padrao_candle(df)
            if padrao and nome_padrao in ['martelo', 'doji', 'engolfo_alta']:
                bonus += 3.5  # AUMENTADO DE 2.0 PARA 3.5
                justificativas.append(f"RSI oversold ({df['rsi'].iloc[-1]:.1f}) com padrão de reversão ({nome_padrao})")
        
        # Forte divergência RSI/Preço
        divergencias = self.detectar_divergencias(df) or []
        for div in divergencias:
            if div['tipo'] == 'positiva' and div['forca'] > 50 and div['candles_atras'] <= 3:
                bonus += 3.0  # AUMENTADO DE 1.5 PARA 3.0
                justificativas.append(f"Forte divergência positiva (força: {div['forca']:.1f}%)")
        
        # Volume muito acima da média em suporte
        if df['volume'].iloc[-1] > df['volume_media'].iloc[-1] * 2:
            # Verificar se está em suporte
            sr_modelo = self.modelar_suporte_resistencia_avancado(df)
            for suporte in sr_modelo['suportes_fortes']:
                if suporte['proximidade'] == 'muito_proximo':
                    bonus += 3.0  # AUMENTADO DE 1.5 PARA 3.0
                    justificativas.append(f"Volume 2x+ acima da média em suporte forte")
        
        return bonus, justificativas
    def identificar_padrao_candle(self, df):
        """Identificar padrões de candles fortes e relevantes"""
        if len(df) < 3:
            return False, ""
            
        ultimo = df.iloc[-1]
        penultimo = df.iloc[-2]
        antepenultimo = df.iloc[-3]
        
        # Calcular tamanho do corpo dos candles (em %)
        corpo_ultimo = abs(ultimo['close'] - ultimo['open']) / ultimo['open'] * 100
        corpo_penultimo = abs(penultimo['close'] - penultimo['open']) / penultimo['open'] * 100
        
        # Verificar se é um candle de alta
        candle_alta = ultimo['close'] > ultimo['open']
        
        # Marubozu (candle com corpo grande e sombras pequenas)
        sombra_superior = ultimo['high'] - max(ultimo['open'], ultimo['close'])
        sombra_inferior = min(ultimo['open'], ultimo['close']) - ultimo['low']
        
        corpo_grande = corpo_ultimo > 0.25  # Aumentado para filtrar padrões mais fortes
        sombras_pequenas = (sombra_superior + sombra_inferior) < (corpo_ultimo * 0.3)
        
        marubozu = corpo_grande and sombras_pequenas and candle_alta
        
        # Engolfo de alta
        penultimo_baixa = penultimo['close'] < penultimo['open']
        engolfo = (candle_alta and penultimo_baixa and 
                ultimo['open'] <= penultimo['close'] and
                ultimo['close'] > penultimo['open'])
        
        # Martelo de fundo (hammer)
        if candle_alta:
            sombra_inferior_grande = sombra_inferior > (corpo_ultimo * 2)
            sombra_superior_pequena = sombra_superior < (corpo_ultimo * 0.5)
            martelo = sombra_inferior_grande and sombra_superior_pequena
        else:
            martelo = False
        
        # Verificar pullback seguido de retomada (para re-entrada)
        pullback_retomada = False
        if len(df) >= 6:
            # Verificar se houve queda e depois recuperação no RSI
            rsi_recente = df['rsi'].iloc[-6:].values
            if (rsi_recente[0] > rsi_recente[1] > rsi_recente[2] and  # Queda no RSI
                rsi_recente[3] < rsi_recente[4] < rsi_recente[5]):    # Recuperação no RSI
                pullback_retomada = True
        
        # Verificar padrão de três candles em sequência ascendente
        tres_soldados = False
        if len(df) >= 3:
            if (df['close'].iloc[-3] > df['open'].iloc[-3] and
                df['close'].iloc[-2] > df['open'].iloc[-2] and
                df['close'].iloc[-1] > df['open'].iloc[-1] and
                df['close'].iloc[-1] > df['close'].iloc[-2] > df['close'].iloc[-3]):
                tres_soldados = True
        
        # Determinar padrão encontrado
        padrao_encontrado = False
        padrao_nome = ""
        
        if marubozu:
            padrao_encontrado = True
            padrao_nome = "Marubozu de alta"
        elif engolfo:
            padrao_encontrado = True
            padrao_nome = "Engolfo de alta"
        elif martelo:
            padrao_encontrado = True
            padrao_nome = "Martelo (hammer)"
        elif pullback_retomada:
            padrao_encontrado = True
            padrao_nome = "Pullback seguido de retomada"
        elif tres_soldados:
            padrao_encontrado = True
            padrao_nome = "Três soldados brancos"
        
        # Classificar força do padrão
        forca_padrao = 0
        if padrao_encontrado:
            if marubozu or tres_soldados:
                forca_padrao = 2  # Padrão forte
            elif engolfo:
                forca_padrao = 1.5  # Padrão moderado a forte
            else:
                forca_padrao = 1  # Padrão padrão
        
        return padrao_encontrado, padrao_nome, forca_padrao

    def get_symbol_info(self):
        """Obter informações sobre o par de trading"""
        info = self.client.get_symbol_info(self.symbol)
        
        # A estrutura pode variar, então vamos encontrar os filtros corretos
        self.tick_size = 0.01  # Valor padrão
        self.step_size = 0.00001  # Valor padrão
        self.min_qty = 0.00001  # Valor padrão
        
        # Encontrar o filtro PRICE_FILTER para tick_size
        for filter in info['filters']:
            if filter['filterType'] == 'PRICE_FILTER':
                self.tick_size = float(filter['tickSize'])
            elif filter['filterType'] == 'LOT_SIZE':
                self.step_size = float(filter['stepSize'])
                self.min_qty = float(filter['minQty'])
        
        print(f"Tick size: {self.tick_size}")
        print(f"Step size: {self.step_size}")
        print(f"Quantidade mínima: {self.min_qty}")

    def normalize_quantity(self, qty):
        """Normaliza a quantidade de acordo com as regras da Binance"""
        print(f"Quantidade ANTES da normalização: {qty}")
        step_size = self.step_size
        step_size_str = str(step_size)

        if '.' in step_size_str:
            step_size_decimals = len(step_size_str.split('.')[1])
        else:
            step_size_decimals = 0

        # Corrige o qty para múltiplo do step_size
        qty_adjusted = round(qty - (qty % float(step_size)), step_size_decimals)

        # Se a quantidade for muito pequena, calcular uma quantidade mínima viável
        if qty_adjusted <= 0:
            # Use no mínimo 0.001 BTC (aproximadamente $86 no preço atual)
            min_viable_qty = max(0.001, self.min_qty * 100)
            return min_viable_qty
        
        print(f"Quantidade APÓS normalização: {qty_adjusted}")
        return qty_adjusted


    def normalize_price(self, price):
        """Normaliza o preço de acordo com as regras da Binance"""
        tick_size = self.tick_size
        tick_size_decimals = len(str(tick_size).split('.')[1])
        return round(price, tick_size_decimals)

    def get_klines(self):
        """Obter dados de velas (klines) da Binance e calcular indicadores"""
        # Obter mais candles para cálculos mais precisos
        max_periodos = max(300, VOLUME_PERIODO + 100)
        
        klines = self.client.get_klines(
            symbol=self.symbol,
            interval=self.timeframe,
            limit=max_periodos
        )
        
        # Converter para DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        # Converter tipos de dados
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        # Calcular médias móveis
        df[f'ma_{MA_CURTA}'] = df['close'].rolling(window=MA_CURTA).mean()
        df[f'ma_{MA_MEDIA}'] = df['close'].rolling(window=MA_MEDIA).mean()
        df[f'ma_{MA_LONGA}'] = df['close'].rolling(window=MA_LONGA).mean()
        
        # Calcular inclinação da MA Longa
        if len(df) > MA_LONGA + 5:
            ma_longa_recente = df[f'ma_{MA_LONGA}'].iloc[-5:].values
            # Calcular inclinação média dos últimos 5 períodos
            df['ma_longa_inclinacao'] = (ma_longa_recente[-1] - ma_longa_recente[0]) / ma_longa_recente[0] * 100
        else:
            df['ma_longa_inclinacao'] = 0
        
        # Calcular RSI usando TALib
        if len(df) >= RSI_PERIODO:
            df['rsi'] = talib.RSI(df['close'].values, timeperiod=RSI_PERIODO)
        else:
            # Cálculo manual alternativo se não tiver dados suficientes
            delta = df['close'].diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=RSI_PERIODO-1, adjust=False).mean()
            ema_down = down.ewm(com=RSI_PERIODO-1, adjust=False).mean()
            rs = ema_up / ema_down
            df['rsi'] = 100 - (100 / (1 + rs))
        
        # Calcular MACD
        if len(df) >= MACD_SLOW:
            macd, signal, hist = talib.MACD(
                df['close'].values, 
                fastperiod=MACD_FAST, 
                slowperiod=MACD_SLOW, 
                signalperiod=MACD_SIGNAL
            )
            df['macd'] = macd
            df['macd_signal'] = signal
            df['macd_hist'] = hist
        
        # Adicionar cálculo da média de volume
        df['volume_media'] = df['volume'].rolling(window=VOLUME_PERIODO).mean()
        
        # Calcular ATR
        df = self.calcular_atr(df, ATR_PERIODO)
        
        # Identificar zonas de suporte e resistência
        self.identificar_suporte_resistencia(df)
        
        # Calcular bandas de Bollinger
        if len(df) >= 20:
            df['bb_upper'], df['bb_middle'], df['bb_lower'] = talib.BBANDS(
                df['close'].values,
                timeperiod=20,
                nbdevup=2,
                nbdevdn=2,
                matype=0
            )
        
        return df

    def verificar_mas_com_tolerancia(self, df, tolerancia_pct=0.1):
        """
        Verifica alinhamento e cruzamento de MAs com tolerância
        """
        ultimo = df.iloc[-1]
        penultimo = df.iloc[-2]
        
        # Calcular diferenças percentuais
        diff_curta_media = abs(ultimo[f'ma_{MA_CURTA}'] - ultimo[f'ma_{MA_MEDIA}']) / ultimo[f'ma_{MA_MEDIA}'] * 100
        diff_media_longa = abs(ultimo[f'ma_{MA_MEDIA}'] - ultimo[f'ma_{MA_LONGA}']) / ultimo[f'ma_{MA_LONGA}'] * 100
        
        # Verificar alinhamento com tolerância
        alinhamento = (
            (ultimo[f'ma_{MA_CURTA}'] >= ultimo[f'ma_{MA_MEDIA}'] * (1 - tolerancia_pct/100)) and
            (ultimo[f'ma_{MA_MEDIA}'] >= ultimo[f'ma_{MA_LONGA}'] * (1 - tolerancia_pct/100))
        )
        
        # Verificar cruzamento com tolerância
        cruzamento = (
            (penultimo[f'ma_{MA_CURTA}'] <= penultimo[f'ma_{MA_MEDIA}'] * (1 + tolerancia_pct/100)) and
            (ultimo[f'ma_{MA_CURTA}'] >= ultimo[f'ma_{MA_MEDIA}'] * (1 - tolerancia_pct/100))
        )
        
        return {
            'alinhamento': alinhamento,
            'cruzamento': cruzamento,
            'diff_curta_media': diff_curta_media,
            'diff_media_longa': diff_media_longa
        }

    def calcular_volume_delta(self, df):
        """
        Calcula o Volume Delta (diferença entre volume de compra e venda)
        
        O Volume Delta nos dá uma visão mais precisa sobre a pressão de compra 
        versus venda do que o volume tradicional.
        
        Args:
            df: DataFrame com dados OHLCV
            
        Returns:
            DataFrame: DataFrame original com colunas adicionais de Volume Delta
        """
        # Criar cópia para não alterar o original
        df_copia = df.copy()
        
        # Identificar candles de alta e baixa
        candles_alta = df_copia['close'] > df_copia['open']
        candles_baixa = df_copia['close'] < df_copia['open']
        candles_neutros = df_copia['close'] == df_copia['open']
        
        # Calcular volume delta por candle
        df_copia['volume_delta'] = 0.0  # Inicializar com zero
        
        # Volume positivo para candles de alta (pressão compradora)
        df_copia.loc[candles_alta, 'volume_delta'] = df_copia.loc[candles_alta, 'volume']
        
        # Volume negativo para candles de baixa (pressão vendedora)
        df_copia.loc[candles_baixa, 'volume_delta'] = -df_copia.loc[candles_baixa, 'volume']
        
        # Para candles neutros, usar metade do volume
        df_copia.loc[candles_neutros, 'volume_delta'] = df_copia.loc[candles_neutros, 'volume'] * 0.1
        
        # Calcular volume delta cumulativo (semelhante ao OBV)
        df_copia['volume_delta_cumulativo'] = df_copia['volume_delta'].cumsum()
        
        # Calcular médias móveis do volume delta
        df_copia['volume_delta_ma5'] = df_copia['volume_delta'].rolling(window=5).mean()
        df_copia['volume_delta_ma20'] = df_copia['volume_delta'].rolling(window=20).mean()
        
        # Calcular força direcional do volume
        df_copia['forca_volume'] = df_copia['volume_delta_ma5'] / df_copia['volume'].rolling(window=5).mean()
        
        # Identificar acumulação e distribuição
        df_copia['acumulacao'] = False
        df_copia['distribuicao'] = False
        
        # Critérios para acumulação (pressão compradora forte)
        condicao_acumulacao = (
            (df_copia['volume_delta_ma5'] > 0) & 
            (df_copia['volume_delta_ma5'] > df_copia['volume_delta_ma20']) &
            (df_copia['volume'] > df_copia['volume_media'] * 1.2)
        )
        df_copia.loc[condicao_acumulacao, 'acumulacao'] = True
        
        # Critérios para distribuição (pressão vendedora forte)
        condicao_distribuicao = (
            (df_copia['volume_delta_ma5'] < 0) & 
            (df_copia['volume_delta_ma5'] < df_copia['volume_delta_ma20']) &
            (df_copia['volume'] > df_copia['volume_media'] * 1.2)
        )
        df_copia.loc[condicao_distribuicao, 'distribuicao'] = True
        
        return df_copia

    def detectar_manipulacao(self, df, limiar_volume=2.5, limiar_movimento=1.5):
        """
        Detecta possíveis padrões de manipulação e armadilhas de liquidez
        
        Identificação de padrões como:
        - Armadilhas de liquidez (stop hunts)
        - Falsos breakouts
        - Manipulação de volume
        
        Args:
            df: DataFrame com dados OHLCV
            limiar_volume: multiplicador mínimo do volume médio para considerar anormal
            limiar_movimento: multiplicador do ATR para considerar movimento anormal
            
        Returns:
            list: Lista de padrões suspeitos detectados com detalhes
        """
        padroes_suspeitos = []
        
        # Precisamos de pelo menos 30 candles para análise confiável
        if len(df) < 30:
            return padroes_suspeitos
        
        # Calcular valores de referência
        df_analise = df.copy()
        
        # Volume médio (20 períodos)
        df_analise['volume_media'] = df_analise['volume'].rolling(window=20).mean()
        df_analise['volume_ratio'] = df_analise['volume'] / df_analise['volume_media']
        
        # Volatilidade média (ATR)
        if 'atr' not in df_analise.columns:
            # Calcular ATR se não existir
            tr1 = df_analise['high'] - df_analise['low']
            tr2 = abs(df_analise['high'] - df_analise['close'].shift())
            tr3 = abs(df_analise['low'] - df_analise['close'].shift())
            
            tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
            df_analise['atr'] = tr.rolling(window=14).mean()
            df_analise['atr_percent'] = df_analise['atr'] / df_analise['close'] * 100
        
        # Variação percentual entre candles
        df_analise['pct_change'] = df_analise['close'].pct_change() * 100
        
        # 1. Detectar "Stop Hunts" / Armadilhas de Liquidez
        for i in range(5, len(df_analise) - 1):
            # Verifique se existe um movimento forte seguido por reversão rápida
            movimento_preco = abs(df_analise['pct_change'].iloc[i])
            movimento_seguinte = df_analise['pct_change'].iloc[i+1]
            volume_anormal = df_analise['volume_ratio'].iloc[i] > limiar_volume
            volatilidade_anormal = movimento_preco > df_analise['atr_percent'].iloc[i] * limiar_movimento
            
            # Condição para stop hunt: movimento forte, volume alto, rápida reversão
            reversao_rapida = movimento_preco * movimento_seguinte < 0  # Sinais opostos
            reversao_significativa = abs(movimento_seguinte) > movimento_preco * 0.5
            
            if volume_anormal and volatilidade_anormal and reversao_rapida and reversao_significativa:
                # Determinar se é armadilha de alta ou baixa
                if df_analise['pct_change'].iloc[i] < 0:  # Queda seguida de alta
                    tipo = "armadilha_baixa"  # Caça de stops de vendas
                    descricao = "Armadilha de baixa (caça de stops de vendas)"
                else:  # Alta seguida de queda
                    tipo = "armadilha_alta"  # Caça de stops de compras
                    descricao = "Armadilha de alta (caça de stops de compras)"
                
                # Calcular força do padrão
                forca = (df_analise['volume_ratio'].iloc[i] / limiar_volume) * (movimento_preco / (df_analise['atr_percent'].iloc[i] * limiar_movimento))
                
                padroes_suspeitos.append({
                    'tipo': tipo,
                    'posicao': i,
                    'preco': df_analise['close'].iloc[i],
                    'volume': df_analise['volume'].iloc[i],
                    'movimento': df_analise['pct_change'].iloc[i],
                    'reversao': df_analise['pct_change'].iloc[i+1],
                    'descricao': descricao,
                    'forca': min(1.0, forca),  # Limitar a 1.0
                    'candles_atras': len(df_analise) - 1 - i
                })
        
        # 2. Detectar Falsos Breakouts
        for i in range(20, len(df_analise) - 1):
            # Encontrar níveis significativos (máximos e mínimos recentes)
            max_recente = df_analise['high'].iloc[i-20:i].max()
            min_recente = df_analise['low'].iloc[i-20:i].min()
            
            # Verificar breakout de alta falso (penetra acima do máximo mas fecha abaixo)
            if (df_analise['high'].iloc[i] > max_recente * 1.001 and  # Quebra ligeiramente o nível
                df_analise['close'].iloc[i] < max_recente and  # Fecha abaixo do nível
                df_analise['close'].iloc[i+1] < df_analise['open'].iloc[i]):  # Próximo candle confirma fracasso
                
                padroes_suspeitos.append({
                    'tipo': "falso_breakout_alta",
                    'posicao': i,
                    'nivel': max_recente,
                    'descricao': "Falso breakout de alta (quebra de resistência falha)",
                    'forca': min(1.0, abs(df_analise['high'].iloc[i] / max_recente - 1) * 50),
                    'candles_atras': len(df_analise) - 1 - i
                })
            
            # Verificar breakout de baixa falso (penetra abaixo do mínimo mas fecha acima)
            if (df_analise['low'].iloc[i] < min_recente * 0.999 and  # Quebra ligeiramente o nível
                df_analise['close'].iloc[i] > min_recente and  # Fecha acima do nível
                df_analise['close'].iloc[i+1] > df_analise['open'].iloc[i]):  # Próximo candle confirma fracasso
                
                padroes_suspeitos.append({
                    'tipo': "falso_breakout_baixa",
                    'posicao': i,
                    'nivel': min_recente,
                    'descricao': "Falso breakout de baixa (quebra de suporte falha)",
                    'forca': min(1.0, abs(df_analise['low'].iloc[i] / min_recente - 1) * 50),
                    'candles_atras': len(df_analise) - 1 - i
                })
        
        # 3. Detectar picos de volume suspeitos sem movimentação de preço
        for i in range(20, len(df_analise)):
            # Volume extremamente alto
            volume_extremo = df_analise['volume_ratio'].iloc[i] > limiar_volume * 2
            # Pouca movimentação de preço
            movimento_pequeno = abs(df_analise['pct_change'].iloc[i]) < df_analise['atr_percent'].iloc[i] * 0.5
            
            if volume_extremo and movimento_pequeno:
                padroes_suspeitos.append({
                    'tipo': "volume_suspeito",
                    'posicao': i,
                    'volume': df_analise['volume'].iloc[i],
                    'volume_ratio': df_analise['volume_ratio'].iloc[i],
                    'descricao': "Volume anormalmente alto sem movimentação significativa de preço",
                    'forca': min(1.0, df_analise['volume_ratio'].iloc[i] / (limiar_volume * 2)),
                    'candles_atras': len(df_analise) - 1 - i
                })
        
        # Filtrar apenas padrões recentes (últimos 10 candles), mais relevantes para decisões
        padroes_recentes = [p for p in padroes_suspeitos if p['candles_atras'] <= 10]
        
        return padroes_recentes

    def classificar_padrao_mercado(self, df, janela=20):
        """
        Classifica o padrão de mercado atual usando análise estatística e regras 
        (simulando um modelo de machine learning)
        
        Padrões classificados:
        - Tendência de alta/baixa
        - Consolidação
        - Acumulação/distribuição
        - Compressão de volatilidade
        - Breakout iminente
        
        Args:
            df: DataFrame com dados OHLCV
            janela: tamanho da janela para análise
            
        Returns:
            dict: Classificação do padrão com confiança e métricas
        """
        from scipy import stats
        import numpy as np
        
        # Garantir dados suficientes
        if len(df) < janela + 10:
            return {'padrao': 'indeterminado', 'confianca': 0.0}
        
        # Extrair janela mais recente
        recente = df.iloc[-janela:].copy()
        
        # Calcular métricas sobre esta janela
        metricas = {}
        
        # 1. Tendência (inclinação da linha de regressão linear)
        x = np.arange(len(recente))
        y = recente['close'].values
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        
        trend_strength = abs(r_value)  # Força da tendência pela correlação
        trend_direction = np.sign(slope)  # Direção da tendência
        
        metricas['trend_strength'] = trend_strength
        metricas['trend_direction'] = trend_direction
        
        # 2. Volatilidade
        metricas['volatilidade'] = recente['atr_percent'].mean() if 'atr_percent' in recente.columns else recente['close'].pct_change().std() * 100
        
        # 3. Compressão de volatilidade (redução contínua)
        if 'atr_percent' in recente.columns:
            atr_inicio = recente['atr_percent'].iloc[:5].mean()
            atr_fim = recente['atr_percent'].iloc[-5:].mean()
            metricas['compressao_volatilidade'] = atr_inicio / max(atr_fim, 0.001) - 1  # % de redução
        else:
            metricas['compressao_volatilidade'] = 0
        
        # 4. Volume
        metricas['volume_trend'] = recente['volume'].iloc[-5:].mean() / recente['volume'].iloc[:-5].mean()
        
        # 5. RSI
        if 'rsi' in recente.columns:
            metricas['rsi_atual'] = recente['rsi'].iloc[-1]
            metricas['rsi_max'] = recente['rsi'].iloc[-5:].max()
            metricas['rsi_min'] = recente['rsi'].iloc[-5:].min()
            metricas['rsi_range'] = metricas['rsi_max'] - metricas['rsi_min']
        else:
            metricas['rsi_atual'] = 50  # Valor neutro
            metricas['rsi_range'] = 0
        
        # 6. Bandas de Bollinger
        bb_dentro = 1.0
        if all(col in recente.columns for col in ['bb_upper', 'bb_middle', 'bb_lower']):
            # Largura das bandas
            recente['bb_width'] = (recente['bb_upper'] - recente['bb_lower']) / recente['bb_middle']
            
            bb_width_inicio = recente['bb_width'].iloc[:5].mean()
            bb_width_fim = recente['bb_width'].iloc[-5:].mean()
            
            metricas['banda_compressao'] = bb_width_inicio / max(bb_width_fim, 0.001) - 1
            
            # % do preço dentro das bandas
            dentro_bandas = ((recente['close'] <= recente['bb_upper']) & 
                            (recente['close'] >= recente['bb_lower'])).mean()
            
            metricas['bb_contencao'] = dentro_bandas
            bb_dentro = dentro_bandas
        else:
            metricas['banda_compressao'] = 0
            metricas['bb_contencao'] = 1
        
        # 7. Níveis de médias móveis
        if all(col in recente.columns for col in [f'ma_{MA_CURTA}', f'ma_{MA_MEDIA}', f'ma_{MA_LONGA}']):
            ultimo = recente.iloc[-1]
            
            # Verificar alinhamento das MAs
            ma_alinhadas_alta = ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}'] > ultimo[f'ma_{MA_LONGA}']
            ma_alinhadas_baixa = ultimo[f'ma_{MA_CURTA}'] < ultimo[f'ma_{MA_MEDIA}'] < ultimo[f'ma_{MA_LONGA}']
            
            metricas['ma_alinhamento'] = 1 if ma_alinhadas_alta else -1 if ma_alinhadas_baixa else 0
            
            # Calcular distância entre MAs (compressão = possível breakout iminente)
            dist_ma_curta_media = abs(ultimo[f'ma_{MA_CURTA}'] - ultimo[f'ma_{MA_MEDIA}']) / ultimo[f'ma_{MA_MEDIA}'] * 100
            dist_ma_media_longa = abs(ultimo[f'ma_{MA_MEDIA}'] - ultimo[f'ma_{MA_LONGA}']) / ultimo[f'ma_{MA_LONGA}'] * 100
            
            metricas['ma_compressao'] = dist_ma_curta_media < 0.2 and dist_ma_media_longa < 0.3
        else:
            metricas['ma_alinhamento'] = 0
            metricas['ma_compressao'] = False
        
        # Calcular scores para cada padrão
        scores = {}
        
        # 1. Tendência de alta
        scores['tendencia_alta'] = (
            (trend_direction > 0) * 0.4 +
            (trend_strength > 0.7) * 0.3 +
            (metricas.get('volume_trend', 0) >= 1.0) * 0.2 +
            (metricas.get('ma_alinhamento', 0) == 1) * 0.3 +
            (metricas.get('rsi_atual', 50) > 50) * 0.1
        ) / 1.3  # Normalizar para 0-1
        
        # 2. Tendência de baixa
        scores['tendencia_baixa'] = (
            (trend_direction < 0) * 0.4 +
            (trend_strength > 0.7) * 0.3 +
            (metricas.get('volume_trend', 0) >= 1.0) * 0.2 +
            (metricas.get('ma_alinhamento', 0) == -1) * 0.3 +
            (metricas.get('rsi_atual', 50) < 50) * 0.1
        ) / 1.3  # Normalizar para 0-1
        
        # 3. Consolidação (range bound)
        scores['consolidacao'] = (
            (trend_strength < 0.3) * 0.5 +
            (metricas.get('volatilidade', 0) < 0.3) * 0.3 +
            (bb_dentro > 0.8) * 0.4 +
            (metricas.get('rsi_range', 0) < 20) * 0.3
        ) / 1.5  # Normalizar para 0-1
        
        # 4. Acumulação
        scores['acumulacao'] = (
            (trend_strength < 0.4) * 0.3 +
            (metricas.get('volume_trend', 0) > 1.2) * 0.4 +
            (metricas.get('rsi_atual', 50) < 45) * 0.2 +
            (metricas.get('volatilidade', 0) < 0.3) * 0.2
        ) / 1.1  # Normalizar para 0-1
        
        # 5. Distribuição
        scores['distribuicao'] = (
            (trend_strength < 0.4) * 0.3 +
            (metricas.get('volume_trend', 0) > 1.2) * 0.4 +
            (metricas.get('rsi_atual', 50) > 55) * 0.2 +
            (metricas.get('volatilidade', 0) < 0.3) * 0.2
        ) / 1.1  # Normalizar para 0-1
        
        # 6. Compressão de volatilidade
        scores['compressao_volatilidade'] = (
            (metricas.get('compressao_volatilidade', 0) > 0.3) * 0.5 +
            (metricas.get('banda_compressao', 0) > 0.3) * 0.4 +
            (bb_dentro > 0.9) * 0.3 +
            (trend_strength < 0.3) * 0.2
        ) / 1.4  # Normalizar para 0-1
        
        # 7. Breakout iminente
        scores['breakout_iminente'] = (
            (metricas.get('compressao_volatilidade', 0) > 0.3) * 0.4 +
            (metricas.get('ma_compressao', False)) * 0.3 +
            (recente['volume'].iloc[-3:].mean() > recente['volume'].iloc[:-3].mean() * 1.2) * 0.4 +
            (bb_dentro > 0.9) * 0.3 +
            (metricas.get('volatilidade', 0) < metricas.get('volatilidade', 100) * 0.7) * 0.3
        ) / 1.7  # Normalizar para 0-1
        
        # Selecionar o padrão mais provável
        melhor_padrao = max(scores.items(), key=lambda x: x[1])
        
        # Filtrar padrões com confiança mínima
        if melhor_padrao[1] < 0.5:
            return {
                'padrao': 'indeterminado',
                'confianca': melhor_padrao[1],
                'metricas': metricas,
                'scores': scores
            }
        
        # Retornar resultado completo
        return {
            'padrao': melhor_padrao[0],
            'confianca': melhor_padrao[1],
            'metricas': metricas,
            'scores': scores
        }
    
    def modelar_suporte_resistencia_avancado(self, df, n_niveis=5, sensibilidade=0.1):
        """
        Implementa análise avançada de níveis de suporte e resistência usando agrupamento estatístico
        
        Args:
            df: DataFrame com dados OHLCV
            n_niveis: número máximo de níveis para retornar em cada direção
            sensibilidade: parâmetro para ajustar sensibilidade da detecção (0.05-0.2 recomendado)
            
        Returns:
            dict: Dicionário com níveis de suporte e resistência e suas características
        """
        import numpy as np
        from scipy.signal import argrelextrema
        from sklearn.cluster import DBSCAN
        
        # Precisamos de dados suficientes
        if len(df) < 100:
            return {
                'suportes': [],
                'resistencias': [],
                'suportes_fortes': [],
                'resistencias_fortes': []
            }
        
        # Criar cópia do dataframe
        df_sr = df.copy().reset_index(drop=True)
        
        # 1. Identificar extremos locais (picos e vales)
        # Usar janela de 5 candles para extremos locais
        max_idx = argrelextrema(df_sr['high'].values, np.greater, order=5)[0]
        min_idx = argrelextrema(df_sr['low'].values, np.less, order=5)[0]
        
        # Extrair preços destes extremos
        max_prices = df_sr['high'].iloc[max_idx].values
        min_prices = df_sr['low'].iloc[min_idx].values
        
        # 2. Identificar clusters usando DBSCAN
        # Para resistências (máximos)
        if len(max_prices) > 1:
            # Normalizar para escala 0-1 para facilitar ajuste do eps
            max_norm = (max_prices - np.min(max_prices)) / (np.max(max_prices) - np.min(max_prices))
            
            # Aplicar DBSCAN para agrupar preços similares
            # Ajustar eps com base no parâmetro de sensibilidade
            max_clustering = DBSCAN(eps=sensibilidade, min_samples=2).fit(max_norm.reshape(-1, 1))
            
            max_labels = max_clustering.labels_
            max_clusters = {}
            
            # Agrupar preços por cluster
            for i, label in enumerate(max_labels):
                if label != -1:  # Ignorar pontos classificados como ruído
                    if label not in max_clusters:
                        max_clusters[label] = []
                    max_clusters[label].append((max_idx[i], max_prices[i]))
        else:
            max_clusters = {}
        
        # Para suportes (mínimos)
        if len(min_prices) > 1:
            # Normalizar
            min_norm = (min_prices - np.min(min_prices)) / (np.max(min_prices) - np.min(min_prices))
            
            # Aplicar DBSCAN
            min_clustering = DBSCAN(eps=sensibilidade, min_samples=2).fit(min_norm.reshape(-1, 1))
            
            min_labels = min_clustering.labels_
            min_clusters = {}
            
            # Agrupar preços por cluster
            for i, label in enumerate(min_labels):
                if label != -1:  # Ignorar ruído
                    if label not in min_clusters:
                        min_clusters[label] = []
                    min_clusters[label].append((min_idx[i], min_prices[i]))
        else:
            min_clusters = {}
        
        # 3. Calcular preço representativo para cada cluster
        resistencias = []
        for label, pontos in max_clusters.items():
            if len(pontos) < 2:
                continue  # Ignorar clusters com apenas um ponto
            
            # Extrair índices e preços
            indices = [p[0] for p in pontos]
            precos = [p[1] for p in pontos]
            
            # Calcular média dos preços no cluster
            preco_medio = np.mean(precos)
            
            # Calcular força baseado no número de toques e volumes
            volumes = [df_sr['volume'].iloc[idx] for idx in indices]
            forca = len(indices) * (1 + np.mean(volumes) / df_sr['volume'].mean())
            
            resistencias.append({
                'preco': preco_medio,
                'toques': len(indices),
                'forca': forca,
                'indice_ultimo_toque': max(indices)
            })
        
        suportes = []
        for label, pontos in min_clusters.items():
            if len(pontos) < 2:
                continue
            
            # Extrair índices e preços
            indices = [p[0] for p in pontos]
            precos = [p[1] for p in pontos]
            
            # Calcular média dos preços no cluster
            preco_medio = np.mean(precos)
            
            # Calcular força baseado no número de toques e volumes
            volumes = [df_sr['volume'].iloc[idx] for idx in indices]
            forca = len(indices) * (1 + np.mean(volumes) / df_sr['volume'].mean())
            
            suportes.append({
                'preco': preco_medio,
                'toques': len(indices),
                'forca': forca,
                'indice_ultimo_toque': max(indices)
            })
        
        # 4. Ordenar por força e filtrar para os mais relevantes
        resistencias = sorted(resistencias, key=lambda x: x['forca'], reverse=True)[:n_niveis]
        suportes = sorted(suportes, key=lambda x: x['forca'], reverse=True)[:n_niveis]
        
        # 5. Identificar níveis de S/R "forte" (toques múltiplos e volumes significativos)
        suportes_fortes = [s for s in suportes if s['toques'] >= 3 or s['forca'] > 5]
        resistencias_fortes = [r for r in resistencias if r['toques'] >= 3 or r['forca'] > 5]
        
        # 6. Adicionar metadados para cada nível
        preco_atual = df_sr['close'].iloc[-1]
        
        for nivel in suportes + resistencias:
            # Calcular distância do preço atual
            distancia_pct = abs(nivel['preco'] - preco_atual) / preco_atual * 100
            nivel['distancia_pct'] = distancia_pct
            
            # Classificar por proximidade
            if distancia_pct < 1.0:
                nivel['proximidade'] = 'muito_proximo'
            elif distancia_pct < 3.0:
                nivel['proximidade'] = 'proximo'
            else:
                nivel['proximidade'] = 'distante'
                
            # Classificar por recência (qtd de candles desde o último toque)
            candles_desde_toque = len(df_sr) - 1 - nivel['indice_ultimo_toque']
            nivel['candles_desde_toque'] = candles_desde_toque
            
            if candles_desde_toque <= 10:
                nivel['recencia'] = 'recente'
            elif candles_desde_toque <= 30:
                nivel['recencia'] = 'medio'
            else:
                nivel['recencia'] = 'antigo'
        
        # 7. Criar heatmap (densidade) de zonas de suporte e resistência
        # Vamos usar uma abordagem simplificada de heatmap em vez de visualização
        range_preco = df_sr['high'].max() - df_sr['low'].min()
        n_bins = 100
        bin_size = range_preco / n_bins
        
        heatmap = np.zeros(n_bins)
        preco_min = df_sr['low'].min()
        
        # Funções para converter preço<->bin
        def preco_para_bin(preco):
            return min(n_bins-1, max(0, int((preco - preco_min) / bin_size)))
        
        def bin_para_preco(bin_idx):
            return preco_min + bin_idx * bin_size
        
        # Calcular heatmap baseado em preços históricos e volumes
        for i in range(len(df_sr)):
            bin_low = preco_para_bin(df_sr['low'].iloc[i])
            bin_high = preco_para_bin(df_sr['high'].iloc[i])
            volume_normalizado = df_sr['volume'].iloc[i] / df_sr['volume'].mean()
            
            # Adicionar ao heatmap
            for bin_idx in range(bin_low, bin_high+1):
                heatmap[bin_idx] += volume_normalizado / (bin_high - bin_low + 1)
        
        # 8. Identificar zonas de alta densidade no heatmap
        zonas_heatmap = []
        threshold = np.mean(heatmap) * 2  # Zonas com pelo menos 2x a densidade média
        
        i = 0
        while i < n_bins:
            if heatmap[i] > threshold:
                inicio = i
                while i < n_bins and heatmap[i] > threshold:
                    i += 1
                fim = i - 1
                
                zonas_heatmap.append({
                    'preco_inicio': bin_para_preco(inicio),
                    'preco_fim': bin_para_preco(fim),
                    'densidade': np.mean(heatmap[inicio:fim+1]),
                    'largura_pct': (bin_para_preco(fim) - bin_para_preco(inicio)) / preco_atual * 100
                })
            i += 1
        
        return {
            'suportes': suportes,
            'resistencias': resistencias,
            'suportes_fortes': suportes_fortes,
            'resistencias_fortes': resistencias_fortes,
            'preco_atual': preco_atual,
            'zonas_heatmap': zonas_heatmap
        }
    def identificar_suporte_resistencia(self, df):
        """Identificar zonas de suporte e resistência com método aprimorado"""
        if len(df) < 100:  # Aumentado para ter dados mais confiáveis
            return
        
        # Usar dados mais extensos para S/R
        df_sr = df.iloc[-100:].copy()
        
        # Encontrar picos (máximos locais) com janela maior
        resistencias = []
        for i in range(3, len(df_sr) - 3):
            if (df_sr['high'].iloc[i] > df_sr['high'].iloc[i-1] and 
                df_sr['high'].iloc[i] > df_sr['high'].iloc[i-2] and
                df_sr['high'].iloc[i] > df_sr['high'].iloc[i-3] and
                df_sr['high'].iloc[i] > df_sr['high'].iloc[i+1] and
                df_sr['high'].iloc[i] > df_sr['high'].iloc[i+2] and
                df_sr['high'].iloc[i] > df_sr['high'].iloc[i+3]):
                resistencias.append(df_sr['high'].iloc[i])
        
        # Encontrar vales (mínimos locais) com janela maior
        suportes = []
        for i in range(3, len(df_sr) - 3):
            if (df_sr['low'].iloc[i] < df_sr['low'].iloc[i-1] and 
                df_sr['low'].iloc[i] < df_sr['low'].iloc[i-2] and
                df_sr['low'].iloc[i] < df_sr['low'].iloc[i-3] and
                df_sr['low'].iloc[i] < df_sr['low'].iloc[i+1] and
                df_sr['low'].iloc[i] < df_sr['low'].iloc[i+2] and
                df_sr['low'].iloc[i] < df_sr['low'].iloc[i+3]):
                suportes.append(df_sr['low'].iloc[i])
        
        # Agrupar níveis próximos com margem reduzida para maior precisão
        self.zonas_sr = {
            "suportes": self._agrupar_niveis(suportes, margem_percentual=0.08),
            "resistencias": self._agrupar_niveis(resistencias, margem_percentual=0.08)
        }
        
        # Classificar por força (frequência de toque)
        self._classificar_sr_por_forca(df)

    def _agrupar_niveis(self, niveis, margem_percentual=0.1):
        """Agrupar níveis de preço próximos com margem ajustável"""
        if not niveis:
            return []
        
        # Ordenar níveis
        niveis_ordenados = sorted(niveis)
        grupos = []
        grupo_atual = [niveis_ordenados[0]]
        
        for i in range(1, len(niveis_ordenados)):
            ultimo_nivel = grupo_atual[-1]
            nivel_atual = niveis_ordenados[i]
            
            if (nivel_atual - ultimo_nivel) / ultimo_nivel <= margem_percentual / 100:
                # Adicionar ao grupo atual
                grupo_atual.append(nivel_atual)
            else:
                # Criar um novo grupo
                grupos.append(grupo_atual)
                grupo_atual = [nivel_atual]
        
        # Adicionar o último grupo
        if grupo_atual:
            grupos.append(grupo_atual)
        
        # Calcular média de cada grupo
        return [sum(grupo) / len(grupo) for grupo in grupos]

    def _classificar_sr_por_forca(self, df):
        """Classificar zonas S/R por força (frequência de toques)"""
        precos = list(df['high']) + list(df['low'])
        
        # Contar "toques" próximos a cada nível
        forca_suportes = []
        for suporte in self.zonas_sr["suportes"]:
            toques = sum(1 for preco in precos if abs(preco - suporte) / suporte <= 0.1 / 100)
            forca_suportes.append((suporte, toques))
        
        forca_resistencias = []
        for resistencia in self.zonas_sr["resistencias"]:
            toques = sum(1 for preco in precos if abs(preco - resistencia) / resistencia <= 0.1 / 100)
            forca_resistencias.append((resistencia, toques))
        
        # Ordenar por força (número de toques)
        forca_suportes.sort(key=lambda x: x[1], reverse=True)
        forca_resistencias.sort(key=lambda x: x[1], reverse=True)
        
        # Guardar apenas os 5 níveis mais fortes, com seus valores de força
        self.zonas_sr["suportes_fortes"] = forca_suportes[:5]
        self.zonas_sr["resistencias_fortes"] = forca_resistencias[:5]

    def esta_proximo_sr(self, preco, margem_estreita=False):
        """Verificar se o preço está próximo de uma zona de S/R"""
        # Margem mais estreita para entrada, mais ampla para alertas
        margem = 0.05 if margem_estreita else 0.1  # % de distância
        
        # Verificar suportes fortes primeiro
        if "suportes_fortes" in self.zonas_sr:
            for suporte, forca in self.zonas_sr["suportes_fortes"]:
                if abs(preco - suporte) / suporte <= margem / 100:
                    return True, f"Próximo ao suporte em {suporte:.2f} (força: {forca})"
        
        # Verificar resistências fortes
        if "resistencias_fortes" in self.zonas_sr:
            for resistencia, forca in self.zonas_sr["resistencias_fortes"]:
                if abs(preco - resistencia) / resistencia <= margem / 100:
                    return True, f"Próximo à resistência em {resistencia:.2f} (força: {forca})"
        
        # Verificar suportes normais
        for suporte in self.zonas_sr["suportes"]:
            if abs(preco - suporte) / suporte <= margem / 100:
                return True, f"Próximo ao suporte em {suporte:.2f}"
        
        # Verificar resistências normais
        for resistencia in self.zonas_sr["resistencias"]:
            if abs(preco - resistencia) / resistencia <= margem / 100:
                return True, f"Próximo à resistência em {resistencia:.2f}"
        
        return False, ""

    def verificar_horario_operacao(self):
        """Verificar se o horário atual é adequado para operações"""
        horario_atual = datetime.now(timezone.utc).strftime("%H:%M")
        hora_atual_utc = datetime.now(timezone.utc).hour
        
        # Adicionar restrições para períodos de madrugada com liquidez muito baixa
        periodos_baixa_liquidez = [
            {'inicio': '01:00', 'fim': '03:30'},  # Período de liquidez extremamente baixa
        ]
        
        # Períodos a evitar (combinando os existentes com os novos)
        todos_periodos = HORARIOS_EVITAR + periodos_baixa_liquidez
        
        for periodo in todos_periodos:
            if periodo['inicio'] <= horario_atual <= periodo['fim']:
                return False, f"Horário não recomendado para operações: {horario_atual} UTC"
        
        return True, ""

    def check_signal(self, df):
        """Verificar se há sinal de entrada com múltiplos filtros e sistema de pontuação flexível"""
        pontuacao = 0
        motivos = []
        contra_indicacoes = []
        forca_sinal = "FRACO"  # Padrão
        criterios_atendidos = 0
        criterios_total = 0
        
        # Substitua seus pesos atuais por:
        self.config = {
            "peso_tendencia": 0.5,     # Baseado na melhor combinação dos seus testes
            "peso_volume": 2.1,        # Volume parece ter importância
            "peso_rsi": 0.8,           # RSI com peso moderado
            "peso_cruzamento": 1.2,    # Cruzamentos com peso moderado
            "peso_alinhamento": 1.9,   # Alinhamento parece importante
            "min_score_tecnico": 5.5   # Aumentando para ser mais seletivo
        }

        # Verificar e aplicar ajustes para período de baixa liquidez
        modo_baixa_liquidez, criterios_noturnos = self.ajustar_criterios_noturnos()
        
        # Verificar contexto de mercado para ajustar critérios
        criterios_contexto = self.ajustar_criterios_por_contexto(df)
        min_score = criterios_contexto['min_pontuacao'] if criterios_contexto else self.config.get("min_score_tecnico", 4.0)
        volume_minimo_pct = criterios_contexto['volume_minimo_pct'] if criterios_contexto else VOLUME_MINIMO_PERCENTUAL
        ma_alinhamento_obrigatorio = criterios_contexto['ma_alinhamento_obrigatorio'] if criterios_contexto else True
        
        # Aplicar critérios noturnos se estiver em período de baixa liquidez
        if modo_baixa_liquidez and criterios_noturnos:
            min_score = criterios_noturnos['pontuacao_minima']
            volume_minimo_pct = criterios_noturnos['volume_minimo_pct']

        # Incorporar análise macro se ativada
        scores_macro = {}
        if USAR_ANALISE_MACRO:
            try:
                # Obter análises macro
                sentimento_score, sentimento_desc, fear_greed_index = self.analisar_sentimento_mercado()
                correlacao_score, correlacao_desc, btc_correlation, eth_correlation = self.analisar_correlacoes()
                dominancia_score, dominancia_desc, btc_dominance, market_cap_total = self.analisar_dominancia_btc()
                
                # Salvar dados para histórico
                self.salvar_analise_macro(
                    fear_greed_index, 
                    btc_dominance, 
                    market_cap_total, 
                    btc_correlation,
                    eth_correlation,
                    sentimento_score, 
                    correlacao_score, 
                    dominancia_score
                )
                
                # Registrar scores para uso no fator final
                scores_macro['sentimento'] = sentimento_score
                scores_macro['correlacao'] = correlacao_score
                scores_macro['dominancia'] = dominancia_score
                
                # Adicionar informações às justificativas
                if sentimento_score > 1.05:
                    motivos.append(f"Sentimento: {sentimento_desc}")
                elif sentimento_score < 0.95:
                    contra_indicacoes.append(f"Sentimento: {sentimento_desc}")
                    
                if correlacao_score > 1.05:
                    motivos.append(f"Correlação: {correlacao_desc}")
                elif correlacao_score < 0.95:
                    contra_indicacoes.append(f"Correlação: {correlacao_desc}")
                    
                if dominancia_score > 1.05:
                    motivos.append(f"Dominância: {dominancia_desc}")
                elif dominancia_score < 0.95:
                    contra_indicacoes.append(f"Dominância: {dominancia_desc}")
            
            except Exception as e:
                self.registrar_log(f"ERRO na análise macro: {str(e)}")
        
        if len(df) < 100:  # Requer mais dados históricos para análise confiável
            return False, "Dados históricos insuficientes para análise confiável"
        
        # Verificar horário de operação
        horario_ok, msg_horario = self.verificar_horario_operacao()
        if not horario_ok:
            contra_indicacoes.append(msg_horario)
            pontuacao -= 1.2  # Penalização forte para horário inadequado
        
        # Limitar número de operações diárias
        dia_atual = datetime.now().day
        if dia_atual != self.ultima_verificacao_dia:
            self.operacoes_hoje = 0
            self.ultima_verificacao_dia = dia_atual
            
        if self.operacoes_hoje >= MAX_OPERACOES_DIA:
            return False, f"Limite de operações diárias atingido ({MAX_OPERACOES_DIA})"
        
        # Classificar padrão de mercado atual
        classificacao = self.classificar_padrao_mercado(df)

        # Ajustar pontuação baseado no padrão detectado
        if classificacao['padrao'] != 'indeterminado':
            # Ajustar com base no tipo de padrão e sua confiança
            confianca = classificacao['confianca']
            
            if classificacao['padrao'] == 'tendencia_alta':
                motivos.append(f"Padrão: Tendência de alta (conf: {confianca:.2f})")
                pontuacao += confianca * 1.5
                criterios_atendidos += 1
                
            elif classificacao['padrao'] == 'acumulacao':
                motivos.append(f"Padrão: Acumulação detectada (conf: {confianca:.2f})")
                pontuacao += confianca * 1.0
                criterios_atendidos += 1
                
            elif classificacao['padrao'] == 'breakout_iminente':
                motivos.append(f"Padrão: Breakout iminente (conf: {confianca:.2f})")
                pontuacao += confianca * 1.2
                criterios_atendidos += 1
                
            elif classificacao['padrao'] == 'compressao_volatilidade':
                motivos.append(f"Padrão: Compressão de volatilidade (conf: {confianca:.2f})")
                pontuacao += confianca * 0.5  # Menor impacto - pode ser breakout para cima ou para baixo
                
            elif classificacao['padrao'] == 'consolidacao':
                motivos.append(f"Padrão: Mercado em consolidação (conf: {confianca:.2f})")
                # Neutro - não altera pontuação
                
            elif classificacao['padrao'] == 'distribuicao':
                contra_indicacoes.append(f"Padrão: Distribuição detectada (conf: {confianca:.2f})")
                pontuacao -= confianca * 1.5
                
            elif classificacao['padrao'] == 'tendencia_baixa':
                contra_indicacoes.append(f"Padrão: Tendência de baixa (conf: {confianca:.2f})")
                pontuacao -= confianca * 2.0
        
        criterios_total += 1  # Contar padrão de mercado como um critério
            
        # Dados mais recentes do mercado
        penultimo = df.iloc[-2]
        ultimo = df.iloc[-1]
        
        # 1. Verificar ATR (volatilidade suficiente)
        atr_atual_percent = ultimo.get('atr_percent', 0)
        atr_minimo_ajustado = ATR_MINIMO_OPERACAO * 1.2
        mercado_ativo = atr_atual_percent >= atr_minimo_ajustado
        
        # Filtrar alta volatilidade
        if atr_atual_percent > ATR_MINIMO_OPERACAO * 3:
            contra_indicacoes.append(f"Volatilidade excessiva: ATR {atr_atual_percent:.2f}%")
            pontuacao -= 1
        
        if not mercado_ativo:
            contra_indicacoes.append(f"Volatilidade insuficiente: ATR {atr_atual_percent:.2f}% (mín: {atr_minimo_ajustado:.2f}%)")
            pontuacao -= 1.2  # Penalização mais forte
        else:
            motivos.append(f"Volatilidade adequada: ATR {atr_atual_percent:.2f}%")
            pontuacao += 0.5
            criterios_atendidos += 1
        
        criterios_total += 1  # Contar volatilidade como um critério
        
        # 2. Verificar inclinação da MA Longa (tendência de fundo)
        inclinacao_ma_min = 0.02
        if 'ma_longa_inclinacao' in df.columns:
            inclinacao_ma_longa = float(df['ma_longa_inclinacao'].iloc[-1])
            tendencia_alta_forte = inclinacao_ma_longa > inclinacao_ma_min
        else:
            # Fallback para comparação direta de médias móveis
            tendencia_alta_forte = float(ultimo[f'ma_{MA_LONGA}']) > float(penultimo[f'ma_{MA_LONGA}'])
        
        if tendencia_alta_forte:
            motivos.append(f"Tendência de alta na MA{MA_LONGA}: {inclinacao_ma_longa:.3f}%")
            pontuacao += 1.5  # Mais peso para tendência forte
            criterios_atendidos += 1
        elif inclinacao_ma_longa > 0:
            motivos.append(f"Tendência de alta fraca na MA{MA_LONGA}: {inclinacao_ma_longa:.3f}%")
            pontuacao += 0.5
        else:
            contra_indicacoes.append(f"Sem tendência de alta na MA{MA_LONGA}: {inclinacao_ma_longa:.3f}%")
            pontuacao -= 0.9  # Penalizar mais fortemente
        
        criterios_total += 1  # Contar tendência como um critério
        
        # 3. Verificar médias móveis com tolerância
        resultados_ma = self.verificar_mas_com_tolerancia(df)
        cruzamento_para_cima = resultados_ma['cruzamento']
        ma_curta_acima_media = ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}']
        todas_mas_alinhadas = resultados_ma['alinhamento']
        
        if cruzamento_para_cima:
            motivos.append("Cruzamento MA7 > MA25 (sinal de entrada)")
            pontuacao += 2  # Peso importante para cruzamento
            criterios_atendidos += 1
        elif ma_curta_acima_media:
            motivos.append("MA7 acima da MA25 (tendência de curto prazo)")
            pontuacao += 1
            criterios_atendidos += 0.5  # Meio critério
        
        if todas_mas_alinhadas:
            motivos.append("Médias móveis alinhadas (MA7 > MA25 > MA99)")
            pontuacao += 1.5  # Aumentado o peso para médias alinhadas
            criterios_atendidos += 1
        elif ma_alinhamento_obrigatorio:
            # Se alinhamento é obrigatório por contexto mas não está alinhado
            contra_indicacoes.append("Médias móveis não alinhadas")
            pontuacao -= 1.5
        
        criterios_total += 1  # Contar médias móveis como um critério
        
        # 4. Verificar RSI
        rsi_atual = ultimo['rsi']
        rsi_ok = 40 <= rsi_atual <= 60
        rsi_sobrevenda = 30 <= rsi_atual < 40
        
        # Verificar se RSI está subindo nos últimos 3 candles
        rsi_subindo = False
        if len(df) >= 4:
            rsi_3_candles = df['rsi'].iloc[-4:].values
            rsi_subindo = (rsi_3_candles[-1] > rsi_3_candles[-2] > rsi_3_candles[-3])
        
        if rsi_ok:
            motivos.append(f"RSI em zona ótima ({rsi_atual:.2f})")
            pontuacao += 1.5
            criterios_atendidos += 1
        elif rsi_sobrevenda and rsi_subindo:
            motivos.append(f"RSI recuperando de sobrevenda ({rsi_atual:.2f})")
            pontuacao += 1
            criterios_atendidos += 0.5
        elif rsi_subindo:
            motivos.append(f"RSI em tendência de alta ({rsi_atual:.2f})")
            pontuacao += 0.5
        else:
            contra_indicacoes.append(f"RSI desfavorável ({rsi_atual:.2f})")
            pontuacao -= 1  # Penalizar mais o RSI desfavorável
        
        criterios_total += 1  # Contar RSI como um critério
        
        # 5. Verificar volume
        volume_ok = ultimo['volume'] >= ultimo['volume_media'] * (volume_minimo_pct / 100)
        volume_aceitavel = ultimo['volume'] >= ultimo['volume_media'] * 1.1  # 110% da média
        
        if volume_ok:
            motivos.append(f"Volume alto ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
            pontuacao += 1.5  # Aumentado para 1.5
            criterios_atendidos += 1
        elif volume_aceitavel:
            motivos.append(f"Volume aceitável ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
            pontuacao += 0.3
        else:
            contra_indicacoes.append(f"Volume baixo ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
            pontuacao -= 0.9  # Penalizar mais fortemente
        
        criterios_total += 1  # Contar volume como um critério
        
        # 6. Verificar Bandas de Bollinger
        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            preco = ultimo['close']
            bb_lower = ultimo['bb_lower']
            bb_upper = ultimo['bb_upper']
            
            # Proximidade à banda inferior (potencial reversão para cima)
            if preco < bb_lower * 1.01:  # Dentro de 1% da banda inferior
                motivos.append("Preço próximo/abaixo da banda inferior de Bollinger")
                pontuacao += 1
                criterios_atendidos += 0.5
            
            # Evitar entradas próximas à banda superior
            if preco > bb_upper * 0.97:  # Dentro de 3% da banda superior
                contra_indicacoes.append("Preço próximo/acima da banda superior de Bollinger")
                pontuacao -= 0.9  # Penalizar mais fortemente
        
        criterios_total += 0.5  # Contar Bollinger como meio critério
        
        # 7. Verificar suporte e resistência
        sr_modelo = self.modelar_suporte_resistencia_avancado(df)
        
        # Verificar proximidade a suportes fortes (positivo para compras)
        proximo_suporte = False
        for suporte in sr_modelo['suportes_fortes']:
            if suporte['proximidade'] == 'muito_proximo':
                motivos.append(f"Preço próximo a suporte forte em {suporte['preco']:.2f} (força: {suporte['forca']:.1f})")
                pontuacao += min(1.5, suporte['forca'] * 0.2)  # Limitar o bônus
                criterios_atendidos += 0.5
                proximo_suporte = True
                break

        # Verificar proximidade a resistências fortes (negativo para compras)
        proximo_resistencia = False
        for resistencia in sr_modelo['resistencias_fortes']:
            if resistencia['proximidade'] == 'muito_proximo':
                contra_indicacoes.append(f"Preço próximo a resistência forte em {resistencia['preco']:.2f} (força: {resistencia['forca']:.1f})")
                pontuacao -= min(1.5, resistencia['forca'] * 0.2)  # Limitar a penalidade
                proximo_resistencia = True
                break
        
        criterios_total += 0.5  # Contar S/R como meio critério
        
        # 8. Calcular bônus para situações especiais
        bonus_pontuacao, bonus_justificativas = self.calcular_bonus_especiais(df)
        if bonus_pontuacao > 0:
            pontuacao += bonus_pontuacao
            motivos.extend(bonus_justificativas)
            criterios_atendidos += 0.5  # Considerar como meio critério adicional
        
        criterios_total += 0.5  # Contar bônus como meio critério
        
        # 9. Análise de divergências
        divergencias = self.detectar_divergencias(df) or []
        if divergencias:
            for div in divergencias:
                if div['tipo'] == 'positiva':
                    motivos.append(f"Divergência positiva em {div['indicador']} (força: {div['forca']:.1f}%)")
                    pontuacao += 1.5  # Aumentar pontuação significativamente
                    criterios_atendidos += 0.5
                elif div['tipo'] == 'negativa':
                    contra_indicacoes.append(f"Divergência negativa em {div['indicador']} (força: {div['forca']:.1f}%)")
                    pontuacao -= 1.5  # Diminuir pontuação significativamente
        
        criterios_total += 0.5  # Contar divergências como meio critério
        
        # 10. Detecção de manipulação e armadilhas
        manipulacoes = self.detectar_manipulacao(df)
        if manipulacoes:
            for manip in manipulacoes:
                if manip['tipo'] in ['armadilha_baixa', 'falso_breakout_baixa'] and manip['candles_atras'] <= 3:
                    # Armadilha de baixa recente pode ser oportunidade de compra
                    motivos.append(f"Possível armadilha de baixa detectada ({manip['descricao']})")
                    pontuacao += 0.5  # Bônus pequeno
                    criterios_atendidos += 0.5
                    
                elif manip['tipo'] in ['armadilha_alta', 'falso_breakout_alta'] and manip['candles_atras'] <= 3:
                    # Armadilha de alta recente é contra-indicação para compra
                    contra_indicacoes.append(f"Possível armadilha de alta detectada ({manip['descricao']})")
                    pontuacao -= 1.5  # Penalidade significativa
        
        criterios_total += 0.5  # Contar manipulação como meio critério
        
        # 11. Análise de Smart Money e Volume Delta
        df_volume = self.calcular_volume_delta(df)
        ultimo_volume = df_volume.iloc[-1]
        
        if ultimo_volume['acumulacao']:
            motivos.append("Acumulação de volume detectada (pressão compradora)")
            pontuacao += 1.0
            criterios_atendidos += 0.5
        
        if ultimo_volume['distribuicao']:
            contra_indicacoes.append("Distribuição de volume detectada (pressão vendedora)")
            pontuacao -= 1.0
        
        # Análise de Smart Money
        analise_smart = self.analisar_smart_money(df)
        
        if analise_smart['acumulacao_detectada']:
            motivos.append(f"Smart Money: Acumulação detectada (força: {analise_smart['forca_sinal']:.1f})")
            pontuacao += min(1.5, analise_smart['forca_sinal'] * 0.3)  # Limitar a contribuição
            criterios_atendidos += 0.5
        
        if analise_smart['distribuicao_detectada']:
            contra_indicacoes.append(f"Smart Money: Distribuição detectada (força: {analise_smart['forca_sinal']:.1f})")
            pontuacao -= min(1.5, analise_smart['forca_sinal'] * 0.3)  # Limitar a penalidade
        
        criterios_total += 0.5  # Contar volume delta/smart money como meio critério
        
        # Aplicar ajuste da análise macro na pontuação final
        if USAR_ANALISE_MACRO and scores_macro:
            # Calcular média dos scores macro
            macro_score_medio = sum(scores_macro.values()) / len(scores_macro)
            
            # Ajustar pontuação técnica usando o peso definido
            pontuacao_ajustada = pontuacao * (1 - PESO_ANALISE_MACRO) + pontuacao * macro_score_medio * PESO_ANALISE_MACRO
            
            # Registrar ajuste no log
            self.registrar_log(f"Pontuação original: {pontuacao:.2f} | Ajuste macro: {macro_score_medio:.2f} | Pontuação final: {pontuacao_ajustada:.2f}")
            
            # Usar pontuação ajustada
            pontuacao = pontuacao_ajustada
        
        # Normalizar a proporção de critérios atendidos para evitar divisão por zero
        proporcao_criterios = criterios_atendidos / criterios_total if criterios_total > 0 else 0
        
        # Determinar nível de confiança e multiplicador de capital
        nivel_confianca, multiplicador_capital = self.determinar_nivel_confianca(pontuacao, criterios_atendidos, criterios_total)
        
        # Determinar força do sinal com base na pontuação e nível de confiança
        if nivel_confianca == "alta":
            forca_sinal = "FORTE"
        elif nivel_confianca == "média":
            forca_sinal = "MODERADO"
        else:
            forca_sinal = "FRACO"
        
        # Formatação dos motivos/contra-indicações para log
        motivos_txt = ", ".join(motivos)
        contra_indicacoes_txt = ", ".join(contra_indicacoes)
        
        # Mensagem detalhada
        mensagem = f"Análise [{forca_sinal}] - Pontuação: {pontuacao:.1f}/10"
        mensagem += f" | Nível: {nivel_confianca.upper()} (Capital: {multiplicador_capital*100:.0f}%)"
        
        if motivos:
            mensagem += f"\nMotivos: {motivos_txt}"
        if contra_indicacoes:
            mensagem += f"\nContra-indicações: {contra_indicacoes_txt}"
        
        # Determinar se o sinal é válido
        max_contra_indicacoes = 1  # Valor padrão
        if modo_baixa_liquidez and criterios_noturnos:
            max_contra_indicacoes = criterios_noturnos['contra_indicacoes_max']
        
        # Sistema flexível: permitir entrada mesmo com pontuação mais baixa se tiver critérios suficientes
        min_criterios_atendidos = 3  # Pelo menos 3 critérios importantes atendidos
        
        # Adicione este trecho no método check_signal antes da determinação final de sinal_valido

        # Verificar tendência geral do mercado
        tendencia_baixa = False
        if 'ma_longa_inclinacao' in df.columns:
            inclinacao_ma_longa = float(df['ma_longa_inclinacao'].iloc[-1])
            tendencia_baixa = inclinacao_ma_longa < -0.02  # Detecta tendência de baixa
        elif len(df) > MA_LONGA + 10:
            media_longa_atual = df[f'ma_{MA_LONGA}'].iloc[-1]
            media_longa_anterior = df[f'ma_{MA_LONGA}'].iloc[-10]
            tendencia_baixa = media_longa_atual < media_longa_anterior

        # Se estiver em tendência de baixa, ser ainda mais restritivo
        if tendencia_baixa and nivel_confianca != "alta":
            sinal_valido = False
            mensagem += "\n❌ Mercado em tendência de baixa - entrando apenas com sinais muito fortes"
            
        # Verificar se temos um sinal válido baseado no nível de confiança e contexto
        # Determinar se o sinal é válido
        sinal_valido = False

        # Caso 1: Nível de confiança alta ou média
        if nivel_confianca in ["alta", "média"]:
            sinal_valido = len(contra_indicacoes) <= max_contra_indicacoes

        # Caso 2: Nível de confiança baixa mas em contexto favorável (RSI extremo ou suporte forte)
        elif nivel_confianca == "baixa" and (rsi_sobrevenda or proximo_suporte):
            sinal_valido = len(contra_indicacoes) <= max_contra_indicacoes + 1  # Tolerância maior

        # Caso 3: Critérios especiais - divergência positiva forte ou armadilha de baixa
        elif (divergencias and any(d['tipo'] == 'positiva' and d['forca'] > 50 for d in divergencias)) or \
            (manipulacoes and any(m['tipo'] == 'armadilha_baixa' and m['candles_atras'] <= 2 for m in manipulacoes)):
            sinal_valido = pontuacao >= 0  # CAMADA DE RESGATE: apenas exige pontuação não negativa
            mensagem += "\n⚠️ Entrada baseada em critérios especiais (divergência/armadilha)"

        # Substitua completamente as linhas 2991-2996 com:
        elif pontuacao > 4.0:  # Limiar muito mais alto
            # Verificar se ATR é adequado
            if atr_atual_percent >= ATR_MINIMO_OPERACAO * 1.2:  # 20% acima do mínimo
                sinal_valido = True
                mensagem += "\n⚠️ CAMADA DE RESGATE: Entrada com pontuação elevada e ATR adequado"
                self.registrar_log(f"CAMADA RESGATE ATIVADA: Pontuação={pontuacao:.2f}, RSI={rsi_atual:.1f}, ATR%={atr_atual_percent:.2f}%")
            else:
                sinal_valido = False
                mensagem += "\n❌ ATR insuficiente para ativação da camada de resgate"
        
        # Caso 2: Nível de confiança baixa mas em contexto favorável (RSI extremo ou suporte forte)
        elif nivel_confianca == "baixa" and (rsi_sobrevenda or proximo_suporte):
            sinal_valido = len(contra_indicacoes) <= max_contra_indicacoes + 1  # Tolerância maior
        
        # Caso 3: Critérios especiais - divergência positiva forte ou armadilha de baixa
        elif (divergencias and any(d['tipo'] == 'positiva' and d['forca'] > 70 for d in divergencias)) or \
            (manipulacoes and any(m['tipo'] == 'armadilha_baixa' and m['candles_atras'] <= 2 for m in manipulacoes)):
            sinal_valido = True
            mensagem += "\n⚠️ Entrada baseada em critérios especiais (divergência/armadilha)"
        
        # Armazenar informações para uso posterior
        if sinal_valido:
            self.motivo_entrada = motivos_txt
            self.atr_atual = ultimo.get('atr', ultimo['close'] * ATR_MINIMO_OPERACAO / 100)
            self.atr_percent_atual = atr_atual_percent
            self.forca_sinal = forca_sinal
            self.nivel_confianca = nivel_confianca
            self.multiplicador_capital = multiplicador_capital
            return True, mensagem
        
        return False, mensagem

    def calcular_niveis_fibonacci(self, df, tendencia='auto', periodos_swing=50):
        """
        Calcula níveis de Fibonacci baseados na tendência detectada
        
        Args:
            df: DataFrame com dados OHLCV
            tendencia: 'alta', 'baixa' ou 'auto' para detecção automática
            periodos_swing: número de períodos para encontrar swing high/low
            
        Returns:
            dict: Dicionário com níveis Fibonacci e informações adicionais
        """
        # Precisamos de dados suficientes
        if len(df) < periodos_swing:
            return {'erro': 'Dados insuficientes para calcular níveis Fibonacci'}
        
        # Detectar tendência automaticamente se solicitado
        if tendencia == 'auto':
            # Verificar inclinação da média móvel longa
            if f'ma_{MA_LONGA}' in df.columns:
                ma_longa_atual = df[f'ma_{MA_LONGA}'].iloc[-1]
                ma_longa_anterior = df[f'ma_{MA_LONGA}'].iloc[-10]
                
                # Decidir baseado na inclinação da MA longa
                if ma_longa_atual > ma_longa_anterior:
                    tendencia = 'alta'
                else:
                    tendencia = 'baixa'
            else:
                # Verificar se o preço atual é maior que há 20 períodos
                preco_atual = df['close'].iloc[-1]
                preco_anterior = df['close'].iloc[-20]
                
                tendencia = 'alta' if preco_atual > preco_anterior else 'baixa'
        
        # Definir pontos de swing com base na tendência
        if tendencia == 'alta':
            # Em tendência de alta, buscamos da mínima à máxima
            swing_low_preco = df['low'].iloc[-periodos_swing:].min()
            swing_low_idx = df['low'].iloc[-periodos_swing:].idxmin()
            
            # Calcular a máxima após o swing low
            df_apos_swing = df.loc[swing_low_idx:]
            swing_high_preco = df_apos_swing['high'].max()
            
            # Range do movimento
            preco_range = swing_high_preco - swing_low_preco
            
            # Níveis de retração (para correções)
            niveis_retracao = {
                '0.0': swing_high_preco,
                '0.236': swing_high_preco - 0.236 * preco_range,
                '0.382': swing_high_preco - 0.382 * preco_range,
                '0.5': swing_high_preco - 0.5 * preco_range,
                '0.618': swing_high_preco - 0.618 * preco_range,
                '0.786': swing_high_preco - 0.786 * preco_range,
                '1.0': swing_low_preco
            }
            
            # Níveis de extensão (para projeções)
            niveis_extensao = {
                '1.0': swing_high_preco,
                '1.272': swing_high_preco + 0.272 * preco_range,
                '1.414': swing_high_preco + 0.414 * preco_range,
                '1.618': swing_high_preco + 0.618 * preco_range,
                '2.0': swing_high_preco + 1.0 * preco_range,
                '2.618': swing_high_preco + 1.618 * preco_range
            }
            
        else:  # tendencia == 'baixa'
            # Em tendência de baixa, buscamos da máxima à mínima
            swing_high_preco = df['high'].iloc[-periodos_swing:].max()
            swing_high_idx = df['high'].iloc[-periodos_swing:].idxmax()
            
            # Calcular a mínima após o swing high
            df_apos_swing = df.loc[swing_high_idx:]
            swing_low_preco = df_apos_swing['low'].min()
            
            # Range do movimento
            preco_range = swing_high_preco - swing_low_preco
            
            # Níveis de retração (para correções)
            niveis_retracao = {
                '0.0': swing_low_preco,
                '0.236': swing_low_preco + 0.236 * preco_range,
                '0.382': swing_low_preco + 0.382 * preco_range,
                '0.5': swing_low_preco + 0.5 * preco_range,
                '0.618': swing_low_preco + 0.618 * preco_range,
                '0.786': swing_low_preco + 0.786 * preco_range,
                '1.0': swing_high_preco
            }
            
            # Níveis de extensão (para projeções)
            niveis_extensao = {
                '1.0': swing_low_preco,
                '1.272': swing_low_preco - 0.272 * preco_range,
                '1.414': swing_low_preco - 0.414 * preco_range,
                '1.618': swing_low_preco - 0.618 * preco_range,
                '2.0': swing_low_preco - 1.0 * preco_range,
                '2.618': swing_low_preco - 1.618 * preco_range
            }
        
        # Verificar níveis próximos ao preço atual
        preco_atual = df['close'].iloc[-1]
        niveis_proximos = {}
        
        for nivel, valor in niveis_retracao.items():
            # Proximidade em percentual
            proximidade = abs(preco_atual - valor) / preco_atual * 100
            
            # Considerar próximo se estiver a menos de 1% de distância
            if proximidade < 1.0:
                niveis_proximos[f'Retração {nivel}'] = {
                    'preco': valor,
                    'distancia_pct': proximidade
                }
        
        for nivel, valor in niveis_extensao.items():
            # Proximidade em percentual
            proximidade = abs(preco_atual - valor) / preco_atual * 100
            
            # Considerar próximo se estiver a menos de 1% de distância
            if proximidade < 1.0:
                niveis_proximos[f'Extensão {nivel}'] = {
                    'preco': valor,
                    'distancia_pct': proximidade
                }
        
        # Retornar resultado completo
        return {
            'niveis_retracao': niveis_retracao,
            'niveis_extensao': niveis_extensao,
            'niveis_proximos': niveis_proximos,
            'preco_atual': preco_atual,
            'tendencia': tendencia,
            'swing_low': swing_low_preco,
            'swing_high': swing_high_preco
        }
    def calcular_parametros_ordem(self, preco_atual):
        """Calcular parâmetros para ordens com stop loss dinâmico baseado no ATR e take profit em níveis"""
        # Stop loss dinâmico baseado no ATR
        atr_valor = getattr(self, 'atr_atual', preco_atual * STOP_LOSS_PERCENTUAL_MINIMO / 100)
        stop_loss_dinamico = max(
            STOP_LOSS_MULTIPLICADOR_ATR * atr_valor,
            preco_atual * STOP_LOSS_PERCENTUAL_MINIMO / 100
        )
        # Limitar ao máximo estabelecido
        stop_loss_dinamico = min(stop_loss_dinamico, preco_atual * STOP_LOSS_PERCENTUAL_MAXIMO / 100)
        
        stop_price = preco_atual - stop_loss_dinamico
        stop_limit_price = stop_price * 0.9997  # Ligeiramente abaixo para garantir execução
        
        # Valores para take profit em níveis
        take_profit_1 = preco_atual * (1 + ALVO_LUCRO_PERCENTUAL_1 / 100)
        take_profit_2 = preco_atual * (1 + ALVO_LUCRO_PERCENTUAL_2 / 100)
        take_profit_3 = preco_atual * (1 + ALVO_LUCRO_PERCENTUAL_3 / 100)
        
        # Calcular quantidade com base no capital por operação
        ticker = self.client.get_symbol_ticker(symbol=self.symbol)
        preco_mercado = float(ticker['price'])
        
        # Extrair a base asset do symbol (por exemplo, "BTC" de "BTCUSDT")
        base_asset = self.symbol.replace('USDT', '')
        
        # Calcular níveis de Fibonacci para alvos mais precisos
        niveis_fib = self.calcular_niveis_fibonacci(df)

        # Verificar se estamos numa tendência de alta
        if niveis_fib['tendencia'] == 'alta':
            # Ajustar take profit baseado em níveis Fibonacci
            if 'niveis_extensao' in niveis_fib:
                # Ajustar TP1 para o primeiro nível de extensão (1.272)
                if '1.272' in niveis_fib['niveis_extensao']:
                    params["take_profit_1"] = max(params["take_profit_1"], 
                                                niveis_fib['niveis_extensao']['1.272'])
                
                # Ajustar TP2 para o segundo nível de extensão (1.414 ou 1.618)
                if '1.414' in niveis_fib['niveis_extensao']:
                    params["take_profit_2"] = max(params["take_profit_2"], 
                                                niveis_fib['niveis_extensao']['1.414'])
                
                # Ajustar TP3 para um nível de extensão maior (1.618 ou 2.0)
                if '1.618' in niveis_fib['niveis_extensao']:
                    params["take_profit_3"] = max(params["take_profit_3"], 
                                                niveis_fib['niveis_extensao']['1.618'])
            
            # Ajustar stop loss usando níveis de retração Fibonacci
            if 'niveis_retracao' in niveis_fib:
                # Usar Fib 0.618 ou 0.786 como potencial stop, mas não mais longe que o stop original
                candidatos_stop = []
                
                if '0.618' in niveis_fib['niveis_retracao']:
                    candidatos_stop.append(niveis_fib['niveis_retracao']['0.618'])
                    
                if '0.786' in niveis_fib['niveis_retracao']:
                    candidatos_stop.append(niveis_fib['niveis_retracao']['0.786'])
                
                if candidatos_stop:
                    # Escolher o stop mais próximo do preço atual, mas não mais longe que o original
                    melhor_stop = max([s for s in candidatos_stop if s < preco_atual], 
                                    default=params["stop_price"])
                    
                    # Usar este stop apenas se for melhor que o original
                    if melhor_stop > params["stop_price"]:
                        params["stop_price"] = melhor_stop
                        params["stop_limit_price"] = melhor_stop * 0.9997

        # Verificar balances disponíveis
        try:
            account_info = self.client.get_account()
            balances = {asset['asset']: float(asset['free']) for asset in account_info['balances']}
            
            # Obter saldo USDT disponível
            usdt_disponivel = balances.get('USDT', 0)
            print(f"Saldo USDT disponível: {usdt_disponivel} USDT")
            
            # Usar capital ajustado dinamicamente
            capital_ajustado = self.ajustar_capital_operacao()
            print(f"Capital ajustado dinamicamente: {capital_ajustado:.2f} USDT (base: {CAPITAL_POR_OPERACAO:.2f})")
            
            # Ajustar a alocação de capital se o saldo disponível for menor que o desejado
            valor_minimo_compra = 20.0  # Mínimo para operar na Binance
            valor_para_operar = min(capital_ajustado, usdt_disponivel * 0.98)  # 98% do saldo disponível
            
            # Verificar se temos saldo suficiente
            if valor_para_operar < valor_minimo_compra:
                return None, (
                    f"❌ Operação cancelada: saldo disponível ({usdt_disponivel:.2f} USDT) insuficiente. "
                    f"Mínimo recomendado: {valor_minimo_compra:.2f} USDT"
                )
                    
            print(f"Valor ajustado para operar: {valor_para_operar:.2f} USDT de {capital_ajustado:.2f} USDT desejados")
            
        except Exception as e:
            print(f"Erro ao verificar saldo: {e}. Usando valor padrão.")
            # Fallback para o caso de erro
            valor_minimo_compra = 20.0
            valor_para_operar = capital_ajustado
        
        # Definir o valor a ser usado na operação: o maior entre valor mínimo e valor calculado
        valor_para_operar = max(valor_minimo_compra, valor_para_operar)
        print(f"Valor final para operar: {valor_para_operar} USDT")

        # Calcular a quantidade baseada nesse valor, reservando ~5% para taxas e arredondamentos
        quantidade_estimada = (valor_para_operar * 0.95) / preco_mercado
        print(f"Quantidade estimada: {quantidade_estimada} {base_asset}")
        quantidade = self.normalize_quantity(quantidade_estimada)
        print(f"Quantidade normalizada final: {quantidade} {base_asset} (aproximadamente {quantidade * preco_mercado} USDT)")

        # Se a quantidade calculada ainda for inválida (por algum erro de arredondamento extremo), cancelar
        if quantidade <= 0 or quantidade < self.min_qty:
            return None, (
                f"❌ Operação cancelada: quantidade ({quantidade:.8f}) abaixo do mínimo permitido ({self.min_qty})."
            )
        
        # Log do stop loss dinâmico
        stop_loss_percent = (preco_atual - stop_price) / preco_atual * 100
        
        # Normalizar todos os preços
        preco_atual = self.normalize_price(preco_atual)
        take_profit_1 = self.normalize_price(take_profit_1)
        take_profit_2 = self.normalize_price(take_profit_2)
        take_profit_3 = self.normalize_price(take_profit_3)
        stop_price = self.normalize_price(stop_price)
        stop_limit_price = self.normalize_price(stop_limit_price)
        
        return {
            "preco_entrada": preco_atual,
            "quantidade": quantidade,
            "take_profit_1": take_profit_1,   # Primeiro alvo (25% da posição)
            "take_profit_2": take_profit_2,   # Segundo alvo (25% da posição)
            "take_profit_3": take_profit_3,   # Alvo final (50% da posição)
            "stop_price": stop_price,
            "stop_limit_price": stop_limit_price,
            "stop_loss_percent": stop_loss_percent
        }, f"Stop loss: {stop_loss_percent:.2f}% ({STOP_LOSS_MULTIPLICADOR_ATR}x ATR), Take profits: {ALVO_LUCRO_PERCENTUAL_1}%, {ALVO_LUCRO_PERCENTUAL_2}%, {ALVO_LUCRO_PERCENTUAL_3}%"

        
    # 8. Adicionar um novo método para verificar se a operação é viável considerando as taxas

    def verificar_viabilidade_operacao(self, preco_atual, parametros):
        """Verifica se a operação é viável considerando as taxas e retornos esperados"""
        # Obter parâmetros
        quantidade = parametros["quantidade"]
        stop_price = parametros["stop_price"]
        take_profit_1 = parametros["take_profit_1"]
        
        # Calcular taxa de compra e venda
        taxa_compra = preco_atual * quantidade * self.taxa_efetiva
        taxa_venda_tp1 = take_profit_1 * quantidade * 0.25 * self.taxa_efetiva  # 25% da posição no TP1
        taxa_venda_tp2 = parametros["take_profit_2"] * quantidade * 0.25 * self.taxa_efetiva  # 25% no TP2
        taxa_venda_tp3 = parametros["take_profit_3"] * quantidade * 0.5 * self.taxa_efetiva  # 50% no TP3
        taxa_venda_sl = stop_price * quantidade * self.taxa_efetiva  # Venda total no SL
        
        # Taxas total para take profit completo
        taxa_total_tp = taxa_compra + taxa_venda_tp1 + taxa_venda_tp2 + taxa_venda_tp3
        
        # Taxas total para stop loss
        taxa_total_sl = taxa_compra + taxa_venda_sl
        
        # Calcular lucro potencial no primeiro take profit (25% da posição)
        lucro_bruto_tp1 = (take_profit_1 - preco_atual) * quantidade * 0.25
        lucro_liquido_tp1 = lucro_bruto_tp1 - (taxa_compra * 0.25) - taxa_venda_tp1
        
        # Calcular perda potencial no stop loss
        perda_bruta_sl = (preco_atual - stop_price) * quantidade
        perda_liquida_sl = perda_bruta_sl + taxa_total_sl
        
        # Verificar se o primeiro take profit compensa as taxas
        tp1_compensa_taxa = lucro_liquido_tp1 > 0
        
        # Calcular razão risco/recompensa considerando as taxas
        # Aqui calculamos quanto ganhamos no melhor cenário (TP3) vs quanto perdemos no pior (SL)
        lucro_maximo = (
            (take_profit_1 - preco_atual) * quantidade * 0.25 +
            (parametros["take_profit_2"] - preco_atual) * quantidade * 0.25 +
            (parametros["take_profit_3"] - preco_atual) * quantidade * 0.5
        ) - taxa_total_tp
        
        perda_maxima = perda_liquida_sl
        
        if perda_maxima > 0:  # Evitar divisão por zero
            risk_reward_ratio = lucro_maximo / perda_maxima
        else:
            risk_reward_ratio = float('inf')  # Sem risco (cenário improvável)
        
        # Adicionar verificação de ROI mínimo considerando taxas
        roi_minimo = 0.5  # ROI mínimo de 0.5% para compensar taxas
        
        # Calcular ROI potencial no cenário médio (considerar média ponderada dos TPs)
        roi_potencial = (
            (ALVO_LUCRO_PERCENTUAL_1 * 0.25) +  # 25% da posição no TP1
            (ALVO_LUCRO_PERCENTUAL_2 * 0.25) +  # 25% da posição no TP2
            (ALVO_LUCRO_PERCENTUAL_3 * 0.5)     # 50% da posição no TP3
        )
        
        # Calcular ROI líquido após taxas
        taxa_percentual = self.taxa_efetiva * 100 * 2  # Taxa de entrada e saída
        roi_liquido = roi_potencial - taxa_percentual
        
        # Verificar ROI mínimo
        if roi_liquido < roi_minimo:
            viavel = False
            mensagem += f"\n- ROI líquido estimado ({roi_liquido:.2f}%) abaixo do mínimo aceitável ({roi_minimo:.2f}%)"
        # Determinar viabilidade
        viavel = tp1_compensa_taxa and risk_reward_ratio >= 0.6 and roi_liquido >= roi_minimo
        
        # Preparar mensagem com detalhes
        mensagem = (
            f"Análise de viabilidade (com taxas):\n"
            f"- Custo total em taxas (TP completo): {taxa_total_tp:.6f} USDT\n"
            f"- Primeiro TP gera lucro após taxas: {'SIM' if tp1_compensa_taxa else 'NÃO'} (lucro líquido TP1: {lucro_liquido_tp1:.6f} USDT)\n"
            f"- Razão risco/recompensa: {risk_reward_ratio:.2f} (mín. recomendado: 1.5)\n"
            f"- Operação considerada {'VIÁVEL' if viavel else 'NÃO VIÁVEL'}"
        )
        
        # Adicionar detalhes ao log
        self.registrar_log(f"VIABILIDADE: {viavel} | R/R={risk_reward_ratio:.2f} | Taxas={taxa_total_tp:.6f}")
        
        return viavel, mensagem

    def executar_ordem_compra(self, params):
        """Executar ordem de compra com sistema de saídas parciais e cálculo de taxas"""
        if MODO_SIMULACAO:
            print("🔸 MODO SIMULAÇÃO: Simulando ordem de compra")
            # Em modo simulação, fingimos que a ordem foi executada ao preço atual
            self.preco_entrada = params["preco_entrada"]
            self.quantidade = params["quantidade"]  # Quantidade calculada
            self.quantidade_restante = self.quantidade  # Inicializar quantidade restante
            self.em_operacao = True
            self.tempo_entrada = datetime.now()
            self.posicao_parcial = False
            self.saidas_parciais = []
            
            # Calcular e registrar taxa de compra
            self.taxa_compra = self.preco_entrada * self.quantidade * self.taxa_efetiva
            self.taxa_total_operacao = self.taxa_compra
            
            # Registrar detalhes da operação
            timestamp = datetime.now()
            self.log_operacoes.append({
                'timestamp': timestamp,
                'tipo': 'ENTRADA (SIMULAÇÃO)',
                'preco': self.preco_entrada,
                'quantidade': self.quantidade,
                'taxa': self.taxa_compra,
                'motivo': self.motivo_entrada,
                'forca_sinal': getattr(self, 'forca_sinal', 'N/A')
            })
            
            # Calcular o valor total da operação em dólares
            valor_operacao = self.preco_entrada * self.quantidade

            # Calcular patrimônio atual
            patrimonio_total = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria

            # Enviar alerta com informação sobre taxa
            self.send_telegram_alert(
                f"✅ COMPRA SIMULADA\n\n"
                f"Preço: {self.preco_entrada:.4f} USDT\n"
                f"Qtd: {self.quantidade:.6f} {self.symbol.replace('USDT', '')}\n"
                f"Valor total: {valor_operacao:.2f} USDT\n"
                f"Taxa: {self.taxa_compra:.6f} USDT\n"
                f"Sinal: {getattr(self, 'forca_sinal', 'N/A')}\n"
                f"Motivo: {self.motivo_entrada}\n\n"
                f"💰 Patrimônio atual: {patrimonio_total:.2f} USDT"
)
            
            # Registrar no log
            self.registrar_log(f"ENTRADA (SIMULAÇÃO): Preço={self.preco_entrada} | Qtd={self.quantidade} | Taxa={self.taxa_compra:.6f} | Motivo={self.motivo_entrada}")
            
            # Incrementar contador de operações do dia
            self.operacoes_hoje += 1
            
            # Atualizar valor máximo da carteira
            carteira_atual = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria - self.taxas_pagas_total
            if carteira_atual > self.valor_maximo_carteira:
                self.valor_maximo_carteira = carteira_atual
                
            return True
        
        try:
            # Ordem de compra a mercado
            ordem = self.client.create_order(
                symbol=self.symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=params["quantidade"]
            )
            
            print(f"Ordem de compra executada: {ordem}")
            self.preco_entrada = float(ordem['fills'][0]['price'])
            self.quantidade = float(ordem['executedQty'])  # usa a quantidade real executada
            self.quantidade_restante = self.quantidade  # Inicializar quantidade restante
            self.em_operacao = True
            self.tempo_entrada = datetime.now()
            self.posicao_parcial = False
            self.saidas_parciais = []
            
            # Calcular taxa da compra em modo real
            # Usa o commission e commissionAsset dos fills para cálculo preciso
            self.taxa_compra = 0
            for fill in ordem['fills']:
                if 'commission' in fill and 'commissionAsset' in fill:
                    commission = float(fill['commission'])
                    commission_asset = fill['commissionAsset']
                    
                    # Se a taxa foi paga em BNB, converter para USDT
                    if commission_asset == 'BNB':
                        # Obter cotação do BNB
                        bnb_price = float(self.client.get_symbol_ticker(symbol='BNBUSDT')['price'])
                        self.taxa_compra += commission * bnb_price
                    elif commission_asset == 'USDT':
                        self.taxa_compra += commission
                    else:
                        # Taxa paga no asset base (BTC neste caso)
                        self.taxa_compra += commission * self.preco_entrada
            
            self.taxa_total_operacao = self.taxa_compra
            self.taxas_pagas_total += self.taxa_compra
            
            # Calcular o valor total da operação em dólares
            valor_operacao = self.preco_entrada * self.quantidade

            # Calcular patrimônio atual
            patrimonio_total = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria

            # Enviar alerta com informações adicionais
            self.send_telegram_alert(
                f"✅ COMPRA REALIZADA\n\n"
                f"Preço: {self.preco_entrada:.4f} USDT\n"
                f"Qtd: {self.quantidade:.6f} {self.symbol.replace('USDT', '')}\n"
                f"Valor total: {valor_operacao:.2f} USDT\n"
                f"Taxa: {self.taxa_compra:.6f} USDT\n"
                f"Sinal: {getattr(self, 'forca_sinal', 'N/A')}\n"
                f"Motivo: {self.motivo_entrada}\n\n"
                f"💰 Patrimônio atual: {patrimonio_total:.2f} USDT"
            )
            
            # Registrar detalhes da operação
            timestamp = datetime.now()
            self.log_operacoes.append({
                'timestamp': timestamp,
                'tipo': 'ENTRADA',
                'preco': self.preco_entrada,
                'quantidade': self.quantidade,
                'taxa': self.taxa_compra,
                'motivo': self.motivo_entrada,
                'forca_sinal': getattr(self, 'forca_sinal', 'N/A')
            })
            
            # Registrar no log
            self.registrar_log(f"ENTRADA: Preço={self.preco_entrada} | Qtd={self.quantidade} | Taxa={self.taxa_compra:.6f} | Motivo={self.motivo_entrada}")
            
            # Configurar stop loss inicial
            self.configurar_stop_loss(params)
            
            # Incrementar contador de operações do dia
            self.operacoes_hoje += 1
            
            # Atualizar valor máximo da carteira
            carteira_atual = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria - self.taxas_pagas_total
            if carteira_atual > self.valor_maximo_carteira:
                self.valor_maximo_carteira = carteira_atual
                
            return True
        except BinanceAPIException as e:
            print(f"Erro ao executar ordem: {e}")
            return False
    def configurar_stop_loss(self, params):
        """Configurar ordem de stop loss após entrada com fallback para stop virtual"""
        if not self.em_operacao:
            return False
            
        # Obter parâmetros de stop loss
        stop_price = params["stop_price"]
        stop_limit_price = params["stop_limit_price"]
        
        # Flag para controlar se estamos usando stop virtual
        self.usando_stop_virtual = False
        
        # Se estamos em modo simulação, não tentamos configurar stop real
        if MODO_SIMULACAO:
            self.stop_virtual_preco = stop_price
            self.usando_stop_virtual = True
            self.registrar_log(f"STOP VIRTUAL: Configurado em {stop_price:.2f} ({params['stop_loss_percent']:.2f}%)")
            return True
        
        try:
            # Tentar criar ordem de stop loss real
            ordem_stop = self.client.create_order(
                symbol=self.symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_STOP_LOSS_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=self.quantidade,
                price=self.normalize_price(stop_limit_price),
                stopPrice=self.normalize_price(stop_price)
            )
            
            self.ordem_stop_id = ordem_stop['orderId']
            print(f"Stop Loss configurado: {stop_price:.2f} USDT ({params['stop_loss_percent']:.2f}%)")
            self.registrar_log(f"STOP LOSS: Configurado em {stop_price:.2f} ({params['stop_loss_percent']:.2f}%)")
            
            return True
        except BinanceAPIException as e:
            print(f"Erro ao configurar stop loss: {e}")
            self.registrar_log(f"ERRO STOP LOSS: {e}")
            
            # FALLBACK: Configurar stop virtual se não conseguir criar stop real
            self.stop_virtual_preco = stop_price
            self.usando_stop_virtual = True
            print(f"FALLBACK: Stop Virtual ativado em {stop_price:.2f} USDT ({params['stop_loss_percent']:.2f}%)")
            self.registrar_log(f"STOP VIRTUAL: Configurado em {stop_price:.2f} ({params['stop_loss_percent']:.2f}%)")
            
            # Enviar alerta sobre o fallback
            self.send_telegram_alert(
                f"⚠️ AVISO: Não foi possível configurar stop loss automático.\n\n"
                f"Um stop loss virtual foi ativado em {stop_price:.2f} USDT.\n"
                f"Erro da Binance: {e}"
            )
            
            return True

    def verificar_stop_loss_movel(self, preco_atual, params=None):
        """Stop Loss Móvel (Trailing Stop) melhorado com níveis dinâmicos"""
        if not self.em_operacao or not self.trailing_stop_ativo:
            return False
            
        # Se já tivemos saídas parciais, ajustar o trailing stop para break-even
        if self.posicao_parcial:
            # Garantir que não vamos sair com prejuízo após ter tido lucro parcial
            novo_stop = max(self.preco_entrada * 1.001, preco_atual * 0.99)
            self.trailing_stop_nivel = max(self.trailing_stop_nivel, novo_stop)
        
        # Verificar se o preço atingiu novos patamares para ajustar o trailing stop
        lucro_percentual = (preco_atual - self.preco_entrada) / self.preco_entrada * 100
        
        # Níveis dinâmicos para trailing stop com base no lucro percentual
        # - Até 0.3%: Não movimenta
        # - 0.3% a 0.6%: Move para 0.15% abaixo do preço atual
        # - 0.6% a 1.0%: Move para 0.25% abaixo do preço atual
        # - Acima de 1.0%: Move para 0.4% abaixo do preço atual
        
        if lucro_percentual >= 0.2 and lucro_percentual < 0.4:
            novo_stop = preco_atual * 0.9985  # 0.15% abaixo (ativação mais rápida)
            msg_trail = "0.15% abaixo"
        elif lucro_percentual >= 0.4 and lucro_percentual < 0.8:
            novo_stop = preco_atual * 0.9975  # 0.25% abaixo
            msg_trail = "0.25% abaixo"
        elif lucro_percentual >= 0.8:
            novo_stop = preco_atual * 0.996   # 0.4% abaixo
            msg_trail = "0.4% abaixo"
        else:
            return False  # Lucro insuficiente para mover o stop
                
        # Só ajustar se o novo stop for maior que o anterior
        if novo_stop <= self.trailing_stop_nivel:
            return False
            
        # Atualizar nível
        self.trailing_stop_nivel = novo_stop
        
        if MODO_SIMULACAO:
            print(f"🔸 MODO SIMULAÇÃO: Trailing Stop ajustado para {self.trailing_stop_nivel:.2f} ({msg_trail})")
            self.registrar_log(f"TRAILING STOP (SIMULAÇÃO): Ajustado para {self.trailing_stop_nivel:.2f} ({msg_trail})")
            return True
            
        try:
            # Cancelar ordem de stop loss anterior
            if self.ordem_stop_id:
                self.client.cancel_order(symbol=self.symbol, orderId=self.ordem_stop_id)
                
            # Calcular preço limite (ligeiramente abaixo para garantir execução)
            stop_limit_price = self.trailing_stop_nivel * 0.999
                
            # Criar nova ordem de stop loss
            quantidade_venda = self.quantidade_restante if hasattr(self, 'quantidade_restante') else self.quantidade
            
            ordem_stop = self.client.create_order(
                symbol=self.symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_STOP_LOSS_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantidade_venda,
                price=self.normalize_price(stop_limit_price),
                stopPrice=self.normalize_price(self.trailing_stop_nivel)
            )
                
            self.ordem_stop_id = ordem_stop['orderId']
            print(f"Trailing Stop ajustado: Novo nível={self.trailing_stop_nivel:.2f} ({msg_trail})")
            self.registrar_log(f"TRAILING STOP: Ajustado para {self.trailing_stop_nivel:.2f} ({msg_trail})")
                
            return True
        except BinanceAPIException as e:
            print(f"Erro ao ajustar trailing stop: {e}")
            return False
    # 4. Modificar o método verificar_take_profit_parcial para contabilizar taxas nas saídas parciais

    def verificar_take_profit_parcial(self, preco_atual, params):
        """Verificar e executar saídas parciais com base nos níveis de take profit, contabilizando taxas"""
        if not self.em_operacao or self.posicao_parcial and not hasattr(self, 'quantidade_restante'):
            return False
            
        # Verificar se estamos em modo simulação
        if MODO_SIMULACAO:
            # Obter níveis de take profit do parâmetro ou usar valores padrões
            tp1 = params.get('take_profit_1', self.preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_1 / 100))
            tp2 = params.get('take_profit_2', self.preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_2 / 100))
            tp3 = params.get('take_profit_3', self.preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_3 / 100))
            
            # Verificar se o preço atingiu o nível 3 (alvo final) e ainda temos posição parcial
            if preco_atual >= tp3 and hasattr(self, 'quantidade_restante') and self.quantidade_restante > 0:
                # Calcular taxa de venda para a quantidade restante
                taxa_venda = preco_atual * self.quantidade_restante * self.taxa_efetiva
                
                # Simular saída total da posição restante considerando taxas
                resultado_bruto = (preco_atual - self.preco_entrada) * self.quantidade_restante
                resultado = resultado_bruto - taxa_venda  # Resultado líquido após taxa
                percentual = (preco_atual - self.preco_entrada) / self.preco_entrada * 100
                
                # Atualizar taxa total da operação
                self.taxa_total_operacao += taxa_venda
                self.taxas_pagas_total += taxa_venda
                
                saida_parcial = {
                    'nivel': 'Alvo Final',
                    'preco': preco_atual,
                    'quantidade': self.quantidade_restante,
                    'resultado_bruto': resultado_bruto,
                    'taxa': taxa_venda,
                    'resultado': resultado,  # Resultado líquido
                    'percentual': percentual
                }
                
                self.saidas_parciais.append(saida_parcial)
                self.lucro_diario += resultado  # Adiciona resultado líquido
                
                # Registrar no log
                self.registrar_log(f"TAKE PROFIT FINAL (SIMULAÇÃO): {resultado:.2f} USDT ({percentual:.2f}%) | Taxa: {taxa_venda:.6f}")
                
                # Enviar alerta
                self.send_telegram_alert(
                    f"✅ TAKE PROFIT FINAL\n\n"
                    f"Preço: {preco_atual:.2f} USDT\n"
                    f"Resultado bruto: +{resultado_bruto:.2f} USDT\n"
                    f"Taxa: {taxa_venda:.6f} USDT\n"
                    f"Resultado líquido: +{resultado:.2f} USDT ({percentual:.2f}%)\n"
                    f"Lucro total operação: {sum(s['resultado'] for s in self.saidas_parciais):.2f} USDT"
                )
                
                # Resetar posição
                self.em_operacao = False
                
                # Adicionar à lista de operações do dia
                self.operacoes_dia.append({
                    'entrada': self.preco_entrada,
                    'saida': preco_atual,
                    'resultado': sum(s['resultado'] for s in self.saidas_parciais),
                    'taxas': self.taxa_total_operacao,
                    'lucro_percentual': percentual,
                    'timestamp': datetime.now(),
                    'duracao_minutos': (datetime.now() - self.tempo_entrada).total_seconds() / 60,
                    'motivo_entrada': self.motivo_entrada,
                    'motivo_saida': 'Take Profit Final',
                    'saidas_parciais': self.saidas_parciais
                })
                
                # Atualizar estatísticas
                self.trades_vencedores += 1
                self.sequencia_perdas_atual = 0
                
                return True
                
            # Verificar se o preço atingiu o nível 2 e ainda não tivemos saída parcial neste nível
            elif preco_atual >= tp2 and (not self.posicao_parcial or 
                (self.saidas_parciais and all(s['nivel'] != 'Alvo 2' for s in self.saidas_parciais))):
                
                # Quantidade para saída parcial (25% da posição original)
                quantidade_saida = self.quantidade * 0.25
                
                # Calcular taxa para esta saída parcial
                taxa_venda = preco_atual * quantidade_saida * self.taxa_efetiva
                
                # Calculamos o resultado desta saída considerando taxas
                resultado_bruto = (preco_atual - self.preco_entrada) * quantidade_saida
                resultado = resultado_bruto - taxa_venda
                percentual = (preco_atual - self.preco_entrada) / self.preco_entrada * 100
                
                # Atualizar taxa total da operação
                self.taxa_total_operacao += taxa_venda
                self.taxas_pagas_total += taxa_venda
                
                # Registro da saída parcial
                saida_parcial = {
                    'nivel': 'Alvo 2',
                    'preco': preco_atual,
                    'quantidade': quantidade_saida,
                    'resultado_bruto': resultado_bruto,
                    'taxa': taxa_venda,
                    'resultado': resultado,
                    'percentual': percentual
                }
                
                # Atualizar a quantidade restante e marcar como posição parcial
                if not hasattr(self, 'quantidade_restante'):
                    self.quantidade_restante = self.quantidade
                
                self.quantidade_restante -= quantidade_saida
                self.posicao_parcial = True
                self.saidas_parciais.append(saida_parcial)
                
                # Adicionar lucro ao dia
                self.lucro_diario += resultado
                
                # Registrar no log
                self.registrar_log(f"TAKE PROFIT PARCIAL 2 (SIMULAÇÃO): {resultado:.2f} USDT ({percentual:.2f}%) | Taxa: {taxa_venda:.6f}")
                
                # Enviar alerta
                self.send_telegram_alert(
                    f"✅ TAKE PROFIT PARCIAL (25%)\n\n"
                    f"Preço: {preco_atual:.2f} USDT\n"
                    f"Resultado bruto: +{resultado_bruto:.2f} USDT\n"
                    f"Taxa: {taxa_venda:.6f} USDT\n"
                    f"Resultado líquido: +{resultado:.2f} USDT ({percentual:.2f}%)\n"
                    f"Restante da posição: {self.quantidade_restante:.6f} BTC"
                )
                
                # Ativar trailing stop quando lucro atingir determinado nível
                lucro_atual = (preco_atual - self.preco_entrada) / self.preco_entrada * 100
                if lucro_atual >= 0.2:  # Ativar mais cedo quando lucro for >= 0.2%
                    self.trailing_stop_ativo = True
                    self.trailing_stop_nivel = preco_atual * 0.998  # Inicialmente 0.2% abaixo
                    print(f"Trailing Stop ativado após take profit parcial: {self.trailing_stop_nivel:.2f}")
                    self.registrar_log(f"TRAILING STOP ATIVADO: {self.trailing_stop_nivel:.2f}")
                
                return True
                
            # Verificar se o preço atingiu o nível 1 e ainda não tivemos saída parcial
            elif preco_atual >= tp1 and not self.posicao_parcial:
                # Quantidade para saída parcial (25% da posição original)
                quantidade_saida = self.quantidade * 0.25
                
                # Calcular taxa para esta saída parcial
                taxa_venda = preco_atual * quantidade_saida * self.taxa_efetiva
                
                # Calculamos o resultado desta saída
                resultado_bruto = (preco_atual - self.preco_entrada) * quantidade_saida
                resultado = resultado_bruto - taxa_venda
                percentual = (preco_atual - self.preco_entrada) / self.preco_entrada * 100
                
                # Atualizar taxa total e acumulada
                self.taxa_total_operacao += taxa_venda
                self.taxas_pagas_total += taxa_venda
                
                # Registro da saída parcial
                saida_parcial = {
                    'nivel': 'Alvo 1',
                    'preco': preco_atual,
                    'quantidade': quantidade_saida,
                    'resultado_bruto': resultado_bruto,
                    'taxa': taxa_venda,
                    'resultado': resultado,
                    'percentual': percentual
                }
                
                # Atualizar a quantidade restante e marcar como posição parcial
                self.quantidade_restante = self.quantidade - quantidade_saida
                self.posicao_parcial = True
                self.saidas_parciais.append(saida_parcial)
                
                # Adicionar lucro ao dia
                self.lucro_diario += resultado
                
                # Registrar no log
                self.registrar_log(f"TAKE PROFIT PARCIAL 1 (SIMULAÇÃO): {resultado:.2f} USDT ({percentual:.2f}%) | Taxa: {taxa_venda:.6f}")
                
                # Enviar alerta
                self.send_telegram_alert(
                    f"✅ TAKE PROFIT PARCIAL (25%)\n\n"
                    f"Preço: {preco_atual:.2f} USDT\n"
                    f"Resultado bruto: +{resultado_bruto:.2f} USDT\n"
                    f"Taxa: {taxa_venda:.6f} USDT\n"
                    f"Resultado líquido: +{resultado:.2f} USDT ({percentual:.2f}%)\n"
                    f"Restante da posição: {self.quantidade_restante:.6f} BTC"
                )
                
                # Ativar trailing stop
                self.trailing_stop_ativo = True
                self.trailing_stop_nivel = self.preco_entrada  # Inicialmente no break-even
                print(f"Trailing Stop ativado no break-even: {self.trailing_stop_nivel:.2f}")
                self.registrar_log(f"TRAILING STOP ATIVADO NO BREAK-EVEN: {self.trailing_stop_nivel:.2f}")
                
                return True
            
            return False
            
        # Modo de operação real (não simulado)
        else:
            # Implementar lógica para saídas parciais em modo real com consideração de taxas
            # Este é apenas um exemplo que precisaria ser adaptado à API da Binance
            try:
                # Obter níveis de take profit do parâmetro
                tp1 = params.get('take_profit_1', self.preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_1 / 100))
                tp2 = params.get('take_profit_2', self.preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_2 / 100))
                tp3 = params.get('take_profit_3', self.preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_3 / 100))
                
                # Verificar níveis e executar ordens de venda parciais conforme necessário
                # [Implementação das ordens reais de venda aqui]
                
                return False  # Placeholder - implementar lógica real
                
            except BinanceAPIException as e:
                print(f"Erro ao executar take profit parcial: {e}")
                return False
        
    def verificar_status_ordens(self):
        """Verificar status das ordens abertas e processar execuções"""
        if not self.em_operacao:
            return
            
        try:
            # Verificar stop virtual se estiver ativado
            if hasattr(self, 'usando_stop_virtual') and self.usando_stop_virtual:
                try:
                    ticker = self.client.get_symbol_ticker(symbol=self.symbol)
                    preco_atual = float(ticker['price'])
                    
                    # Verificar se o preço caiu abaixo do stop virtual
                    if preco_atual <= self.stop_virtual_preco:
                        print(f"⚠️ STOP VIRTUAL ACIONADO: Preço atual ({preco_atual:.2f}) abaixo do stop ({self.stop_virtual_preco:.2f})")
                        self.registrar_log(f"STOP VIRTUAL ACIONADO: {preco_atual:.2f} <= {self.stop_virtual_preco:.2f}")
                        
                        # Executar venda de emergência
                        self.executar_venda_emergencia(preco_atual, "Stop Loss Virtual")
                        return
                except Exception as e:
                    print(f"Erro ao verificar stop virtual: {e}")
            
            # O resto da função permanece igual para verificar ordens reais
            if MODO_SIMULACAO:
                # Em modo simulação, verificamos se o preço atingiu o stop loss
                try:
                    ticker = self.client.get_symbol_ticker(symbol=self.symbol)
                    preco_atual = float(ticker['price'])
                    
                    # Verificar se o preço caiu abaixo do trailing stop
                    if self.trailing_stop_ativo and preco_atual < self.trailing_stop_nivel:
                        self.executar_venda_manual(preco_atual, "Stop Loss Móvel Simulado")
                except Exception as e:
                    print(f"Erro ao verificar preço em simulação: {e}")
                return
                
            ordens_abertas = self.client.get_open_orders(symbol=self.symbol)
            
            # Se não há ordens abertas e estávamos em operação, significa que uma ordem foi executada
            if len(ordens_abertas) == 0 and self.em_operacao:
                # Verificar histórico de ordens recentes para determinar resultado
                historico = self.client.get_all_orders(symbol=self.symbol, limit=10)
                
                # Filtrar apenas as ordens executadas (status = FILLED)
                ordens_executadas = [ordem for ordem in historico if ordem['status'] == 'FILLED']
                
                if ordens_executadas:
                    ultima_ordem = ordens_executadas[-1]
                    
                    # Se a última ordem foi uma venda
                    if ultima_ordem['side'] == 'SELL':
                        preco_venda = float(ultima_ordem['price'] or ultima_ordem.get('lastPrice', 0))
                        if preco_venda == 0:  # Fallback se não conseguir o preço diretamente
                            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
                            preco_venda = float(ticker['price'])
                            
                        quantidade = float(ultima_ordem['executedQty'])
                        
                        # Se tínhamos saídas parciais, usar a quantidade restante
                        quantidade_inicial = self.quantidade_restante if hasattr(self, 'quantidade_restante') else self.quantidade
                        
                        # Verificar se a quantidade vendida corresponde ao que esperávamos
                        if abs(quantidade - quantidade_inicial) / quantidade_inicial < 0.01:  # dentro de 1% de tolerância
                            resultado = (preco_venda - self.preco_entrada) * quantidade
                            
                            # Determinar motivo da saída
                            if preco_venda >= self.preco_entrada:
                                motivo_saida = "Take Profit Automático"
                            else:
                                motivo_saida = "Stop Loss Automático"
                            
                            # Registrar operação como encerrada
                            self.executar_venda_manual(preco_venda, motivo_saida)
        except BinanceAPIException as e:
            print(f"Erro ao verificar ordens: {e}")

    # 5. Modificar o método executar_venda_manual para considerar taxas

    def executar_venda_manual(self, preco_venda, motivo_saida):
        """Encerrar posição manualmente ou registrar execução de saída automática, considerando taxas"""
        if not self.em_operacao:
            print("Não há operação em andamento para encerrar")
            return False
        
        # CORREÇÃO: Cancelar qualquer ordem de stop loss pendente
        if hasattr(self, 'ordem_stop_id') and self.ordem_stop_id:
            try:
                self.client.cancel_order(symbol=self.symbol, orderId=self.ordem_stop_id)
                print(f"Stop loss anterior cancelado: {self.ordem_stop_id}")
                self.registrar_log(f"CANCELAMENTO: Stop loss anterior {self.ordem_stop_id} cancelado")
                self.ordem_stop_id = None
            except Exception as e:
                print(f"Erro ao cancelar stop loss anterior: {e}")
                self.registrar_log(f"ERRO: Falha ao cancelar stop loss anterior: {e}")
        
        # Calcular resultado
        if hasattr(self, 'quantidade_restante'):
            quantidade_venda = self.quantidade_restante
        else:
            quantidade_venda = self.quantidade
        
        # CORREÇÃO: Executar venda real antes de calcular taxas e resultados
        ordem_executada = False
        if not MODO_SIMULACAO:
            try:
                print(f"Executando venda real a mercado de {quantidade_venda} {self.symbol}")
                ordem = self.client.create_order(
                    symbol=self.symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=self.normalize_quantity(quantidade_venda)
                )
                
                # Verificar se a ordem foi executada
                if 'fills' in ordem and len(ordem['fills']) > 0:
                    # Usar o preço médio de execução real
                    preco_total = 0
                    qtd_total = 0
                    for fill in ordem['fills']:
                        preco_fill = float(fill['price'])
                        qtd_fill = float(fill['qty'])
                        preco_total += preco_fill * qtd_fill
                        qtd_total += qtd_fill
                    
                    if qtd_total > 0:
                        preco_venda = preco_total / qtd_total
                        print(f"Venda executada ao preço médio: {preco_venda}")
                        
                    ordem_executada = True
                else:
                    print("⚠️ Ordem enviada, mas sem confirmação de execução - verificando status")
                    # Verificar status da ordem
                    try:
                        ordem_status = self.client.get_order(symbol=self.symbol, orderId=ordem['orderId'])
                        if ordem_status['status'] == 'FILLED':
                            ordem_executada = True
                            print(f"Ordem confirmada como executada: {ordem_status['status']}")
                        else:
                            print(f"⚠️ Ordem não executada completamente: {ordem_status['status']}")
                            self.registrar_log(f"ALERTA: Venda não completada, status={ordem_status['status']}")
                    except Exception as e_status:
                        print(f"Erro ao verificar status da ordem: {e_status}")
                
                if not ordem_executada:
                    self.registrar_log(f"ERRO: Falha na execução da venda manual")
                    return False
                    
            except Exception as e:
                print(f"Erro ao executar venda: {e}")
                self.registrar_log(f"ERRO VENDA: {e}")
                # Continuar com cálculos mesmo em caso de erro
                # mas marcar explicitamente no log
                self.registrar_log("AVISO: Calculando resultado com base no preço teórico devido a erro")
        
        # Calcular taxa de venda
        if MODO_SIMULACAO:
            taxa_venda = preco_venda * quantidade_venda * self.taxa_efetiva
        else:
            if ordem_executada and 'fills' in ordem:
                # Calcular taxa real baseada nos fills
                taxa_venda = 0
                for fill in ordem['fills']:
                    if 'commission' in fill and 'commissionAsset' in fill:
                        commission = float(fill['commission'])
                        commission_asset = fill['commissionAsset']
                        
                        # Converter taxa para USDT dependendo do asset
                        if commission_asset == 'BNB':
                            bnb_price = float(self.client.get_symbol_ticker(symbol='BNBUSDT')['price'])
                            taxa_venda += commission * bnb_price
                        elif commission_asset == 'USDT':
                            taxa_venda += commission
                        else:
                            taxa_venda += commission * preco_venda
            else:
                # Estimativa se não temos dados reais
                taxa_venda = preco_venda * quantidade_venda * self.taxa_efetiva
        
        # Atualizar taxa total da operação e acumulada
        self.taxa_total_operacao += taxa_venda
        self.taxas_pagas_total += taxa_venda
        
        # Calcular resultado da operação (bruto e líquido)
        resultado_bruto = (preco_venda - self.preco_entrada) * quantidade_venda
        resultado = resultado_bruto - taxa_venda  # Resultado líquido após taxa
        percentual = (preco_venda - self.preco_entrada) / self.preco_entrada * 100
        
        # Adicionar ao lucro ou perda diária (valor líquido)
        if resultado > 0:
            self.lucro_diario += resultado
            self.trades_vencedores += 1
            self.sequencia_perdas_atual = 0
            status = "LUCRO"
        else:
            self.perda_diaria += abs(resultado)
            self.trades_perdedores += 1
            self.sequencia_perdas_atual += 1
            self.maior_sequencia_perdas = max(self.maior_sequencia_perdas, self.sequencia_perdas_atual)
            status = "PERDA"
        
        # Incluir resultados de saídas parciais se houver
        resultado_total = resultado
        taxas_total = taxa_venda
        if self.posicao_parcial and self.saidas_parciais:
            for saida in self.saidas_parciais:
                resultado_total += saida['resultado']
                taxas_total += saida.get('taxa', 0)
        
        # Calcular percentual total considerando saídas parciais
        percentual_total = (resultado_total + taxas_total) / (self.preco_entrada * self.quantidade) * 100
        
        # Adicionar à lista de operações do dia
        self.operacoes_dia.append({
            'entrada': self.preco_entrada,
            'saida': preco_venda,
            'resultado_bruto': resultado_bruto + (sum(s.get('resultado_bruto', 0) for s in self.saidas_parciais) if self.saidas_parciais else 0),
            'taxas': self.taxa_total_operacao,
            'resultado': resultado_total,  # Resultado líquido total
            'lucro_percentual': percentual_total,
            'timestamp': datetime.now(),
            'duracao_minutos': (datetime.now() - self.tempo_entrada).total_seconds() / 60,
            'motivo_entrada': self.motivo_entrada,
            'motivo_saida': motivo_saida,
            'saidas_parciais': self.saidas_parciais if hasattr(self, 'saidas_parciais') else []
        })
        
        # Registrar detalhes da operação no log
        self.log_operacoes.append({
            'timestamp': datetime.now(),
            'tipo': f'SAÍDA ({status})',
            'preco': preco_venda,
            'quantidade': quantidade_venda,
            'taxa': taxa_venda,
            'resultado_bruto': resultado_bruto,
            'resultado': resultado,
            'percentual': percentual,
            'resultado_total': resultado_total,
            'taxas_total': taxas_total,
            'percentual_total': percentual_total,
            'motivo': motivo_saida
        })
        
        # Registrar no log
        self.registrar_log(
            f"SAÍDA {status}: Preço={preco_venda:.2f} | " +
            f"Resultado bruto={resultado_bruto:.2f} | Taxa={taxa_venda:.6f} | " +
            f"Resultado líquido={resultado:.2f} USDT ({percentual:.2f}%) | " +
            f"Motivo: {motivo_saida}"
        )
        
        # Calcular patrimônio antes e depois
        patrimonio_antes = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria
        patrimonio_depois = patrimonio_antes + resultado

        # Enviar alerta com emoji adequado e informações adicionais
        emoji = "✅" if resultado > 0 else "❌"
        self.send_telegram_alert(
            f"{emoji} POSIÇÃO ENCERRADA: {status}\n\n"
            f"Entrada: {self.preco_entrada:.4f} USDT\n"
            f"Saída: {preco_venda:.4f} USDT\n"
            f"Resultado bruto: {resultado_bruto:.2f} USDT\n"
            f"Taxa: {taxa_venda:.6f} USDT\n"
            f"Resultado líquido: {resultado:.2f} USDT ({percentual:.2f}%)\n"
            f"Resultado total da operação: {resultado_total:.2f} USDT\n"
            f"Taxas totais: {taxas_total:.6f} USDT\n"
            f"Motivo: {motivo_saida}\n"
            f"Duração: {(datetime.now() - self.tempo_entrada).total_seconds() / 60:.1f} min\n\n"
            f"💰 Patrimônio antes: {patrimonio_antes:.2f} USDT\n"
            f"💰 Patrimônio depois: {patrimonio_depois:.2f} USDT ({(patrimonio_depois/patrimonio_antes - 1)*100:.3f}%)"
        )
        
        # Resetar variáveis de controle
        self.em_operacao = False
        self.trailing_stop_ativo = False
        self.preco_entrada = 0
        self.quantidade = 0
        self.ordem_id = None
        self.ordem_stop_id = None
        self.posicao_parcial = False
        self.saidas_parciais = []
        self.taxa_total_operacao = 0
        if hasattr(self, 'quantidade_restante'):
            delattr(self, 'quantidade_restante')
        self.ultima_operacao_resultado = resultado
        self.ultima_operacao_motivo = motivo_saida
        self.ultimo_preco_saida = preco_venda
        self.ultima_operacao_timestamp = datetime.now()
        
        return True 
        
    def executar_venda_emergencia(self, preco_atual, motivo_saida):
        """Executar venda de emergência quando o stop virtual é acionado"""
        if not self.em_operacao:
            print("Não há operação em andamento para encerrar")
            return False
        
        print(f"⚠️ EXECUTANDO VENDA DE EMERGÊNCIA: {motivo_saida}")
        self.registrar_log(f"VENDA DE EMERGÊNCIA: {motivo_saida} a {preco_atual:.2f}")
        
        # Se estamos em modo simulação, apenas registrar
        if MODO_SIMULACAO:
            self.executar_venda_manual(preco_atual, motivo_saida)
            return True
        
        try:
            # Tentar vender a quantidade restante ao preço de mercado
            quantidade_venda = self.quantidade_restante if hasattr(self, 'quantidade_restante') else self.quantidade
            
            # Verificar se a quantidade é válida
            if quantidade_venda <= 0:
                print(f"Quantidade inválida para venda: {quantidade_venda}")
                return False
                
            # Executar ordem de venda a mercado
            ordem = self.client.create_order(
                symbol=self.symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=self.normalize_quantity(quantidade_venda)
            )
            
            print(f"Ordem de venda de emergência executada: {ordem}")
            
            # Calcular preço médio de venda a partir do fill
            preco_venda = 0
            quantidade_vendida = 0
            
            for fill in ordem['fills']:
                quantidade_fill = float(fill['qty'])
                preco_fill = float(fill['price'])
                quantidade_vendida += quantidade_fill
                preco_venda += preco_fill * quantidade_fill
            
            if quantidade_vendida > 0:
                preco_venda = preco_venda / quantidade_vendida
            else:
                preco_venda = preco_atual
                
            # Registrar com o mecanismo normal de saída
            self.executar_venda_manual(preco_venda, f"{motivo_saida} (Venda Emergencial)")
            return True
            
        except BinanceAPIException as e:
            print(f"Erro ao executar venda de emergência: {e}")
            self.registrar_log(f"ERRO VENDA EMERGÊNCIA: {e}")
            
            # Ainda registrar a saída para efeitos de contabilidade, mesmo que falhe
            self.executar_venda_manual(preco_atual, f"{motivo_saida} (Falha na Execução)")
            return False
    
    def verificar_alertas(self, df):
        """Verificar condições para alertas de potenciais oportunidades"""
        # Se já estamos em uma operação, não enviar alertas de entrada
        if self.em_operacao:
            return
            
        if len(df) < 2:
            return
            
        # Obter os últimos dois candles
        penultimo = df.iloc[-2]
        ultimo = df.iloc[-1]
        
        # Verificar condições específicas para alerta
        
        # 1. Cruzamento MA7 acima de MA25
        cruzamento = (penultimo[f'ma_{MA_CURTA}'] <= penultimo[f'ma_{MA_MEDIA}'] and
                    ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}'])
                        
        # 2. MA99 em tendência de alta
        if 'ma_longa_inclinacao' in df.columns:
            tendencia_alta_forte = float(df['ma_longa_inclinacao'].iloc[-1]) > 0
        else:
            tendencia_alta_forte = float(ultimo[f'ma_{MA_LONGA}']) > float(penultimo[f'ma_{MA_LONGA}'])
        
        # 3. RSI entre valores ótimos
        rsi_otimo = RSI_ZONA_OTIMA_MIN <= ultimo['rsi'] <= RSI_ZONA_OTIMA_MAX
        
        # 4. Volume acima da média
        volume_alto = ultimo['volume'] >= ultimo['volume_media'] * (VOLUME_MINIMO_PERCENTUAL / 100)
        
        # 5. Verificar padrões de candles
        padrao_candle, nome_padrao, _ = self.identificar_padrao_candle(df)
        
        # Verificar proximidade a zonas S/R
        preco_atual = ultimo['close']
        proximo_sr, msg_sr = self.esta_proximo_sr(preco_atual)
        
        # Construir condições presentes
        condicoes = []
        if cruzamento:
            condicoes.append("MA7 cruzou acima da MA25")
        if tendencia_alta_forte:
            condicoes.append("MA99 em tendência de alta")
        if rsi_otimo:
            condicoes.append(f"RSI em zona ótima ({ultimo['rsi']:.2f})")
        if volume_alto:
            condicoes.append(f"Volume alto ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
        if padrao_candle:
            condicoes.append(f"Padrão de candle: {nome_padrao}")
        if proximo_sr:
            condicoes.append(f"⚠️ {msg_sr}")
        
        # Determinar tipo e força do sinal
        if len(condicoes) >= 3 and (cruzamento or padrao_candle) and tendencia_alta_forte:
            # Montar mensagem de alerta
            mensagem = f"🔔 *ALERTA: Condições Favoráveis* 🔔\n\n"
            mensagem += f"*{self.symbol}: ${ultimo['close']:.2f}*\n\n"
            mensagem += "Condições detectadas:\n"
            for cond in condicoes:
                mensagem += f"• {cond}\n"
            
            # Adicionar avaliação geral
            if len(condicoes) >= 4 and not (proximo_sr and "resistência" in msg_sr):
                mensagem += "\n⭐⭐⭐ *SINAL FORTE* ⭐⭐⭐"
            elif len(condicoes) >= 3:
                mensagem += "\n⭐⭐ *SINAL MODERADO* ⭐⭐"
            else:
                mensagem += "\n⭐ *SINAL FRACO* ⭐"
            
            # Enviar alerta
            # Verificar configurações de cada usuário antes de enviar
            for user_id in self.alert_system.user_settings.settings:
                # Verificar se este usuário quer receber alertas de condições favoráveis
                if self.alert_system.user_wants_alerts(user_id):
                    # Enviar alerta para este usuário específico
                    self.alert_system.send_telegram(mensagem, chat_id=user_id)
            
    def verificar_metas_diarias(self):
        """Verificar se atingimos as metas ou limites diários - Apenas registra, não interrompe execução"""
        percentual_lucro = (self.lucro_diario / CAPITAL_TOTAL) * 100
        percentual_perda = (self.perda_diaria / CAPITAL_TOTAL) * 100
        
        print(f"Status atual: Lucro {percentual_lucro:.2f}% | Perda {percentual_perda:.2f}%")
        self.registrar_log(f"STATUS: Lucro {percentual_lucro:.2f}% | Perda {percentual_perda:.2f}%")
        
        # Verificar se é um novo dia
        dia_atual = datetime.now().day
        if dia_atual != self.ultima_verificacao_dia:
            # Resetar contadores para o novo dia
            self.lucro_diario = 0
            self.perda_diaria = 0
            self.operacoes_dia = []
            self.operacoes_hoje = 0
            self.ultima_verificacao_dia = dia_atual
            self.registrar_log("NOVO DIA: Contadores resetados")
            return False
        
        # Verificar se atingiu a meta diária - apenas registra, não para execução
        if percentual_lucro >= ALVO_DIARIO_PERCENTUAL:
            print(f"META DIÁRIA ATINGIDA! Lucro de {self.lucro_diario:.2f} USDT ({percentual_lucro:.2f}%)")
            self.registrar_log(f"META DIÁRIA ATINGIDA! Lucro de {self.lucro_diario:.2f} USDT ({percentual_lucro:.2f}%)")
            
            # Enviar alerta
            self.send_telegram_alert(
                f"🎯 META DIÁRIA ATINGIDA!\n\n"
                f"Lucro: {self.lucro_diario:.2f} USDT ({percentual_lucro:.2f}%)\n"
                f"Total de operações: {len(self.operacoes_dia)}\n"
                f"Taxa de acerto: {(self.trades_vencedores / max(1, self.trades_vencedores + self.trades_perdedores)) * 100:.1f}%\n\n"
                f"Continuando a buscar oportunidades com gestão de risco reforçada."
            )
            
            return True  # Retorna True apenas para indicar meta atingida, mas não interrompe execução
        
        # Verificar se atingiu o limite de perda - apenas registra, não para execução
        if percentual_perda >= PERDA_MAXIMA_PERCENTUAL:
            print(f"LIMITE DE PERDA ATINGIDO! Perda de {self.perda_diaria:.2f} USDT ({percentual_perda:.2f}%)")
            self.registrar_log(f"LIMITE DE PERDA ATINGIDO! Perda de {self.perda_diaria:.2f} USDT ({percentual_perda:.2f}%)")
            
            # Enviar alerta
            self.send_telegram_alert(
                f"⛔ LIMITE DE PERDA ATINGIDO!\n\n"
                f"Perda: {self.perda_diaria:.2f} USDT ({percentual_perda:.2f}%)\n"
                f"Continuando com tamanho reduzido de operações e gestão de risco reforçada."
            )
            
            return True  # Retorna True apenas para indicar limite atingido, mas não interrompe execução
        
        # Verificar drawdown excessivo
        drawdown = (self.valor_maximo_carteira - (CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria)) / self.valor_maximo_carteira * 100
        if drawdown > 2.0:  # Drawdown de 2% em relação ao pico
            print(f"ALERTA DE DRAWDOWN! {drawdown:.2f}% abaixo do máximo da carteira")
            self.registrar_log(f"ALERTA DE DRAWDOWN: {drawdown:.2f}% abaixo do máximo")
            
            # Não encerra operações, mas avisa
            if drawdown > 5.0 and not hasattr(self, 'alerta_drawdown_enviado'):
                self.alerta_drawdown_enviado = True
                self.send_telegram_alert(
                    f"⚠️ DRAWDOWN SIGNIFICATIVO!\n\n"
                    f"Atual: {drawdown:.2f}% abaixo do máximo\n"
                    f"Reduzindo tamanho das posições automaticamente para 50% do valor padrão."
                )
        
        return False

    def registrar_log(self, mensagem):
        """Registrar mensagem no arquivo de log"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"{timestamp} - {mensagem}\n"
        
        # Nome do arquivo de log com a data atual
        data_atual = datetime.now().strftime("%Y%m%d")
        nome_arquivo = f"{self.pasta_logs}/log_{data_atual}.txt"
        
        with open(nome_arquivo, "a", encoding='utf-8') as f:
            f.write(log_line)

    def send_telegram_alert(self, message):
        """Enviar alerta via Telegram com throttling"""
        if not hasattr(self, 'telegram_token') or self.telegram_token == 'SEU_TOKEN_AQUI':
            print("Telegram não configurado corretamente")
            return False
                
        # Evitar spam de alertas (mínimo 30 segundos entre alertas do mesmo tipo)
        current_time = time.time()
        message_type = message.split('\n')[0]  # Usar primeira linha como tipo
        
        # Inicializar dicionário se não existir
        if not hasattr(self, 'last_alert_times'):
            self.last_alert_times = {}
                
        # Verificar se este tipo de mensagem foi enviado recentemente
        if message_type in self.last_alert_times:
            if current_time - self.last_alert_times[message_type] < 30:
                print(f"Alerta ignorado (cooldown ativo para {message_type})")
                return False
                    
        # Atualizar timestamp para este tipo de alerta
        self.last_alert_times[message_type] = current_time
        
        try:
            # Sanitizar a mensagem para evitar problemas de formatação
            # Remover caracteres que podem causar problemas no Telegram
            sanitized_message = message.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
            
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": sanitized_message,
                "parse_mode": "MarkdownV2"  # Mudado para MarkdownV2 que lida melhor com escapes
            }
            
            response = requests.post(url, data=data)
            success = response.status_code == 200
            
            if success:
                print(f"Alerta Telegram enviado com sucesso!")
            else:
                # Se falhar com MarkdownV2, tentar sem formatação
                if 'parse_mode' in data:
                    del data['parse_mode']
                    data['text'] = message  # Usar mensagem original sem escapes
                    response = requests.post(url, data=data)
                    success = response.status_code == 200
                    print(f"Alerta enviado sem formatação após falha inicial")
                else:
                    print(f"Erro ao enviar alerta: {response.text}")
                        
            return success
        except Exception as e:
            print(f"Erro ao enviar alerta Telegram: {e}")
            return False

    def plotar_grafico(self, df, mostrar_sinais=True, salvar=True):
        """Plotar gráfico com indicadores e sinais"""
        plt.figure(figsize=(14, 10))
        
        # Subplot para preço e médias móveis
        ax1 = plt.subplot(4, 1, 1)
        ax1.plot(df['timestamp'], df['close'], label='Preço', color='black')
        ax1.plot(df['timestamp'], df[f'ma_{MA_CURTA}'], label=f'MA {MA_CURTA}', color='blue')
        ax1.plot(df['timestamp'], df[f'ma_{MA_MEDIA}'], label=f'MA {MA_MEDIA}', color='orange')
        ax1.plot(df['timestamp'], df[f'ma_{MA_LONGA}'], label=f'MA {MA_LONGA}', color='red')
        
        # Marcar zonas de suporte e resistência
        ultimo_preco = df['close'].iloc[-1]
        y_min, y_max = ultimo_preco * 0.95, ultimo_preco * 1.05
        
        # Mostrar suportes e resistências fortes
        if "suportes_fortes" in self.zonas_sr:
            for suporte, forca in self.zonas_sr["suportes_fortes"]:
                if y_min <= suporte <= y_max:
                    ax1.axhline(y=suporte, color='green', linestyle='--', alpha=0.5)
                    ax1.text(df['timestamp'].iloc[-1], suporte, f"S: {suporte:.2f} ({forca})", color='green')
        
        if "resistencias_fortes" in self.zonas_sr:
            for resistencia, forca in self.zonas_sr["resistencias_fortes"]:
                if y_min <= resistencia <= y_max:
                    ax1.axhline(y=resistencia, color='red', linestyle='--', alpha=0.5)
                    ax1.text(df['timestamp'].iloc[-1], resistencia, f"R: {resistencia:.2f} ({forca})", color='red')
        
        # Mostrar bandas de Bollinger se disponíveis
        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            ax1.plot(df['timestamp'], df['bb_upper'], 'k--', alpha=0.3)
            ax1.plot(df['timestamp'], df['bb_lower'], 'k--', alpha=0.3)
            ax1.fill_between(df['timestamp'], df['bb_upper'], df['bb_lower'], color='gray', alpha=0.1)
        
        # Marcar sinais
        if mostrar_sinais:
            # Cruzamentos
            for i in range(1, len(df)):
                if (df[f'ma_{MA_CURTA}'].iloc[i-1] <= df[f'ma_{MA_MEDIA}'].iloc[i-1] and
                    df[f'ma_{MA_CURTA}'].iloc[i] > df[f'ma_{MA_MEDIA}'].iloc[i]):
                    ax1.scatter(df['timestamp'].iloc[i], df['close'].iloc[i], color='green', marker='^', s=100)
            
            # Marcar operações do dia no gráfico
            for op in self.operacoes_dia:
                # Marcar entrada
                entrada_idx = df[df['close'] == op['entrada']].index.tolist()
                if not entrada_idx and len(df) > 0:
                    # Procurar o candle mais próximo se não achar o preço exato
                    entrada_idx = [df['close'].sub(op['entrada']).abs().idxmin()]
                
                if entrada_idx:
                    ax1.scatter(df['timestamp'].iloc[entrada_idx[0]], op['entrada'], color='blue', marker='o', s=100)
                    ax1.text(df['timestamp'].iloc[entrada_idx[0]], op['entrada']*1.001, "E", color='blue')
                
                # Marcar saída
                saida_idx = df[df['close'] == op['saida']].index.tolist()
                if not saida_idx and len(df) > 0:
                    # Procurar o candle mais próximo
                    saida_idx = [df['close'].sub(op['saida']).abs().idxmin()]
                
                if saida_idx:
                    marker_color = 'green' if op['resultado'] > 0 else 'red'
                    ax1.scatter(df['timestamp'].iloc[saida_idx[0]], op['saida'], color=marker_color, marker='x', s=100)
                    ax1.text(df['timestamp'].iloc[saida_idx[0]], op['saida']*1.001, "S", color=marker_color)
        
        ax1.set_title(f'{self.symbol} - {self.timeframe} - {datetime.now().strftime("%Y-%m-%d %H:%M")}')
        ax1.set_ylabel('Preço')
        ax1.legend()
        ax1.grid(True)
        
        # Subplot para MACD
        if 'macd' in df.columns and 'macd_signal' in df.columns and 'macd_hist' in df.columns:
            ax2 = plt.subplot(4, 1, 2, sharex=ax1)
            ax2.plot(df['timestamp'], df['macd'], label='MACD', color='blue')
            ax2.plot(df['timestamp'], df['macd_signal'], label='Signal', color='red')
            
            # Histograma MACD
            for i in range(len(df)):
                if i > 0:
                    hist = df['macd_hist'].iloc[i]
                    color = 'green' if hist > 0 else 'red'
                    ax2.bar(df['timestamp'].iloc[i], hist, color=color, alpha=0.5, width=0.7)
            
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            ax2.set_ylabel('MACD')
            ax2.legend()
            ax2.grid(True)
        
        # Subplot para volume
        ax3 = plt.subplot(4, 1, 3, sharex=ax1)
        
        # Barras de volume coloridas de acordo com direção do preço
        for i in range(len(df)):
            if i > 0:
                color = 'green' if df['close'].iloc[i] >= df['open'].iloc[i] else 'red'
                ax3.bar(df['timestamp'].iloc[i], df['volume'].iloc[i], color=color, alpha=0.5, width=0.7)
        
        ax3.plot(df['timestamp'], df['volume_media'], color='blue', label=f'Média ({VOLUME_PERIODO} períodos)')
        ax3.set_ylabel('Volume')
        ax3.legend()
        ax3.grid(True)
        
        # Subplot para RSI
        ax4 = plt.subplot(4, 1, 4, sharex=ax1)
        ax4.plot(df['timestamp'], df['rsi'], color='blue', label='RSI')
        ax4.axhline(y=RSI_SOBRECOMPRA, color='red', linestyle='--')
        ax4.axhline(y=RSI_SOBREVENDA, color='green', linestyle='--')
        ax4.axhline(y=RSI_ZONA_OTIMA_MAX, color='orange', linestyle='--', alpha=0.5)
        ax4.axhline(y=RSI_ZONA_OTIMA_MIN, color='orange', linestyle='--', alpha=0.5)
        ax4.fill_between(df['timestamp'], RSI_ZONA_OTIMA_MIN, RSI_ZONA_OTIMA_MAX, color='green', alpha=0.1)
        ax4.set_ylim(0, 100)
        ax4.set_ylabel('RSI')
        ax4.grid(True)
        
        plt.tight_layout()
        
        # Salvar gráfico na pasta de logs
        if salvar:
            data_hora = datetime.now().strftime("%Y%m%d_%H%M%S")
            plt.savefig(f"{self.pasta_logs}/{self.symbol}_{self.timeframe}_{data_hora}.png")
            plt.close()
        else:
            plt.show()

    def executar_venda_manual(self, preco_venda, motivo_saida):
        """Encerrar posição manualmente ou registrar execução de saída automática, considerando taxas"""
        if not self.em_operacao:
            print("Não há operação em andamento para encerrar")
            return False
        
        # CORREÇÃO: Cancelar qualquer ordem de stop loss pendente
        if hasattr(self, 'ordem_stop_id') and self.ordem_stop_id:
            try:
                self.client.cancel_order(symbol=self.symbol, orderId=self.ordem_stop_id)
                print(f"Stop loss anterior cancelado: {self.ordem_stop_id}")
                self.registrar_log(f"CANCELAMENTO: Stop loss anterior {self.ordem_stop_id} cancelado")
                self.ordem_stop_id = None
            except Exception as e:
                print(f"Erro ao cancelar stop loss anterior: {e}")
                self.registrar_log(f"ERRO: Falha ao cancelar stop loss anterior: {e}")
        
        # Calcular resultado
        if hasattr(self, 'quantidade_restante'):
            quantidade_venda = self.quantidade_restante
        else:
            quantidade_venda = self.quantidade
        
        # CORREÇÃO: Executar venda real antes de calcular taxas e resultados
        ordem_executada = False
        if not MODO_SIMULACAO:
            try:
                print(f"Executando venda real a mercado de {quantidade_venda} {self.symbol}")
                ordem = self.client.create_order(
                    symbol=self.symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=self.normalize_quantity(quantidade_venda)
                )
                
                # Verificar se a ordem foi executada
                if 'fills' in ordem and len(ordem['fills']) > 0:
                    # Usar o preço médio de execução real
                    preco_total = 0
                    qtd_total = 0
                    for fill in ordem['fills']:
                        preco_fill = float(fill['price'])
                        qtd_fill = float(fill['qty'])
                        preco_total += preco_fill * qtd_fill
                        qtd_total += qtd_fill
                    
                    if qtd_total > 0:
                        preco_venda = preco_total / qtd_total
                        print(f"Venda executada ao preço médio: {preco_venda}")
                        
                    ordem_executada = True
                else:
                    print("⚠️ Ordem enviada, mas sem confirmação de execução - verificando status")
                    # Verificar status da ordem
                    try:
                        ordem_status = self.client.get_order(symbol=self.symbol, orderId=ordem['orderId'])
                        if ordem_status['status'] == 'FILLED':
                            ordem_executada = True
                            print(f"Ordem confirmada como executada: {ordem_status['status']}")
                        else:
                            print(f"⚠️ Ordem não executada completamente: {ordem_status['status']}")
                            self.registrar_log(f"ALERTA: Venda não completada, status={ordem_status['status']}")
                    except Exception as e_status:
                        print(f"Erro ao verificar status da ordem: {e_status}")
                
                if not ordem_executada:
                    self.registrar_log(f"ERRO: Falha na execução da venda manual")
                    return False
                    
            except Exception as e:
                print(f"Erro ao executar venda: {e}")
                self.registrar_log(f"ERRO VENDA: {e}")
                # Continuar com cálculos mesmo em caso de erro
                # mas marcar explicitamente no log
                self.registrar_log("AVISO: Calculando resultado com base no preço teórico devido a erro")
        
        # Calcular taxa de venda
        if MODO_SIMULACAO:
            taxa_venda = preco_venda * quantidade_venda * self.taxa_efetiva
        else:
            if ordem_executada and 'fills' in ordem:
                # Calcular taxa real baseada nos fills
                taxa_venda = 0
                for fill in ordem['fills']:
                    if 'commission' in fill and 'commissionAsset' in fill:
                        commission = float(fill['commission'])
                        commission_asset = fill['commissionAsset']
                        
                        # Converter taxa para USDT dependendo do asset
                        if commission_asset == 'BNB':
                            bnb_price = float(self.client.get_symbol_ticker(symbol='BNBUSDT')['price'])
                            taxa_venda += commission * bnb_price
                        elif commission_asset == 'USDT':
                            taxa_venda += commission
                        else:
                            taxa_venda += commission * preco_venda
            else:
                # Estimativa se não temos dados reais
                taxa_venda = preco_venda * quantidade_venda * self.taxa_efetiva
        
        # Atualizar taxa total da operação e acumulada
        self.taxa_total_operacao += taxa_venda
        self.taxas_pagas_total += taxa_venda
        
        # Calcular resultado da operação (bruto e líquido)
        resultado_bruto = (preco_venda - self.preco_entrada) * quantidade_venda
        resultado = resultado_bruto - taxa_venda  # Resultado líquido após taxa
        percentual = (preco_venda - self.preco_entrada) / self.preco_entrada * 100
        
        # Adicionar ao lucro ou perda diária (valor líquido)
        if resultado > 0:
            self.lucro_diario += resultado
            self.trades_vencedores += 1
            self.sequencia_perdas_atual = 0
            status = "LUCRO"
        else:
            self.perda_diaria += abs(resultado)
            self.trades_perdedores += 1
            self.sequencia_perdas_atual += 1
            self.maior_sequencia_perdas = max(self.maior_sequencia_perdas, self.sequencia_perdas_atual)
            status = "PERDA"
        
        # Incluir resultados de saídas parciais se houver
        resultado_total = resultado
        taxas_total = taxa_venda
        if self.posicao_parcial and self.saidas_parciais:
            for saida in self.saidas_parciais:
                resultado_total += saida['resultado']
                taxas_total += saida.get('taxa', 0)
        
        # Calcular percentual total considerando saídas parciais
        percentual_total = (resultado_total + taxas_total) / (self.preco_entrada * self.quantidade) * 100
        
        # Adicionar à lista de operações do dia
        self.operacoes_dia.append({
            'entrada': self.preco_entrada,
            'saida': preco_venda,
            'resultado_bruto': resultado_bruto + (sum(s.get('resultado_bruto', 0) for s in self.saidas_parciais) if self.saidas_parciais else 0),
            'taxas': self.taxa_total_operacao,
            'resultado': resultado_total,  # Resultado líquido total
            'lucro_percentual': percentual_total,
            'timestamp': datetime.now(),
            'duracao_minutos': (datetime.now() - self.tempo_entrada).total_seconds() / 60,
            'motivo_entrada': self.motivo_entrada,
            'motivo_saida': motivo_saida,
            'saidas_parciais': self.saidas_parciais if hasattr(self, 'saidas_parciais') else []
        })
        
        # Registrar detalhes da operação no log
        self.log_operacoes.append({
            'timestamp': datetime.now(),
            'tipo': f'SAÍDA ({status})',
            'preco': preco_venda,
            'quantidade': quantidade_venda,
            'taxa': taxa_venda,
            'resultado_bruto': resultado_bruto,
            'resultado': resultado,
            'percentual': percentual,
            'resultado_total': resultado_total,
            'taxas_total': taxas_total,
            'percentual_total': percentual_total,
            'motivo': motivo_saida
        })
        
        # Registrar no log
        self.registrar_log(
            f"SAÍDA {status}: Preço={preco_venda:.2f} | " +
            f"Resultado bruto={resultado_bruto:.2f} | Taxa={taxa_venda:.6f} | " +
            f"Resultado líquido={resultado:.2f} USDT ({percentual:.2f}%) | " +
            f"Motivo: {motivo_saida}"
        )
        
        # Calcular patrimônio antes e depois
        patrimonio_antes = CAPITAL_TOTAL + self.lucro_diario - self.perda_diaria
        patrimonio_depois = patrimonio_antes + resultado

        # Enviar alerta com emoji adequado e informações adicionais
        emoji = "✅" if resultado > 0 else "❌"
        self.send_telegram_alert(
            f"{emoji} POSIÇÃO ENCERRADA: {status}\n\n"
            f"Entrada: {self.preco_entrada:.4f} USDT\n"
            f"Saída: {preco_venda:.4f} USDT\n"
            f"Resultado bruto: {resultado_bruto:.2f} USDT\n"
            f"Taxa: {taxa_venda:.6f} USDT\n"
            f"Resultado líquido: {resultado:.2f} USDT ({percentual:.2f}%)\n"
            f"Resultado total da operação: {resultado_total:.2f} USDT\n"
            f"Taxas totais: {taxas_total:.6f} USDT\n"
            f"Motivo: {motivo_saida}\n"
            f"Duração: {(datetime.now() - self.tempo_entrada).total_seconds() / 60:.1f} min\n\n"
            f"💰 Patrimônio antes: {patrimonio_antes:.2f} USDT\n"
            f"💰 Patrimônio depois: {patrimonio_depois:.2f} USDT ({(patrimonio_depois/patrimonio_antes - 1)*100:.3f}%)"
        )
        
        # Resetar variáveis de controle
        self.em_operacao = False
        self.trailing_stop_ativo = False
        self.preco_entrada = 0
        self.quantidade = 0
        self.ordem_id = None
        self.ordem_stop_id = None
        self.posicao_parcial = False
        self.saidas_parciais = []
        self.taxa_total_operacao = 0
        if hasattr(self, 'quantidade_restante'):
            delattr(self, 'quantidade_restante')
        self.ultima_operacao_resultado = resultado
        self.ultima_operacao_motivo = motivo_saida
        self.ultimo_preco_saida = preco_venda
        self.ultima_operacao_timestamp = datetime.now()
        
        return True

    def iniciar(self, intervalo_segundos=5):
        """Iniciar o bot em loop contínuo sem interrupção"""
        print(f"Bot iniciado em modo contínuo. Verificando a cada {intervalo_segundos} segundos.")
        print(f"Modo: {'SIMULAÇÃO' if MODO_SIMULACAO else 'REAL - OPERAÇÕES COM CAPITAL REAL'}")
        
        self.registrar_log(
            f"BOT INICIADO EM MODO CONTÍNUO: Capital={CAPITAL_TOTAL} USDT | "
            f"Meta={ALVO_DIARIO_PERCENTUAL}% | "
            f"Modo={'SIMULAÇÃO' if MODO_SIMULACAO else 'REAL'}"
        )
        
        # Flag para controle de execução contínua
        execucao_continua = True
        
        while execucao_continua:  # Loop infinito
            try:
                print(f"\n--- {datetime.now()} ---")
                
                # Verificar se já vamos procurar uma moeda alternativa:
                # 1. Se não estamos em nenhuma operação 
                # 2. E já passou tempo suficiente desde a última busca (20 minutos)
                # 3. E estamos sem oportunidades há algum tempo (3 minutos)
                agora = datetime.now()
                if (not self.em_operacao and 
                    (agora - self.ultima_busca_moedas).total_seconds() > 1200 and  # 20 minutos
                    self.tempo_sem_oportunidades > 180):  # 3 minutos
                    
                    moeda_sugerida = self.buscar_moeda_alternativa()
                    
                    if moeda_sugerida:
                        self.send_telegram_alert(
                            f"⚠️ AUSÊNCIA DE OPORTUNIDADES\n\n"
                            f"Atual: {self.symbol}\n"
                            f"Tempo sem boas oportunidades: {self.tempo_sem_oportunidades//60} minutos\n\n"
                            f"Uma moeda alternativa foi sugerida. Responda com /mudar_{moeda_sugerida} para alterar."
                        )
                    
                    # Resetar contadores
                    self.ultima_busca_moedas = agora
                    self.tempo_sem_oportunidades = 0
                
                # Executar ciclo normal
                self.executar_ciclo()
                
                # Se não estamos em operação, incrementar contador de tempo sem oportunidades
                if not self.em_operacao:
                    self.tempo_sem_oportunidades += intervalo_segundos
                else:
                    # Resetar contador quando estamos em operação
                    self.tempo_sem_oportunidades = 0
                    
                time.sleep(intervalo_segundos)
                
            except KeyboardInterrupt:
                print("\nBot interrompido manualmente pelo usuário.")
                execucao_continua = False  # Única forma de sair do loop é interrupção manual
                self.registrar_log("BOT INTERROMPIDO MANUALMENTE PELO USUÁRIO")
                
            except Exception as e:
                print(f"Erro recuperável: {e}")
                import traceback
                traceback.print_exc()
                self.registrar_log(f"ERRO RECUPERÁVEL: {str(e)}")
                
                # Tentar enviar alerta de erro, mas não interromper o bot
                try:
                    self.send_telegram_alert(f"⚠️ ERRO RECUPERÁVEL\n\n{str(e)}\n\nO bot continuará operando.")
                except:
                    pass
                
                # Tempo para recuperação antes de continuar
                print("Aguardando 60 segundos para recuperação...")
                time.sleep(60)
                
        # Relatório final somente se sair do loop
        self.gerar_relatorio()
    # 6. Modificar o método gerar_relatorio para incluir informações sobre taxas

    def gerar_relatorio(self):
        """Gerar relatório de desempenho incluindo análise de taxas"""
        print("\n--- RELATÓRIO DE DESEMPENHO ---")
        print(f"Início: {self.data_inicio}")
        print(f"Fim: {datetime.now()}")
        print(f"Total de operações: {len(self.operacoes_dia)}")
        print(f"Lucro total: {self.lucro_diario:.2f} USDT ({(self.lucro_diario/CAPITAL_TOTAL)*100:.2f}%)")
        print(f"Perda total: {self.perda_diaria:.2f} USDT ({(self.perda_diaria/CAPITAL_TOTAL)*100:.2f}%)")
        print(f"Taxas pagas: {self.taxas_pagas_total:.4f} USDT ({(self.taxas_pagas_total/CAPITAL_TOTAL)*100:.4f}%)")
        
        # Calcular resultado líquido (considerando taxas)
        resultado_liquido = self.lucro_diario - self.perda_diaria
        resultado_percentual = (resultado_liquido / CAPITAL_TOTAL) * 100
        
        # Calcular impacto das taxas no resultado
        if resultado_liquido > 0 and self.taxas_pagas_total > 0:
            impacto_taxas_percentual = (self.taxas_pagas_total / (resultado_liquido + self.taxas_pagas_total)) * 100
            print(f"Impacto das taxas: {impacto_taxas_percentual:.2f}% do resultado bruto")
        
        # Inicializa taxa_acerto com valor padrão
        taxa_acerto = 0.0
        
        # Performance
        if self.trades_vencedores + self.trades_perdedores > 0:
            taxa_acerto = self.trades_vencedores / (self.trades_vencedores + self.trades_perdedores) * 100
            print(f"Taxa de acerto: {taxa_acerto:.2f}% ({self.trades_vencedores}/{self.trades_vencedores + self.trades_perdedores})")
            print(f"Maior sequência de perdas: {self.maior_sequencia_perdas}")
        else:
            print("Não há trades computados para calcular taxa de acerto.")
        
        # Valor máximo da carteira
        print(f"Valor máximo da carteira: {self.valor_maximo_carteira:.2f} USDT")
        
        # Maior drawdown
        carteira_atual = CAPITAL_TOTAL + resultado_liquido - self.taxas_pagas_total
        drawdown = (self.valor_maximo_carteira - carteira_atual) / self.valor_maximo_carteira * 100
        if self.valor_maximo_carteira > CAPITAL_TOTAL:
            print(f"Drawdown máximo: {drawdown:.2f}%")
        
        if self.operacoes_dia:
            # Calcular estatísticas incluindo taxas
            resultado_bruto_total = sum(op.get('resultado_bruto', 0) for op in self.operacoes_dia)
            taxas_total = sum(op.get('taxas', 0) for op in self.operacoes_dia)
            resultado_liquido_total = sum(op.get('resultado', 0) for op in self.operacoes_dia)
            
            print(f"Resultado bruto total: {resultado_bruto_total:.2f} USDT")
            print(f"Taxas totais: {taxas_total:.4f} USDT")
            print(f"Resultado líquido total: {resultado_liquido_total:.2f} USDT")
            
            # Estatísticas adicionais
            lucros = [op['resultado'] for op in self.operacoes_dia if op['resultado'] > 0]
            perdas = [abs(op['resultado']) for op in self.operacoes_dia if op['resultado'] < 0]
            
            if lucros:
                print(f"Lucro médio: {sum(lucros)/len(lucros):.2f} USDT")
                print(f"Maior lucro: {max(lucros):.2f} USDT")
            
            if perdas:
                print(f"Perda média: {sum(perdas)/len(perdas):.2f} USDT")
                print(f"Maior perda: {max(perdas):.2f} USDT")
            
            # Tempo médio em operação
            if 'duracao_minutos' in self.operacoes_dia[0]:
                tempo_medio = sum(op.get('duracao_minutos', 0) for op in self.operacoes_dia) / len(self.operacoes_dia)
                print(f"Tempo médio em operação: {tempo_medio:.1f} minutos")
            
            # Detalhes das operações
            print("\nDetalhes das operações:")
            for i, op in enumerate(self.operacoes_dia, 1):
                resultado = "LUCRO" if op['resultado'] > 0 else "PERDA"
                taxas_op = op.get('taxas', 0)
                
                print(f"Op #{i}: {resultado} {op['resultado']:.2f} USDT ({op.get('lucro_percentual', 0):.2f}%) | " +
                    f"Taxas: {taxas_op:.4f} USDT | " +
                    f"Entrada: {op['entrada']} | Saída: {op['saida']} | " +
                    f"Motivo entrada: {op.get('motivo_entrada', 'N/A')} | " +
                    f"Motivo saída: {op.get('motivo_saida', 'N/A')}")
                
                # Mostrar saídas parciais se houver
                if 'saidas_parciais' in op and op['saidas_parciais']:
                    for saida in op['saidas_parciais']:
                        print(f"  - Saída Parcial {saida['nivel']}: {saida['resultado']:.2f} USDT ({saida['percentual']:.2f}%) | Taxa: {saida.get('taxa', 0):.4f} USDT")
        
        # Incluir informações de análise macro no relatório
        if USAR_ANALISE_MACRO:
            print("\n--- ANÁLISE MACRO ---")
            
            try:
                # Obter análises macro mais recentes
                sentimento_score, sentimento_desc, _ = self.analisar_sentimento_mercado()
                correlacao_score, correlacao_desc, _, _ = self.analisar_correlacoes()
                dominancia_score, dominancia_desc, _, _ = self.analisar_dominancia_btc()
                
                print(f"Sentimento de mercado: {sentimento_desc} (multiplicador: {sentimento_score:.2f})")
                print(f"Correlação: {correlacao_desc} (multiplicador: {correlacao_score:.2f})")
                print(f"Dominância BTC: {dominancia_desc} (multiplicador: {dominancia_score:.2f})")
                
                # Gerar gráfico final
                caminho_grafico = self.visualizar_indicadores_macro()
                if caminho_grafico:
                    print(f"Gráfico de indicadores macro gerado: {caminho_grafico}")
            except Exception as e:
                print(f"Erro ao gerar relatório de análise macro: {e}")

        # Enviar relatório por Telegram
        if hasattr(self, 'telegram_token') and self.telegram_token != 'SEU_TOKEN_AQUI':
            resultado_emoji = "📈" if resultado_liquido > 0 else "📉"
            
            # Calcular patrimônio inicial e final
            patrimonio_inicial = CAPITAL_TOTAL
            patrimonio_final = CAPITAL_TOTAL + resultado_liquido
            
            mensagem = (
                f"{resultado_emoji} *RELATÓRIO DE DESEMPENHO*\n\n"
                f"Período: {self.data_inicio.strftime('%d/%m/%Y %H:%M')} a {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                f"Total de operações: *{len(self.operacoes_dia)}*\n"
                f"Resultado bruto: *{resultado_liquido + self.taxas_pagas_total:.2f} USDT*\n"
                f"Taxas: *{self.taxas_pagas_total:.4f} USDT*\n"
                f"Resultado líquido: *{resultado_liquido:.2f} USDT ({resultado_percentual:.2f}%)*\n"
                f"Taxa de acerto: *{taxa_acerto:.1f}%*\n\n"
                f"🔹 Lucros: {self.lucro_diario:.2f} USDT ({(self.lucro_diario/CAPITAL_TOTAL)*100:.2f}%)\n"
                f"🔸 Perdas: {self.perda_diaria:.2f} USDT\n"
                f"💰 Impacto das taxas: {(self.taxas_pagas_total / max(1, resultado_liquido + self.taxas_pagas_total)) * 100:.2f}% do resultado bruto\n\n"
                f"💼 Patrimônio inicial: *{patrimonio_inicial:.2f} USDT*\n"
                f"💼 Patrimônio final: *{patrimonio_final:.2f} USDT* ({(patrimonio_final/patrimonio_inicial - 1)*100:.2f}%)"
            )
            
            # Adicionar informações de análise macro, se disponíveis
            if USAR_ANALISE_MACRO:
                try:
                    sentimento_score, sentimento_desc, _ = self.analisar_sentimento_mercado()
                    dominancia_score, dominancia_desc, _, _ = self.analisar_dominancia_btc()
                    
                    mensagem += f"\n*ANÁLISE MACRO ATUAL:*\n"
                    mensagem += f"🧠 Sentimento: {sentimento_desc}\n"
                    mensagem += f"👑 Dominância BTC: {dominancia_desc}\n"
                except Exception as e:
                    self.registrar_log(f"Erro ao adicionar análise macro ao relatório: {e}")
            
            self.send_telegram_alert(mensagem)
        
        # Registrar relatório no log
        self.registrar_log(
            f"RELATÓRIO FINAL: Operações={len(self.operacoes_dia)} | " +
            f"Resultado bruto={resultado_liquido + self.taxas_pagas_total:.2f} USDT | " +
            f"Taxas={self.taxas_pagas_total:.4f} USDT | " +
            f"Resultado líquido={resultado_liquido:.2f} USDT ({resultado_percentual:.2f}%) | " +
            f"Taxa de acerto={taxa_acerto:.1f}%"
        )
        
        # Salvar relatório detalhado em CSV
        self.salvar_relatorio_csv()
        
        # Plotar gráfico de performance
        self.plotar_performance()

    def send_telegram_image(self, image_path, caption=""):
        """Enviar imagem via Telegram"""
        if not hasattr(self, 'telegram_token') or self.telegram_token == 'SEU_TOKEN_AQUI':
            print("Telegram não configurado corretamente")
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
            
            # Verificar se o arquivo existe
            if not os.path.exists(image_path):
                print(f"Erro: arquivo de imagem não encontrado em {image_path}")
                return False
                
            # Sanitizar a legenda para evitar problemas de formatação
            sanitized_caption = caption.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
            
            with open(image_path, 'rb') as img:
                files = {'photo': img}
                data = {
                    'chat_id': self.telegram_chat_id,
                    'caption': sanitized_caption,
                    'parse_mode': 'MarkdownV2'
                }
                
                response = requests.post(url, files=files, data=data)
                success = response.status_code == 200
                
                if success:
                    print(f"Imagem enviada com sucesso via Telegram!")
                    self.registrar_log(f"Imagem enviada via Telegram: {image_path}")
                else:
                    # Se falhar com MarkdownV2, tentar sem formatação
                    if 'parse_mode' in data:
                        del data['parse_mode']
                        data['caption'] = caption  # Usar legenda original sem escapes
                        response = requests.post(url, files=files, data=data)
                        success = response.status_code == 200
                        print(f"Imagem enviada sem formatação após falha inicial")
                    else:
                        print(f"Erro ao enviar imagem: {response.text}")
                        self.registrar_log(f"Erro ao enviar imagem via Telegram: {response.text}")
                        
                return success
        except Exception as e:
            print(f"Erro ao enviar imagem via Telegram: {e}")
            self.registrar_log(f"Erro ao enviar imagem via Telegram: {str(e)}")
            return False
    
    def salvar_relatorio_csv(self):
        """Salvar relatório detalhado em CSV"""
        data_atual = datetime.now().strftime("%Y%m%d")
        arquivo_csv = f"{self.pasta_logs}/relatorio_{data_atual}.csv"
        
        # Criar DataFrame para log de operações
        if self.log_operacoes:
            df_log = pd.DataFrame(self.log_operacoes)
            df_log.to_csv(arquivo_csv, index=False)
            print(f"Relatório detalhado salvo em: {arquivo_csv}")
        
        # Salvar operações completas em formato mais estruturado
        if self.operacoes_dia:
            arquivo_operacoes = f"{self.pasta_logs}/operacoes_{data_atual}.csv"
            df_operacoes = pd.DataFrame(self.operacoes_dia)
            
            # Converter listas e dicts para strings para facilitar o CSV
            if 'saidas_parciais' in df_operacoes.columns:
                df_operacoes['saidas_parciais'] = df_operacoes['saidas_parciais'].apply(lambda x: str(x) if x else "")
            
            df_operacoes.to_csv(arquivo_operacoes, index=False)
            print(f"Operações detalhadas salvas em: {arquivo_operacoes}")

    # 7. Modificar o método plotar_performance para incluir análises de taxas

    def plotar_performance(self):
        """Plotar gráfico de performance incluindo análise de taxas"""
        if not self.operacoes_dia:
            return
        
        plt.figure(figsize=(14, 12))  # Aumentado em altura para acomodar gráfico adicional
        
        # Subplot para evolução do capital
        ax1 = plt.subplot(4, 1, 1)  # Modificado para 4 subplots (adicionamos um para taxas)
        
        # Preparar dados
        datas = []
        capital = []
        capital_atual = CAPITAL_TOTAL
        
        # Adicionar ponto inicial
        datas.append(self.data_inicio)
        capital.append(capital_atual)
        
        # Adicionar cada operação
        for op in sorted(self.operacoes_dia, key=lambda x: x.get('timestamp', self.data_inicio) if 'timestamp' in x else self.data_inicio):
            if 'timestamp' in op:
                data_op = op['timestamp']
            else:
                # Estimar timestamp se não estiver disponível
                data_op = self.data_inicio + timedelta(minutes=len(datas)*15)
            
            capital_atual += op['resultado']  # Valor já considera taxas
            datas.append(data_op)
            capital.append(capital_atual)
        
        # Plotar evolução do capital
        ax1.plot(datas, capital, 'b-', linewidth=2)
        ax1.axhline(y=CAPITAL_TOTAL, color='r', linestyle='--', alpha=0.5)
        ax1.set_title('Evolução do Capital (Após Taxas)')
        ax1.set_ylabel('Capital (USDT)')
        ax1.grid(True)
        
        # Subplot para resultados individuais
        ax2 = plt.subplot(4, 1, 2)
        
        # Extrair resultados
        resultados = [op['resultado'] for op in self.operacoes_dia]
        taxas = [op.get('taxas', 0) for op in self.operacoes_dia]
        operacoes = list(range(1, len(resultados) + 1))
        
        # Cores baseadas no resultado
        cores = ['green' if res > 0 else 'red' for res in resultados]
        
        # Plotar barras de resultado
        ax2.bar(operacoes, resultados, color=cores)
        ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax2.set_title('Resultado Líquido por Operação (Após Taxas)')
        ax2.set_xlabel('Operação #')
        ax2.set_ylabel('Resultado (USDT)')
        ax2.grid(True)
        
        # Subplot para taxas por operação
        ax3 = plt.subplot(4, 1, 3)
        
        # Plotar barras de taxas
        ax3.bar(operacoes, taxas, color='orange')
        ax3.set_title('Taxas por Operação')
        ax3.set_xlabel('Operação #')
        ax3.set_ylabel('Taxa (USDT)')
        ax3.grid(True)
        
        # Subplot para distribuição de resultados
        ax4 = plt.subplot(4, 1, 4)
        
        # Adicionar resultados brutos e líquidos para comparação
        resultados_brutos = [op.get('resultado_bruto', op['resultado'] + op.get('taxas', 0)) for op in self.operacoes_dia]
        
        # Preparar bins para os histogramas
        todos_resultados = resultados + resultados_brutos
        max_val = max(todos_resultados)
        min_val = min(todos_resultados)
        bins = np.linspace(min_val, max_val, 15)
        
        # Histograma de resultados
        ax4.hist(resultados, bins=bins, alpha=0.7, color='blue', label='Resultado Líquido')
        ax4.hist(resultados_brutos, bins=bins, alpha=0.4, color='green', label='Resultado Bruto (antes das taxas)')
        ax4.axvline(x=0, color='r', linestyle='--', alpha=0.5)
        ax4.set_title('Distribuição de Resultados')
        ax4.set_xlabel('Resultado (USDT)')
        ax4.set_ylabel('Frequência')
        ax4.legend()
        ax4.grid(True)
        
        plt.tight_layout()
        
        # Salvar gráfico
        data_hora = datetime.now().strftime("%Y%m%d_%H%M%S")
        plt.savefig(f"{self.pasta_logs}/performance_{data_hora}.png")
        plt.close()
        print(f"Gráfico de performance salvo em: {self.pasta_logs}/performance_{data_hora}.png")
        
        # Criar gráfico adicional específico para análise de taxas
        plt.figure(figsize=(14, 8))
        
        # Subplot para proporção taxas/resultado
        ax_prop = plt.subplot(1, 2, 1)
        
        # Calcular dados para o gráfico de pizza
        total_bruto = sum(resultados_brutos)
        total_liquido = sum(resultados)
        total_taxas = sum(taxas)
        
        if total_bruto > 0:
            # Gráfico de pizza para operações lucrativas
            labels = ['Resultado Líquido', 'Taxas']
            sizes = [max(0, total_liquido), total_taxas]
            explode = (0.1, 0)  # Explode a primeira fatia
            
            ax_prop.pie(sizes, explode=explode, labels=labels, autopct='%1.1f%%',
                    shadow=True, startangle=90, colors=['green', 'red'])
            ax_prop.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle
            ax_prop.set_title('Proporção: Resultado Líquido vs Taxas')
        
        # Subplot para evolução das taxas acumuladas
        ax_tax = plt.subplot(1, 2, 2)
        
        # Preparar dados
        taxas_acumuladas = []
        acumulado = 0
        
        for taxa in taxas:
            acumulado += taxa
            taxas_acumuladas.append(acumulado)
        
        # Plotar evolução das taxas
        ax_tax.plot(operacoes, taxas_acumuladas, 'r-', linewidth=2)
        ax_tax.set_title('Taxas Acumuladas')
        ax_tax.set_xlabel('Operação #')
        ax_tax.set_ylabel('Taxas Acumuladas (USDT)')
        ax_tax.grid(True)
        
        plt.tight_layout()
        
        # Salvar gráfico de taxas
        plt.savefig(f"{self.pasta_logs}/taxas_analise_{data_hora}.png")
        plt.close()
        print(f"Gráfico de análise de taxas salvo em: {self.pasta_logs}/taxas_analise_{data_hora}.png")

    # 8. Adicionar um novo método para verificar se a operação é viável considerando as taxas

    
    def testar_parametros(capital_por_operacao_pct=3, alvo_diario=0.8, alvo_lucro_1=0.15, 
                        alvo_lucro_2=0.3, alvo_lucro_3=0.5, stop_loss_atr=1.0, 
                        stop_loss_min=0.3, volume_min=115, dias=1, simulacao=True):
        """Testar o bot com parâmetros específicos"""
        
        # Atualizar constantes globais
        global CAPITAL_POR_OPERACAO_PERCENTUAL, ALVO_DIARIO_PERCENTUAL, ALVO_LUCRO_PERCENTUAL_1
        global ALVO_LUCRO_PERCENTUAL_2, ALVO_LUCRO_PERCENTUAL_3, STOP_LOSS_MULTIPLICADOR_ATR
        global STOP_LOSS_PERCENTUAL_MINIMO, VOLUME_MINIMO_PERCENTUAL, MODO_SIMULACAO
        
        CAPITAL_POR_OPERACAO_PERCENTUAL = capital_por_operacao_pct
        ALVO_DIARIO_PERCENTUAL = alvo_diario
        ALVO_LUCRO_PERCENTUAL_1 = alvo_lucro_1
        ALVO_LUCRO_PERCENTUAL_2 = alvo_lucro_2
        ALVO_LUCRO_PERCENTUAL_3 = alvo_lucro_3
        STOP_LOSS_MULTIPLICADOR_ATR = stop_loss_atr
        STOP_LOSS_PERCENTUAL_MINIMO = stop_loss_min
        VOLUME_MINIMO_PERCENTUAL = volume_min
        MODO_SIMULACAO = simulacao
        
        # Recalcular capital por operação
        global CAPITAL_POR_OPERACAO
        CAPITAL_POR_OPERACAO = CAPITAL_TOTAL * CAPITAL_POR_OPERACAO_PERCENTUAL / 100
        
        # Inicializar e executar o bot
        bot = BinanceScalpingBotMelhorado(API_KEY, API_SECRET, SYMBOL, TIMEFRAME, CAPITAL_POR_OPERACAO)
        
        # Se for teste rápido, apenas verificar sinais
        if dias == 0:
            df = bot.get_klines()
            sinal, mensagem = bot.check_signal(df)
            print(f"Análise de sinal: {mensagem}")
            params, msg_params = bot.calcular_parametros_ordem(float(df['close'].iloc[-1]))
            if params:
                print(f"Parâmetros: {msg_params}")
            return
        
        # Executar pelo número de dias especificado
        inicio = datetime.now()
        fim = inicio + timedelta(days=dias)
        
        try:
            while datetime.now() < fim:
                print(f"\n--- {datetime.now()} ---")
                bot.executar_ciclo()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nTeste interrompido pelo usuário.")
        finally:
            # Gerar relatório
            bot.gerar_relatorio()
            
            # Calcular taxa de acerto com validação para evitar divisão por zero
            taxa_acerto = 0
            if (bot.trades_vencedores + bot.trades_perdedores) > 0:
                taxa_acerto = 100 * bot.trades_vencedores / (bot.trades_vencedores + bot.trades_perdedores)
            
            # Retornar resultado para comparação
            resultado = {
                'lucro': bot.lucro_diario,
                'perda': bot.perda_diaria,
                'resultado_liquido': bot.lucro_diario - bot.perda_diaria,
                'resultado_percentual': (bot.lucro_diario - bot.perda_diaria) / CAPITAL_TOTAL * 100,
                'trades_total': bot.trades_vencedores + bot.trades_perdedores,
                'taxa_acerto': taxa_acerto,
                'parametros': {
                    'capital_por_operacao_pct': capital_por_operacao_pct,
                    'alvo_diario': alvo_diario,
                    'alvo_lucro_1': alvo_lucro_1,
                    'alvo_lucro_2': alvo_lucro_2,
                    'alvo_lucro_3': alvo_lucro_3,
                    'stop_loss_atr': stop_loss_atr,
                    'stop_loss_min': stop_loss_min,
                    'volume_min': volume_min
                }
            }
            
            print(f"\nResultado do teste: {resultado['resultado_percentual']:.2f}% com taxa de acerto {resultado['taxa_acerto']:.1f}%")
            return resultado

# Exemplo de uso
if __name__ == "__main__":
    try:
        # Exibir informações do módulo
        print("\nVersões dos módulos:")
        from binance import __version__ as binance_version
        print(f"python-binance: {binance_version}")
        import pandas as pd
        print(f"pandas: {pd.__version__}")
        import numpy as np
        print(f"numpy: {np.__version__}")
        import talib
        print(f"talib: {talib.__version__}")
        
        # Verificar se é para testar parâmetros ou executar normalmente
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == 'teste':
            print("\n--- MODO DE TESTE DE PARÂMETROS ---")
            resultado = testar_parametros(
                capital_por_operacao_pct=3,  # % do capital total
                alvo_diario=0.8,             # % alvo diário
                alvo_lucro_1=0.15,           # % primeiro take profit
                alvo_lucro_2=0.3,            # % segundo take profit
                alvo_lucro_3=0.5,            # % terceiro take profit
                stop_loss_atr=1.0,           # multiplicador ATR
                stop_loss_min=0.3,           # % mínimo stop loss
                volume_min=115,              # % do volume médio
                dias=1,                      # dias de teste
                simulacao=True               # modo simulação
            )
        elif len(sys.argv) > 1 and sys.argv[1] == 'otimizacao':
            # Modo de otimização de parâmetros
            print("\n--- MODO DE OTIMIZAÇÃO DE PARÂMETROS ---")
            resultados = []
            
            # Testar diferentes combinações de parâmetros
            for cap in [2, 3, 5]:
                for tp1 in [0.15, 0.2]:
                    for sl in [0.3, 0.4]:
                        print(f"\nTestando: Capital={cap}%, TP1={tp1}%, SL={sl}%")
                        res = testar_parametros(
                            capital_por_operacao_pct=cap,
                            alvo_lucro_1=tp1,
                            stop_loss_min=sl,
                            dias=1
                        )
                        resultados.append(res)
            
            # Ordenar resultados pelo resultado percentual
            resultados.sort(key=lambda x: x['resultado_percentual'], reverse=True)
            
            # Mostrar melhores resultados
            print("\n--- MELHORES COMBINAÇÕES DE PARÂMETROS ---")
            for i, res in enumerate(resultados[:3], 1):
                print(f"{i}. Resultado: {res['resultado_percentual']:.2f}% | " +
                     f"Taxa de acerto: {res['taxa_acerto']:.1f}% | " +
                     f"Parâmetros: Cap={res['parametros']['capital_por_operacao_pct']}%, " +
                     f"TP1={res['parametros']['alvo_lucro_1']}%, " +
                     f"SL={res['parametros']['stop_loss_min']}%")
        else:
            # Modo normal - iniciar bot em produção
            print("\n--- INICIANDO BOT DE TRADING ---")
            bot = BinanceScalpingBotMelhorado(API_KEY, API_SECRET, SYMBOL, TIMEFRAME, CAPITAL_POR_OPERACAO)
            bot.iniciar(intervalo_segundos=5)
        
    except Exception as e:
        import traceback
        print(f"\nErro ao executar o bot: {e}")
        print("\nDetalhe do erro:")
        traceback.print_exc()
 
