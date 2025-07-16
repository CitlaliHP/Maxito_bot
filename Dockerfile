FROM python:3.11-slim

WORKDIR /app

# Copia el código y el requirements.txt
COPY Maxito/ .

# Copia el archivo .env al contenedor 
COPY .env .env

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

CMD ["python", "app.py"]
