from tests.fixtures.sample_plugins import PLUGINS


@PLUGINS.decorator("beta")
class Beta:
    pass
