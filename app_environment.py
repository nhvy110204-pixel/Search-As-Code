from enum import Enum

class AppEnvironment(str, Enum):
    dev = "dev"
    prod = "prod"
    test = "test"

    @classmethod
    def is_production_env(cls, env):
        return env == cls.prod

    @classmethod
    def is_local_env(cls, env):
        return env == cls.dev or env == cls.test

    @classmethod
    def is_remote_env(cls, env):
        return env == cls.prod

    @classmethod
    def is_test_env(cls, env):
        return env == cls.test
