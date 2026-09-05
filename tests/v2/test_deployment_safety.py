"""The deploy path must refuse to ship a runtime with no prompt-attack detection.

This file exists because of a real incident. Runtime **v25** deployed cleanly,
reported READY, and had no Bedrock Guardrails at all: `deploy_runtime.py` read
`VOUCH_GUARDRAIL_ID` with a `""` default, the runtime saw an empty id and fell
back to no detector, and nothing at any layer said so. It was caught only by
hand-diffing deployed environment variables against the previous version.

The defect was not the missing export. It was that a deploy which FORGETS a
security control was indistinguishable from one that never wanted it. So the
absent case is now a hard stop, waiving it takes a deliberately awkward opt-in,
and the deployed configuration is read back and compared before the script
reports success.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy_runtime.py"


@pytest.fixture(scope="module")
def deploy_module():
    """Import the deploy script without running it."""
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("vouch_deploy_runtime", DEPLOY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ==========================================================================
# refusal — the v25 defect, in every shape it can take
# ==========================================================================


def test_a_missing_guardrail_id_refuses_the_deploy(deploy_module) -> None:
    with pytest.raises(deploy_module.DeploymentRefused) as refusal:
        deploy_module.guardrail_config({})
    # The message must say what to do, not merely that something is wrong.
    assert "VOUCH_GUARDRAIL_ID" in str(refusal.value)
    assert "NO prompt-attack detection" in str(refusal.value)


def test_an_empty_guardrail_id_refuses_the_deploy(deploy_module) -> None:
    """The exact v25 shape: the variable exists and is empty."""
    with pytest.raises(deploy_module.DeploymentRefused):
        deploy_module.guardrail_config({"VOUCH_GUARDRAIL_ID": ""})


def test_a_whitespace_guardrail_id_refuses_the_deploy(deploy_module) -> None:
    """`export VOUCH_GUARDRAIL_ID=" "` must not read as configured."""
    with pytest.raises(deploy_module.DeploymentRefused):
        deploy_module.guardrail_config({"VOUCH_GUARDRAIL_ID": "   "})


def test_the_refusal_names_the_waiver_rather_than_hiding_it(deploy_module) -> None:
    with pytest.raises(deploy_module.DeploymentRefused) as refusal:
        deploy_module.guardrail_config({})
    assert deploy_module.UNSAFE_OPT_IN in str(refusal.value)


# ==========================================================================
# the waiver — possible, but never by accident
# ==========================================================================


def test_the_waiver_requires_the_exact_phrase(deploy_module) -> None:
    """`=1` or `=true` must NOT waive a security control."""
    for value in ("1", "true", "yes", "please", ""):
        with pytest.raises(deploy_module.DeploymentRefused):
            deploy_module.guardrail_config({deploy_module.UNSAFE_OPT_IN: value})


def test_the_waiver_works_when_stated_explicitly(deploy_module) -> None:
    config = deploy_module.guardrail_config({
        deploy_module.UNSAFE_OPT_IN: "i-accept-no-prompt-attack-detection",
    })
    # It ships an EMPTY id — the runtime must know it has no detector rather
    # than being handed a plausible-looking wrong one.
    assert config["VOUCH_GUARDRAIL_ID"] == ""


def test_the_waiver_phrase_is_not_something_anyone_types_by_habit(deploy_module) -> None:
    assert deploy_module.UNSAFE_OPT_IN.startswith("VOUCH_DEPLOY_WITHOUT")


# ==========================================================================
# valid configuration proceeds, and carries its version
# ==========================================================================


def test_a_valid_guardrail_id_is_accepted(deploy_module) -> None:
    config = deploy_module.guardrail_config({"VOUCH_GUARDRAIL_ID": "wok5lemdo1ze"})
    assert config["VOUCH_GUARDRAIL_ID"] == "wok5lemdo1ze"
    # DRAFT is the documented default, and it is stated rather than implied.
    assert config["VOUCH_GUARDRAIL_VERSION"] == "DRAFT"


def test_a_published_version_is_carried_through(deploy_module) -> None:
    """Reproducibility: DRAFT moves when the guardrail is edited, a version does not."""
    config = deploy_module.guardrail_config({
        "VOUCH_GUARDRAIL_ID": "wok5lemdo1ze",
        "VOUCH_GUARDRAIL_VERSION": "3",
    })
    assert config["VOUCH_GUARDRAIL_VERSION"] == "3"


def test_the_id_is_trimmed_rather_than_shipped_with_whitespace(deploy_module) -> None:
    config = deploy_module.guardrail_config({"VOUCH_GUARDRAIL_ID": " wok5lemdo1ze \n"})
    assert config["VOUCH_GUARDRAIL_ID"] == "wok5lemdo1ze"


# ==========================================================================
# the deployed runtime is read back — sending is not the same as landing
# ==========================================================================


class _FakeControl:
    def __init__(self, deployed: dict):
        self._deployed = deployed

    def get_agent_runtime(self, **_kwargs):
        return {"environmentVariables": self._deployed}


def test_a_stripped_value_is_caught_after_deployment(deploy_module) -> None:
    """Exactly the v25 outcome: sent correctly, absent on the runtime."""
    expected = {"VOUCH_GUARDRAIL_ID": "wok5lemdo1ze", "VOUCH_GUARDRAIL_VERSION": "DRAFT"}
    control = _FakeControl({"VOUCH_GUARDRAIL_ID": "", "VOUCH_GUARDRAIL_VERSION": ""})

    with pytest.raises(deploy_module.DeploymentRefused) as refusal:
        deploy_module.verify_deployed_guardrail(control, expected, "26")
    assert "did not land" in str(refusal.value)


def test_a_wrong_guardrail_on_the_runtime_is_caught(deploy_module) -> None:
    expected = {"VOUCH_GUARDRAIL_ID": "wok5lemdo1ze", "VOUCH_GUARDRAIL_VERSION": "DRAFT"}
    control = _FakeControl({"VOUCH_GUARDRAIL_ID": "someotherguardrail",
                            "VOUCH_GUARDRAIL_VERSION": "DRAFT"})
    with pytest.raises(deploy_module.DeploymentRefused):
        deploy_module.verify_deployed_guardrail(control, expected, "26")


def test_a_matching_runtime_passes_verification(deploy_module) -> None:
    expected = {"VOUCH_GUARDRAIL_ID": "wok5lemdo1ze", "VOUCH_GUARDRAIL_VERSION": "DRAFT"}
    deploy_module.verify_deployed_guardrail(_FakeControl(dict(expected)), expected, "26")


# ==========================================================================
# structural guarantees about the script itself
# ==========================================================================


def test_the_script_has_no_empty_string_default_for_the_guardrail(deploy_module) -> None:
    """The literal v25 line must not come back.

    `os.environ.get("VOUCH_GUARDRAIL_ID", "")` is the defect: it converts a
    missing security control into a valid-looking configuration value.
    """
    source = DEPLOY.read_text()
    assert 'os.environ.get("VOUCH_GUARDRAIL_ID", "")' not in source
    assert "guardrail_config()" in source


def test_validation_runs_before_the_build(deploy_module) -> None:
    """A deploy that will be refused should be refused before a 36 MB build."""
    source = DEPLOY.read_text()
    main = source[source.index("def main()"):]
    assert main.index("guardrail_config()") < main.index("build()")


def test_content_capture_stays_off_in_the_deployed_environment(deploy_module) -> None:
    """The observability boundary must survive this change (no prompts, no <thinking>)."""
    source = DEPLOY.read_text()
    for off in (
        '"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false"',
        '"OTEL_GENAI_CAPTURE_MESSAGE_CONTENT": "false"',
        '"STRANDS_OTEL_ENABLE_CONSOLE_EXPORT": "false"',
    ):
        assert off in source, f"{off} is no longer pinned off"


def test_the_runtime_reads_the_guardrail_version_from_configuration() -> None:
    """The version must be configuration, not a hard-coded constant.

    A run recorded against DRAFT cannot be replayed against the same policy,
    because DRAFT moves whenever the guardrail is edited. Being able to pin a
    published version is what makes the security path reproducible.
    """
    from vouch.v2.aws import BedrockGuardrailDetector

    detector = BedrockGuardrailDetector("gid", "7")
    assert detector.guardrail_version == "7"
    assert detector.__name__ == "bedrock-guardrails:gid:7"

    # Unset still means DRAFT, and the name records which was used.
    assert BedrockGuardrailDetector("gid").guardrail_version == "DRAFT"


def test_main_can_actually_call_deploy_with_the_validated_config(deploy_module) -> None:
    """The wiring, not just the validator.

    The first cut of this fix validated correctly and then crashed with
    `TypeError: deploy() takes 1 positional argument but 2 were given` — the
    unit tests all passed because they called `guardrail_config()` directly and
    never exercised the call path. A signature check is cheap; discovering this
    during a real deploy is not.
    """
    import inspect

    parameters = inspect.signature(deploy_module.deploy).parameters
    assert "guardrails" in parameters, "deploy() cannot receive the validated config"

    main_source = inspect.getsource(deploy_module.main)
    assert "deploy(archive, guardrails)" in main_source
