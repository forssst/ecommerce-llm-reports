"""Blok 4 — bezpieczeństwo generowanego SQL (read-only).

System pozwala LLM-owi generować dowolny SQL i wykonuje go na Postgresie. Ten blok
sprawdza, czy próba wygenerowania SQL modyfikującego dane może faktycznie coś zepsuć.
Poprawnie: połączenie do danych powinno być READ-ONLY (osobny użytkownik Postgresa
z prawami tylko SELECT), więc DROP/DELETE/UPDATE się nie wykona.

To test na poziomie WARSTWY DANYCH, nie modelu — nie zależy od tego, co akurat
wygeneruje LLM. Łączymy się TĄ SAMĄ rolą read-only, której backend używa do
wykonywania SQL-a od LLM (_run_and_validate, karty Metabase) i próbujemy DDL.

Naprawione 2026-07-06: backend tworzy rolę 'readonly' przy starcie
(_ensure_readonly_role) i wykonuje nią cały SQL pochodzący od modelu.
"""
import os
import uuid
import pytest

pytestmark = pytest.mark.sql_safety

# Te testy wykonują SQL bezpośrednio na Postgresie przez sterownik backendu.
# Wymagają dostępu do biblioteki psycopg2 i zmiennych PG_* (jak w kontenerze).
psycopg2 = pytest.importorskip("psycopg2")

PG = dict(
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", "5432")),
    dbname=os.getenv("PG_DB", "analytics"),
    # Ta sama rola, którą backend wykonuje SQL wygenerowany przez LLM.
    user=os.getenv("PG_RO_USER", "readonly"),
    password=os.getenv("PG_RO_PASS", "readonly"),
)


def _connect():
    try:
        return psycopg2.connect(**PG)
    except Exception as e:
        pytest.skip(f"Postgres niedostępny z hosta ({e}). Uruchom: "
                    f"PG_HOST=localhost PG_PORT=5432 pytest tests/test_sql_safety.py")


def test_polaczenie_czyta_dane():
    """Kontrola pozytywna — połączenie działa i SELECT przechodzi."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    conn.close()


def test_drop_table_powinien_byc_zablokowany():
    """Próba utworzenia i usunięcia tabeli powinna zostać odrzucona przez uprawnienia
    (read-only role). Jeśli przechodzi — LLM mógłby wygenerować destrukcyjny SQL."""
    conn = _connect()
    conn.autocommit = True
    tname = f"public.evil_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute(f"CREATE TABLE {tname} (x int)")
            cur.execute(f"DROP TABLE {tname}")
    conn.close()
