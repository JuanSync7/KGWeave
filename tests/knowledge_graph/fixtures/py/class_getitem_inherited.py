"""Fixture: ``__class_getitem__`` inheritance — single hop (v1.15-#2).

Class ``Base`` directly declares ``__class_getitem__``; class
``Sub(Base)`` inherits it without declaring any methods of its own.
Both must be tagged ``semantic_role='class-getitem-hook'`` since the
v1.15-#2 connector enables ``chase_bases=True``.
"""


class Base:
    def __class_getitem__(cls, item):
        return cls


class Sub(Base):
    pass
