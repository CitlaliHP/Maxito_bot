import os
import io
import sqlite3
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
user_files = {}  # {user_id: {"type": "csv"|"sqlite", "data": df|conn}}

MAX_FILAS = 100_000

# --- Utilidades ---
def traducir_a_codigo(prompt: str) -> str:
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
        logger.exception("Error al comunicarse con Groq")
        raise RuntimeError("❌ Hubo un problema al conectarse con la IA.") from e

def limpiar_codigo(codigo: str) -> str:
    codigo = codigo.strip("`").strip()
    if "```python" in codigo:
        codigo = codigo.replace("python", "", 1).strip()
    lineas = [line.strip() for line in codigo.splitlines() if line.strip()]
    return lineas[0] if lineas else ""

def quiere_grafica(pregunta: str) -> bool:
    keywords = ["gráfico", "grafica", "gráfica", "histograma", "barras", "dispersión", "pie", "plot"]
    return any(k in pregunta.lower() for k in keywords)

def resumir_columnas(df: pd.DataFrame) -> str:
    resumen = "Estructura del DataFrame:\n"
    for col in df.columns:
        tipo = df[col].dtype
        resumen += f"- {col} ({tipo})\n"
    return resumen

def resumir_sqlite(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    resumen = "Tablas y columnas en la base de datos:\n"
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tablas = [t[0] for t in cursor.fetchall()]
        for tabla in tablas:
            resumen += f"\n🗃️ {tabla}:\n"
            cursor.execute(f"PRAGMA table_info({tabla})")
            columnas = cursor.fetchall()
            for col in columnas:
                resumen += f"- {col[1]} ({col[2]})\n"
        return resumen
    except Exception as e:
        return f"⚠️ Error al leer estructura de la base de datos: {e}"

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋 Envíame un archivo CSV o SQLite (.db) para comenzar.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    file_name = file.file_name.lower()

    if not (file_name.endswith(".csv") or file_name.endswith(".db")):
        await update.message.reply_text("❌ Solo acepto archivos CSV o SQLite (.db)")
        return

    file_path = f"/tmp/{file.file_name}"
    file_obj = await file.get_file()
    await file_obj.download_to_drive(file_path)

    try:
        if file_name.endswith(".csv"):
            df = pd.read_csv(file_path)
            if len(df) > MAX_FILAS:
                await update.message.reply_text(f"⚠️ El archivo CSV es muy grande. Máximo: {MAX_FILAS} filas.")
                return
            user_files[update.effective_user.id] = {"type": "csv", "data": df}
            await update.message.reply_text("✅ CSV cargado. Ahora hazme una pregunta sobre los datos.")

        elif file_name.endswith(".db"):
            conn = sqlite3.connect(file_path)
            user_files[update.effective_user.id] = {"type": "sqlite", "data": conn}
            await update.message.reply_text("✅ Base de datos SQLite cargada. Ahora hazme una pregunta sobre los datos.")

    except Exception as e:
        logger.exception("Error procesando archivo")
        await update.message.reply_text(f"❌ No se pudo procesar el archivo: {e}")

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_files:
        await update.message.reply_text("📄 Primero debes enviarme un archivo CSV o SQLite.")
        return

    user_file = user_files[user_id]
    tipo = user_file["type"]
    pregunta = update.message.text.strip()

    if len(pregunta) > 400:
        await update.message.reply_text("❌ La pregunta es demasiado larga. Máximo 400 caracteres.")
        return

    es_grafica = quiere_grafica(pregunta)

    if tipo == "csv":
        df = user_file["data"]
        contexto_seguro = {"df": df, "pd": pd, "plt": plt}
        resumen = resumir_columnas(df)

        if es_grafica:
            prompt = f"""
            Tengo un DataFrame llamado `df`. Su estructura es:
            {resumen}

            Genera una sola línea de código Python con pandas o matplotlib que cree un gráfico según esta pregunta:
            "{pregunta}"
            ⚠️ Instrucciones importantes:
                - Usa solo columnas relevantes a la pregunta.
                - Usa `kind='bar'`, `hist()`, `kind='pie'` según el tipo de gráfico.
                - No uses `print()`, ni texto adicional, ni markdown.
                - Usa `df` como nombre del DataFrame.
            """
        else:
            prompt = f"""
                Tengo un DataFrame llamado `df`. Su estructura es la siguiente:
                {resumen}

                Responde solo con una línea de código `pandas` que conteste esta pregunta:

                "{pregunta}"

                Por ejemplo:
                df[df["edad"] > 30]

                No des explicaciones. Solo la expresión que retorne el resultado.
                - No uses `print()`, ni texto adicional, ni markdown.
                - Usa `df` como nombre del DataFrame.
                """

        try:
            codigo = limpiar_codigo(traducir_a_codigo(prompt))
            logger.info(f"Código generado: {codigo}")

            if "df" not in codigo or ";" in codigo:
                print(codigo)
                raise ValueError("❌ Código inseguro generado.")

            if es_grafica:
                plt.figure()
                eval(codigo, contexto_seguro)
                buffer = io.BytesIO()
                plt.savefig(buffer, format="png")
                buffer.seek(0)
                plt.close()
                await update.message.reply_photo(photo=InputFile(buffer, filename="grafica.png"))
            else:
                resultado = eval(codigo, contexto_seguro)
                if isinstance(resultado, pd.DataFrame):
                    mensaje = "📭 Sin resultados." if resultado.empty else resultado.head(10).to_string(index=False)
                else:
                    mensaje = f"🧠 {str(resultado)}"
                await update.message.reply_text(mensaje)

        except Exception as e:
            logger.exception("Error procesando pregunta CSV")
            await update.message.reply_text("⚠️ Error al procesar tu solicitud con el archivo CSV.")

    elif tipo == "sqlite":
        conn = user_file["data"]
        resumen = resumir_sqlite(conn)
        prompt = f"""
            Tengo una base de datos SQLite. Su estructura es la siguiente:
            {resumen}

            Tu tarea es generar una única consulta SQL que responda la siguiente pregunta del usuario:

            "{pregunta}"

            ⚠️ Instrucciones estrictas:
            - Usa solo SQL estándar compatible con SQLite.
            - No incluyas texto, explicaciones, ni formato markdown.
            - No uses comillas invertidas (`) ni bloques de código.
            - Devuelve exclusivamente la instrucción SQL, comenzando con SELECT, INSERT, UPDATE, etc.

            Ejemplo válido:
            SELECT nombre FROM clientes WHERE edad > 30;

            Responde únicamente con la línea de consulta.
            """


        try:
            sql = limpiar_codigo(traducir_a_codigo(prompt))
            logger.info(f"SQL generado: {sql}")
            cursor = conn.cursor()
            cursor.execute(sql)
            filas = cursor.fetchall()
            columnas = [desc[0] for desc in cursor.description] if cursor.description else []

            if not filas:
                await update.message.reply_text("📭 La consulta no devolvió resultados.")
                return

            tabla = pd.DataFrame(filas, columns=columnas)
            mensaje = tabla.head(10).to_string(index=False)
            await update.message.reply_text(mensaje)

        except Exception as e:
            logger.exception("Error procesando pregunta SQLite")
            await update.message.reply_text("⚠️ Error al procesar tu solicitud con la base de datos.")

# --- Main ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    app.run_polling()

if __name__ == "__main__":
    main()
