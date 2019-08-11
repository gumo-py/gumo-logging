import json
import logging
import os
import sys
import inspect
import traceback
import datetime
import dataclasses

from typing import Optional
from typing import Tuple
from typing import Callable

@dataclasses.dataclass(frozen=True)
class LoggerContext:
    trace: Optional[str] = None
    span_id: Optional[str] = None


class GumoLogger:
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    FATAL = logging.FATAL
    CRITICAL = logging.CRITICAL

    def __init__(
            self,
            project_id: str,
            default_logger: logging.Logger,
            error_logger: logging.Logger,
            logger_context: LoggerContext,
            structured_log_enabled: Optional[bool] = True,
            fetch_logger_context_func: Optional[Callable[[], str]] = None,
    ):
        self._project_id = project_id
        self._default_logger = default_logger
        self._error_logger = error_logger

        self._logger_context = logger_context
        self._structured_log_enabled = structured_log_enabled
        self._fetch_logger_context_func = fetch_logger_context_func

        self._cwd = os.getcwd() + '/'

    def getLevelName(self, level) -> str:
        from logging import getLevelName
        return getLevelName(level)

    def _build_message_text(self, msg) -> str:
        if isinstance(msg, BaseException):
            err: BaseException = msg
            return '\n'.join([
                repr(err),
                traceback.format_exc()
            ])

        return str(msg)

    def _build_log_payload(self, level, msg) -> dict:
        j = {
            'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
            'Message': self._build_message_text(msg),
            'severity': self.getLevelName(level),
        }

        if self._logger_context.trace is not None:
            j['logging.googleapis.com/trace'] = self._logger_context.trace
        if self._logger_context.span_id is not None:
            j['logging.googleapis.com/spanId'] = self._logger_context.span_id

        caller = self._find_caller()
        if caller is not None:
            j['logging.googleapis.com/sourceLocation'] = caller

        return j

    def _json_formatter(self, d: dict) -> str:
        return json.dumps(d, ensure_ascii=False)

    def _log_text_formatter(self, d: dict) -> str:
        line = d.get('logging.googleapis.com/sourceLocation', {}).get('line', '-')
        file = d.get('logging.googleapis.com/sourceLocation', {}).get('file', '<unknown>')
        file = file.replace(self._cwd, '')

        msg = '[{timestamp}]{severity}:{file}:{line}: {message}'.format(
            timestamp=datetime.datetime.now(),
            severity=d.get('severity'),
            file=file,
            line=line,
            message=d.get('Message')
        )
        return msg

    def _formatter(self, d: dict) -> str:
        if self._structured_log_enabled:
            return self._json_formatter(d)
        else:
            return self._log_text_formatter(d)

    def _fetch_logger_context(self):
        if self._fetch_logger_context_func is None:
            return

        context = self._fetch_logger_context_func()
        if context is None:
            return
        self._logger_context = context


    def _log(self, level, msg):
        self._fetch_logger_context()

        payload = self._build_log_payload(level=level, msg=msg)
        if level >= self.ERROR:
            self._error_logger.log(level, self._formatter(payload))
        else:
            self._default_logger.log(level, self._formatter(payload))

    def debug(self, msg):
        self._log(level=self.DEBUG, msg=msg)

    def info(self, msg):
        self._log(level=self.INFO, msg=msg)

    def warning(self, msg):
        self._log(level=self.WARNING, msg=msg)

    def error(self, msg):
        self._log(level=self.ERROR, msg=msg)

    def exception(self, msg):
        self.error(msg)

    def critical(self, msg):
        self._log(level=self.CRITICAL, msg=msg)

    def fatal(self, msg):
        self._log(level=self.FATAL, msg=msg)

    def log(self, level, msg):
        self._log(level=level, msg=msg)

    def _find_caller(self) -> Optional[dict]:
        caller_stack: Optional[inspect.FrameInfo] = None
        callee_is_custom_logger = False

        for stack in inspect.stack():
            stack: inspect.FrameInfo = stack
            stack_self = stack.frame.f_locals.get('self')
            stack_in_custom_logger = stack_self is not None and isinstance(stack_self, self.__class__)

            if stack_in_custom_logger:
                callee_is_custom_logger = True
            else:
                if callee_is_custom_logger:
                    caller_stack = stack
                    break

        if caller_stack is None:
            return

        file: str = caller_stack.filename
        return {
            'file': file,
            'line': caller_stack.lineno,
            'function': caller_stack.function,
        }


class LoggerManager:
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    FATAL = logging.FATAL
    CRITICAL = logging.CRITICAL

    def __init__(
            self,
            fetch_logger_context_func: Optional[Callable[[], str]] = None,
    ):
        self._project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', '<unknown-project>')
        self._fetch_logger_context_func = fetch_logger_context_func

        is_google_platform = os.environ.get('GAE_DEPLOYMENT_ID') is not None
        self._structured_log_enabled = is_google_platform

        self._default_logger, self._default_handler = self._build_logger(
            logger_name='default_logger',
            stream=sys.stdout,
            level=self.DEBUG
        )
        self._error_logger, self._error_handler = self._build_logger(
            logger_name='default_logger',
            stream=sys.stderr,
            level=self.DEBUG
        )

    @staticmethod
    def _build_logger(logger_name, stream, level) -> Tuple[logging.Logger, logging.Handler]:
        formatter = logging.Formatter('%(message)s')

        handler = logging.StreamHandler(stream=stream)
        handler.setLevel(level)
        handler.setFormatter(formatter)

        logger = logging.getLogger(logger_name)
        logger.propagate = False
        logger.setLevel(level)
        if not logger.hasHandlers():
            logger.addHandler(handler)
        return (logger, handler)

    def getLevelName(self, level) -> str:
        from logging import getLevelName
        return getLevelName(level)

    def flush(self):
        self._default_handler.flush()
        self._error_handler.flush()

    def _build_trace_and_span(self, trace_header: str) -> Tuple[Optional[str], Optional[str]]:
        if trace_header is None:
            return (None, None)

        trace_id = None
        span_id = None

        if trace_header.find('/') >= 0:
            trace_id, span_id = trace_header.split('/', )
            if span_id.find(';') >= 0:
                span_id = span_id.split(';')[0]

        trace = f'projects/{self._project_id}/traces/{trace_id}'

        return (trace, span_id)

    def getLoggerContext(self, trace_header: Optional[str] = None) -> LoggerContext:
        trace, span_id = self._build_trace_and_span(trace_header)
        return LoggerContext(
            trace=trace,
            span_id=span_id,
        )

    def getLogger(self, trace_header: Optional[str] = None) -> GumoLogger:
        logger_context = self.getLoggerContext(trace_header=trace_header)

        return GumoLogger(
            project_id=self._project_id,
            default_logger=self._default_logger,
            error_logger=self._error_logger,
            logger_context=logger_context,
            structured_log_enabled=self._structured_log_enabled,
            fetch_logger_context_func=self._fetch_logger_context_func,
        )
