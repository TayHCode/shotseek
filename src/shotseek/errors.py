class AppError(Exception):
    def __init__(self, code, message, hint="", exit_code=2):
        super().__init__(message)
        self.code, self.message, self.hint, self.exit_code = code, message, hint, exit_code

    def as_dict(self):
        return dict(code=self.code, message=self.message, hint=self.hint, exit_code=self.exit_code)


def warning(code, message):
    return {"code": code, "message": message}
