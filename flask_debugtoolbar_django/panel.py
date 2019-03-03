
from django.db import connections
from flask_debugtoolbar.panels import DebugPanel
import jinja2
from . import jinja_filters

from .tracking import unwrap_cursor, wrap_cursor


class DjangoSQLPanel(DebugPanel):
    """Panel that shows information about Django SQL operations.
    """

    name = 'Django SQL'
    has_content = True

    def __init__(self, *args, **kwargs):
        super(DjangoSQLPanel, self).__init__(*args, **kwargs)
        self.jinja_env.loader = jinja2.ChoiceLoader(
            [
                self.jinja_env.loader,
                jinja2.PrefixLoader(
                    {'debug_tb_django': jinja2.PackageLoader(__name__, 'templates')}
                ),
            ]
        )
        filters = (
            'format_stack_trace',
            'embolden_file',
            'format_dict',
            'highlight',
            'pluralize',
        )
        for jfilter in filters:
            self.jinja_env.filters[jfilter] = getattr(jinja_filters, jfilter)

        self._offset = {k: len(connections[k].queries) for k in connections}
        self._sql_time = 0
        self._num_queries = 0
        self._queries = []
        self._databases = {}
        self._transaction_status = {}
        self._transaction_ids = {}

        self.enable_instrumentation()

    def enable_instrumentation(self):
        # This is thread-safe because database connections are thread-local.
        for connection in connections.all():
            wrap_cursor(connection, self)

    def disable_instrumentation(self):
        for connection in connections.all():
            unwrap_cursor(connection)

    def record(self, alias, **kwargs):
        self._queries.append((alias, kwargs))
        if alias not in self._databases:
            self._databases[alias] = {
                "time_spent": kwargs["duration"],
                "num_queries": 1,
            }
        else:
            self._databases[alias]["time_spent"] += kwargs["duration"]
            self._databases[alias]["num_queries"] += 1
        self._sql_time += kwargs["duration"]
        self._num_queries += 1

    def title(self):
        return 'Django SQL'

    def nav_title(self):
        return 'Django SQL'

    def nav_subtitle(self):
        # fun = lambda x, y: (x, len(y), '%.2f' % sum(z['time'] for z in y))
        # ctx = {'operations': [], 'count': 0, 'time': 0}

        #     ctx['time'] += sum(x['time'] for x in self.operation_tracker.updates)

        # if self.operation_tracker.removes:
        #     ctx['operations'].append(fun('delete', self.operation_tracker.removes))
        #     ctx['count'] += len(self.operation_tracker.removes)
        #     ctx['time'] += sum(x['time'] for x in self.operation_tracker.removes)

        ctx = {}
        ctx['count'] = self._num_queries
        ctx['time'] = '%.2f' % self._sql_time
        return self.render('debug_tb_django/subtitle.html', ctx)

    def url(self):
        return ''

    def content(self):
        context = self.context.copy()
        context['queries'] = [q[1] for q in self._queries]
        return self.render('debug_tb_django/panel.html', context)
