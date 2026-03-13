#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import base64
import requests
import logging
import tempfile
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import xml.etree.ElementTree as ET

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '8213746990:AAG-jpTTnok-VWRlMb02J5w2yFmastnhljQ')
ALLOWED_USERS = []  # Lista de IDs de usuarios permitidos, vacío = todos
NUBE_USER = os.environ.get('NUBE_USER', 'marcos.puig')
NUBE_PASS = os.environ.get('NUBE_PASS', 'covid*.202N569e929')
NUBE_URL = os.environ.get('NUBE_URL', 'https://nube.reduc.edu.cu')
WEBDAV_URL = f"{NUBE_URL}/remote.php/webdav"

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NubeREDUCBot:
    def __init__(self):
        self.auth_string = base64.b64encode(f"{NUBE_USER}:{NUBE_PASS}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth_string}",
            "OCS-APIRequest": "true"
        }
        
    def verificar_usuario(self, user_id):
        """Verifica si el usuario está autorizado"""
        if not ALLOWED_USERS:
            return True
        return user_id in ALLOWED_USERS
    
    def crear_directorio(self, path):
        """Crea un directorio en la nube"""
        try:
            response = requests.request(
                "MKCOL",
                f"{WEBDAV_URL}/{path}",
                headers=self.headers,
                timeout=10
            )
            return response.status_code in [201, 204, 405]
        except Exception as e:
            logger.error(f"Error creando directorio: {e}")
            return False
    
    def subir_archivo(self, file_path, remote_path):
        """Sube un archivo a la nube"""
        try:
            with open(file_path, 'rb') as f:
                response = requests.put(
                    f"{WEBDAV_URL}/{remote_path}",
                    data=f,
                    headers=self.headers,
                    timeout=30
                )
            return response.status_code in [201, 204], response.status_code
        except Exception as e:
            logger.error(f"Error subiendo archivo: {e}")
            return False, None
    
    def verificar_archivo(self, remote_path):
        """Verifica si el archivo existe en la nube"""
        try:
            response = requests.request(
                "PROPFIND",
                f"{WEBDAV_URL}/{remote_path}",
                headers=self.headers,
                timeout=10
            )
            return response.status_code == 207
        except Exception as e:
            logger.error(f"Error verificando archivo: {e}")
            return False
    
    def crear_enlace_publico(self, remote_path):
        """Crea un enlace público para el archivo"""
        try:
            data = {
                'path': f"/{remote_path}",
                'shareType': '3',
                'permissions': '1'
            }
            
            response = requests.post(
                f"{NUBE_URL}/ocs/v2.php/apps/files_sharing/api/v1/shares",
                headers={**self.headers, 'Content-Type': 'application/x-www-form-urlencoded'},
                data=data,
                timeout=10
            )
            
            if response.status_code == 200:
                root = ET.fromstring(response.text)
                url_element = root.find('.//url')
                if url_element is not None and url_element.text:
                    return url_element.text
            return None
        except Exception as e:
            logger.error(f"Error creando enlace: {e}")
            return None
    
    def listar_archivos(self, path=""):
        """Lista archivos en un directorio"""
        try:
            response = requests.request(
                "PROPFIND",
                f"{WEBDAV_URL}/{path}",
                headers={**self.headers, 'Depth': '1'},
                timeout=10
            )
            
            if response.status_code == 207:
                root = ET.fromstring(response.text)
                files = []
                for response_elem in root.findall('.//{DAV:}response'):
                    href = response_elem.find('.//{DAV:}href')
                    if href is not None and href.text != f"/remote.php/webdav/{path}":
                        name = href.text.split('/')[-2] if href.text.endswith('/') else href.text.split('/')[-1]
                        if name:
                            files.append(name)
                return files
            return []
        except Exception as e:
            logger.error(f"Error listando archivos: {e}")
            return []

# Inicializar bot
nube_bot = NubeREDUCBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    
    if not nube_bot.verificar_usuario(user.id):
        await update.message.reply_text("❌ No estás autorizado para usar este bot.")
        return
    
    welcome_msg = (
        f"👋 ¡Hola {user.first_name}!\n\n"
        "Soy el bot de subida a Nube REDUC.\n\n"
        "📤 **Comandos disponibles:**\n"
        "/start - Mostrar este mensaje\n"
        "/help - Ayuda detallada\n"
        "/list - Listar archivos en test_files\n"
        "/status - Ver estado del servicio\n\n"
        "**Para subir un archivo:**\n"
        "Simplemente envíame cualquier archivo y lo subiré automáticamente a la carpeta 'test_files' en la nube."
    )
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    help_msg = (
        "📚 **Ayuda del Bot**\n\n"
        "**Funcionalidades:**\n"
        "• Subir archivos a Nube REDUC\n"
        "• Crear enlaces públicos automáticamente\n"
        "• Verificar estado de subidas\n\n"
        "**Cómo usar:**\n"
        "1. Envía cualquier archivo (foto, documento, etc.)\n"
        "2. El bot lo subirá a la carpeta 'test_files'\n"
        "3. Recibirás un enlace público para compartir\n\n"
        "**Límites:**\n"
        "• Tamaño máximo: Depende de Telegram (50MB para bots)\n"
        "• Formatos soportados: Todos\n\n"
        "**Comandos:**\n"
        "/list - Ver archivos en la nube\n"
        "/status - Verificar conexión"
    )
    
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /status - Verifica el estado del servicio"""
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    status_msg = "🔍 **Verificando estado...**\n\n"
    await update.message.reply_text(status_msg, parse_mode='Markdown')
    
    try:
        if nube_bot.crear_directorio("test_files"):
            status_msg += "✅ Conexión con Nube REDUC: **OK**\n"
            status_msg += f"✅ Usuario: `{NUBE_USER}`\n"
            
            test_content = f"Test file from Telegram bot at {datetime.now()}"
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(test_content)
                test_file = f.name
            
            success, code = nube_bot.subir_archivo(test_file, "test_files/bot_test.txt")
            os.unlink(test_file)
            
            if success:
                status_msg += "✅ Prueba de escritura: **OK**\n"
            else:
                status_msg += f"❌ Prueba de escritura: Falló (HTTP {code})\n"
        else:
            status_msg += "❌ No se pudo conectar a la nube\n"
            
    except Exception as e:
        status_msg += f"❌ Error: {str(e)}\n"
    
    status_msg += f"\n🕐 Última verificación: {datetime.now().strftime('%H:%M:%S')}"
    
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /list - Lista archivos en test_files"""
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    await update.message.reply_text("📂 **Obteniendo lista de archivos...**", parse_mode='Markdown')
    
    files = nube_bot.listar_archivos("test_files")
    
    if files:
        msg = "📁 **Archivos en test_files:**\n\n"
        for i, file in enumerate(files, 1):
            msg += f"{i}. `{file}`\n"
    else:
        msg = "📁 La carpeta 'test_files' está vacía o no existe."
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la recepción de documentos"""
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    document = update.message.document
    
    msg = await update.message.reply_text(
        f"📥 **Recibido archivo:** `{document.file_name}`\n"
        f"📦 Tamaño: {document.file_size / 1024:.1f} KB\n\n"
        f"🔄 Subiendo a Nube REDUC...",
        parse_mode='Markdown'
    )
    
    try:
        file = await context.bot.get_file(document.file_id)
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            await file.download_to_drive(tmp_file.name)
            local_path = tmp_file.name
        
        timestamp = int(time.time())
        remote_filename = f"{timestamp}_{document.file_name}"
        remote_path = f"test_files/{remote_filename}"
        
        nube_bot.crear_directorio("test_files")
        success, status_code = nube_bot.subir_archivo(local_path, remote_path)
        
        if success:
            if nube_bot.verificar_archivo(remote_path):
                share_url = nube_bot.crear_enlace_publico(remote_path)
                
                success_msg = (
                    f"✅ **Archivo subido exitosamente!**\n\n"
                    f"📄 **Nombre:** `{document.file_name}`\n"
                    f"📦 **Tamaño:** {document.file_size / 1024:.1f} KB\n"
                )
                
                if share_url:
                    success_msg += f"\n🔗 **Enlace público:**\n{share_url}"
                else:
                    success_msg += f"\n⚠️ No se pudo crear enlace público"
                
                keyboard = [
                    [InlineKeyboardButton("📂 Ver en navegador", url=f"{NUBE_URL}/index.php/apps/files/files/1985220?dir=/test_files")],
                ]
                if share_url:
                    keyboard.append([InlineKeyboardButton("🔗 Compartir enlace", url=share_url)])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await msg.edit_text(success_msg, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                await msg.edit_text("⚠️ Archivo subido pero no se pudo verificar en la nube.")
        else:
            error_msg = f"❌ **Error al subir el archivo**\n"
            if status_code:
                error_msg += f"Código HTTP: {status_code}"
            else:
                error_msg += "No se pudo conectar con el servidor"
            
            await msg.edit_text(error_msg, parse_mode='Markdown')
        
        os.unlink(local_path)
        
    except Exception as e:
        logger.error(f"Error procesando archivo: {e}")
        await msg.edit_text(f"❌ Error inesperado: {str(e)[:100]}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la recepción de fotos"""
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    photo = update.message.photo[-1]
    
    msg = await update.message.reply_text(
        f"📸 **Foto recibida**\n"
        f"📦 Tamaño: {photo.file_size / 1024:.1f} KB\n\n"
        f"🔄 Subiendo a Nube REDUC...",
        parse_mode='Markdown'
    )
    
    try:
        file = await context.bot.get_file(photo.file_id)
        
        timestamp = int(time.time())
        filename = f"photo_{timestamp}.jpg"
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            await file.download_to_drive(tmp_file.name)
            local_path = tmp_file.name
        
        remote_path = f"test_files/{filename}"
        
        nube_bot.crear_directorio("test_files")
        success, status_code = nube_bot.subir_archivo(local_path, remote_path)
        
        if success:
            share_url = nube_bot.crear_enlace_publico(remote_path)
            
            success_msg = (
                f"✅ **Foto subida exitosamente!**\n\n"
                f"📸 **Nombre:** `{filename}`\n"
                f"📦 **Tamaño:** {photo.file_size / 1024:.1f} KB\n"
            )
            
            if share_url:
                success_msg += f"\n🔗 **Enlace público:**\n{share_url}"
            
            await msg.edit_text(success_msg, parse_mode='Markdown')
        else:
            await msg.edit_text(f"❌ Error al subir la foto (HTTP {status_code})")
        
        os.unlink(local_path)
        
    except Exception as e:
        logger.error(f"Error procesando foto: {e}")
        await msg.edit_text(f"❌ Error inesperado: {str(e)[:100]}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja errores"""
    logger.error(f"Error en update {update}: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Ocurrió un error inesperado. Por favor, intenta de nuevo."
        )

async def webhook_health_check(request):
    """Endpoint para health check de Render"""
    return "OK"

def main():
    """Función principal"""
    # Para Render, necesitamos un pequeño servidor web
    if 'RENDER' in os.environ:
        from flask import Flask, request
        import threading
        
        app = Flask(__name__)
        
        @app.route('/')
        def health_check():
            return "Bot de Nube REDUC está funcionando!", 200
        
        @app.route('/healthz')
        def healthz():
            return "OK", 200
        
        # Iniciar Flask en un hilo separado
        def run_flask():
            app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
        
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
    
    # Crear aplicación de Telegram
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Añadir manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_error_handler(error_handler)
    
    # Información de inicio
    print("=" * 50)
    print("Bot de Nube REDUC iniciado")
    print(f"Token: {TELEGRAM_TOKEN[:10]}...")
    print(f"Usuario: {NUBE_USER}")
    print(f"URL: {NUBE_URL}")
    if 'RENDER' in os.environ:
        print(f"Render PORT: {os.environ.get('PORT', '10000')}")
    print("=" * 50)
    
    # Iniciar bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
