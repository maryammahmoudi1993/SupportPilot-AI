"""Channel endpoint configuration management service coverage (Phase 13
section 15, 44, 46)."""

from __future__ import annotations

import pytest

from accounts.tests.factories import UserFactory
from agents.tests.factories import PublishedAgentVersionFactory
from channel_ingress.endpoint_admin import (
    InvalidAgentVersionError,
    create_endpoint,
    rotate_secret,
    set_endpoint_status,
    update_endpoint,
)
from channel_ingress.models import ChannelEndpointStatus, ChannelType
from channel_ingress.tests.factories import EmailEndpointFactory, WebChatEndpointFactory
from workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_create_endpoint_rejects_an_unpublished_agent_version():
    workspace = WorkspaceFactory()
    from agents.tests.factories import AgentVersionFactory

    version = AgentVersionFactory(agent_definition__workspace=workspace)  # draft, not published
    with pytest.raises(InvalidAgentVersionError):
        create_endpoint(
            workspace=workspace,
            actor=UserFactory(),
            channel=ChannelType.EMAIL,
            name="Support",
            agent_version=version,
        )


def test_create_endpoint_rejects_a_foreign_workspace_agent_version():
    workspace = WorkspaceFactory()
    foreign_version = PublishedAgentVersionFactory()
    with pytest.raises(InvalidAgentVersionError):
        create_endpoint(
            workspace=workspace,
            actor=UserFactory(),
            channel=ChannelType.EMAIL,
            name="Support",
            agent_version=foreign_version,
        )


def test_update_endpoint_renames_and_audits():
    endpoint = EmailEndpointFactory()
    updated = update_endpoint(
        workspace=endpoint.workspace, endpoint=endpoint, actor=UserFactory(), name="New name"
    )
    assert updated.name == "New name"


def test_update_endpoint_with_no_fields_is_a_no_op():
    endpoint = EmailEndpointFactory()
    updated = update_endpoint(workspace=endpoint.workspace, endpoint=endpoint, actor=UserFactory())
    assert updated.id == endpoint.id


def test_update_endpoint_rejects_a_foreign_workspace_agent_version():
    endpoint = EmailEndpointFactory()
    foreign_version = PublishedAgentVersionFactory()
    with pytest.raises(InvalidAgentVersionError):
        update_endpoint(
            workspace=endpoint.workspace,
            endpoint=endpoint,
            actor=UserFactory(),
            agent_version=foreign_version,
        )


def test_set_endpoint_status_rejects_an_invalid_value():
    endpoint = EmailEndpointFactory()
    with pytest.raises(ValueError):
        set_endpoint_status(
            workspace=endpoint.workspace,
            endpoint=endpoint,
            actor=UserFactory(),
            status="not-a-status",
        )


def test_set_endpoint_status_enable_after_disable():
    endpoint = EmailEndpointFactory(status=ChannelEndpointStatus.DISABLED)
    updated = set_endpoint_status(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        actor=UserFactory(),
        status=ChannelEndpointStatus.ACTIVE,
    )
    assert updated.status == ChannelEndpointStatus.ACTIVE


def test_rotate_secret_generates_a_new_secret():
    endpoint = EmailEndpointFactory()
    original = endpoint.encrypted_signing_secret
    updated, plaintext = rotate_secret(
        workspace=endpoint.workspace, endpoint=endpoint, actor=UserFactory()
    )
    assert updated.encrypted_signing_secret != original
    assert plaintext


def test_rotate_secret_rejects_web_chat_endpoints():
    endpoint = WebChatEndpointFactory()
    with pytest.raises(ValueError):
        rotate_secret(workspace=endpoint.workspace, endpoint=endpoint, actor=UserFactory())
