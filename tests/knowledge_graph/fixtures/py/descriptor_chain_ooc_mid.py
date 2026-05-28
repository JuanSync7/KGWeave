"""4-hop descriptor chain with out-of-corpus mid-hop (v1.14-#4 fixture).

A -> B(A) -> C(ExternalC) -> D(C). A declares __get__. Expected:
A and B tagged descriptor (in-corpus chain). C and D NOT tagged
(chain broken at out-of-corpus C).
"""


class A:
    def __get__(self, instance, owner):
        pass


class B(A):
    pass


class C(ExternalC):  # noqa: F821 — chain breaks here
    pass


class D(C):
    pass
