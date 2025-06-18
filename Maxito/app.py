import os
import pandas as pd
from telegram import Update # type: ignore
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,ContextTypes, filters # type: ignore

from groq import Groq # type: ignore

# 🔐 Claves 
TELEGRAM_BOT_TOKEN = "7857884148:AAH88TAfYOCKjk5ySqhOd0rOccA24_jpQRM"
GROQ_API_KEY = "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"

# Inicializa el cliente Groq
groq_client = Groq(api_key=GROQ_API_KEY)

# Memoria para almacenar CSV por usuario
user_csvs = {}

# Función para preguntar al modelo Groq
def ask_groq_llama4(prompt: str) -> str:
    response = groq_client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_completion_tokens=1024,
        top_p=1,
        stream=False
    )
    return response.choices[0].message.content

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋\nEnvíame un archivo CSV para comenzar.")

# Manejador de archivos CSV
async def handle_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if file.mime_type != 'text/csv':
        await update.message.reply_text("❌ Solo acepto archivos CSV.")
        return

    file_path = f"/tmp/{file.file_name}"
    file_obj = await file.get_file()
    await file_obj.download_to_drive(file_path)

    try:
        df = pd.read_csv(file_path)
        user_csvs[update.effective_user.id] = df
        await update.message.reply_text("✅ CSV recibido. Ahora hazme una pregunta sobre los datos.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error al leer el CSV: {e}")

# Manejador de texto (preguntas)
async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_csvs:
        await update.message.reply_text("📄 Primero debes enviarme un archivo CSV.")
        return

    df = user_csvs[user_id]
    csv_preview = df.head().to_csv(index=False)

    prompt = f"""
Tengo el siguiente archivo CSV:

{csv_preview}

Ahora responde esta pregunta del usuario de forma clara y basada en los datos:

{update.message.text}
"""

    try:
        answer = ask_groq_llama4(prompt)
        await update.message.reply_text(answer)
    except Exception as e:
        await update.message.reply_text(f"❌ Error al consultar Groq: {e}")

# Iniciar el bot
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_csv))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    app.run_polling()

if __name__ == "__main__":
    main()
