set -e
apt-get update -qq && apt-get install -y -qq --no-install-recommends libpq-dev gcc >/dev/null
cd /repo/backend
pip install --upgrade pip -q
pip install -e '.[dev]' -q
export DJANGO_SETTINGS_MODULE=config.settings
export SECRET_KEY=ci-test-secret-key
export DEBUG=False
export SECURE_SSL_REDIRECT=False
export ALLOWED_HOSTS=localhost,127.0.0.1
export DATABASE_URL=postgres://postgres:postgres@db:5432/supportpilot
export REDIS_URL=redis://redis:6379/0
export CACHE_URL=redis://redis:6379/1
export OBSERVABILITY_METRICS_TOKEN=ci-test-metrics-token
python -m pytest --cov --cov-report=term-missing -q > /tmp/ci_suite_result.log 2>&1
echo "PYTEST_EXIT:$?"
tail -600 /tmp/ci_suite_result.log
