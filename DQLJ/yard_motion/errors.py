import math


class MotionError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MotionError("INVALID_COMMAND", "参数必须为有限数值", 422)
    return float(value)
