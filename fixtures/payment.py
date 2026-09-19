import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from engine.models import Observation

ROOT = Path(__file__).resolve().parents[1]


def db_config():
    return {"host": os.getenv("PGHOST", "127.0.0.1"), "port": int(os.getenv("PGPORT", "55432")),
            "dbname": os.getenv("PGDATABASE", "stateproof"), "user": os.getenv("PGUSER", "stateproof"),
            "password": os.getenv("PGPASSWORD", ""), "connect_timeout": 3}


class PaymentFixture:
    id = "payment-v1"

    def reset(self, schema):
        with psycopg.connect(**db_config(), autocommit=True) as db:
            db.execute(f'CREATE SCHEMA "{schema}"')
            db.execute(f'''CREATE TABLE "{schema}".payments (
                operation_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                amount_minor BIGINT NOT NULL, currency TEXT NOT NULL,
                status TEXT NOT NULL, effect_id TEXT)''')

    def worker_command(self):
        java = str(Path(os.environ["JAVA_HOME"]) / "bin/java") if os.getenv("JAVA_HOME") else "java"
        return [java, "-cp", os.pathsep.join([str(ROOT / "worker/build"), str(ROOT / "worker/lib/*")]), "PaymentWorker"]

    def worker_env(self, schema, provider_url):
        c = db_config()
        return {**os.environ, "JDBC_URL": f'jdbc:postgresql://{c["host"]}:{c["port"]}/{c["dbname"]}?connectTimeout=3&socketTimeout=8',
                "APP_SCHEMA": schema, "PGUSER": c["user"], "PGPASSWORD": c["password"], "PROVIDER_URL": provider_url}

    def application(self, schema):
        with psycopg.connect(**db_config(), row_factory=dict_row) as db:
            return db.execute(f'SELECT * FROM "{schema}".payments ORDER BY operation_id').fetchall()

    def observe(self, schema, ledger):
        return Observation(ledger=ledger, application=self.application(schema), dependenciesHealthy=True)

    def cleanup(self, schema):
        with psycopg.connect(**db_config(), autocommit=True) as db:
            db.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
