from django.contrib.admin.apps import AdminConfig
from django.contrib.auth.apps import AuthConfig
from django.contrib.contenttypes.apps import ContentTypesConfig

#When these built-in Django apps create database objects, so to use MongoDB's ObjectId system instead of Django's normal integer ID system we use this code.
class MongoAdminConfig(AdminConfig):
        default_auto_field = "django_mongodb_backend.fields.ObjectIdAutoField"

class MongoAuthConfig(AuthConfig):
        default_auto_field = "django_mongodb_backend.fields.ObjectIdAutoField"

class MongoContentTypesConfig(ContentTypesConfig):
        default_auto_field = "django_mongodb_backend.fields.ObjectIdAutoField"