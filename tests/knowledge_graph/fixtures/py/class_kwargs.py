"""Class kwargs propagation fixture (v1.15-#3)."""


class Base:
    def __init_subclass__(cls, **kwargs):  # noqa: D401
        pass


ALPHA = "alpha"
BETA = "beta"


class Child(Base, name=ALPHA, config=BETA):
    pass


class MetaCls(type):
    pass


class Other(Base, metaclass=MetaCls):
    pass


class Bare(Base):
    pass
