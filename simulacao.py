from binance.client import Client
from binance.exceptions import BinanceAPIException

# Substitua pelas suas chaves reais
api_key = "gYzsw6dYN0ukl1Vm3FDMS0fLugwpacnJLD8XMNZL5WwUxErVnfWzamEwYttviUT8"
api_secret = "Z6huY9KvuJvy7OMnPdjY2w8yauuUR1D7kfCNOTLkk6gVwQfrqooW8WVz2Ll8aRjt"

client = Client(api_key, api_secret)

try:
    # Verificar saldo
    print("Verificando saldo...")
    account_info = client.get_account()
    for balance in account_info['balances']:
        if float(balance['free']) > 0:
            print(f"{balance['asset']}: {balance['free']}")
    
    # Tentar uma ordem de teste
    print("\nTentando ordem de teste...")
    order = client.create_test_order(
        symbol='BTCUSDT',
        side='BUY',
        type='MARKET',
        quoteOrderQty=10
    )
    print("Ordem de teste bem-sucedida!")
    
    # Descomentar para tentar uma ordem real
    print("\nTentando ordem real...")
    real_order = client.create_order(
        symbol='BTCUSDT',
        side='BUY',
        type='MARKET',
        quoteOrderQty=10
    )
    print(f"Ordem real executada: {real_order}")
    
except BinanceAPIException as e:
    print(f"Erro da API Binance: {e.code} - {e.message}")
except Exception as e:
    print(f"Erro inesperado: {e}")