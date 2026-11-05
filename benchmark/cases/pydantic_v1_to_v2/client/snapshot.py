from app.models import load_user, user_dict, user_json

print(user_dict("ada", 36))
print(user_json("ada", 36))
print(repr(load_user({"name": "ada", "age": 36})))
