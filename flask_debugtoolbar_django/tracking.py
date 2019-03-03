import datetime
import inspect
import json
import os
from threading import local
from time import time

from django.utils import six
from django.utils.encoding import DjangoUnicodeDecodeError, force_text
import flask

# from debug_toolbar import settings as dt_settings
# from debug_toolbar.utils import get_stack, get_template_info, tidy_stacktrace


def WANT_STACK_TRACE():
    return flask.current_app.config.get('DEBUG_TB_DJANGO', {}).get(
        'SHOW_STACKTRACES', True
    )


class SQLQueryTriggered(Exception):
    """Thrown when template panel triggers a query"""

    pass


class ThreadLocalState(local):
    def __init__(self):
        self.enabled = True

    @property
    def Wrapper(self):
        if self.enabled:
            return NormalCursorWrapper
        return ExceptionCursorWrapper

    def recording(self, v):
        self.enabled = v


state = ThreadLocalState()
recording = state.recording  # export function


def wrap_cursor(connection, panel):
    if not hasattr(connection, "_djdt_cursor"):
        connection._djdt_cursor = connection.cursor

        def cursor(*args, **kwargs):
            # Per the DB API cursor() does not accept any arguments. There's
            # some code in the wild which does not follow that convention,
            # so we pass on the arguments even though it's not clean.
            # See:
            # https://github.com/jazzband/django-debug-toolbar/pull/615
            # https://github.com/jazzband/django-debug-toolbar/pull/896
            return state.Wrapper(
                connection._djdt_cursor(*args, **kwargs), connection, panel
            )

        connection.cursor = cursor
        return cursor


def unwrap_cursor(connection):
    if hasattr(connection, "_djdt_cursor"):
        del connection._djdt_cursor
        del connection.cursor


class ExceptionCursorWrapper(object):
    """
    Wraps a cursor and raises an exception on any operation.
    Used in Templates panel.
    """

    def __init__(self, cursor, db, logger):
        pass

    def __getattr__(self, attr):
        raise SQLQueryTriggered()


class NormalCursorWrapper(object):
    """
    Wraps a cursor and logs queries.
    """

    def __init__(self, cursor, db, logger):
        self.cursor = cursor
        # Instance of a BaseDatabaseWrapper subclass
        self.db = db
        # logger must implement a ``record`` method
        self.logger = logger

    def _quote_expr(self, element):
        if isinstance(element, six.string_types):
            try:
                return "'%s'" % force_text(element).replace("'", "''")
            except DjangoUnicodeDecodeError:
                return repr(element)
        else:
            return repr(element)

    def _quote_params(self, params):
        if not params:
            return params
        if isinstance(params, dict):
            return {key: self._quote_expr(value) for key, value in params.items()}
        return [self._quote_expr(p) for p in params]

    def _decode(self, param):
        # If a sequence type, decode each element separately
        if isinstance(param, list) or isinstance(param, tuple):
            return [self._decode(element) for element in param]

        # If a dictionary type, decode each value separately
        if isinstance(param, dict):
            return {key: self._decode(value) for key, value in param.items()}

        # make sure datetime, date and time are converted to string by force_text
        CONVERT_TYPES = (datetime.datetime, datetime.date, datetime.time)
        try:
            return force_text(param, strings_only=not isinstance(param, CONVERT_TYPES))
        except UnicodeDecodeError:
            return "(encoded string)"

    def _record(self, method, sql, params):
        start_time = time()
        try:
            return method(sql, params)
        finally:
            stop_time = time()
            duration = (stop_time - start_time) * 1000
            if WANT_STACK_TRACE():
                stacktrace = _get_stacktrace()
            else:
                stacktrace = []
            _params = ""
            try:
                _params = json.dumps(self._decode(params))
            except TypeError:
                pass  # object not JSON serializable

            alias = getattr(self.db, "alias", "default")
            conn = self.db.connection
            vendor = getattr(conn, "vendor", "unknown")

            params = {
                "vendor": vendor,
                "alias": alias,
                "sql": self.db.ops.last_executed_query(
                    self.cursor, sql, self._quote_params(params)
                ),
                "duration": duration,
                "raw_sql": sql,
                "params": _params,
                "raw_params": params,
                "stacktrace": stacktrace,
                "start_time": start_time,
                "stop_time": stop_time,
                # "is_slow": duration > dt_settings.get_config()["SQL_WARNING_THRESHOLD"],
                "is_select": sql.lower().strip().startswith("select"),
            }

            if vendor == "postgresql":
                # If an erroneous query was ran on the connection, it might
                # be in a state where checking isolation_level raises an
                # exception.
                try:
                    iso_level = conn.isolation_level
                except conn.InternalError:
                    iso_level = "unknown"
                params.update(
                    {
                        "trans_id": self.logger.get_transaction_id(alias),
                        "trans_status": conn.get_transaction_status(),
                        "iso_level": iso_level,
                        "encoding": conn.encoding,
                    }
                )

            # We keep `sql` to maintain backwards compatibility
            self.logger.record(**params)

    def callproc(self, procname, params=None):
        return self._record(self.cursor.callproc, procname, params)

    def execute(self, sql, params=None):
        return self._record(self.cursor.execute, sql, params)

    def executemany(self, sql, param_list):
        return self._record(self.cursor.executemany, sql, param_list)

    def __getattr__(self, attr):
        return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.cursor)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()


def _get_stacktrace():
    if WANT_STACK_TRACE():
        try:
            stack = inspect.stack()
        except IndexError:
            # this is a work around because python's inspect.stack() sometimes fail
            # when jinja templates are on the stack
            return [
                (
                    "",
                    0,
                    "Error retrieving stack",
                    "Could not retrieve stack. IndexError exception occured in inspect.stack(). "
                    "This error might occur when jinja2 templates is on the stack.",
                )
            ]

        return _tidy_stacktrace(reversed(stack))
    else:
        return []


# Taken from Django Debug Toolbar 0.8.6
def _tidy_stacktrace(stack):
    """
    Clean up stacktrace and remove all entries that:
    1. Are part of flask (except contrib apps)
    2. Are part of SocketServer (used by flask's dev server)
    3. Are the last entry (which is part of our stacktracing code)

    ``stack`` should be a list of frame tuples from ``inspect.stack()``
    """
    flask_path = os.path.realpath(os.path.dirname(flask.__file__))
    flask_path = os.path.normpath(os.path.join(flask_path, '..'))
    flask_dtb_mongo = os.path.realpath(os.path.dirname(__file__))
    flask_dtb_mongo = os.path.normpath(os.path.join(flask_dtb_mongo, '..'))
    # socketserver_path = os.path.realpath(os.path.dirname(SocketServer.__file__))
    # pymongo_path = os.path.realpath(os.path.dirname(pymongo.__file__))

    trace = []
    for frame, path, line_no, func_name, text in (f[:5] for f in stack):
        s_path = os.path.realpath(path)
        # Support hiding of frames -- used in various utilities that provide
        # inspection.
        if '__traceback_hide__' in frame.f_locals:
            continue
        if (
            flask.current_app.config.get('DEBUG_TB_MONGO', {}).get(
                'HIDE_FLASK_FROM_STACKTRACES', True
            )
            and flask_path in s_path
        ):
            continue
        if flask_dtb_mongo in s_path:
            continue
        # if socketserver_path in s_path:
        #     continue
        # if pymongo_path in s_path:
        #     continue
        if not text:
            text = ''
        else:
            text = (''.join(text)).strip()
        trace.append((path, line_no, func_name, text))
    return trace
