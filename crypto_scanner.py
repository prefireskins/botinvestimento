import requests
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from binance.client import Client
import json
import os
from tabulate import tabulate
import sys
from alert_system import AlertSystem

from binance_scalping_bot import (
    STOP_LOSS_MULTIPLICADOR_ATR,
    ALVO_LUCRO_PERCENTUAL_1,
    ALVO_LUCRO_PERCENTUAL_2,
    ALVO_LUCRO_PERCENTUAL_3
)
# === CONFIGURAÇÕES DE LUCRO E STOP ===

# Percentuais de lucro para saídas parciais
ALVO_LUCRO_PERCENTUAL_1 = 0.3  # Take Profit Parcial 1 = 0.3%
ALVO_LUCRO_PERCENTUAL_2 = 0.7  # Take Profit Parcial 2 = 0.7%
ALVO_LUCRO_PERCENTUAL_3 = 1.0  # Take Profit Final = 1.0%

# Multiplicador do ATR usado para definir o stop loss
STOP_LOSS_MULTIPLICADOR_ATR = 1.5


try:
    # Importar apenas o que precisamos, não o módulo inteiro
    from telegram_bot import request_trading_approval, get_approval_results
    TELEGRAM_APPROVAL_AVAILABLE = True
    print("Módulo telegram_bot carregado com sucesso.")
except ImportError:
    TELEGRAM_APPROVAL_AVAILABLE = False
    print("Aviso: Módulo telegram_bot não disponível. A confirmação pelo Telegram não estará ativa.")
except Exception as e:
    TELEGRAM_APPROVAL_AVAILABLE = False
    print(f"Erro ao carregar telegram_bot: {e}. A confirmação pelo Telegram não estará ativa.")

# Importar configurações do bot principal (se disponível)
try:
    from binance_scalping_bot import (
        API_KEY, API_SECRET, ATR_MINIMO_OPERACAO, 
        RSI_PERIODO, VOLUME_MINIMO_PERCENTUAL,
        MA_CURTA, MA_MEDIA, MA_LONGA, TIMEFRAME
    )
except ImportError:
    print("Arquivo de configuração do bot principal não encontrado. Usando valores padrão.")
    # Valores padrão se não conseguir importar
    API_KEY = 'gYzsw6dYN0ukl1Vm3FDMS0fLugwpacnJLD8XMNZL5WwUxErVnfWzamEwYttviUT8'
    API_SECRET = 'Z6huY9KvuJvy7OMnPdjY2w8yauuUR1D7kfCNOTLkk6gVwQfrqooW8WVz2Ll8aRjt'
    ATR_MINIMO_OPERACAO = 0.12
    RSI_PERIODO = 14
    VOLUME_MINIMO_PERCENTUAL = 115
    MA_CURTA = 7
    MA_MEDIA = 25
    MA_LONGA = 99
    TIMEFRAME = '3m'  # Timeframe padrão

CONFIG = {
    "top_moedas": 100,
    "min_volume_usd": 50000000,
    "min_variacao_1h": 1.5,
    "min_variacao_24h": 3.0,
    "max_pares_analisar": 10,
    "max_recomendacoes": 3,
    "tempo_entre_requisicoes": 1,
    "pasta_logs": "market_scans",
    "timeframes_testar": ['3m', '5m', '15m'],
    
    # Aumentar os parâmetros de qualidade
    "atr_minimo": 0.18,           # Aumentado para garantir volatilidade suficiente
    "volume_minimo_pct": 150,      # Volume mais alto exigido (150% da média)
    "inclinacao_ma_min": 0.02,     # Tendência mais forte necessária
    "rsi_zona_min": 40,
    "rsi_zona_max": 60,
    
    "priorizar_tendencia": True,
    "filtrar_alta_volatilidade": True,
    "min_score_tecnico": 4.0,      # Pontuação mínima mais alta (5.0 em vez de 4.5)
    "peso_tendencia": 1.5,
    "peso_volume": 1.5,
    "peso_rsi": 1.5,
    "peso_cruzamento": 2.0,
    "peso_alinhamento": 1.5,
    "peso_atr": 0.5,
    "peso_bollinger": 1.0,
    "peso_suporte_resistencia": 1.0,
    "peso_tendencia": 1.5,
    "peso_volume": 1.5,
    "peso_rsi": 1.5,
    "peso_cruzamento": 2.0,
    "peso_alinhamento": 1.5,
    "peso_atr": 0.5,
    "peso_bollinger": 1.0,
    "peso_suporte_resistencia": 1.0,
    
    # Mantenha as configurações existentes...
}

# Configurar sistema de alertas globalmente
TELEGRAM_TOKEN = "7103442744:AAHTHxLnVixhNWcsvmG2mU1uqWUNwGktfxw"
TELEGRAM_CHAT_ID = "7002398112"  # Este é o chat ID existente no código

global_alert_system = AlertSystem(
    enable_telegram=True,
    telegram_token=TELEGRAM_TOKEN,
    telegram_chat_id=TELEGRAM_CHAT_ID
)

def solicitar_aprovacao_alternativa(symbol):
        """Método alternativo para aprovação caso o Telegram falhe"""
        print("\n" + "=" * 60)
        print(f"CONFIRMAÇÃO NECESSÁRIA PARA OPERAR {symbol}")
        print("=" * 60)
        print("\nO bot Telegram pode não estar funcionando corretamente.")
        print("Por favor, responda diretamente aqui:")
        
        while True:
            resposta = input("\nDeseja prosseguir com a operação? (s/n): ").strip().lower()
            if resposta in ['s', 'sim', 'y', 'yes']:
                return True
            elif resposta in ['n', 'nao', 'não', 'no']:
                return False
            else:
                print("Resposta inválida. Por favor, digite 's' para sim ou 'n' para não.")
                
class CryptoMarketScanner:
    def __init__(self, api_key, api_secret, config=None):
        self.config = CONFIG if config is None else config
        self.client = Client(api_key, api_secret)
        self.timeframe = TIMEFRAME
        self.symbol = None 

        # Inicializar o sistema de alertas como atributo da classe
        self.alert_system = AlertSystem(
            enable_telegram=True,
            telegram_token=TELEGRAM_TOKEN,
            telegram_chat_id=TELEGRAM_CHAT_ID
        )
        
        # Criar pasta para logs se não existir
        if not os.path.exists(self.config["pasta_logs"]):
            os.makedirs(self.config["pasta_logs"])
            
        # Cache para evitar chamadas repetidas à API
        self.cache = {
            "simbolos_binance": None,
            "cotacoes_coingecko": None,
            "klines": {}
        }
        
        # Inicializar silenciosamente o sistema de alertas
        try:
            self.alert_system.send_telegram("Sistema inicializado", TELEGRAM_CHAT_ID)
        except Exception as e:
            print(f"Aviso: Sistema de alertas pode não estar funcionando corretamente: {str(e)}")

    def obter_simbolos_binance(self):
        """Obter lista de todos os símbolos de trading disponíveis na Binance"""
        if self.cache["simbolos_binance"] is not None:
            return self.cache["simbolos_binance"]
        
        info_exchange = self.client.get_exchange_info()
        simbolos = []
        
        for s in info_exchange['symbols']:
            # Filtrar apenas pares com USDT
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                # Encontrar os filtros corretos por tipo
                min_qty = None
                tick_size = None
                
                for filter in s['filters']:
                    if filter['filterType'] == 'LOT_SIZE':
                        min_qty = float(filter['minQty'])
                    elif filter['filterType'] == 'PRICE_FILTER':
                        tick_size = float(filter['tickSize'])
                
                # Adicionar à lista apenas se encontrou os filtros necessários
                if min_qty is not None and tick_size is not None:
                    simbolos.append({
                        'symbol': s['symbol'],
                        'baseAsset': s['baseAsset'],
                        'quoteAsset': s['quoteAsset'],
                        'minQty': min_qty,
                        'tickSize': tick_size
                    })
        
        self.cache["simbolos_binance"] = simbolos
        return simbolos

    def obter_dados_coingecko(self):
        """Obter dados das top moedas do CoinGecko"""
        if self.cache["cotacoes_coingecko"] is not None:
            return self.cache["cotacoes_coingecko"]
            
        url = f'https://api.coingecko.com/api/v3/coins/markets'
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': self.config["top_moedas"],
            'page': 1,
            'sparkline': False,
            'price_change_percentage': '1h,24h'
        }
        
        print(f"Consultando top {self.config['top_moedas']} moedas no CoinGecko...")
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            print(f"Erro ao consultar CoinGecko: {response.status_code}")
            print(response.text)
            return []
            
        dados = response.json()
        self.cache["cotacoes_coingecko"] = dados
        return dados

    def registrar_log(self, mensagem):
        """Registrar mensagem no arquivo de log ou imprimir no console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"{timestamp} - {mensagem}"
        
        # Imprimir no console
        print(log_line)
        
        # Opcional: salvar em arquivo se a pasta_logs estiver definida
        if hasattr(self, 'config') and "pasta_logs" in self.config:
            try:
                # Nome do arquivo de log com a data atual
                data_atual = datetime.now().strftime("%Y%m%d")
                nome_arquivo = f"{self.config['pasta_logs']}/scanner_log_{data_atual}.txt"
                
                # Criar pasta se não existir
                os.makedirs(os.path.dirname(nome_arquivo), exist_ok=True)
                
                # Salvar log
                with open(nome_arquivo, "a", encoding='utf-8') as f:
                    f.write(log_line + "\n")
            except Exception as e:
                print(f"Erro ao salvar log: {e}")

    def mapear_simbolos_binance_coingecko(self, dados_coingecko, simbolos_binance):
        """Mapear moedas do CoinGecko para símbolos da Binance"""
        mapeamento = []
        
        # Lista de símbolos de stablecoins conhecidas para filtrar
        stablecoins = ['usdt', 'usdc', 'busd', 'dai', 'tusd', 'usdd', 'usdp', 'gusd', 'fdusd']
        
        # Criar dicionário de símbolos da Binance para pesquisa rápida
        simbolos_dict = {s['baseAsset'].lower(): s for s in simbolos_binance}
        
        for moeda in dados_coingecko:
            simbolo = moeda['symbol'].upper()
            simbolo_lower = moeda['symbol'].lower()
            
            # Filtrar stablecoins
            if simbolo_lower in stablecoins or 'usd' in simbolo_lower:
                continue
                
            # Verificar se existe par com USDT na Binance
            binance_symbol = f"{simbolo}USDT"
            
            # Tentar com o símbolo direto e depois com o ID
            if simbolo.lower() in simbolos_dict:
                info_binance = simbolos_dict[simbolo.lower()]
                mapeamento.append({
                    'id_coingecko': moeda['id'],
                    'symbol_coingecko': moeda['symbol'].upper(),
                    'name': moeda['name'],
                    'symbol_binance': info_binance['symbol'],
                    'price_change_24h': moeda.get('price_change_percentage_24h', 0),
                    'price_change_1h': moeda.get('price_change_percentage_1h_in_currency', 0),
                    'volume_24h': moeda['total_volume'],
                    'current_price': moeda['current_price'],
                    'market_cap': moeda['market_cap']
                })
        
        return mapeamento


    def filtrar_melhores_pares(self, mapeamento):
        """Filtrar os melhores pares com base nos critérios de volume e variação"""
        # Verificar volume mínimo
        pares_volume = [p for p in mapeamento if p['volume_24h'] >= self.config["min_volume_usd"]]
        
        # Adicionar score para cada par
        for par in pares_volume:
            # Normalizar volume (0-100)
            max_volume = max([p['volume_24h'] for p in pares_volume])
            volume_score = (par['volume_24h'] / max_volume) * 100
            
            # Normalizar variação absoluta (0-100)
            variacao_1h_abs = abs(par['price_change_1h']) if par['price_change_1h'] else 0
            variacao_24h_abs = abs(par['price_change_24h']) if par['price_change_24h'] else 0
            
            max_var_1h = max([abs(p['price_change_1h']) for p in pares_volume if p['price_change_1h']])
            max_var_24h = max([abs(p['price_change_24h']) for p in pares_volume if p['price_change_24h']])
            
            var_1h_score = (variacao_1h_abs / max_var_1h) * 100 if max_var_1h > 0 else 0
            var_24h_score = (variacao_24h_abs / max_var_24h) * 100 if max_var_24h > 0 else 0
            
            # Score composto (volume tem peso maior)
            par['score'] = (volume_score * 0.6) + (var_1h_score * 0.2) + (var_24h_score * 0.2)
        
        # Ordenar por score
        pares_ordenados = sorted(pares_volume, key=lambda x: x['score'], reverse=True)
        
        # Retornar top N pares para análise
        return pares_ordenados[:self.config["max_pares_analisar"]]

    def get_klines(self, symbol, timeframe, limit=200):
        """Obter dados de velas (klines) da Binance e calcular indicadores"""
        # Verificar cache
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in self.cache["klines"]:
            return self.cache["klines"][cache_key]
            
        # Obter dados da API - aumentar o limite para assegurar cálculos adequados
        klines = self.client.get_klines(
            symbol=symbol,
            interval=timeframe,
            limit=limit
        )
        
        # Verificar se obteve dados suficientes
        if len(klines) < 100:
            print(f"Aviso: Dados insuficientes para {symbol} em {timeframe}. Obteve {len(klines)} candles.")
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
        
        # Calcular RSI
        delta = df['close'].diff().dropna()
        ganhos = delta.copy()
        perdas = delta.copy()
        ganhos[ganhos < 0] = 0
        perdas[perdas > 0] = 0
        perdas = abs(perdas)

        # Médias móveis exponenciais para suavizar
        window_length = RSI_PERIODO
        avg_gain = ganhos.ewm(com=window_length-1, min_periods=window_length).mean()
        avg_loss = perdas.ewm(com=window_length-1, min_periods=window_length).mean()

        # Calcular RS e RSI
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # Adicionar cálculo da média de volume
        df['volume_media'] = df['volume'].rolling(window=20).mean()
        
        # Calcular ATR (Average True Range)
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        df['atr_percent'] = df['atr'] / df['close'] * 100
        
        # Calcular Bandas de Bollinger
        if len(df) >= 20:
            # Médias móveis simples
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            # Desvio padrão
            df['bb_std'] = df['close'].rolling(window=20).std()
            # Bandas
            df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
            df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
        
        # Salvar no cache
        self.cache["klines"][cache_key] = df
        
        return df

    def check_signal(self, df):
        """Verificar se há sinal de entrada com múltiplos filtros e sistema de pontuação flexível"""

        # Exemplo de código para colocar no início da função check_signal
        print(f"DEBUG - check_signal: min_score_config={self.config.get('min_score_tecnico')}, ATR_MINIMO={ATR_MINIMO_OPERACAO}")

        pontuacao = 0
        motivos = []
        contra_indicacoes = []
        forca_sinal = "FRACO"  # Padrão
        criterios_atendidos = 0
        criterios_total = 0
        
        # Obter pesos configuráveis
        peso_tendencia = self.config.get("peso_tendencia", 1.5)
        peso_volume = self.config.get("peso_volume", 1.5)
        peso_rsi = self.config.get("peso_rsi", 1.5)
        peso_cruzamento = self.config.get("peso_cruzamento", 2.0)
        peso_alinhamento = self.config.get("peso_alinhamento", 1.5)
        peso_atr = self.config.get("peso_atr", 0.5)
        peso_bollinger = self.config.get("peso_bollinger", 1.0)
        peso_suporte_resistencia = self.config.get("peso_suporte_resistencia", 1.0)

        if len(df) < 100:  # Requer mais dados históricos para análise confiável
            return 0, "Dados históricos insuficientes"
        
        # Dados mais recentes do mercado
        penultimo = df.iloc[-2]
        ultimo = df.iloc[-1]
        
        # Usar configurações personalizadas do CONFIG, com fallback para valores padrão
        atr_minimo = self.config.get("atr_minimo", ATR_MINIMO_OPERACAO)
        volume_minimo_pct = self.config.get("volume_minimo_pct", VOLUME_MINIMO_PERCENTUAL)
        inclinacao_ma_min = self.config.get("inclinacao_ma_min", 0.02)  # Aumentado para 0.02
        rsi_zona_min = self.config.get("rsi_zona_min", 40)
        rsi_zona_max = self.config.get("rsi_zona_max", 60)
        
        # 1. Verificar ATR (volatilidade suficiente) - Critério mais rigoroso
        atr_atual_percent = ultimo.get('atr_percent', 0)
        atr_minimo_ajustado = atr_minimo * 1.2  # Aumentar o requisito mínimo de ATR em 20%
        mercado_ativo = atr_atual_percent >= atr_minimo_ajustado

        # Filtrar alta volatilidade se configurado
        if self.config.get("filtrar_alta_volatilidade", False) and atr_atual_percent > atr_minimo * 3:
            contra_indicacoes.append(f"Volatilidade excessiva: ATR {atr_atual_percent:.2f}%")
            pontuacao -= 1

        if not mercado_ativo:
            contra_indicacoes.append(f"Volatilidade insuficiente: ATR {atr_atual_percent:.2f}% (mín: {atr_minimo_ajustado:.2f}%)")
            pontuacao -= peso_atr * 1.2  # Penalizar mais fortemente volatilidade insuficiente
        else:
            motivos.append(f"Volatilidade adequada: ATR {atr_atual_percent:.2f}%")
            pontuacao += peso_atr  # Peso configurável para volatilidade
            criterios_atendidos += 1
        
        # 2. Verificar inclinação da MA Longa (tendência de fundo) - Critério mais rigoroso
        if 'ma_longa_inclinacao' in df.columns:
            inclinacao_ma_longa = df['ma_longa_inclinacao'].iloc[-1]
            tendencia_alta_forte = inclinacao_ma_longa > inclinacao_ma_min
        else:
            # Fallback para comparação direta de médias móveis
            tendencia_alta_forte = float(ultimo[f'ma_{MA_LONGA}']) > float(penultimo[f'ma_{MA_LONGA}'])
        
        # Priorizar tendência se configurado
        if tendencia_alta_forte:
            motivos.append(f"Tendência de alta na MA{MA_LONGA}: {inclinacao_ma_longa:.3f}%")
            pontuacao += peso_tendencia  # Peso configurável para tendência
            criterios_atendidos += 1
            
        elif inclinacao_ma_longa > 0:
            motivos.append(f"Tendência de alta fraca na MA{MA_LONGA}: {inclinacao_ma_longa:.3f}%")
            pontuacao += peso_tendencia * 0.33
        else:
            contra_indicacoes.append(f"Sem tendência de alta na MA{MA_LONGA}")
            pontuacao -= peso_tendencia * 0.6  # Penalizar mais fortemente
        
        # 3. Verificar cruzamento de médias móveis
        cruzamento_para_cima = (
            penultimo[f'ma_{MA_CURTA}'] <= penultimo[f'ma_{MA_MEDIA}'] and
            ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}']
        )
        
        ma_curta_acima_media = ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}']
        todas_mas_alinhadas = (ultimo[f'ma_{MA_CURTA}'] > ultimo[f'ma_{MA_MEDIA}'] > ultimo[f'ma_{MA_LONGA}'])
        
        if cruzamento_para_cima:
            motivos.append("Cruzamento MA7 > MA25 (sinal de entrada)")
            pontuacao += peso_cruzamento  # Peso configurável para cruzamento
            criterios_atendidos += 1
        elif ma_curta_acima_media:
            motivos.append("MA7 acima da MA25 (tendência de curto prazo)")
            pontuacao += peso_cruzamento * 0.5 
        
        if todas_mas_alinhadas:
            motivos.append("Médias móveis alinhadas (MA7 > MA25 > MA99)")
            pontuacao += peso_alinhamento  # Peso configurável para alinhamento
            criterios_atendidos += 1
        
        # 4. Verificar RSI - Critério mais rigoroso
        rsi_atual = ultimo['rsi']
        rsi_ok = rsi_zona_min <= rsi_atual <= rsi_zona_max  # Usar valores configurados
        rsi_sobrevenda = 30 <= rsi_atual < 40
        
        # Verificar se RSI está subindo nos últimos 3 candles
        rsi_subindo = False
        if len(df) >= 4:
            rsi_3_candles = df['rsi'].iloc[-4:].values
            rsi_subindo = (rsi_3_candles[-1] > rsi_3_candles[-2] > rsi_3_candles[-3])
        
        if rsi_ok:
            motivos.append(f"RSI em zona ótima ({rsi_atual:.2f})")
            pontuacao += peso_rsi  # Peso configurável para RSI
            criterios_atendidos += 1
        elif rsi_sobrevenda and rsi_subindo:
            motivos.append(f"RSI recuperando de sobrevenda ({rsi_atual:.2f})")
            pontuacao += peso_rsi * 0.67  # 67% do peso
            criterios_atendidos += 0.5
        elif rsi_subindo:
            motivos.append(f"RSI em tendência de alta ({rsi_atual:.2f})")
            pontuacao += peso_rsi * 0.33
        else:
            contra_indicacoes.append(f"RSI desfavorável ({rsi_atual:.2f})")
            pontuacao -= peso_rsi * 0.67 
        
        # 5. Verificar volume - Critério mais rigoroso
        volume_minimo_ajustado = volume_minimo_pct * 1.3  # Aumentar o requisito mínimo de volume em 30%
        volume_ok = ultimo['volume'] >= ultimo['volume_media'] * (volume_minimo_ajustado / 100)
        volume_aceitavel = ultimo['volume'] >= ultimo['volume_media'] * 1.1  # 110% da média (aumentado)

        if volume_ok:
            motivos.append(f"Volume alto ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
            pontuacao += peso_volume  # Peso configurável para volume
            criterios_atendidos += 1
        elif volume_aceitavel:
            motivos.append(f"Volume aceitável ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
            pontuacao += peso_volume * 0.2  # 20% do peso
        else:
            contra_indicacoes.append(f"Volume baixo ({ultimo['volume']/ultimo['volume_media']*100:.0f}% da média)")
            pontuacao -= peso_volume * 0.6  # Penalização
                
        # 6. Verificar Bandas de Bollinger
        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            preco = ultimo['close']
            bb_lower = ultimo['bb_lower']
            bb_upper = ultimo['bb_upper']
            
            # Proximidade à banda inferior (potencial reversão para cima)
            if preco < bb_lower * 1.01:  # Dentro de 1% da banda inferior
                motivos.append("Preço próximo/abaixo da banda inferior de Bollinger")
                pontuacao += 1
            
            # Evitar entradas próximas à banda superior
            if preco > bb_upper * 0.97:  # Dentro de 3% da banda superior
                contra_indicacoes.append("Preço próximo/acima da banda superior de Bollinger")
                pontuacao -= 0.9  # Penalizar mais fortemente
        
        # Formatação dos motivos/contra-indicações para log
        motivos_txt = ", ".join(motivos)
        contra_indicacoes_txt = ", ".join(contra_indicacoes)
        
        # Determinar força do sinal com base na pontuação - Critério mais rigoroso
        if pontuacao >= 4.0:  # Aumentado de 5 para 6.5
            forca_sinal = "FORTE"
        elif pontuacao >= 2.5:  # Aumentado de 3 para 4.5
            forca_sinal = "MODERADO"
        else:
            forca_sinal = "FRACO"

        # Verificar se atende ao score mínimo configurado - Aumentado
        min_score = self.config.get("min_score_tecnico", 4.0)  # Usa valor do CONFIG

        # Formatação dos motivos/contra-indicações para log
        motivos_txt = ", ".join(motivos)
        contra_indicacoes_txt = ", ".join(contra_indicacoes)

        # Mensagem detalhada
        mensagem = f"Análise [{forca_sinal}] - Pontuação: {pontuacao:.1f}/10"

        # Adicionar detalhes dos critérios
        if motivos:
            mensagem += f"\nMotivos: {motivos_txt}"
        if contra_indicacoes:
            mensagem += f"\nContra-indicações: {contra_indicacoes_txt}"

        # NOVA VERSÃO:
        # SIMPLIFICAÇÃO RADICAL - QUALQUER pontuação positiva é considerada válida
        min_score = self.config.get("min_score_tecnico", 4.0)
        pontuacao_suficiente = pontuacao >= min_score

        # Se pontuação é positiva MAS não suficiente, adicionar mensagem de camada de resgate
        if pontuacao > 0 and not pontuacao_suficiente:
            mensagem += "\n⚠️ CAMADA RESGATE: Entrada com pontuação positiva"
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - CAMADA RESGATE ATIVADA: Pontuação={pontuacao:.2f}, RSI={rsi_atual:.1f}, ATR%={atr_atual_percent:.2f}%")

        # MUDANÇA CRÍTICA: Retornar True para QUALQUER pontuação positiva
        if pontuacao > 0:
            return True, mensagem
        else:
            return False, f"Análise [{forca_sinal}] - Pontuação: {pontuacao:.1f}/10 (pontuação negativa)\nMotivos: {motivos_txt}\nContra-indicações: {contra_indicacoes_txt}"

    def registrar_decisao_trading(self, df, pontuacao, criterios, decisao, timestamp=None):
        """
        Registra detalhadamente uma decisão de trading para análise posterior
        """
        if timestamp is None:
            timestamp = datetime.now()
            
        # Extrair valores dos indicadores relevantes
        ultimo_candle = df.iloc[-1]
        
        registro = {
            "timestamp": timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "pontuacao_total": pontuacao,
            "decisao": decisao,  # True/False
            
            # Indicadores técnicos
            "rsi": float(ultimo_candle['rsi']),
            "atr_percent": float(ultimo_candle.get('atr_percent', 0)),
            "volume_ratio": float(ultimo_candle['volume'] / ultimo_candle['volume_media']),
            "ma_curta": float(ultimo_candle[f'ma_{MA_CURTA}']),
            "ma_media": float(ultimo_candle[f'ma_{MA_MEDIA}']),
            "ma_longa": float(ultimo_candle[f'ma_{MA_LONGA}']),
            "ma_longa_inclinacao": float(df['ma_longa_inclinacao'].iloc[-1] if 'ma_longa_inclinacao' in df.columns else 0),
            
            # Critérios detalhados
            "criterios": criterios,
            
            # Configuração de pesos usada
            "pesos": {
                "peso_tendencia": self.config.get("peso_tendencia", 1.5),
                "peso_volume": self.config.get("peso_volume", 1.5), 
                "peso_rsi": self.config.get("peso_rsi", 1.5),
                "peso_cruzamento": self.config.get("peso_cruzamento", 2.0),
                "peso_alinhamento": self.config.get("peso_alinhamento", 1.5)
            }
        }
        
        # Criar pasta para logs de decisões se não existir
        decisoes_dir = os.path.join(self.config["pasta_logs"], "decisoes")
        os.makedirs(decisoes_dir, exist_ok=True)
        
        # Nome do arquivo baseado na data
        data_arquivo = timestamp.strftime("%Y%m%d")
        caminho_arquivo = os.path.join(decisoes_dir, f"decisoes_{data_arquivo}.csv")
        
        # Converter para DataFrame
        registro_df = pd.DataFrame([registro])
        
        # Verificar se arquivo existe e adicionar cabeçalho se necessário
        modo = 'a' if os.path.exists(caminho_arquivo) else 'w'
        incluir_cabecalho = modo == 'w'
        
        # Salvar em CSV
        registro_df.to_csv(caminho_arquivo, mode=modo, header=incluir_cabecalho, index=False)
        
        return registro
    def analisar_par(self, symbol, timeframes=None):
        if timeframes is None:
            timeframes = self.config["timeframes_testar"]
                
        resultados = {}
        pontuacao_total = 0
        df_principal = None  # Inicializar df_principal
        
        for tf in timeframes:
            try:
                df = self.get_klines(symbol, tf, limit=200)
                
                # Definir o primeiro DataFrame como principal (geralmente o menor timeframe)
                if df_principal is None:
                    df_principal = df
                
                # Aqui está ocorrendo o erro. Vamos corrigir:
                try:
                    pontuacao, analise = self.check_signal(df)
                    # DIAGNÓSTICO AQUI
                    print(f"DEBUG ANÁLISE: {symbol} {tf} - Signal={pontuacao >= self.config.get('min_score_tecnico', 4.0)}, Resgate={'CAMADA RESGATE' in analise}, Pontuação={pontuacao}")    

                    # AQUI: Garantir que os sinais da camada de resgate são registrados para decisões
                    decisao = pontuacao >= self.config.get("min_score_tecnico", 4.0) or "CAMADA RESGATE" in analise
                    self.registrar_decisao_trading(df, pontuacao, analise, decisao)
                    
                    # Use esta variável ao registrar a decisão
                    if hasattr(self, 'registrar_decisao_trading'):
                        self.registrar_decisao_trading(df, pontuacao, analise, decisao)

                    resultados[tf] = {
                        'pontuacao': pontuacao,
                        'analise': analise,
                        'preco': df['close'].iloc[-1],
                        'decisao': decisao  # Adicionar esta informação
                    }
                    
                    # Dar mais peso para timeframes maiores
                    peso = 1.0
                    if tf == '15m':
                        peso = 1.5
                    elif tf == '1h':
                        peso = 2.0
                        
                    pontuacao_total += pontuacao * peso

                    # Contar decisões para estatísticas
                    if decisao:
                        decisoes_count += 1
                except Exception as err:
                    print(f"Erro ao avaliar {symbol} em {tf}: {err}")
                    resultados[tf] = {'pontuacao': 0, 'analise': f"Erro na avaliação: {err}", 'preco': df['close'].iloc[-1]}
                    
            except Exception as e:
                print(f"Erro ao analisar {symbol} em {tf}: {e}")
                resultados[tf] = {'pontuacao': 0, 'analise': f"Erro: {e}", 'preco': 0}
        
        # Adicione este código no método analisar_par() antes de calcular as pontuações
        if df_principal is not None and len(df_principal) > 0:
            # Verificar se RSI foi calculado
            if 'rsi' in df_principal.columns:
                ultimo_rsi = df_principal['rsi'].iloc[-1]
                print(f"Diagnóstico {symbol} - RSI calculado: {ultimo_rsi:.2f}")
            else:
                print(f"AVISO: RSI não calculado para {symbol}")
                
            # Verificar se ATR foi calculado
            if 'atr_percent' in df_principal.columns:
                ultimo_atr = df_principal['atr_percent'].iloc[-1]
                print(f"Diagnóstico {symbol} - ATR% calculado: {ultimo_atr:.2f}%")
            else:
                print(f"AVISO: ATR não calculado para {symbol}")

        # Média ponderada das pontuações
        num_timeframes = sum(1.0 if tf == '3m' or tf == '5m' else 1.5 if tf == '15m' else 2.0 for tf in timeframes if tf in resultados)
        pontuacao_media = pontuacao_total / max(1, num_timeframes)
        
        # Certificar que df_principal não é None
        if df_principal is None and timeframes:
            try:
                # Tentar obter pelo menos um DataFrame válido
                for tf in timeframes:
                    df_principal = self.get_klines(symbol, tf)
                    if df_principal is not None:
                        break
            except Exception:
                # Se falhar, criar um DataFrame mínimo para evitar erro
                import pandas as pd
                df_principal = pd.DataFrame({'close': [0], 'rsi': [50], 'atr_percent': [0]})
        # Verificação de diagnóstico
        if df_principal is not None and len(df_principal) > 0:
            # Verificar se RSI foi calculado
            if 'rsi' in df_principal.columns:
                ultimo_rsi = df_principal['rsi'].iloc[-1]
                print(f"Diagnóstico {symbol} - RSI calculado: {ultimo_rsi:.2f}")
            else:
                print(f"AVISO: RSI não calculado para {symbol}")
                
            # Verificar se ATR foi calculado
            if 'atr_percent' in df_principal.columns:
                ultimo_atr = df_principal['atr_percent'].iloc[-1]
                print(f"Diagnóstico {symbol} - ATR% calculado: {ultimo_atr:.2f}%")
            else:
                print(f"AVISO: ATR não calculado para {symbol}")
                
            # Quantidade de candles e médias móveis
            print(f"Diagnóstico {symbol} - Quantidade de candles: {len(df_principal)}")
            
            # Verificar médias móveis
            if f'ma_{MA_CURTA}' in df_principal.columns:
                print(f"Diagnóstico {symbol} - MA{MA_CURTA}: {df_principal[f'ma_{MA_CURTA}'].iloc[-1]:.2f}")
            else:
                print(f"AVISO: MA{MA_CURTA} não calculada para {symbol}")
                
            if f'ma_{MA_MEDIA}' in df_principal.columns:
                print(f"Diagnóstico {symbol} - MA{MA_MEDIA}: {df_principal[f'ma_{MA_MEDIA}'].iloc[-1]:.2f}")
            else:
                print(f"AVISO: MA{MA_MEDIA} não calculada para {symbol}")
                
            if f'ma_{MA_LONGA}' in df_principal.columns:
                print(f"Diagnóstico {symbol} - MA{MA_LONGA}: {df_principal[f'ma_{MA_LONGA}'].iloc[-1]:.2f}")
            else:
                print(f"AVISO: MA{MA_LONGA} não calculada para {symbol}")
        else:
            print(f"AVISO: DataFrame principal não disponível ou vazio para {symbol}")
        # No final da função analisar_par, adicione ou modifique:
    
        return {
            'symbol': symbol,
            'pontuacao_media': pontuacao_media,
            'timeframes': resultados,
            'df_principal': df_principal,
            'info_mercado': {
                'volume_24h': 0,
                'price_change_24h': 0,
                'current_price': df_principal['close'].iloc[-1] if df_principal is not None and len(df_principal) > 0 else 0,
                'rsi': df_principal['rsi'].iloc[-1] if df_principal is not None and len(df_principal) > 0 and 'rsi' in df_principal.columns else 50,
                'atr_percent': df_principal['atr_percent'].iloc[-1] if df_principal is not None and len(df_principal) > 0 and 'atr_percent' in df_principal.columns else 0
            },
            'decisoes_count': decisoes_count  # ADICIONAR ISTO
        }

    def escanear_mercado(self):
        """Escanear o mercado e encontrar os melhores pares para operar"""
        print(f"Iniciando escaneamento de mercado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Passo 1: Obter dados do CoinGecko
        dados_coingecko = self.obter_dados_coingecko()
        
        if not dados_coingecko:
            print("Erro: Não foi possível obter dados do CoinGecko.")
            return []
            
        print(f"Obtidos dados de {len(dados_coingecko)} moedas do CoinGecko.")
        
        # Passo 2: Obter símbolos disponíveis na Binance
        simbolos_binance = self.obter_simbolos_binance()
        print(f"Encontrados {len(simbolos_binance)} pares na Binance.")
        
        # Passo 3: Mapear moedas do CoinGecko para símbolos da Binance
        mapeamento = self.mapear_simbolos_binance_coingecko(dados_coingecko, simbolos_binance)
        print(f"Mapeados {len(mapeamento)} pares entre CoinGecko e Binance.")
        
        # Passo 4: Filtrar os melhores pares por volume e variação
        melhores_pares = self.filtrar_melhores_pares(mapeamento)
        print(f"Selecionados {len(melhores_pares)} pares para análise técnica.")
        
        # Exibir os melhores pares selecionados
        print("\nMelhores pares por volume e variação:")
        tabela_pares = []
        for i, par in enumerate(melhores_pares, 1):
            tabela_pares.append([
                i,
                par['symbol_binance'],
                f"${par['current_price']:.4f}",
                f"${par['volume_24h']:,.0f}",
                f"{par['price_change_1h']:.2f}%" if par['price_change_1h'] else "N/A",
                f"{par['price_change_24h']:.2f}%" if par['price_change_24h'] else "N/A",
                f"{par['score']:.1f}"
            ])
        
        print(tabulate(tabela_pares, 
                      headers=["#", "Par", "Preço", "Volume 24h", "Var. 1h", "Var. 24h", "Score"],
                      tablefmt="grid"))
        
        # Passo 5: Analisar sinais técnicos para cada par
        print("\nAnalisando sinais técnicos para os pares selecionados...")
        resultados_analise = []
        
        for par in melhores_pares:
            print(f"Analisando {par['symbol_binance']}...")
            try:
                resultado = self.analisar_par(par['symbol_binance'])
                resultado['info_mercado'] = par
                resultados_analise.append(resultado)
                
                # Pequena pausa para evitar rate limit
                time.sleep(self.config["tempo_entre_requisicoes"])
            except Exception as e:
                print(f"Erro ao analisar {par['symbol_binance']}: {e}")
        
        # Ordenar por pontuação técnica
        resultados_ordenados = sorted(resultados_analise, key=lambda x: x['pontuacao_media'], reverse=True)
        
        # Antes do return, adicione:
        melhor_par = self.selecionar_melhor_par(resultados_analise)
        return melhor_par  # Retorna apenas o símbolo do melhor par
    
        
    def iniciar_escaneamento_continuo(self, intervalo_espera=15, tempo_maximo=None):
        """
        Método para escaneamento contínuo com espera entre tentativas
        
        Args:
            intervalo_espera: minutos entre verificações
            tempo_maximo: tempo máximo em segundos para tentar encontrar um par
        """
        print(f"\n🔄 MODO DE ESCANEAMENTO CONTÍNUO ATIVADO")
        print(f"Procurando pares adequados para trading a cada {intervalo_espera} minutos...\n")
        
        # Tempo de início para controle de tempo máximo
        tempo_inicio = time.time()
        
        while True:
            try:
                # Verificar se ultrapassou o tempo máximo (se definido)
                if tempo_maximo and (time.time() - tempo_inicio) > tempo_maximo:
                    print(f"Tempo máximo de busca ({tempo_maximo} segundos) atingido.")
                    return None
                    
                # Limpar cache antes de nova tentativa
                self.cache = {
                    "simbolos_binance": None,
                    "cotacoes_coingecko": None,
                    "klines": {}
                }
                
                print(f"\n--- NOVA ANÁLISE EM {datetime.now().strftime('%H:%M:%S')} ---")
                # Tentar encontrar par para operar
                symbol = self.escanear_mercado()
                
                if symbol:
                    # Par encontrado, verificar autorização
                    print(f"\n✅ Par encontrado: {symbol}")
                    
                    # NOVA PARTE: Solicitar confirmação pelo Telegram se disponível
                    try:
                        if TELEGRAM_APPROVAL_AVAILABLE:
                            print("Solicitando confirmação pelo Telegram...")
                            
                            # Enviar solicitação de aprovação com timeout de 5 minutos
                            iniciar_bot = request_trading_approval(symbol, timeout=300)
                            
                            print(f"Resultado final da aprovação: {iniciar_bot}")
                            
                            # VERIFICAÇÃO mais detalhada
                            if iniciar_bot is True:  # Verificação explícita para True
                                print("✅ Operação APROVADA pelo Telegram! Retornando símbolo...")
                                # IMPORTANTE: Retorno explícito do símbolo
                                return symbol
                            elif iniciar_bot is False:  # Verificação explícita para False
                                print("❌ Operação REJEITADA pelo Telegram.")
                            else:
                                print(f"⚠️ Resposta inconclusiva do Telegram (valor: {iniciar_bot}).")
                                # Tentar método alternativo
                                if solicitar_aprovacao_alternativa(symbol):
                                    return symbol
                            
                            # Se chegou aqui, não foi aprovado
                            print(f"Tentando novamente em {intervalo_espera} minutos...")
                            print(f"Próxima verificação às {(datetime.now() + timedelta(minutes=intervalo_espera)).strftime('%H:%M:%S')}")
                            time.sleep(intervalo_espera * 60)
                            continue
                        else:
                            # Se Telegram não disponível, usar método alternativo
                            print("Telegram não disponível, usando método alternativo.")
                            if solicitar_aprovacao_alternativa(symbol):
                                return symbol
                            else:
                                # Aguardar antes da próxima verificação
                                print(f"Tentando novamente em {intervalo_espera} minutos...")
                                time.sleep(intervalo_espera * 60)
                                continue
                    except Exception as e:
                        print(f"Erro ao solicitar aprovação pelo Telegram: {e}")
                        import traceback
                        traceback.print_exc()
                        
                        # Em caso de erro, tentar método alternativo
                        print("Usando método alternativo de aprovação devido a erro no Telegram.")
                        if solicitar_aprovacao_alternativa(symbol):
                            return symbol
                        else:
                            # Aguardar antes da próxima verificação
                            print(f"Tentando novamente em {intervalo_espera} minutos...")
                            time.sleep(intervalo_espera * 60)
                            continue
                
                # Se não encontrou, esperar e tentar novamente
                print(f"Nenhum par encontrado. Tentando novamente em {intervalo_espera} minutos...")
                print(f"Próxima verificação às {(datetime.now() + timedelta(minutes=intervalo_espera)).strftime('%H:%M:%S')}")
                time.sleep(intervalo_espera * 60)
            
            except Exception as e:
                print(f"Erro no escaneamento: {e}")
                import traceback
                traceback.print_exc()
                print(f"Tentando novamente em {intervalo_espera} minutos...")
                time.sleep(intervalo_espera * 60)

    def registrar_resultados(self, recomendacoes, pares_analisados):
        """Registrar resultados da análise em arquivo"""
        data_atual = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_arquivo = f"{self.config['pasta_logs']}/scan_{data_atual}.json"
        
        # Preparar dados para salvar
        dados = {
            'timestamp': datetime.now().isoformat(),
            'pares_analisados': pares_analisados,
            'recomendacoes': recomendacoes,
            'config': self.config
        }
        
        with open(nome_arquivo, 'w') as f:
            json.dump(dados, f, indent=2)
            
        print(f"Resultados salvos em: {nome_arquivo}")
        
        # Gerar também um relatório em texto
        nome_relatorio = f"{self.config['pasta_logs']}/relatorio_{data_atual}.txt"
        
        with open(nome_relatorio, 'w') as f:
            f.write(f"RELATÓRIO DE ESCANEAMENTO DE MERCADO - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            f.write("RECOMENDAÇÕES PARA TRADING:\n")
            f.write("-" * 50 + "\n")
            
            for i, rec in enumerate(recomendacoes, 1):
                symbol = rec['symbol']
                pontuacao = rec['pontuacao_media']
                info = rec['info_mercado']
                
                f.write(f"{i}. {symbol} - Pontuação: {pontuacao:.2f}/10\n")
                f.write(f"   Preço: ${par['current_price']:.4f}\n")
                f.write(f"   Volume 24h: ${par['volume_24h']:,.0f}\n")
                f.write(f"   Variação 1h: {par['price_change_1h']:.2f}%\n")
                f.write(f"   Variação 24h: {par['price_change_24h']:.2f}%\n\n")
                
                for tf, dados in rec['timeframes'].items():
                    f.write(f"   Timeframe {tf}:\n")
                    f.write(f"   {dados['analise']}\n\n")
                    
                f.write("-" * 50 + "\n")
            
        print(f"Relatório detalhado salvo em: {nome_relatorio}")

    def exibir_recomendacoes(self, recomendacoes):
        """Exibir recomendações finais"""
        print("\n" + "=" * 80)
        print("RECOMENDAÇÕES PARA TRADING HOJE")
        print("=" * 80)
        
        if not recomendacoes:
            print("\nNenhum par recomendado. Considere ajustar os parâmetros de filtro.")
            return
            
        for i, rec in enumerate(recomendacoes, 1):
            symbol = rec['symbol']
            pontuacao = rec['pontuacao_media']
            info = rec['info_mercado']
            
            print(f"\n{i}. {symbol} - Pontuação: {pontuacao:.2f}/10")
            print(f"   Preço: ${par['current_price']:.4f}")
            print(f"   Volume 24h: ${par['volume_24h']:,.0f}")
            print(f"   Variação 1h: {info.get('price_change_1h', 0):.2f}%")
            print(f"   Variação 24h: {info.get('price_change_24h', 0):.2f}%")
            
            # Mostrar análise do timeframe principal
            tf_principal = self.config["timeframes_testar"][0]
            if tf_principal in rec['timeframes']:
                print(f"\n   Análise ({tf_principal}):")
                linhas_analise = rec['timeframes'][tf_principal]['analise'].split('\n')
                for linha in linhas_analise:
                    print(f"   {linha}")
        
        print("\n" + "=" * 80)
        print(f"Para iniciar o bot com um dos pares recomendados, use:")
        for rec in recomendacoes:
            tf_recomendado = max(self.config["timeframes_testar"], key=lambda tf: rec['timeframes'][tf]['pontuacao'] if tf in rec['timeframes'] else 0)
            print(f"python binance_scalping_bot.py --symbol {rec['symbol']} --timeframe {tf_recomendado}")
        print("=" * 80)

    def selecionar_melhor_par(self, pares_analisados):
        def verificar_consistencia_tendencia(df):
            """
            Verificar se MA99 está consistentemente subindo
            nos últimos 2-3 candles
            """
            # Verificar inclinação da MA99
            ma_longa_recente = df[f'ma_{MA_LONGA}'].iloc[-3:].values

            # Verificar se há tendência de alta consistente
            inclinacao = (ma_longa_recente[-1] - ma_longa_recente[0]) / ma_longa_recente[0] * 100

            # Pelo menos 2 candles com tendência de alta
            return inclinacao > 0.02  # Aumentado para 0.02% para ser mais restritivo

        def calcular_score_lucro(par):
            """
            Calcular score de potencial lucrativo do par
            """
            score = 0
            info = par['info_mercado']

            # Componentes do score
            score += par['pontuacao_media'] * 2.0

            # Volume como indicador de liquidez
            score += min(info.get('volume_24h', 0) / 10_000_000, 5)

            # Ajuste para RSI mais restritivo (zona 40-60)
            rsi = info.get('rsi', 50)  # Valor padrão se não existir
            if 40 <= rsi <= 60:
                # Dentro da zona segura (mais restritiva)
                score += 2.0
            elif 35 <= rsi < 40 or 60 < rsi <= 65:
                # Próximo, mas ainda aceitável
                score += 0.5
            else:
                # Fora da zona ideal
                score -= 1.0

            # Variação de preço moderada
            preco_change = info.get('price_change_24h', 0)
            if abs(preco_change) <= 5.0:  # Mais restritivo
                score += abs(preco_change) * 0.5

            # Penalizar volatilidade extrema ou insuficiente
            atr_percent = info.get('atr_percent', 0)
            if atr_percent > 2.0 or atr_percent < 0.18:  # Mínimo aumentado para 0.18%
                score -= 3.0
            else:
                score += (1 - abs(atr_percent - 0.5)) * 3.0

            # Priorizar pares com potencial de alta
            if preco_change > 0:
                score += 2.0

            return score
        
        # Adicionar log detalhado de todos os pares
        print("\n--- DETALHES DA ANÁLISE DE PARES ---")
        for par in pares_analisados:
            # Atualizar os dados de RSI e ATR do DataFrame principal para o info_mercado
            if 'df_principal' in par and par['df_principal'] is not None and len(par['df_principal']) > 0:
                if 'rsi' in par['df_principal'].columns:
                    par['info_mercado']['rsi'] = par['df_principal']['rsi'].iloc[-1]
                if 'atr_percent' in par['df_principal'].columns:
                    par['info_mercado']['atr_percent'] = par['df_principal']['atr_percent'].iloc[-1]
            
            info = par['info_mercado']
            # 🧠 PRINT DE DEBUG PARA VERIFICAR PONTUAÇÃO TÉCNICA
            print(f"DEBUG | {par['symbol']} | Pontuação técnica: {par['pontuacao_media']:.2f}")

            # 🧠 PRINT DE DEBUG DAS MÉDIAS
            if 'df_principal' in par and par['df_principal'] is not None and len(par['df_principal']) > 0:
                df = par['df_principal']
                ultimo_candle = df.iloc[-1]
                print(f"MA7: {ultimo_candle.get(f'ma_{MA_CURTA}')}, MA25: {ultimo_candle.get(f'ma_{MA_MEDIA}')}, MA99: {ultimo_candle.get(f'ma_{MA_LONGA}')}")
                print(f"Candles disponíveis para {par['symbol']}: {len(df)}")
            print(f"Par: {par['symbol']} | Pontuação: {par['pontuacao_media']:.2f} | "
                f"Volume: ${info.get('volume_24h', 0):,.0f} | "
                f"RSI: {info.get('rsi', 0):.2f} | "
                f"ATR%: {info.get('atr_percent', 0):.2f}%")
        
        # CRITÉRIOS MUITO MAIS RÍGIDOS - Mínimo de 6.5 de pontuação
        MIN_PONTUACAO = 4.0
        
        # Critérios originais - mais rígidos
        pares_validos = []
        for par in pares_analisados:
            info = par['info_mercado']
            # Usar os valores calculados do DataFrame principal
            if 'df_principal' in par and par['df_principal'] is not None and len(par['df_principal']) > 0:
                df = par['df_principal']
                ultimo_candle = df.iloc[-1] if len(df) > 0 else None
                
                # Critérios muito mais rígidos
                # Exigir pontuação mínima de 6.5 (alinhada com binance_scalping_bot.py)
                pontuacao_ok = par['pontuacao_media'] >= MIN_PONTUACAO
                
                # Se não tiver pontuação mínima, já descarta
                if not pontuacao_ok:
                    continue
                    
                rsi_ok = 40 <= info.get('rsi', 50) <= 60  # Faixa mais restrita
                atr_ok = 0.18 <= info.get('atr_percent', 0) <= 2.0  # ATR mínimo mais alto
                volume_ok = info.get('volume_24h', 0) > 10_000_000 and ultimo_candle['volume'] >= ultimo_candle['volume_media'] * 1.3  # Volume recente pelo menos 130% da média
                
                # Verificar médias móveis alinhadas corretamente
                if ultimo_candle is not None:
                    mas_alinhadas = (
                        ultimo_candle.get(f'ma_{MA_CURTA}', 0) > 
                        ultimo_candle.get(f'ma_{MA_MEDIA}', 0) > 
                        ultimo_candle.get(f'ma_{MA_LONGA}', 0)
                    )
                    # Adicionar verificação de cruzamento recente
                    cruzamento_recente = False
                    if len(df) >= 3:
                        penultimo = df.iloc[-2]
                        if (penultimo[f'ma_{MA_CURTA}'] <= penultimo[f'ma_{MA_MEDIA}'] and
                            ultimo_candle[f'ma_{MA_CURTA}'] > ultimo_candle[f'ma_{MA_MEDIA}']):
                            cruzamento_recente = True
                else:
                    mas_alinhadas = False
                    cruzamento_recente = False
                
                # Exigir mais critérios atendidos simultaneamente
                condicoes = [
                    pontuacao_ok,  # NOVO: pontuação mínima obrigatória
                    volume_ok,
                    atr_ok,
                    rsi_ok,
                    mas_alinhadas
                ]

                # Exigir pelo menos 4 de 5 critérios SENDO QUE pontuação_ok é OBRIGATÓRIO
                # MODIFICAÇÃO: Reduzir exigência para mais trades
                # Exigir pelo menos 2 de 5 critérios e pontuação ok
                criterios_atendidos = sum(condicoes[1:])  # Contar apenas os critérios não obrigatórios

                if pontuacao_ok and criterios_atendidos >= 2:  # Reduzido de 3 para 2
                    # Código para solicitar aprovação...
                    
                    # Transferir valores diagnósticos para info_mercado
                    if 'df_principal' in par and par['df_principal'] is not None and len(par['df_principal']) > 0:
                        df = par['df_principal']
                        if 'rsi' in df.columns:
                            par['info_mercado']['rsi'] = float(df['rsi'].iloc[-1])
                        if 'atr_percent' in df.columns:
                            par['info_mercado']['atr_percent'] = float(df['atr_percent'].iloc[-1])
                            
                    pares_validos.append(par)
        
        # Se não encontrar pares válidos, NÃO usar critérios relaxados
        if not pares_validos:
            print("Nenhum par atende aos critérios rigorosos de seleção. Não aplicando critérios relaxados.")
            return None

        for par in pares_validos:
            if 'score_lucro' not in par:
                par['score_lucro'] = calcular_score_lucro(par)

        # Ordenar por score de lucro
        pares_validos.sort(key=lambda x: x['score_lucro'], reverse=True)

        if not pares_validos:
            print("Nenhum par válido após ordenação.")
            return None

        # Selecionar o melhor par
        melhor_par = pares_validos[0]

        # Log detalhado da seleção
        print("\n--- PAR SELECIONADO AUTOMATICAMENTE ---")
        print(f"Símbolo: {melhor_par['symbol']}")
        print(f"Pontuação Técnica: {melhor_par['pontuacao_media']:.2f}")
        print(f"Score de Lucro: {melhor_par['score_lucro']:.2f}")
        print(f"Preço: ${melhor_par['info_mercado'].get('current_price', 0):.4f}")
        print(f"Volume 24h: ${melhor_par['info_mercado'].get('volume_24h', 0):,.0f}")
        print(f"Variação 24h: {melhor_par['info_mercado'].get('price_change_24h', 0):.2f}%")

        # Buscar valores do DataFrame principal para garantir precisão
        atr_valor = 0
        rsi_valor = 0
        if 'df_principal' in melhor_par and melhor_par['df_principal'] is not None:
            df = melhor_par['df_principal']
            if len(df) > 0:
                if 'atr_percent' in df.columns:
                    atr_valor = df['atr_percent'].iloc[-1]
                if 'rsi' in df.columns:
                    rsi_valor = df['rsi'].iloc[-1]

        print(f"Volatilidade (ATR): {atr_valor:.2f}%")
        print(f"RSI: {rsi_valor:.2f}")

        # Enviar alerta pelo Telegram se for uma boa oportunidade
        if melhor_par['pontuacao_media'] >= MIN_PONTUACAO and atr_valor >= 0.18:
            try:
                # Compor mensagem detalhada
                mensagem = (
                    f"🔥 OPORTUNIDADE DE ALTA QUALIDADE\n\n"
                    f"Par: {melhor_par['symbol']}\n"
                    f"Pontuação: {melhor_par['pontuacao_media']:.2f}/10\n"
                    f"Preço: ${melhor_par['info_mercado'].get('current_price', 0):.4f}\n"
                    f"ATR: {atr_valor:.2f}%\n"
                    f"RSI: {rsi_valor:.2f}\n"
                )
                
                # Verificar se dados de volume estão disponíveis
                volume_info_added = False
                if 'df_principal' in melhor_par and melhor_par['df_principal'] is not None:
                    df = melhor_par['df_principal']
                    if len(df) > 0:
                        ultimo_candle = df.iloc[-1]
                        if 'volume' in ultimo_candle and 'volume_media' in ultimo_candle and ultimo_candle['volume_media'] > 0:
                            ratio = ultimo_candle['volume'] / ultimo_candle['volume_media'] * 100
                            mensagem += f"Volume: {ratio:.0f}% da média\n\n"
                            volume_info_added = True
                
                if not volume_info_added:
                    mensagem += "Volume: Dados não disponíveis\n\n"
                
                # Adicionar comando para iniciar
                mensagem += (
                    f"Comando para iniciar:\n"
                    f"`python binance_scalping_bot.py --symbol {melhor_par['symbol']}`"
                )
                
                # Usar o sistema de alertas da instância
                print("Enviando alerta de oportunidade via Telegram...")
                success = self.alert_system.send_alert(mensagem, "OPORTUNIDADE DE ALTA QUALIDADE")
                
                # Registrar resultado do envio
                if success:
                    print("✅ Alerta enviado com sucesso!")
                else:
                    print("❌ Falha ao enviar alerta!")
                    
                    # Tentar envio direto como fallback
                    try:
                        import requests
                        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                        data = {
                            "chat_id": TELEGRAM_CHAT_ID,
                            "text": mensagem
                        }
                        response = requests.post(url, data=data)
                        print(f"Tentativa direta: {response.status_code} - {response.text[:100]}")
                    except Exception as direct_err:
                        print(f"Erro também na tentativa direta: {str(direct_err)}")
                    
            except Exception as e:
                print(f"Erro ao enviar alerta Telegram: {str(e)}")
                import traceback
                traceback.print_exc()  # Mostrar o stack trace completo

        return melhor_par['symbol']  # Retorna o símbolo do melhor par

    def otimizar_parametros_pontuacao(self, historico_dias=30, num_combinacoes=20):
        """
        Otimiza os parâmetros de pontuação usando dados históricos
        
        Args:
            historico_dias: Número de dias de histórico para analisar
            num_combinacoes: Número de combinações a testar
        
        Returns:
            dict: Melhores parâmetros encontrados
        """
        print(f"\n=== INICIANDO OTIMIZAÇÃO DE PARÂMETROS (ÚLTIMOS {historico_dias} DIAS) ===\n")
        
        # Pasta para resultados
        pasta_resultados = os.path.join(self.config["pasta_logs"], "otimizacao")
        os.makedirs(pasta_resultados, exist_ok=True)
        
        # Obter histórico de preços para o período
        data_fim = datetime.now()
        data_inicio = data_fim - timedelta(days=historico_dias)
        
        print(f"Obtendo dados históricos de {data_inicio.strftime('%Y-%m-%d')} a {data_fim.strftime('%Y-%m-%d')}")
        
        # Usar pares populares para otimização
        pares_teste = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
        
        # Gerar combinações de parâmetros
        import random
        
        combinacoes = []
        for _ in range(num_combinacoes):
            combinacao = {
                "peso_tendencia": round(random.uniform(0.5, 2.5), 1),
                "peso_volume": round(random.uniform(0.5, 2.5), 1),
                "peso_rsi": round(random.uniform(0.5, 2.5), 1),
                "peso_cruzamento": round(random.uniform(1.0, 3.0), 1),
                "peso_alinhamento": round(random.uniform(0.5, 2.5), 1),
                "min_score_tecnico": round(random.uniform(4.0, 7.0), 1)
            }
            combinacoes.append(combinacao)
        
        # Adicionar a configuração atual como referência
        configuracao_atual = {
            "peso_tendencia": self.config.get("peso_tendencia", 1.5),
            "peso_volume": self.config.get("peso_volume", 1.5),
            "peso_rsi": self.config.get("peso_rsi", 1.5),
            "peso_cruzamento": self.config.get("peso_cruzamento", 2.0),
            "peso_alinhamento": self.config.get("peso_alinhamento", 1.5),
            "min_score_tecnico": self.config.get("min_score_tecnico", 5.5)
        }
        combinacoes.append(configuracao_atual)
        
        # Resultados de cada combinação
        resultados_combinacoes = []
        
        for idx, combinacao in enumerate(combinacoes):
            print(f"\nTestando combinação {idx+1}/{len(combinacoes)}: {combinacao}")
            
            # Aplicar combinação aos parâmetros
            config_backup = {}
            for param, valor in combinacao.items():
                config_backup[param] = self.config.get(param)
                self.config[param] = valor
            
            # Testar cada par
            resultados_pares = []
            
            for par in pares_teste:
                print(f"  Analisando {par}...")
                
                try:
                    # Obter dados históricos
                    df = self.get_klines(par, self.timeframe, limit=500)
                    
                    # Simular análises e decisões
                    sinais_corretos = 0
                    total_decisoes = 0
                    lucro_simulado = 0
                    
                    # Analisar cada ponto de entrada potencial
                    for i in range(200, len(df) - 50):  # Deixar espaço para indicadores e para verificar resultado
                        # Dados até este ponto
                        df_atual = df.iloc[:i+1].copy()
                        
                        # Verificar sinal
                        pontuacao, analise = self.check_signal(df_atual)
                        sinal_entrada = pontuacao >= combinacao["min_score_tecnico"] or "CAMADA RESGATE" in analise
                        
                        if sinal_entrada:
                            # Simular resultado da operação
                            preco_entrada = df_atual['close'].iloc[-1]
                            
                            # Verificar resultado nos próximos 20 candles
                            proximos_candles = df.iloc[i+1:i+21]
                            
                            # Simular stop loss e take profit
                            atr = df_atual['atr'].iloc[-1] if 'atr' in df_atual.columns else preco_entrada * 0.01
                            stop_loss = preco_entrada - (STOP_LOSS_MULTIPLICADOR_ATR * atr)
                            take_profit1 = preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_1 / 100)
                            take_profit2 = preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_2 / 100)
                            take_profit3 = preco_entrada * (1 + ALVO_LUCRO_PERCENTUAL_3 / 100)
                            
                            # Verificar se atingiu stop ou take profit
                            atingiu_stop = False
                            atingiu_tp = False
                            preco_saida = None
                            
                            for j, candle in proximos_candles.iterrows():
                                if candle['low'] <= stop_loss:
                                    atingiu_stop = True
                                    preco_saida = stop_loss
                                    break
                                elif candle['high'] >= take_profit2:  # Usar TP2 como referência
                                    atingiu_tp = True
                                    preco_saida = take_profit2
                                    break
                            
                            # Se não atingiu nem stop nem TP, usar último preço
                            if not atingiu_stop and not atingiu_tp and len(proximos_candles) > 0:
                                preco_saida = proximos_candles['close'].iloc[-1]
                            elif not preco_saida:
                                preco_saida = preco_entrada  # Fallback
                            
                            # Calcular resultado
                            resultado_pct = (preco_saida - preco_entrada) / preco_entrada * 100
                            
                            # Considerar sinal correto se resultou em lucro
                            if resultado_pct > 0:
                                sinais_corretos += 1
                            
                            # Acumular lucro simulado
                            lucro_simulado += resultado_pct
                            
                            total_decisoes += 1
                    
                    # Calcular taxa de acerto
                    taxa_acerto = sinais_corretos / max(1, total_decisoes) * 100
                    
                    # Armazenar resultado do par
                    resultados_pares.append({
                        "par": par,
                        "total_decisoes": total_decisoes,
                        "sinais_corretos": sinais_corretos,
                        "taxa_acerto": taxa_acerto,
                        "lucro_simulado": lucro_simulado
                    })
                    
                    print(f"    Decisões: {total_decisoes}, Taxa de acerto: {taxa_acerto:.1f}%, Lucro: {lucro_simulado:.2f}%")
                    
                except Exception as e:
                    print(f"  Erro ao analisar {par}: {e}")
                    continue
            
            # Consolidar resultados de todos os pares para esta combinação
            if resultados_pares:
                total_decisoes = sum(r["total_decisoes"] for r in resultados_pares)
                total_corretos = sum(r["sinais_corretos"] for r in resultados_pares)
                lucro_total = sum(r["lucro_simulado"] for r in resultados_pares)
                
                taxa_acerto_media = total_corretos / max(1, total_decisoes) * 100
                lucro_medio = lucro_total / len(resultados_pares)
                
                resultado_combinacao = {
                    "combinacao": combinacao,
                    "total_decisoes": total_decisoes,
                    "taxa_acerto": taxa_acerto_media,
                    "lucro_medio": lucro_medio,
                    "resultados_pares": resultados_pares
                }
                
                resultados_combinacoes.append(resultado_combinacao)
                
                print(f"  Resultado combinação: Taxa acerto média: {taxa_acerto_media:.1f}%, Lucro médio: {lucro_medio:.2f}%")
            
            # Restaurar configuração original
            for param, valor in config_backup.items():
                self.config[param] = valor
        
        # Ordenar resultados por lucro médio
        resultados_combinacoes = sorted(resultados_combinacoes, key=lambda x: x["lucro_medio"], reverse=True)
        
        # Salvar resultados
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_resultados = os.path.join(pasta_resultados, f"resultados_otimizacao_{timestamp}.json")
        
        with open(arquivo_resultados, 'w') as f:
            json.dump(resultados_combinacoes, f, indent=2)
        
        # Exibir melhores combinações
        print("\n=== MELHORES COMBINAÇÕES DE PARÂMETROS ===")
        
        for i, resultado in enumerate(resultados_combinacoes[:5]):
            print(f"\n{i+1}. Lucro médio: {resultado['lucro_medio']:.2f}%, Taxa acerto: {resultado['taxa_acerto']:.1f}%")
            print(f"   Parâmetros: {resultado['combinacao']}")
        
        # Retornar a melhor combinação
        if resultados_combinacoes:
            melhor_combinacao = resultados_combinacoes[0]["combinacao"]
            
            print("\n=== MELHOR COMBINAÇÃO ENCONTRADA ===")
            print(f"Parâmetros: {melhor_combinacao}")
            print(f"Lucro médio: {resultados_combinacoes[0]['lucro_medio']:.2f}%")
            print(f"Taxa de acerto: {resultados_combinacoes[0]['taxa_acerto']:.1f}%")
            
            return melhor_combinacao
        
        return None
def main():
    print("===== CRYPTO MARKET SCANNER =====")
    
    # Inicializar recomendacoes como lista vazia antes de qualquer uso
    recomendacoes = []
    
    api_key = API_KEY
    api_secret = API_SECRET
    
    # Definir CAPITAL_POR_OPERACAO aqui ou importar
    try:
        from binance_scalping_bot import CAPITAL_POR_OPERACAO
    except ImportError:
        CAPITAL_POR_OPERACAO = 5.0  # Valor padrão se não conseguir importar
    
    if api_key == 'gYzsw6dYN0ukl1Vm3FDMS0fLugwpacnJLD8XMNZL5WwUxErVnfWzamEwYttviUT8' or api_secret == 'Z6huY9KvuJvy7OMnPdjY2w8yauuUR1D7kfCNOTLkk6gVwQfrqooW8WVz2Ll8aRjt':
        print("\nATENÇÃO: Você precisa configurar suas chaves de API da Binance.")
        print("Edite o arquivo para incluir suas chaves API no início ou use as chaves do seu bot principal.")
        
        api_key_input = input("Digite sua API Key da Binance (ou Enter para usar as configuradas): ")
        api_secret_input = input("Digite sua API Secret da Binance (ou Enter para usar as configuradas): ")
        
        if api_key_input.strip():
            api_key = api_key_input
        if api_secret_input.strip():
            api_secret = api_secret_input
    
    try:
        scanner = CryptoMarketScanner(api_key, api_secret)
        
        # Menu de opções ampliado
        print("\nSelecione o modo de operação:")
        print("1. Escaneamento único")
        print("2. Escaneamento contínuo")
        print("3. Otimização de parâmetros")
        print("4. Aplicar parâmetros otimizados")
        
        opcao = input("Opção (1-4): ").strip()
        
        if opcao == "1":
            # Escaneamento único (código original)
            print("Analisando mercado para encontrar os melhores pares para trading...")
            melhor_par = scanner.escanear_mercado()
            
        elif opcao == "2":
            # Escaneamento contínuo (código original)
            print("(O bot continuará procurando pares adequados periodicamente até encontrar)")
            try:
                intervalo = int(input("Intervalo entre verificações (minutos): "))
            except ValueError:
                intervalo = 15  # Valor padrão
                print(f"Valor inválido. Usando intervalo padrão de {intervalo} minutos.")
            
            # Iniciar escaneamento contínuo
            melhor_par = scanner.iniciar_escaneamento_continuo(intervalo)
            
        elif opcao == "3":
            # Otimização de parâmetros
            print("\nIniciando otimização de parâmetros...")
            
            try:
                dias = int(input("Quantidade de dias para análise histórica (padrão: 30): ") or "30")
                combinacoes = int(input("Número de combinações a testar (padrão: 100): ") or "100")
            except ValueError:
                dias = 30
                combinacoes = 100
                print("Valor inválido. Usando valores padrão.")
            
            melhores_parametros = scanner.otimizar_parametros_pontuacao(dias, combinacoes)
            
            if melhores_parametros:
                print("\nDeseja aplicar estes parâmetros e iniciar escaneamento contínuo? (s/n)")
                aplicar = input("Resposta [s/n]: ").strip().lower()
                
                if aplicar == 's' or aplicar == 'sim':
                    # Aplicar parâmetros otimizados
                    for param, valor in melhores_parametros.items():
                        scanner.config[param] = valor
                    
                    print("\nParâmetros aplicados. Iniciando escaneamento contínuo...")
                    
                    # Definir intervalo fixo de 1 minuto sem perguntar ao usuário
                    intervalo = 1
                    print(f"Usando intervalo fixo de {intervalo} minuto entre verificações.")
                    
                    # Iniciar escaneamento contínuo em vez de único
                    melhor_par = scanner.iniciar_escaneamento_continuo(intervalo)
                else:
                    # Se não aplicar os parâmetros, não seguir com escaneamento
                    print("Parâmetros otimizados não aplicados. Saindo.")
                    return
            else:
                print("Otimização não encontrou parâmetros melhores. Saindo.")
                return
            
        elif opcao == "4":
            # Aplicar parâmetros otimizados de um arquivo
            print("\nCarregando parâmetros otimizados de arquivo...")
            
            pasta_resultados = os.path.join(scanner.config["pasta_logs"], "otimizacao")
            
            # Criar pasta se não existir
            os.makedirs(pasta_resultados, exist_ok=True)
            
            # Verificar se há arquivos
            if not os.path.exists(pasta_resultados) or not os.listdir(pasta_resultados):
                print("Nenhum arquivo de otimização encontrado. Execute a otimização primeiro.")
                return
                
            arquivos = [f for f in os.listdir(pasta_resultados) if f.startswith("resultados_otimizacao_")]
            
            if not arquivos:
                print("Nenhum arquivo de otimização encontrado. Execute a otimização primeiro.")
                return
            
            # Ordenar por data (mais recente primeiro)
            arquivos.sort(reverse=True)
            
            print("\nArquivos de otimização disponíveis:")
            for i, arquivo in enumerate(arquivos[:5]):
                print(f"{i+1}. {arquivo}")
            
            try:
                escolha = int(input("\nEscolha o arquivo (1-5): "))
                if 1 <= escolha <= min(5, len(arquivos)):
                    arquivo_selecionado = arquivos[escolha-1]
                    
                    # Carregar arquivo
                    caminho_completo = os.path.join(pasta_resultados, arquivo_selecionado)
                    with open(caminho_completo, 'r') as f:
                        resultados = json.load(f)
                    
                    if resultados:
                        melhor_combinacao = resultados[0]["combinacao"]
                        
                        print(f"\nParâmetros carregados: {melhor_combinacao}")
                        
                        # Aplicar parâmetros
                        for param, valor in melhor_combinacao.items():
                            scanner.config[param] = valor
                        
                        print("\nParâmetros aplicados. Iniciando escaneamento...")
                        melhor_par = scanner.escanear_mercado()
                    else:
                        print("Arquivo de resultados vazio.")
                        return
                else:
                    print("Opção inválida.")
                    return
            except (ValueError, IndexError):
                print("Opção inválida.")
                return
        
        else:
            print("Opção inválida.")
            return
        
        # O código abaixo é executado após o escaneamento em qualquer modo
        
        # Atualizar recomendacoes
        if isinstance(melhor_par, list):
            recomendacoes = melhor_par
        elif melhor_par:
            recomendacoes = [{'symbol': melhor_par}]
        
        if melhor_par:
            # Importações para iniciar o bot
            try:
                from binance_scalping_bot import BinanceScalpingBotMelhorado
                import binance_scalping_bot
                
                binance_scalping_bot.SYMBOL = melhor_par
                
                print(f"\n✅ Par encontrado e aprovado: {melhor_par}")
                
                # Iniciar diretamente se viemos do modo de escaneamento contínuo
                if opcao == "2":
                    iniciar_bot = True
                else:
                    # Solicitar aprovação pelo Telegram para os outros modos
                    iniciar_bot = False
                    if TELEGRAM_APPROVAL_AVAILABLE:
                        print("Solicitando confirmação pelo Telegram...")
                        iniciar_bot = request_trading_approval(melhor_par, timeout=300)
                        print(f"Resultado da aprovação: {iniciar_bot}")
                    else:
                        print("Deseja iniciar o bot de trading automaticamente? (s/n)")
                        resposta_bot = input("Resposta [s/n]: ").strip().lower()
                        iniciar_bot = resposta_bot == 's' or resposta_bot == 'sim'

                # Iniciar o bot se aprovado
                if iniciar_bot:
                    print(f"Iniciando bot com {melhor_par}...")
                    bot = BinanceScalpingBotMelhorado(
                        API_KEY, 
                        API_SECRET, 
                        melhor_par, 
                        TIMEFRAME, 
                        CAPITAL_POR_OPERACAO
                    )
                    bot.iniciar()
                else:
                    print(f"Para iniciar o bot manualmente, execute: python binance_scalping_bot.py --symbol {melhor_par}")
            except ImportError:
                print(f"\n✅ Par encontrado: {melhor_par}")
                print("Não foi possível iniciar o bot automaticamente.")
                print(f"Execute manualmente com: python binance_scalping_bot.py --symbol {melhor_par}")
        else:
            print("Nenhum par encontrado para operar hoje.")
        
        # Verificar se recomendacoes tem algum elemento
        if recomendacoes:  # Agora esta linha está garantida a funcionar
            print("\nDeseja iniciar o bot com um dos pares recomendados?")
            for i, rec in enumerate(recomendacoes, 1):
                print(f"{i}. {rec['symbol']}")
            print("0. Sair")
            
            try:
                escolha = int(input(f"\nEscolha uma opção (0-{len(recomendacoes)}): "))
                if 1 <= escolha <= len(recomendacoes):
                    par_escolhido = recomendacoes[escolha-1]['symbol']
                    
                    # Obter timeframe
                    tfs = recomendacoes[escolha-1].get('timeframes', {})
                    tf_recomendado = max(tfs.keys(), key=lambda tf: tfs[tf]['pontuacao']) if tfs else TIMEFRAME
                    
                    print(f"\nIniciando bot com {par_escolhido} no timeframe {tf_recomendado}...")
                    
                    try:
                        from binance_scalping_bot import BinanceScalpingBotMelhorado
                        import binance_scalping_bot
                        
                        binance_scalping_bot.SYMBOL = par_escolhido
                        binance_scalping_bot.TIMEFRAME = tf_recomendado
                        
                        print(f"Iniciando bot com {par_escolhido} ({tf_recomendado})...")
                        bot = BinanceScalpingBotMelhorado(
                            API_KEY, 
                            API_SECRET, 
                            par_escolhido, 
                            tf_recomendado, 
                            CAPITAL_POR_OPERACAO
                        )
                        bot.iniciar(intervalo_segundos=5)
                        
                    except ImportError:
                        print("\nNão foi possível iniciar o bot automaticamente.")
                        print(f"Execute manualmente com: python binance_scalping_bot.py --symbol {par_escolhido} --timeframe {tf_recomendado}")
            except ValueError:
                print("Opção inválida. Saindo.")
        
    except Exception as e:
        print(f"Erro ao executar scanner: {e}")
        import traceback
        traceback.print_exc()
if __name__ == "__main__":
    main()        
