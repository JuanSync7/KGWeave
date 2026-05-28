"""@staticmethod / @classmethod / no decorator — NOT tagged (v1.15-#4 fixture)."""


class Klass:
    @staticmethod
    def s():
        return 1

    @classmethod
    def c(cls):
        return 1

    def plain(self):
        return 1
