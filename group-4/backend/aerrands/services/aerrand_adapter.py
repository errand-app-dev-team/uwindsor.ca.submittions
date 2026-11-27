
"""Integration interface between the Partner API and Aerrand's core platform."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string


class AerrandAdapterError(Exception):
    """Base exception for integration errors."""


class AerrandAdapterUnavailable(AerrandAdapterError):
    """The integration is not configured; no operation was attempted."""


class AerrandAdapterOutcomeUnknown(AerrandAdapterError):
    """An operation may have reached Aerrand, but its result is unknown."""


class AerrandAdapterNotFound(AerrandAdapterError):
    """The requested Aerrand resource was not found or is inaccessible."""


class AerrandAdapterConflict(AerrandAdapterError):
    """The requested operation conflicts with the delivery's current state."""


@dataclass(frozen=True)
class PartnerIdentity:
    business_owner_id: str
    api_key_id: str
    environment: str


@dataclass(frozen=True)
class BookingRequest:
    quote_id: str
    pickup: dict[str, Any]
    dropoffs: list[dict[str, Any]]
    vehicle_type: str
    scheduled_at: str | None
    payment: dict[str, Any] | None
    external_reference: str | None
    metadata: dict[str, Any]
    max_total: str | None


class AerrandAdapter(ABC):
    """Contract implemented by the actual Aerrand platform integration."""

    @abstractmethod
    def create_booking(
        self,
        booking: BookingRequest,
        quote: Any,
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def list_bookings(
        self,
        partner: PartnerIdentity,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict:
        pass

    @abstractmethod
    def get_booking(
        self,
        aerrand_id: str,
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def get_tracking(
        self,
        aerrand_id: str,
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def get_proof(
        self,
        aerrand_id: str,
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def cancel_booking(
        self,
        aerrand_id: str,
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def update_dropoff(
        self,
        aerrand_id: str,
        stop_id: str,
        changes: dict[str, Any],
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def update_pickup(
        self,
        aerrand_id: str,
        changes: dict[str, Any],
        partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def get_public_tracking(
            self,
            aerrand_id: str,
    ) -> dict:
        pass

    @abstractmethod
    def generate_checklist(
            self,
            item: dict[str, Any],
            partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def attach_checklist(
            self,
            aerrand_id: str,
            checklists: list[str],
            partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def attach_tags(
            self,
            aerrand_id: str,
            tags: list[str],
            partner: PartnerIdentity,
    ) -> dict:
        pass

    @abstractmethod
    def get_service_areas(
            self,
            partner: PartnerIdentity,
    ) -> dict:
        pass


class UnconfiguredAerrandAdapter(AerrandAdapter):
    """Fail safely until the real Aerrand integration is connected."""

    def _unavailable(self):
        raise AerrandAdapterUnavailable(
            "Aerrand core Order/Delivery integration is not configured."
        )

    def create_booking(self, booking, quote, partner):
        self._unavailable()

    def list_bookings(self, partner, cursor=None, limit=20):
        self._unavailable()

    def get_booking(self, aerrand_id, partner):
        self._unavailable()

    def get_tracking(self, aerrand_id, partner):
        self._unavailable()

    def get_proof(self, aerrand_id, partner):
        self._unavailable()

    def cancel_booking(self, aerrand_id, partner):
        self._unavailable()

    def update_dropoff(self, aerrand_id, stop_id, changes, partner):
        self._unavailable()

    def update_pickup(self, aerrand_id, changes, partner):
        self._unavailable()

    def get_public_tracking(self, aerrand_id):
        self._unavailable()

    def generate_checklist(self, item, partner):
        self._unavailable()

    def attach_checklist(self, aerrand_id, checklists, partner):
        self._unavailable()

    def attach_tags(self, aerrand_id, tags, partner):
        self._unavailable()

    def get_service_areas(self, partner):
        self._unavailable()


def get_aerrand_adapter() -> AerrandAdapter:
    """Load the configured delivery integration."""

    adapter_path = getattr(
        settings,
        "AERRAND_ADAPTER_CLASS",
        None,
    )

    if not adapter_path:
        return UnconfiguredAerrandAdapter()

    adapter_class = import_string(adapter_path)
    adapter = adapter_class()

    if not isinstance(adapter, AerrandAdapter):
        raise TypeError(
            "AERRAND_ADAPTER_CLASS must implement AerrandAdapter."
        )

    return adapter
