import enum


class TaskStatus(enum.Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SKIPPED = "Skipped"
    PASS = "Pass"
    FAILED = "Failed"
    BLOCKED = "Blocked"
    NA = "NA"
    UNKNOWN = "Unknown"
    ABORTED = "Aborted"
    QUEUED = "Queued"
    PROCESSING = "Processing"
    SETUP = "Setup"


class ExecutionMode(enum.Enum):
    PARALLEL = "parallel"
    SERIAL = "serial"


# Constants Parameters
CONST_ALL = "All"
CONST_NOTEST = "NoTest"

# Queued Retry
QUEUED_RETRY_COUNT = 3
QUEUED_RETRY_DELAY = 10  # seconds

# Track Result
TRACK_RESULT_INTERVAL = 10  # seconds
TRACK_RESULT_TIMEOUT = 6 * 60 * 60  # 6 hours