from backend.services.gee import GEEService


def test_carbonate_layer():
    gee = GEEService()
    result = gee.get_layer_tiles("carbonate")
    assert "tile_url" in result
    assert "{z}" in result["tile_url"]


def test_silica_layer():
    gee = GEEService()
    result = gee.get_layer_tiles("silica")
    assert "tile_url" in result
