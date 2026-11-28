def classFactory(iface):
    from .plugin import Connect

    return Connect(iface)
