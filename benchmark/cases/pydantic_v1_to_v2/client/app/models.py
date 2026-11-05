from pydantic import BaseModel


class User(BaseModel):
    name: str
    age: int


def user_dict(name, age):
    return User(name=name, age=age).dict()


def user_json(name, age):
    return User(name=name, age=age).json()


def load_user(payload):
    return User.parse_obj(payload)
