import pytest

from buzz.providers import DeterministicProvider, ModelRequest, ProviderContractError


def test_deterministic_provider_returns_structured_response_offline():
    response = DeterministicProvider().complete(
        ModelRequest(operation="classify", input={"objective": "diagnose readiness"})
    )
    assert response.provider == "deterministic"
    assert response.output == {
        "operation": "classify",
        "input": {"objective": "diagnose readiness"},
    }


def test_provider_request_rejects_invalid_output_contract():
    with pytest.raises(ProviderContractError, match="object structured output"):
        DeterministicProvider().complete(
            ModelRequest(operation="classify", input={}, output_schema="freeform")
        )


def test_provider_request_rejects_zero_budget():
    with pytest.raises(ProviderContractError, match="max_output_tokens"):
        DeterministicProvider().complete(ModelRequest(operation="classify", input={}, max_output_tokens=0))
