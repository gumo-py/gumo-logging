import flask.views

from gumo.logging import LoggerManager
from gumo.logging import GumoLogger

logger_manager = LoggerManager()

app = flask.Flask('app')


def getLogger() -> GumoLogger:
    if 'logger' in flask.g:
        return flask.g.logger

    return logger_manager.getLogger()


@app.before_request
def on_before_request():
    flask.g.logger = logger_manager.getLogger(
        trace_header=flask.request.headers.get('X-Cloud-Trace-Context')
    )


@app.after_request
def on_after_request(response):
    logger_manager.flush()
    return response


@app.route('/')
def root():
    flask.g.logger.info('Hello. This is test log message.')
    flask.g.logger.debug('Hello. This is test DEBUG log message.')
    return 'Hello'


def another_function():
    return 1 / 0


def some_function():
    return another_function()


class ErrorViews(flask.views.MethodView):
    @property
    def logger(self) -> GumoLogger:
        return flask.g.logger

    def get(self):
        self.logger.warning('This is test warning message.')

        try:
            some_function()
        except Exception as e:
            self.logger.exception(e)
            return f'raise something error: {e}'


app.add_url_rule(
    '/error',
    view_func=ErrorViews.as_view('error'),
    methods=['GET']
)


if __name__ == '__main__':
    app.run(port='8080', debug=True)
