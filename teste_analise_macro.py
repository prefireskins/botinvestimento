from binance_scalping_bot import BinanceScalpingBotMelhorado, API_KEY, API_SECRET, SYMBOL, TIMEFRAME, CAPITAL_POR_OPERACAO

def testar_analise_macro():
    print("Teste de Análise Macro")
    print("======================\n")
    
    # Inicializar bot
    bot = BinanceScalpingBotMelhorado(API_KEY, API_SECRET, SYMBOL, TIMEFRAME, CAPITAL_POR_OPERACAO)
    
    # Testar análise de sentimento
    print("\n1. Testando Análise de Sentimento:")
    sentimento_score, sentimento_desc, fear_greed = bot.analisar_sentimento_mercado()
    print(f"Score: {sentimento_score}")
    print(f"Descrição: {sentimento_desc}")
    print(f"Fear & Greed: {fear_greed}")
    
    # Testar análise de correlação
    print("\n2. Testando Análise de Correlação:")
    correlacao_score, correlacao_desc, btc_corr, eth_corr = bot.analisar_correlacoes()
    print(f"Score: {correlacao_score}")
    print(f"Descrição: {correlacao_desc}")
    print(f"Correlação BTC: {btc_corr}")
    print(f"Correlação ETH: {eth_corr}")
    
    # Testar análise de dominância
    print("\n3. Testando Análise de Dominância:")
    dominancia_score, dominancia_desc, btc_dom, market_cap = bot.analisar_dominancia_btc()
    print(f"Score: {dominancia_score}")
    print(f"Descrição: {dominancia_desc}")
    print(f"Dominância BTC: {btc_dom}%")
    print(f"Market Cap Total: ${market_cap:,.0f}")
    
    # Salvar dados e gerar gráfico
    print("\n4. Salvando dados e gerando gráfico:")
    bot.salvar_analise_macro(
        fear_greed, btc_dom, market_cap, btc_corr, eth_corr,
        sentimento_score, correlacao_score, dominancia_score
    )
    
    caminho_grafico = bot.visualizar_indicadores_macro()
    print(f"Gráfico gerado: {caminho_grafico}")
    
    print("\nTeste completo!")

if __name__ == "__main__":
    testar_analise_macro()