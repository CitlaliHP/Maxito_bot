import os
import io
import logging
import pandas as pd
import matplotlib.pyplot as plt
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔐 Claves
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Cliente Groq
groq_client = Groq(api_key=GROQ_API_KEY)

# Memoria por usuario
user_csvs = {}


# Limite de filas permitidas
MAX_FILAS = 100_000

# 🧠 Preguntar a Groq para obtener código pandas

def traducir_a_pandas(prompt: str) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_completion_tokens=256,
            top_p=1,
            stream=False
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.exception("Error al comunicarse con Groq")
        raise RuntimeError("❌ Hubo un problema al conectarse con la IA. Intenta de nuevo.") from e


# 📊 Resumen de estructura para dar contexto a la IA

def resumir_columnas(df: pd.DataFrame) -> str:
    resumen = "Estructura del DataFrame:\n"
    for col in df.columns:
        tipo = df[col].dtype
        resumen += f"- {col} ({tipo})\n"
    return resumen

# 🧹 Limpiar código

def limpiar_codigo(codigo: str) -> str:
    codigo = codigo.strip("`").strip()
    if "```python" in codigo:
        codigo = codigo.replace("python", "", 1).strip()
    lineas = [line.strip() for line in codigo.splitlines() if line.strip()]
    return lineas[0] if lineas else ""

# 🎯 Detectar si es una gráfica

def quiere_grafica(pregunta: str) -> bool:
    keywords = ["gráfico", "grafica", "gráfica", "histograma", "barras", "dispersión", "pie", "plot"]
    return any(k in pregunta.lower() for k in keywords)

# 🚀 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋 Envíame un archivo CSV para comenzar.")

# 📎 Recibir archivo CSV
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
        if len(df) > MAX_FILAS:
            await update.message.reply_text(f"⚠️ El archivo es demasiado grande. Máximo permitido: {MAX_FILAS} filas.")
            return
        """
        user_csvs[update.effective_user.id] = {
            'df': df,
            'timestamp': time.time()
        }"""
        user_csvs[update.effective_user.id] = df
        await update.message.reply_text("✅ CSV recibido. Ahora hazme una pregunta sobre los datos.")
    except pd.errors.EmptyDataError:
        await update.message.reply_text("⚠️ El archivo CSV está vacío.")
    except pd.errors.ParserError:
        await update.message.reply_text("⚠️ El archivo no tiene un formato CSV válido.")
    except Exception as e:
        logging.exception("Error leyendo el CSV")
        await update.message.reply_text(f"⚠️ Error inesperado al leer el CSV: {e}")
   

# 🧠 Manejador de preguntas
async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_csvs:
        await update.message.reply_text("📄 Primero debes enviarme un archivo CSV.")
        return

    df = user_csvs[user_id]
    columnas = resumir_columnas(df)
    pregunta = update.message.text.strip()

    if len(pregunta) > 400:
        await update.message.reply_text("❌ La pregunta es demasiado larga. Máximo 400 caracteres.")
        return
    es_grafica = quiere_grafica(pregunta)

    if es_grafica:
        prompt = f"""
        Tengo un DataFrame llamado `df`. Su estructura es la siguiente:
        {columnas}

        Genera una sola línea de código Python que use pandas o matplotlib para crear un gráfico, siguiendo exactamente la instrucción del usuario:

        "{pregunta}"

        ⚠️ Instrucciones importantes:
        - Usa solo columnas relevantes a la pregunta.
        - Usa `kind='bar'`, `hist()`, `kind='pie'` según el tipo de gráfico.
        - No uses `print()`, ni texto adicional, ni markdown.
        - Usa `df` como nombre del DataFrame.

        Solo responde con la línea de código. Nada más.
        """
    else:
        prompt = f"""
        Tengo un DataFrame llamado `df`. Su estructura es la siguiente:
        {columnas}

        Responde solo con una línea de código `pandas` que conteste esta pregunta:

        "{pregunta}"

        Por ejemplo:
        df[df["edad"] > 30]

        No des explicaciones. Solo la expresión que retorne el resultado.
        - No uses `print()`, ni texto adicional, ni markdown.
        - Usa `df` como nombre del DataFrame.
        """

    try:
        codigo = traducir_a_pandas(prompt)
        codigo = limpiar_codigo(codigo)

        logger.info(f"Código generado: {codigo}")

        if "df" not in codigo or ";" in codigo:
            raise ValueError("❌ Código inseguro o inválido generado.")

        contexto_seguro = {"df": df, "pd": pd, "plt": plt}

        if es_grafica:
            try:
                eval(codigo, contexto_seguro)
            except Exception as eval_error:
                raise RuntimeError(f"⚠️ No se pudo generar el gráfico: {eval_error}")
            buffer = io.BytesIO()
            plt.savefig(buffer, format="png")
            buffer.seek(0)
            plt.close()
            await update.message.reply_photo(photo=InputFile(buffer, filename="grafica.png"))
        else:
            try:
                resultado = eval(codigo, contexto_seguro)
            except Exception as eval_error:
                raise RuntimeError(f"⚠️ No se pudo ejecutar el código generado: {eval_error}")

            if isinstance(resultado, pd.DataFrame):
                mensaje = "📭 No se encontraron resultados." if resultado.empty else resultado.head(10).to_string(index=False)
            else:
                mensaje = f"🧠 {str(resultado)}"

            await update.message.reply_text(mensaje)

    except Exception as e:
        logger.error("Error durante el manejo de la pregunta", exc_info=True)
        await update.message.reply_text(f"⚠️ Ocurrió un error al procesar tu solicitud")

# ▶️ Iniciar el bot
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_csv))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    app.run_polling()

if __name__ == "__main__":
    main()
