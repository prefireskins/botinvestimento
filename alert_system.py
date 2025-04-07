import requests
import os
import platform
import time
import json
from datetime import datetime

# Gerenciamento de configurações de usuários
class UserSettings:
    def __init__(self, settings_file='user_settings.json'):
        self.settings_file = settings_file
        self.settings = self.load_settings()
    
    def init_settings_file(self):
        """Inicializa o arquivo de configurações se não existir"""
        if not os.path.exists(self.settings_file):
            with open(self.settings_file, 'w') as f:
                json.dump({}, f)
    
    def load_settings(self):
        """Carrega as configurações dos usuários"""
        self.init_settings_file()
        with open(self.settings_file, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    
    def save_settings(self):
        """Salva as configurações dos usuários"""
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f)
    
    def get_user_settings(self, user_id):
        """Obtém as configurações de um usuário específico"""
        user_id = str(user_id)  # Converte para string para usar como chave
        
        if user_id not in self.settings:
            # Configurações padrão
            self.settings[user_id] = {
                "condicoes_favoraveis": True,  # Por padrão, recebe notificações
            }
            self.save_settings()
        
        return self.settings[user_id]
    
    def update_user_setting(self, user_id, setting_name, value):
        """Atualiza uma configuração específica de um usuário"""
        user_id = str(user_id)
        
        if user_id not in self.settings:
            self.settings[user_id] = {}
        
        self.settings[user_id][setting_name] = value
        self.save_settings()


# Configurações para o sistema de alertas
class AlertSystem:
    def __init__(self, enable_sound=True, enable_telegram=False, telegram_token=None, telegram_chat_id=None, settings_file='user_settings.json'):
        self.enable_sound = enable_sound
        self.enable_telegram = enable_telegram
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.last_alert_time = 0  # Para evitar spam de alertas
        self.alert_cooldown = 60  # Tempo mínimo entre alertas (segundos)
        
        # Inicializar gerenciamento de configurações de usuários
        self.user_settings = UserSettings(settings_file)

    def play_sound(self):
        """Tocar som de alerta no terminal"""
        if not self.enable_sound:
            return
            
        # Diferente método para diferentes sistemas operacionais
        system = platform.system()
        
        try:
            if system == 'Darwin':  # macOS
                sound_file = '/System/Library/Sounds/Ping.aiff'
                if os.path.exists(sound_file):
                    result = os.system(f'afplay {sound_file}')
                    if result != 0:
                        print("\a")  # Fallback para bipe padrão se o comando falhar
                else:
                    print("\a")  # Fallback se o arquivo não existir
                    
            elif system == 'Linux':
                # Verificar se o comando aplay existe
                if os.system("which aplay > /dev/null 2>&1") == 0:
                    sound_file = '/usr/share/sounds/sound-icons/prompt.wav'
                    if os.path.exists(sound_file):
                        os.system(f'aplay -q {sound_file} &>/dev/null &')
                    else:
                        print("\a")  # Fallback se o arquivo não existir
                else:
                    print("\a")  # Fallback se aplay não estiver disponível
                    
            elif system == 'Windows':
                try:
                    import winsound
                    winsound.Beep(1000, 500)  # Frequência 1000Hz, duração 500ms
                except ImportError:
                    print("\a")  # Fallback se winsound não estiver disponível
            else:
                print("\a")  # Fallback para sistemas não reconhecidos
        except Exception as e:
            print(f"Erro ao reproduzir som: {e}")
            print("\a")  # Fallback para bipe padrão do terminal
            
    def send_telegram(self, message, chat_id=None):
        """Enviar mensagem via Telegram"""
        if not self.enable_telegram or not self.telegram_token:
            return False
            
        # Usar chat_id específico se fornecido, caso contrário usar o padrão
        target_chat_id = chat_id if chat_id else self.telegram_chat_id
        
        if not target_chat_id:
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                "chat_id": target_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except requests.RequestException as e:
            print(f"Erro de requisição ao enviar mensagem para Telegram: {e}")
            return False
        except requests.Timeout:
            print("Timeout ao enviar mensagem para Telegram")
            return False
        except ValueError as e:
            print(f"Erro de valor ao enviar mensagem para Telegram: {e}")
            return False
        except Exception as e:
            print(f"Erro inesperado ao enviar mensagem para Telegram: {e}")
            return False
    
    def user_wants_alerts(self, chat_id):
        """Verifica se o usuário quer receber alertas de condições favoráveis"""
        user_settings = self.user_settings.get_user_settings(chat_id)
        return user_settings.get("condicoes_favoraveis", True)
            
    def send_alert(self, message, alert_type="INFO", chat_id=None):
        """Enviar alerta (som + telegram se configurado)"""
        current_time = time.time()
        
        # Evitar spam de alertas (cooldown)
        if current_time - self.last_alert_time < self.alert_cooldown:
            return
            
        self.last_alert_time = current_time
        
        # Formatar mensagem com timestamp e tipo
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"🚨 ALERTA [{alert_type}] - {timestamp} 🚨\n{message}"
        
        # Exibir no console com destaque
        print("\n" + "=" * 80)
        print(formatted_message)
        print("=" * 80 + "\n")
        
        # Tocar som
        self.play_sound()
        
        # Enviar para Telegram se habilitado
        if self.enable_telegram:
            # Se for um chat específico, verificar configurações do usuário
            if chat_id:
                if alert_type in ["SINAL FORTE", "SINAL POTENCIAL"] and not self.user_wants_alerts(chat_id):
                    # Usuário optou por não receber alertas de condições favoráveis
                    return
                
                self.send_telegram(formatted_message, chat_id)
            else:
                # Envio para o chat_id padrão
                self.send_telegram(formatted_message)

    # Métodos para gerenciar configurações de usuário
    def toggle_condicoes_favoraveis(self, user_id):
        """Alternar configuração de receber alertas de condições favoráveis"""
        user_settings = self.user_settings.get_user_settings(user_id)
        current_value = user_settings.get("condicoes_favoraveis", True)
        
        # Inverter valor atual
        self.user_settings.update_user_setting(user_id, "condicoes_favoraveis", not current_value)
        
        return not current_value  # Retorna o novo valor

    def get_settings_status(self, user_id):
        """Obter status atual das configurações do usuário"""
        user_settings = self.user_settings.get_user_settings(user_id)
        
        # Criar mensagem de status
        condicoes_status = "ATIVADOS" if user_settings.get("condicoes_favoraveis", True) else "DESATIVADOS"
        
        return f"Configurações atuais:\n\n" \
               f"• Alertas de condições favoráveis: {condicoes_status}"


# Adicionando comandos para gerenciar configurações via Telegram

# Exemplo de como implementar comandos para o bot do Telegram
"""
# Para implementar no seu código do bot do Telegram:

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Inicializar bot
bot = TeleBot("SEU_TOKEN_AQUI")

# Inicializar sistema de alertas
alert_system = AlertSystem(
    enable_sound=True,
    enable_telegram=True,
    telegram_token="SEU_TOKEN_AQUI",
    telegram_chat_id=None  # Não definimos um padrão, pois enviaremos para usuários específicos
)

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
    button_text = "🔕 Desativar alertas" if current_status else "🔔 Ativar alertas"
    markup.add(InlineKeyboardButton(button_text, callback_data="toggle_alerts"))
    
    # Enviar mensagem com status atual
    status_message = alert_system.get_settings_status(user_id)
    bot.send_message(user_id, status_message, reply_markup=markup)

# Handler para callbacks dos botões
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id
    
    if call.data == "toggle_alerts":
        # Alternar configuração
        new_status = alert_system.toggle_condicoes_favoraveis(user_id)
        
        # Atualizar mensagem
        status_text = "ATIVADOS" if new_status else "DESATIVADOS"
        bot.answer_callback_query(call.id, f"Alertas {status_text} com sucesso!")
        
        # Enviar menu atualizado
        settings_command(call.message)

# Para integrações avançadas, adicione isso na função que envia alertas:
def verificar_alertas(self, df):
    # ... código existente ...
    
    # Se temos condições favoráveis, enviar alerta
    if len(condicoes) >= 2:  # Pelo menos duas condições favoráveis
        mensagem_alerta += "\n".join(condicoes)
        
        # Determinar tipo de alerta
        if cruzamento and tendencia_alta and rsi_otimo and volume_alto and not proximo_sr:
            alert_type = "SINAL FORTE"
        else:
            alert_type = "SINAL POTENCIAL"
        
        # Enviar para todos os usuários cadastrados
        for user_id in self.alert_system.user_settings.settings:
            # Verificar se este usuário quer receber alertas
            if self.alert_system.user_wants_alerts(user_id):
                self.alert_system.send_alert(mensagem_alerta, alert_type, chat_id=user_id)
"""