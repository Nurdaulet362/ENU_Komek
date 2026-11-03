"""Temporary, isolated visitor workspaces for a single-process public demo."""
from contextlib import contextmanager
from contextvars import ContextVar
from http.cookies import SimpleCookie
from pathlib import Path
import secrets
import shutil
import tempfile
import threading
import time

from .search import SearchEngine

CURRENT = ContextVar('enu_workspace', default=None)
POOL = {}
POOL_LOCK = threading.RLock()
ROOT = Path(tempfile.mkdtemp(prefix='enu-visitors-'))
MAX_VISITORS = 12
TTL = 1800

class BusyError(Exception):
    pass

@contextmanager
def visitor(cookie):
    jar = SimpleCookie()
    try:
        jar.load(cookie or '')
        token = jar['enu_session'].value if 'enu_session' in jar else ''
    except Exception:
        token = ''
    now = time.monotonic()
    with POOL_LOCK:
        # Remove only inactive workspaces, never a request currently using one.
        for key, item in list(POOL.items()):
            if now - item['used'] > TTL and item['users'] == 0 and item['lock'].acquire(blocking=False):
                try:
                    shutil.rmtree(item['data'], ignore_errors=True)
                    del POOL[key]
                finally:
                    item['lock'].release()
        fresh = token not in POOL
        if fresh:
            if len(POOL) >= MAX_VISITORS:
                raise BusyError()
            token = secrets.token_urlsafe(32)
            folder = ROOT / token
            folder.mkdir(mode=0o700)
            POOL[token] = {'values': {'ENU_PROVIDER': 'gemini', 'ENU_MODEL': ''}, 'data': folder,
                           'documents': [], 'files': {}, 'engine': SearchEngine([]),
                           'lock': threading.RLock(), 'used': now, 'requests': [], 'uploads': 0, 'users': 0}
        space = POOL[token]
        space['used'] = now
        space['users'] += 1
    space['lock'].acquire()
    context = CURRENT.set(space)
    try:
        yield space, token
    finally:
        space['used'] = time.monotonic()
        CURRENT.reset(context)
        space['lock'].release()
        with POOL_LOCK:
            space['users'] -= 1
