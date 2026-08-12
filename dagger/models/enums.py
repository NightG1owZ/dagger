from enum import Enum


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ReportFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    CSV = "csv"
    HTML = "html"
    ALL = "all"


class RampStrategy(str, Enum):
    LINEAR = "linear"
    STEP = "step"


class RunStatus(str, Enum):
    INIT = "init"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ERROR = "error"
