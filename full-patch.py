import os
import sys

def patch_bot_file():
    # Arquivo a ser modificado
    file_path = 'binance_scalping_bot.py'
    
    # Verificar se o arquivo existe
    if not os.path.exists(file_path):
        print(f"Erro: Arquivo {file_path} não encontrado.")
        return False
    
    # Ler o conteúdo do arquivo
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Procurar e substituir o código problemático
    old_code = """            # Verificar configurações de cada usuário antes de enviar
            for user_id in self.alerts.user_settings.settings:
                # Verificar se este usuário quer receber alertas de condições favoráveis
                if self.alerts.user_wants_alerts(user_id):
                    # Enviar alerta para este usuário específico
                    self.alerts.send_telegram(mensagem, chat_id=user_id)"""
    
    new_code = """            # Verificar configurações de cada usuário antes de enviar
            for user_id in self.alert_system.user_settings.settings:
                # Verificar se este usuário quer receber alertas de condições favoráveis
                if self.alert_system.user_wants_alerts(user_id):
                    # Enviar alerta para este usuário específico
                    self.alert_system.send_telegram(mensagem, chat_id=user_id)"""
    
    # Verificar se o código problemático foi encontrado
    if old_code not in content:
        print("Aviso: Não foi possível encontrar o código exato para substituição.")
        print("Tentando método alternativo de substituição...")
        
        # Método alternativo - substituir apenas as referências a "self.alerts"
        content = content.replace("self.alerts.user_settings", "self.alert_system.user_settings")
        content = content.replace("self.alerts.user_wants_alerts", "self.alert_system.user_wants_alerts")
        content = content.replace("self.alerts.send_telegram", "self.alert_system.send_telegram")
    else:
        # Substituir o código problemático
        content = content.replace(old_code, new_code)
    
    # Criar cópia de backup do arquivo original
    backup_path = file_path + '.bak'
    with open(backup_path, 'w', encoding='utf-8') as file:
        with open(file_path, 'r', encoding='utf-8') as original:
            file.write(original.read())
    
    print(f"Backup criado em {backup_path}")
    
    # Escrever o conteúdo modificado de volta ao arquivo
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)
    
    print(f"Arquivo {file_path} atualizado com sucesso!")
    return True

if __name__ == "__main__":
    print("Aplicando patch para corrigir o bug do bot Binance...")
    if patch_bot_file():
        print("Patch aplicado com sucesso! Você pode executar o bot novamente.")
    else:
        print("Falha ao aplicar o patch. Verifique o arquivo e tente novamente.")