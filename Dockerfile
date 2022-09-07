FROM ubuntu:22.04

ENV POETRY_VERSION=1.2

RUN apt-get update -y
RUN apt-get install -y python3 python3-pip python3-gdbm
RUN python3 -m pip install poetry==${POETRY_VERSION}


WORKDIR /app
COPY config.toml .
COPY mun-course-auto-check.py .
COPY pyproject.toml .
COPY poetry.lock .

RUN poetry config virtualenvs.in-project true --local
RUN poetry install --without dev
RUN poetry run playwright install chromium --with-deps

CMD ["poetry", "run", "python3", "-u", "mun-course-auto-check.py"]
