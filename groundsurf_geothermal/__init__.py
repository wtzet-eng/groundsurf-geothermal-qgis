"""GroundSurf Studio Connector QGIS plugin. Importable without QGIS for testing."""


def classFactory(iface):
    from .plugin import GroundSurfGeothermalPlugin
    return GroundSurfGeothermalPlugin(iface)
