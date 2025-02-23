class KotonebotError(Exception):
    pass

class KotonebotWarning(Warning):
    pass

class UnrecoverableError(KotonebotError):
    pass

class GameUpdateNeededError(UnrecoverableError):
    def __init__(self):
        super().__init__(
            'Game update required. '
            'Please go to Play Store and update the game manually.'
        )

class ResourceFileMissingError(KotonebotError):
    def __init__(self, file_path: str, description: str):
        self.file_path = file_path
        self.description = description
        super().__init__(f'Resource file ({description}) "{file_path}" is missing.')