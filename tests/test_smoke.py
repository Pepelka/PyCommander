def test_import_app():
    from pycommander.app import TotalCommanderApp
    from pycommander import __version__

    assert TotalCommanderApp
    assert __version__