import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from alert_system import AlertSystem
import threading
import queue
import time
import os
# Configurações de timeout para requests
import requests
requests.packages.urllib3.util.connection.HAS_IPV6 = False  # Desabilitar IPv6
latest_approval_result = None
latest_approval_symbol = None
# Configurar seu bot do Telegram
TOKEN = "7103442744:AAHTHxLnVixhNWcsvmG2mU1uqWUNwGktfxw"

# ======= SINGLETON PATTERN ========
# Criar um arquivo de lock para garantir que apenas uma instância do bot esteja rodando
LOCK_FILE = os.path.expanduser("~/.telegram_bot_lock")

def is_bot_running():
    """Verificar se o bot já está rodando em outra instância"""
    if os.path.exists(LOCK_FILE):
        # Verificar se o processo que criou o arquivo de lock ainda está vivo
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
                
            # Tentar enviar um sinal nulo ao processo para verificar se está vivo
            try:
                os.kill(pid, 0)  # Sinal 0 apenas verifica se o processo existe
                return True  # Processo existe, bot já está rodando
            except OSError:
                # Processo não existe mais, podemos sobrescrever o lock
                pass
        except (ValueError, FileNotFoundError):
            # Arquivo corrompido ou removido, podemos sobrescrever
            pass
    
    # Criar novo arquivo de lock
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    return False

# Verificar se o bot já está rodando
bot_already_running = is_bot_running()

# Inicializar bot apenas se não estiver rodando em outra instância
# Sempre inicializar o bot
bot = telebot.TeleBot(TOKEN)
bot_already_running = False

# Variáveis globais para comunicação entre threads
pending_approvals = {}  # Armazena as moedas aguardando aprovação
approval_results = {}   # Armazena os resultados das aprovações
message_queue = queue.Queue()  # Fila para envio de mensagens

# Adicionar um lock para evitar condições de corrida
approval_lock = threading.Lock()

# Inicializar sistema de alertas com Telegram ativado
alert_system = AlertSystem(
    enable_sound=True,
    enable_telegram=True,
    telegram_token=TOKEN,  # Mesmo token do bot
    telegram_chat_id=None  # Não usamos um chat_id padrão, enviamos para cada usuário individualmente
)

# Notificação sobre status do bot
if bot_already_running:
    print("AVISO: Bot do Telegram já está rodando em outra instância. Usando instância existente.")
else:
    print("Bot do Telegram inicializado como instância principal.")

# Define all bot handlers only if we're the main instance
if bot:
    @bot.message_handler(commands=['sim', 'nao'])
    def approval_command(message):
        """Comando para aprovar ou recusar uma operação"""
        global latest_approval_result, latest_approval_symbol
        
        user_id = str(message.chat.id)
        command = message.text.lower().strip()
        print(f"Comando recebido: {command} de user_id: {user_id}")

        
        # Verificar se há uma moeda pendente de aprovação para este usuário
        if user_id not in pending_approvals or not pending_approvals[user_id]:
            bot.send_message(user_id, "Nenhuma operação pendente de aprovação no momento.")
            return
        
        # Obter a moeda pendente
        symbol = pending_approvals[user_id]
        approved = command == '/sim'
        
        # Definir resultado com lock para evitar condições de corrida
        with approval_lock:
            key = f"{user_id}_{symbol}"
            approval_results[key] = approved
            print(f"APROVAÇÃO VIA COMANDO: Key={key}, Resultado={approved}")
            
            # NOVO: Atualizar variável global também!
            if symbol == latest_approval_symbol:
                latest_approval_result = approved
                print(f"✅ Variável global atualizada: {latest_approval_result}")
            
        # Limpar a pendência
        pending_approvals[user_id] = None
        
        # Enviar confirmação
        if approved:
            bot.send_message(user_id, f"✅ Você APROVOU a operação com {symbol}. O bot irá prosseguir.")
        else:
            bot.send_message(user_id, f"❌ Você RECUSOU a operação com {symbol}. O bot irá buscar outra oportunidade.")
        
        print(f"approval_results atualizado: {approval_results}")

    # Handler para callbacks dos botões
    # Handler para callbacks dos botões
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global latest_approval_result, latest_approval_symbol
    
    user_id = str(call.message.chat.id)
    data = call.data
    print(f"Callback recebido: {data} de user_id: {user_id}")

    if call.data == "toggle_alerts":
        # Alternar configuração
        new_status = alert_system.toggle_condicoes_favoraveis(user_id)
        
        # Atualizar mensagem
        status_text = "ATIVADOS" if new_status else "DESATIVADOS"
        bot.answer_callback_query(call.id, f"Alertas {status_text} com sucesso!")
        
        # Atualizar menu
        settings_command(call.message)
    
    # Processar callbacks de aprovação de trading
    elif call.data.startswith("approve_") or call.data.startswith("reject_"):
        symbol = call.data.split("_")[1]
        approved = call.data.startswith("approve_")
        
        print(f"DEBUG - Processando callback de aprovação: {call.data}")
        print(f"DEBUG - Symbol: {symbol}, Approved: {approved}")
        
        # Verificar se este símbolo está pendente para o usuário
        if user_id in pending_approvals and pending_approvals[user_id] == symbol:
            # Definir resultado com lock
            with approval_lock:
                key = f"{user_id}_{symbol}"
                approval_results[key] = approved
                print(f"APROVAÇÃO VIA CALLBACK: Key={key}, Resultado={approved}")
                
                # NOVO: Atualizar variável global também!
                if symbol == latest_approval_symbol:
                    latest_approval_result = approved
                    print(f"✅ Variável global atualizada: {latest_approval_result}")
                
            # Limpar a pendência
            pending_approvals[user_id] = None
            
            # Responder ao callback
            if approved:
                bot.answer_callback_query(call.id, f"Você APROVOU a operação com {symbol}")
                bot.edit_message_text(
                    f"✅ Você APROVOU a operação com {symbol}. O bot irá prosseguir.",
                    chat_id=user_id,
                    message_id=call.message.message_id
                )
            else:
                bot.answer_callback_query(call.id, f"Você RECUSOU a operação com {symbol}")
                bot.edit_message_text(
                    f"❌ Você RECUSOU a operação com {symbol}. O bot irá buscar outra oportunidade.",
                    chat_id=user_id,
                    message_id=call.message.message_id
                )
            
            print(f"Callback processado: {call.data} de user_id: {user_id}")
            print(f"approval_results atualizado: {approval_results}")
            print(f"latest_approval_result = {latest_approval_result}")
        else:
            print(f"ERRO: Símbolo {symbol} não pendente para usuário {user_id}")
            print(f"pending_approvals = {pending_approvals}")
            bot.answer_callback_query(call.id, "Erro ao processar resposta. Tente novamente.")

    # Comando /start
    @bot.message_handler(commands=['start'])
    def start_command(message):
        user_id = message.chat.id
        bot.send_message(user_id, "Bem-vindo ao bot de alertas! Use /configuracoes para gerenciar suas notificações.")

    # Comando /configuracoes
    @bot.message_handler(commands=['configuracoes'])
    def settings_command(message):
        user_id = message.chat.id
        
        # Obter status atual
        user_settings = alert_system.user_settings.get_user_settings(user_id)
        current_status = user_settings.get("condicoes_favoraveis", True)
        
        # Criar teclado inline
        markup = InlineKeyboardMarkup()
        button_text = "🔕 Desativar alertas de condições favoráveis" if current_status else "🔔 Ativar alertas de condições favoráveis"
        markup.add(InlineKeyboardButton(button_text, callback_data="toggle_alerts"))
        
        # Enviar mensagem com status atual
        status_message = alert_system.get_settings_status(user_id)
        bot.send_message(user_id, status_message, reply_markup=markup)

def request_trading_approval(symbol, timeout=300):
    global latest_approval_result, latest_approval_symbol
    
    print("\n--- SOLICITAÇÃO DE APROVAÇÃO ---")
    print(f"Símbolo: {symbol}")
    print(f"Timeout: {timeout} segundos")
    
    # Resetar variáveis globais
    latest_approval_result = None
    latest_approval_symbol = symbol
    
    print(f"DEBUG: Enviando solicitação de aprovação. Bot inicializado: {bot is not None}")
    
    if bot is None:
        print("ERRO: Bot do Telegram não inicializado!")
        return False
    
    # Limpar resultados anteriores com o mesmo símbolo
    with approval_lock:
        for key in list(approval_results.keys()):
            if key.endswith(f"_{symbol}"):
                del approval_results[key]
    
    # Verificar se há usuários para enviar mensagem
    usuarios = list(alert_system.user_settings.settings.keys())
    print(f"Usuários encontrados: {usuarios}")
    
    if not usuarios:
        print("ERRO: Nenhum usuário configurado para receber mensagens!")
        return False
    
    # Enviar mensagem para todos os usuários cadastrados com botões inline
    for user_id in usuarios:
        # Garantir que user_id seja string
        user_id_str = str(user_id)
        # Marcar como pendente para este usuário
        pending_approvals[user_id_str] = symbol
        
        # Criar markup com botões inline
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ SIM", callback_data=f"approve_{symbol}"),
            InlineKeyboardButton("❌ NÃO", callback_data=f"reject_{symbol}")
        )
        
        # Enviar mensagem com botões
        try:
            print(f"Enviando mensagem para usuário: {user_id_str}")
            bot.send_message(
                user_id,
                f"🔔 *CONFIRMAÇÃO NECESSÁRIA*\n\n"
                f"O bot encontrou uma oportunidade de operar *{symbol}*\n\n"
                f"Deseja prosseguir com esta operação?\n\n"
                f"Responda utilizando os botões abaixo ou enviando /sim ou /nao",
                parse_mode="Markdown",
                reply_markup=markup
            )
            print(f"Solicitação enviada para o usuário {user_id_str}")
        except Exception as e:
            print(f"ERRO ao enviar solicitação para {user_id_str}: {e}")
    
    # Loop de espera com tempo máximo
    print(f"Aguardando resposta por até {timeout} segundos...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # Imprimir estado atual para debug
        if time.time() - start_time % 10 < 0.5:  # A cada ~10 segundos
            print(f"DEBUG - Estado atual: latest_approval_result={latest_approval_result}, symbol={latest_approval_symbol}")
            print(f"DEBUG - pending_approvals={pending_approvals}")
            print(f"DEBUG - approval_results={approval_results}")
            
        # NOVA ABORDAGEM: Verificar variável global primeiro
        if latest_approval_result is not None and latest_approval_symbol == symbol:
            print(f"✅ Aprovação detectada via variável global: {latest_approval_result}")
            return latest_approval_result
            
        # Verificar todos os usuários
        for user_id_str in list(pending_approvals.keys()):
            if pending_approvals.get(user_id_str) == symbol:
                check_key = f"{user_id_str}_{symbol}"
                
                with approval_lock:
                    if check_key in approval_results:
                        result = approval_results[check_key]
                        print(f"✅ Aprovação encontrada para key: {check_key}, resultado: {result}")
                        
                        # Salvar na variável global para redundância
                        latest_approval_result = result
                        
                        # Limpar pendência
                        pending_approvals[user_id_str] = None
                        
                        # FORÇAR retorno imediato!!
                        return result
        
        # Pausa curta
        time.sleep(0.5)
    
    print(f"⏱️ Tempo esgotado para aprovação de {symbol}")
    return False

def get_approval_results():
    """Função para acessar o dicionário de aprovações de forma segura"""
    with approval_lock:
        # Retornar uma cópia para evitar problemas de concorrência
        return approval_results.copy()

# Iniciar o bot apenas se formos a instância principal
bot_thread = None

def start_bot():
    global bot_thread
    
    print("DEPURANDO start_bot(): Iniciando verificação")
    
    # Verificar se já existe uma thread
    if bot_thread and bot_thread.is_alive():
        print("DEPURANDO start_bot(): Thread já existe e está ativa")
        return False
    
    # Encerrar thread anterior se existir
    if bot_thread:
        try:
            bot_thread.join(timeout=5)
        except:
            pass
    
    print("DEPURANDO start_bot(): Preparando nova thread")
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()
    print("DEPURANDO start_bot(): Thread iniciada")
    return True

def bot_polling():
    if not bot:
        print("ERRO: Nenhum bot para iniciar polling.")
        return
        
    try:
        print("DEPURANDO bot_polling(): Iniciando polling...")
        # Adicionar parâmetros de timeout e retry
        bot.polling(
            none_stop=True, 
            interval=0.5,  # Intervalo entre tentativas
            timeout=30     # Timeout para cada requisição
        )
    except Exception as e:
        print(f"ERRO no polling do bot: {e}")
        import traceback
        traceback.print_exc()
        
        # Tentar reiniciar o bot após erro
        print("Tentando reiniciar o bot em 10 segundos...")
        time.sleep(10)
        start_bot()

# Funções exportadas
__all__ = ['request_trading_approval', 'get_approval_results', 'start_bot']

# Iniciar bot automaticamente ao importar o módulo somente se formos a instância principal
# Iniciar bot automaticamente ao importar o módulo
start_bot()
# Limpar arquivo de lock quando o script for encerrado
def cleanup():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
                
            if pid == os.getpid():
                os.remove(LOCK_FILE)
                print("Arquivo de lock removido.")
        except:
            pass

import atexit
atexit.register(cleanup)

if __name__ == "__main__":
    print("Bot iniciado em modo standalone! Pressione Ctrl+C para encerrar.")
    # Iniciar bot automaticamente ao importar o módulo
if not bot_already_running:
    start_bot()
