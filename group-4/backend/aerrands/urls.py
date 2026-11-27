
from django.urls import path

from . import views


urlpatterns = [
    # Quote creation and retrieval
    path("quotes", views.create_quote, name="create-quote"),
    path("quotes/<str:quote_id>", views.retrieve_quote, name="retrieve-quote"),

    # Delivery creation and retrieval
    path("errands", views.aerrands_collection, name="aerrands-collection"),
    path("errands/<str:aerrand_id>", views.retrieve_aerrand, name="retrieve-aerrand"),

    # Delivery tracking, proof, and cancellation
    path(
        "errands/<str:aerrand_id>/tracking",
        views.retrieve_aerrand_tracking,
        name="retrieve-aerrand-tracking",
    ),
    path(
        "errands/<str:aerrand_id>/proof",
        views.retrieve_aerrand_proof,
        name="retrieve-aerrand-proof",
    ),
    path(
        "errands/<str:aerrand_id>/cancel",
        views.cancel_aerrand,
        name="cancel-aerrand",
    ),
    path(
        "errands/<str:aerrand_id>/dropoff/<str:stop_id>",
        views.update_aerrand_dropoff,
        name="update-aerrand-dropoff",
    ),
    path(
    "errands/<str:aerrand_id>/pickup",
        views.update_aerrand_pickup,
        name="update-aerrand-pickup",
    ),
    path(
        "errands/<str:aerrand_id>/public",
        views.retrieve_public_aerrand_tracking,
        name="retrieve-public-aerrand-tracking",
    ),
    path(
        "checklists/generate",
        views.generate_checklist,
        name="generate-checklist",
    ),
    path(
        "errands/<str:aerrand_id>/checklist",
        views.attach_aerrand_checklist,
        name="attach-aerrand-checklist",
    ),
    path(
        "errands/<str:aerrand_id>/tags",
        views.attach_aerrand_tags,
        name="attach-aerrand-tags",
    ),
    path(
        "service-areas",
        views.retrieve_service_areas,
        name="retrieve-service-areas",
    ),

]
