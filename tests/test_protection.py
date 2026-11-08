import json

import pytest
import requests

from clients.delta import Delta, UncertainOrder


class ProtectiveSession:
    def __init__(self):
        self.sent = []

    def send(self, request, **options):
        self.sent.append(request)
        if request.method == "GET":
            data = [
                {
                    "id": 321,
                    "bracket_order": True,
                    "stop_order_type": "stop_loss_order",
                    "stop_price": "80.0",
                }
            ]
        else:
            data = {"id": 321, "stop_price": "100.0"}
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"success": True, "result": data}).encode()
        return response


def test_stop_ladder_edits_existing_protection_instead_of_creating_another_bracket():
    session = ProtectiveSession()
    receipt = Delta("fixture-key", "fixture-secret", session).protect(84, "100.0")
    assert receipt["stop_price"] == "100.0"
    assert [r.method for r in session.sent] == ["GET", "PUT"]
    assert json.loads(session.sent[1].body) == {"id": 321, "product_id": 84, "stop_price": "100.0"}


@pytest.mark.parametrize("change", [{"id": 999}, {"stop_price": "NaN"}])
def test_wrong_stop_acknowledgement_is_not_accepted_or_retried(change):
    class WrongReceipt(ProtectiveSession):
        def send(self, request, **options):
            response = super().send(request, **options)
            if request.method == "PUT":
                payload = response.json()
                payload["result"].update(change)
                response._content = json.dumps(payload).encode()
            return response

    session = WrongReceipt()
    with pytest.raises(UncertainOrder):
        Delta("fixture-key", "fixture-secret", session).protect(84, "100.0")
    assert [r.method for r in session.sent] == ["GET", "PUT"]
