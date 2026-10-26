# [A] Một ảnh dùng chung cho api, worker, ui và metrics-job (khác nhau ở `command` trong docker-compose.yml).
# Repo có nhiều package cấp gốc (app, core, ui, ...) nên không cài chính repo bằng pip (setuptools từ chối
# "multiple top-level packages"): chỉ cài phụ thuộc đọc từ pyproject.toml, code chạy từ /srv nhờ PYTHONPATH.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv

WORKDIR /srv

# Lớp phụ thuộc tách riêng: sửa code không phải cài lại thư viện.
COPY pyproject.toml ./
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; open('/tmp/requirements.txt', 'w').write('\n'.join(deps) + '\n')" \
 && pip install -r /tmp/requirements.txt

COPY . .
RUN mkdir -p /srv/data/uploads

EXPOSE 8000 8501
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
