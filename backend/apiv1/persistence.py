"""File-backed persistence for the in-memory (mongomock) database.

In production the app stores domain data in MongoDB. On a machine without a Mongo
server we use an in-memory database, which is normally lost on restart. Setting
``PERSIST_DB=1`` keeps that same in-memory database but **saves every change to a
file on disk** and **reloads it on startup** — so a business's keys, deliveries,
wallet, events and saved addresses are still there after the server restarts, and
entering the same business name brings its whole history back.

Everything is stored with ``pickle`` so dates and ids survive round-trips exactly.
Writes go to a temp file and are atomically renamed, so a crash mid-write can't
corrupt the data.
"""
import os
import pickle

_PATH = os.environ.get(
    "PERSIST_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".aerrand-data.pkl"),
)


def path():
    return _PATH


def load_into(database):
    """Load saved documents from disk into a fresh database. Safe if no file yet."""
    if not os.path.exists(_PATH):
        return
    try:
        with open(_PATH, "rb") as f:
            data = pickle.load(f)
    except Exception:  # noqa: BLE001 — a corrupt/old file just starts empty
        return
    for name, docs in (data or {}).items():
        if docs:
            database[name].delete_many({})
            database[name].insert_many(docs)


def save():
    """Write the whole database to disk. Called after each change (see middleware)."""
    from . import db as dbmod

    database = dbmod.get_db()
    try:
        names = list(database.list_collection_names())
    except Exception:  # noqa: BLE001
        names = ["api_keys", "quotes", "errands", "wallets", "wallet_transactions",
                 "webhook_endpoints", "webhook_events", "webhook_deliveries", "saved_addresses"]
    data = {}
    for name in names:
        try:
            docs = list(database[name].find())
        except Exception:  # noqa: BLE001
            docs = []
        if docs:
            data[name] = docs
    tmp = _PATH + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    os.replace(tmp, _PATH)
