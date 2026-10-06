from tests.fixtures.sample_plugins import PLUGINS


@PLUGINS.decorator("alpha")
class Alpha:
    pass
