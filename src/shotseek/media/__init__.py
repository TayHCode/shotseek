class MediaError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def load(entry, settings):
    if entry.kind == "photo":
        from .photos import load_photo
        return load_photo(entry.path, settings)
    from .videos import load_video
    return load_video(entry.path, settings)


def orientation(width, height):
    if abs(width - height) <= .05 * max(width, height):
        return "square"
    return "landscape" if width > height else "portrait"
