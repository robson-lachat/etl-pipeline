# Estágio 1: Builder para gerenciar o Poetry
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Instala o Poetry
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Copia os arquivos de dependência
COPY pyproject.toml poetry.lock ./

# Instala as dependências (apenas as necessárias para rodar)
RUN poetry install --no-root --only main

# Estágio 2: Runner (Imagem final, leve e sem Poetry)
FROM python:3.12-slim AS runner

WORKDIR /app

# 1. Injeta o ambiente virtual no PATH
ENV PATH="/app/.venv/bin:$PATH"

# 2. CORREÇÃO: Informa ao Python onde encontrar o módulo "etl_pipeline"
ENV PYTHONPATH="/app/src"

# Copia o ambiente virtual compilado no Estágio 1
COPY --from=builder /app/.venv /app/.venv

# Copia a pasta de código e o arquivo de variáveis de ambiente
COPY src/ ./src
COPY .env ./

# Executa o script
CMD ["python", "-m", "etl_pipeline.main"]