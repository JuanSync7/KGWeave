"""Lambda capture-analysis fixture for v1.7-#5.

Lambdas, by index in the expected PyLambda emission order (start asc):

1. Top-level no-param no-capture:           parent=PyModule,   captures=[]
2. Lambda with params, no captures:         parent=PyModule,   captures=[]
3. Lambda inside def f capturing outer y:   parent=PyFunction f, captures=["y"]
4. Module-level lambda calling foo:         parent=PyModule,   captures=["foo"]
5. Method-body lambda capturing self:       parent=PyFunction m, captures=["self"]
6. Outer of nested lambda:                  parent=PyModule,   captures=[]
7. Inner of nested lambda (lambda y: x+y):  parent=PyLambda (outer), captures=["x"]
"""

from __future__ import annotations


# 1. top-level no-param no-capture
no_caps = lambda: 0  # noqa: E731

# 2. params only, no captures
add_one = lambda x: x + 1  # noqa: E731


def f():
    """Capture an outer local."""
    y = 1
    # 3. captures y from enclosing function scope
    return lambda x: x + y


def foo(arg):
    return arg


# 4. module-level lambda referencing module-level foo
call_foo = lambda x: foo(x)  # noqa: E731


class C:
    attr = 0

    def m(self):
        # 5. method-body lambda capturing self
        return lambda x: self.attr + x


# 6 + 7. nested lambdas
nested = lambda x: (lambda y: x + y)  # noqa: E731
