"""Razorpay client interface with two implementations.

- MockRazorpay: in-process simulator with fault injection (the eval/demo harness).
- RazorpayHTTP: real test-mode API client (api.razorpay.com, basic auth).

Both expose the same surface, so the pipeline and reconciler cannot tell them apart.
"""
import base64
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx

from gateway.core.config import get_settings


class PaymentsError(Exception):
    """Definitive failure — the API answered and said no."""


class PaymentsTimeout(Exception):
    """Ambiguous outcome — the call timed out and the result is UNKNOWN.

    The caller must not retry blindly; the reconciler resolves via ground-truth fetch.
    """


@dataclass
class OrderResult:
    order_id: str
    receipt: str
    amount_paise: int
    currency: str
    status: str  # created | paid | attempted


@dataclass
class PaymentInfo:
    payment_id: str
    order_id: str
    status: str  # created | authorized | captured | failed | refunded
    amount_paise: int
    method: str = "upi"


class RazorpayClient(Protocol):
    def create_order(self, *, receipt: str, amount_paise: int, currency: str, notes: dict) -> OrderResult: ...
    def fetch_order_by_receipt(self, receipt: str) -> Optional[OrderResult]: ...
    def fetch_order_payments(self, order_id: str) -> list[PaymentInfo]: ...
    def create_payment_link(self, *, reference_id: str, amount_paise: int,
                            description: str, notes: dict) -> tuple[str, str]: ...
    def create_refund(self, payment_id: str, amount_paise: int) -> str: ...


# --------------------------------------------------------------------------
# Mock implementation (fault-injection harness)
# --------------------------------------------------------------------------

@dataclass
class _MockOrder:
    order: OrderResult
    notes: dict
    payments: list[PaymentInfo] = field(default_factory=list)


class MockRazorpay:
    """Simulates Razorpay test mode, including its unpleasant behaviours on demand.

    Fault injection:
      arm_fault("timeout_after_create")   -> next create_order times out but the order IS
                                             created server-side (the nasty ambiguous case)
      arm_fault("timeout_before_create")  -> next create_order times out, nothing created
      arm_fault("error")                  -> next create_order fails definitively
      arm_fault("fetch_timeout")          -> next fetch_order_payments times out
    """

    def __init__(self) -> None:
        self.orders: dict[str, _MockOrder] = {}       # order_id -> record
        self.by_receipt: dict[str, str] = {}          # receipt -> order_id
        self.links: dict[str, dict] = {}
        self._fault: Optional[str] = None

    def arm_fault(self, fault: str) -> None:
        self._fault = fault

    def _take_fault(self, *matches: str) -> Optional[str]:
        if self._fault in matches:
            fault, self._fault = self._fault, None
            return fault
        return None

    def create_order(self, *, receipt: str, amount_paise: int, currency: str, notes: dict) -> OrderResult:
        fault = self._take_fault("timeout_after_create", "timeout_before_create", "error")
        if fault == "error":
            raise PaymentsError("BAD_REQUEST_ERROR: simulated definitive failure")
        if fault == "timeout_before_create":
            raise PaymentsTimeout("simulated timeout; order NOT created server-side")

        if receipt in self.by_receipt:
            # Razorpay allows duplicate receipts; we surface the pre-existing order so the
            # idempotency layer can adopt it. (The layer must check before creating.)
            existing = self.orders[self.by_receipt[receipt]].order
            raise PaymentsError(f"order already exists for receipt {receipt}: {existing.order_id}")

        order = OrderResult(
            order_id=f"order_MOCK{uuid.uuid4().hex[:14]}",
            receipt=receipt, amount_paise=amount_paise, currency=currency, status="created",
        )
        self.orders[order.order_id] = _MockOrder(order=order, notes=dict(notes))
        self.by_receipt[receipt] = order.order_id

        if fault == "timeout_after_create":
            raise PaymentsTimeout("simulated timeout; order WAS created server-side")
        return order

    def fetch_order_by_receipt(self, receipt: str) -> Optional[OrderResult]:
        order_id = self.by_receipt.get(receipt)
        return self.orders[order_id].order if order_id else None

    def fetch_order_payments(self, order_id: str) -> list[PaymentInfo]:
        if self._take_fault("fetch_timeout"):
            raise PaymentsTimeout("simulated timeout on payment fetch")
        record = self.orders.get(order_id)
        if record is None:
            raise PaymentsError(f"order not found: {order_id}")
        return list(record.payments)

    def create_payment_link(self, *, reference_id: str, amount_paise: int,
                            description: str, notes: dict) -> tuple[str, str]:
        link_id = f"plink_MOCK{uuid.uuid4().hex[:12]}"
        self.links[link_id] = {"reference_id": reference_id, "amount_paise": amount_paise,
                               "description": description, "notes": dict(notes), "status": "created"}
        return link_id, f"https://rzp.io/mock/{link_id}"

    def create_refund(self, payment_id: str, amount_paise: int) -> str:
        for record in self.orders.values():
            for payment in record.payments:
                if payment.payment_id == payment_id and payment.status == "captured":
                    payment.status = "refunded"
                    return f"rfnd_MOCK{uuid.uuid4().hex[:12]}"
        raise PaymentsError(f"no captured payment found: {payment_id}")

    # --- demo/test helpers (not part of the client protocol) ---------------

    def simulate_link_payment(self, link_id: str) -> tuple[str, PaymentInfo]:
        """A principal pays a payment link: Razorpay creates the backing order + payment."""
        link = self.links[link_id]
        order = OrderResult(order_id=f"order_MOCK{uuid.uuid4().hex[:14]}",
                            receipt=link["reference_id"], amount_paise=link["amount_paise"],
                            currency="INR", status="paid")
        self.orders[order.order_id] = _MockOrder(order=order, notes=dict(link["notes"]))
        self.by_receipt.setdefault(order.receipt, order.order_id)
        payment = PaymentInfo(payment_id=f"pay_MOCK{uuid.uuid4().hex[:14]}",
                              order_id=order.order_id, status="captured",
                              amount_paise=order.amount_paise)
        self.orders[order.order_id].payments.append(payment)
        link["status"] = "paid"
        return order.order_id, payment

    def simulate_payment(self, order_id: str, *, success: bool = True) -> PaymentInfo:
        record = self.orders[order_id]
        payment = PaymentInfo(
            payment_id=f"pay_MOCK{uuid.uuid4().hex[:14]}",
            order_id=order_id,
            status="captured" if success else "failed",
            amount_paise=record.order.amount_paise,
        )
        record.payments.append(payment)
        if success:
            record.order.status = "paid"
        return payment


# --------------------------------------------------------------------------
# Real test-mode implementation
# --------------------------------------------------------------------------

class RazorpayHTTP:
    BASE = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str, timeout: float = 10.0) -> None:
        token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self._client = httpx.Client(
            base_url=self.BASE, timeout=timeout,
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise PaymentsTimeout(str(exc)) from exc
        if response.status_code >= 400:
            raise PaymentsError(f"{response.status_code}: {response.text[:500]}")
        return response.json()

    def create_order(self, *, receipt: str, amount_paise: int, currency: str, notes: dict) -> OrderResult:
        data = self._request("POST", "/orders", json={
            "amount": amount_paise, "currency": currency, "receipt": receipt, "notes": notes,
        })
        return OrderResult(order_id=data["id"], receipt=data.get("receipt", receipt),
                           amount_paise=data["amount"], currency=data["currency"], status=data["status"])

    def fetch_order_by_receipt(self, receipt: str) -> Optional[OrderResult]:
        data = self._request("GET", "/orders", params={"receipt": receipt, "count": 1})
        items = data.get("items", [])
        if not items:
            return None
        item = items[0]
        return OrderResult(order_id=item["id"], receipt=item.get("receipt", receipt),
                           amount_paise=item["amount"], currency=item["currency"], status=item["status"])

    def fetch_order_payments(self, order_id: str) -> list[PaymentInfo]:
        data = self._request("GET", f"/orders/{order_id}/payments")
        return [PaymentInfo(payment_id=item["id"], order_id=order_id, status=item["status"],
                            amount_paise=item["amount"], method=item.get("method", ""))
                for item in data.get("items", [])]

    def create_payment_link(self, *, reference_id: str, amount_paise: int,
                            description: str, notes: dict) -> tuple[str, str]:
        data = self._request("POST", "/payment_links", json={
            "amount": amount_paise, "currency": "INR", "reference_id": reference_id,
            "description": description, "notes": notes,
        })
        return data["id"], data["short_url"]

    def create_refund(self, payment_id: str, amount_paise: int) -> str:
        data = self._request("POST", f"/payments/{payment_id}/refund", json={"amount": amount_paise})
        return data["id"]


# --------------------------------------------------------------------------

_mock_singleton: Optional[MockRazorpay] = None


def get_client() -> RazorpayClient:
    settings = get_settings()
    if settings.razorpay_mode == "mock":
        global _mock_singleton
        if _mock_singleton is None:
            _mock_singleton = MockRazorpay()
        return _mock_singleton
    return RazorpayHTTP(settings.razorpay_key_id, settings.razorpay_key_secret)


def reset_mock() -> None:
    """Test helper: fresh simulator state."""
    global _mock_singleton
    _mock_singleton = None
