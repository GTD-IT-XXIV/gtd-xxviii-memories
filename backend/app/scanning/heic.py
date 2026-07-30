_registered = False


def register_heif_opener() -> None:
    """Registers pillow_heif as a Pillow plugin so Image.open() transparently handles
    .heic/.heif files. Must be called once before any Image.open() call."""
    global _registered
    if _registered:
        return
    import pillow_heif

    pillow_heif.register_heif_opener()
    _registered = True
