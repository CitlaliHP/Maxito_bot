import os
import pandas as pd
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Tu token de Telegram y API Key de Groq
TELEGRAM_BOT_TOKEN = "TU_TOKEN_TELEGRAM"
GROQ_API_KEY = "TU_API_KEY_GROQ"
GROQ_MODEL = "llama3-70b-8192"  # o mixtral-8x7b-32768

# Diccionario para almacenar CSV por usuario
user_csvs = {}

# Función para enviar prompt al modelo de Groq
def ask_groq(prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Responde preguntas basadas en datos CSV de manera precisa."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    response = requests.post(url, headers=headers, json=payload)
    return response.json()['choices'][0]['message']['content']

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola, envíame un archivo CSV para comenzar.")

# Manejar CSV
async def handle_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if file.mime_type == 'text/csv':
        file_path = f"/tmp/{file.file_name}"
        file_obj = await file.get_file()
        await file_obj.download_to_drive(file_path)

        df = pd.read_csv(file_path)
        user_csvs[update.effective_user.id] = df
        await update.message.reply_text("CSV cargado. Ahora puedes hacer preguntas.")
    else:
        await update.message.reply_text("Por favor, envía un archivo en formato CSV.")

# Manejar preguntas del usuario
async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_csvs:
        await update.message.reply_text("Primero envía un archivo CSV.")
        return

    df = user_csvs[user_id]
    csv_text = df.head(30).to_csv(index=False)  # Limita para evitar tokens excesivos

    prompt = f"""Este es el contenido de un archivo CSV:

{csv_text}

Con base en este CSV, responde la siguiente pregunta del usuario:
{update.message.text}
"""

    try:
        answer = ask_groq(prompt)
        await update.message.reply_text(answer)
    except Exception as e:
        await update.message.reply_text("Ocurrió un error al consultar Groq.")

# Iniciar la aplicación
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_csv))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    app.run_polling()

if __name__ == "__main__":
    main()