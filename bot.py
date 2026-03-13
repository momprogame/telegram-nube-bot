#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import base64
import requests
import logging
import tempfile
import time
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import xml.etree.ElementTree as ET

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '8213746990:AAG-jpTTnok-VWRlMb02J5w2yFmastnhljQ')
ALLOWED_USERS = []  # Vacío = todos pueden usar
NUBE_USER = os.environ.get('NUBE_USER', 'marcos.puig')
NUBE_PASS = os.environ.get('NUBE_PASS', 'covid*.202N569e929')
NUBE_URL = os.environ.get('NUBE_URL', 'https://nube.reduc.edu.cu')
WEBDAV_URL = f"{NUBE_URL}/remote.php/webdav"

# Configurar logging para Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Función para probar conexión a Nube REDUC
def test_nube_connection():
    """Prueba la conexión a Nube REDUC"""
    try:
        logger.info("🔄 Probando conexión a Nube REDUC...")
        
        # Test 1: DNS resolution
        import socket
        try:
            hostname = NUBE_URL.replace('https://', '').replace('http://', '').split('/')[0]
            ip = socket.gethostbyname(hostname)
            logger.info(f"✅ DNS: {hostname} -> {ip}")
        except Exception as e:
            logger.error(f"❌ DNS Error: {e}")
            return False
        
        # Test 2: HTTP connection
        try:
            response = requests.get(NUBE_URL, timeout=10, verify=True)
            logger.info(f"✅ HTTP: Status {response.status_code}")
        except requests.exceptions.SSLError as e:
            logger.error(f"❌ SSL Error: {e}")
            logger.info("Intentando sin verificar SSL...")
            response = requests.get(NUBE_URL, timeout=10, verify=False)
            logger.info(f"✅ HTTP (sin SSL): Status {response.status_code}")
        except Exception as e:
            logger.error(f"❌ HTTP Error: {e}")
            return False
        
        # Test 3: WebDAV authentication
        auth_string = base64.b64encode(f"{NUBE_USER}:{NUBE_PASS}".encode()).decode()
        headers = {"Authorization": f"Basic {auth_string}"}
        
        try:
            response = requests.request(
                "PROPFIND",
                f"{WEBDAV_URL}/",
                headers=headers,
                timeout=10,
                verify=False
            )
            if response.status_code in [207, 401, 403]:
                logger.info(f"✅ WebDAV: Status {response.status_code}")
                if response.status_code == 401:
                    logger.error("❌ Autenticación fallida - Credenciales incorrectas")
                    return False
                return True
            else:
                logger.error(f"❌ WebDAV: Status inesperado {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ WebDAV Error: {e}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error general: {e}")
        return False

class NubeREDUCBot:
    def __init__(self):
        self.auth_string = base64.b64encode(f"{NUBE_USER}:{NUBE_PASS}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth_string}",
            "OCS-APIRequest": "true"
        }
        # Session con retry
        self.session = requests.Session()
        self.session.verify = False  # Temporal, solo para debug
        
    def verificar_usuario(self, user_id):
        if not ALLOWED_USERS:
            return True
        return user_id in ALLOWED_USERS
    
    def crear_directorio(self, path):
        try:
            response = self.session.request(
                "MKCOL", f"{WEBDAV_URL}/{path}",
                headers=self.headers, timeout=15
            )
            return response.status_code in [201, 204, 405]
        except Exception as e:
            logger.error(f"Error creando directorio: {e}")
            return False
    
    def subir_archivo(self, file_path, remote_path):
        try:
            with open(file_path, 'rb') as f:
                response = self.session.put(
                    f"{WEBDAV_URL}/{remote_path}",
                    data=f, headers=self.headers, timeout=45
                )
            return response.status_code in [201, 204], response.status_code
        except Exception as e:
            logger.error(f"Error subiendo archivo: {e}")
            return False, None
    
    def verificar_archivo(self, remote_path):
        try:
            response = self.session.request(
                "PROPFIND", f"{WEBDAV_URL}/{remote_path}",
                headers=self.headers, timeout=15
            )
            return response.status_code == 207
        except Exception as e:
            logger.error(f"Error verificando: {e}")
            return False
    
    def crear_enlace_publico(self, remote_path):
        try:
            data = {
                'path': f"/{remote_path}",
                'shareType': '3',
                'permissions': '1'
            }
            response = self.session.post(
                f"{NUBE_URL}/ocs/v2.php/apps/files_sharing/api/v1/shares",
                headers={**self.headers, 'Content-Type': 'application/x-www-form-urlencoded'},
                data=data, timeout=15
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
        try:
            response = self.session.request(
                "PROPFIND", f"{WEBDAV_URL}/{path}",
                headers={**self.headers, 'Depth': '1'}, timeout=15
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
            logger.error(f"Error listando: {e}")
            return []

# Inicializar bot
nube_bot = NubeREDUCBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not nube_bot.verificar_usuario(user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    welcome_msg = (
        f"👋 ¡Hola {user.first_name}!\n\n"
        "Soy el bot de subida a Nube REDUC.\n\n"
        "📤 **Comandos:**\n"
        "/start - Este mensaje\n"
        "/help - Ayuda\n"
        "/list - Listar archivos\n"
        "/status - Ver estado\n"
        "/test - Probar conexión\n\n"
        "**Para subir:** Envíame cualquier archivo"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    help_msg = (
        "📚 **Ayuda**\n\n"
        "**Cómo usar:**\n"
        "1. Envía cualquier archivo\n"
        "2. El bot lo subirá a 'test_files'\n"
        "3. Recibirás un enlace público\n\n"
        "**Límites:** 50MB máximo\n\n"
        "**Comandos de diagnóstico:**\n"
        "/status - Estado general\n"
        "/test - Probar conexión detallada"
    )
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para probar conexión detallada"""
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    msg = await update.message.reply_text("🔍 **Ejecutando diagnóstico...**", parse_mode='Markdown')
    
    results = []
    
    # Test 1: Conexión a Internet
    try:
        r = requests.get("https://www.google.com", timeout=5)
        results.append("✅ Internet: Conectado")
    except:
        results.append("❌ Internet: Sin conexión")
    
    # Test 2: DNS de Nube REDUC
    try:
        import socket
        hostname = NUBE_URL.replace('https://', '').replace('http://', '').split('/')[0]
        ip = socket.gethostbyname(hostname)
        results.append(f"✅ DNS: {hostname} -> {ip}")
    except:
        results.append(f"❌ DNS: No se pudo resolver {hostname}")
    
    # Test 3: Conexión HTTP
    try:
        r = requests.get(NUBE_URL, timeout=5)
        results.append(f"✅ HTTP: {r.status_code}")
    except Exception as e:
        results.append(f"❌ HTTP: {str(e)[:50]}")
    
    # Test 4: Autenticación
    try:
        auth = base64.b64encode(f"{NUBE_USER}:{NUBE_PASS}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}
        r = requests.request("PROPFIND", f"{WEBDAV_URL}/", headers=headers, timeout=5)
        if r.status_code == 207:
            results.append("✅ WebDAV: Autenticación OK")
        elif r.status_code == 401:
            results.append("❌ WebDAV: Credenciales incorrectas")
        else:
            results.append(f"❌ WebDAV: Status {r.status_code}")
    except Exception as e:
        results.append(f"❌ WebDAV: {str(e)[:50]}")
    
    response = "📊 **Resultados del diagnóstico:**\n\n" + "\n".join(results)
    await msg.edit_text(response, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    status_msg = "🔍 **Verificando estado...**\n\n"
    msg = await update.message.reply_text(status_msg, parse_mode='Markdown')
    
    try:
        if nube_bot.crear_directorio("test_files"):
            status_msg += "✅ Conexión Nube REDUC: **OK**\n"
            status_msg += f"✅ Usuario: `{NUBE_USER}`\n"
            status_msg += f"✅ URL: `{NUBE_URL}`\n"
            
            # Prueba de escritura
            try:
                test_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
                test_file.write(f"Test at {datetime.now()}")
                test_file.close()
                
                success, code = nube_bot.subir_archivo(test_file.name, "test_files/bot_test.txt")
                os.unlink(test_file.name)
                
                if success:
                    status_msg += "✅ Escritura: **OK**\n"
                else:
                    status_msg += f"❌ Escritura: Falló (HTTP {code})\n"
            except Exception as e:
                status_msg += f"❌ Escritura: {str(e)[:50]}\n"
        else:
            status_msg += "❌ No se pudo conectar a la nube\n"
    except Exception as e:
        status_msg += f"❌ Error: {str(e)[:100]}\n"
    
    status_msg += f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    await msg.edit_text(status_msg, parse_mode='Markdown')

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    msg = await update.message.reply_text("📂 **Obteniendo lista...**", parse_mode='Markdown')
    
    try:
        files = nube_bot.listar_archivos("test_files")
        
        if files:
            file_list = "📁 **Archivos en test_files:**\n\n"
            for i, file in enumerate(files, 1):
                file_list += f"{i}. `{file}`\n"
        else:
            file_list = "📁 La carpeta 'test_files' está vacía o no existe."
        
        await msg.edit_text(file_list, parse_mode='Markdown')
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    document = update.message.document
    
    # Verificar tamaño (45MB para dejar margen)
    if document.file_size > 45 * 1024 * 1024:
        await update.message.reply_text("❌ El archivo es demasiado grande (máximo 45MB)")
        return
    
    msg = await update.message.reply_text(
        f"📥 **Recibido:** `{document.file_name}`\n"
        f"📦 {document.file_size/1024:.1f} KB\n\n🔄 Subiendo...",
        parse_mode='Markdown'
    )
    
    try:
        file = await context.bot.get_file(document.file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            local_path = tmp.name
        
        timestamp = int(time.time())
        remote_filename = f"{timestamp}_{document.file_name}"
        remote_path = f"test_files/{remote_filename}"
        
        nube_bot.crear_directorio("test_files")
        success, status_code = nube_bot.subir_archivo(local_path, remote_path)
        
        if success:
            share_url = nube_bot.crear_enlace_publico(remote_path)
            success_msg = (
                f"✅ **¡Archivo subido!**\n\n"
                f"📄 **Nombre:** `{document.file_name}`\n"
                f"📦 **Tamaño:** {document.file_size/1024:.1f} KB\n"
            )
            if share_url:
                success_msg += f"\n🔗 **Enlace:**\n{share_url}"
            
            # Crear botones
            keyboard = []
            if share_url:
                keyboard.append([InlineKeyboardButton("🔗 Abrir enlace", url=share_url)])
            keyboard.append([InlineKeyboardButton("📂 Ver carpeta", 
                            url=f"{NUBE_URL}/index.php/apps/files?dir=/test_files")])
            
            await msg.edit_text(
                success_msg, 
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
        else:
            await msg.edit_text(f"❌ Error al subir (HTTP {status_code})")
        
        os.unlink(local_path)
    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not nube_bot.verificar_usuario(update.effective_user.id):
        await update.message.reply_text("❌ No autorizado.")
        return
    
    photo = update.message.photo[-1]
    msg = await update.message.reply_text(
        f"📸 **Foto**\n📦 {photo.file_size/1024:.1f} KB\n\n🔄 Subiendo...",
        parse_mode='Markdown'
    )
    
    try:
        file = await context.bot.get_file(photo.file_id)
        timestamp = int(time.time())
        filename = f"photo_{timestamp}.jpg"
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            local_path = tmp.name
        
        nube_bot.crear_directorio("test_files")
        success, status_code = nube_bot.subir_archivo(local_path, f"test_files/{filename}")
        
        if success:
            share_url = nube_bot.crear_enlace_publico(f"test_files/{filename}")
            success_msg = (
                f"✅ **¡Foto subida!**\n\n"
                f"📸 **Nombre:** `{filename}`\n"
                f"📦 **Tamaño:** {photo.file_size/1024:.1f} KB\n"
            )
            if share_url:
                success_msg += f"\n🔗 **Enlace:**\n{share_url}"
            
            await msg.edit_text(success_msg, parse_mode='Markdown')
        else:
            await msg.edit_text(f"❌ Error al subir (HTTP {status_code})")
        
        os.unlink(local_path)
    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")

def main():
    print("=" * 60)
    print("Bot de Nube REDUC - Iniciando...")
    print("=" * 60)
    print(f"Token: {TELEGRAM_TOKEN[:10]}...")
    print(f"Usuario: {NUBE_USER}")
    print(f"URL: {NUBE_URL}")
    print("=" * 60)
    
    # Probar conexión a Nube REDUC al inicio
    if test_nube_connection():
        print("✅ Conexión a Nube REDUC: OK")
    else:
        print("❌ Conexión a Nube REDUC: FALLÓ")
        print("   El bot seguirá funcionando pero puede haber problemas")
    
    print("=" * 60)
    print("🚀 Iniciando bot de Telegram...")
    
    try:
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("list", list_command))
        application.add_handler(CommandHandler("test", test_command))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        print("✅ Bot configurado correctamente")
        print("📡 Esperando mensajes...")
        print("=" * 60)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
