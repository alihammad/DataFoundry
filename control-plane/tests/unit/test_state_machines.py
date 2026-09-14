"""T023: unit tests for Platform and DeploymentRun state machines
(data-model.md), including the one-active-run invariant and paused-on-
credential-expiry behaviour.
"""

from __future__ import annotations

import pytest
from datafoundry.controlplane.db.models import PlatformStatus, RunStatus
from datafoundry.controlplane.db.state_machines import (
    ACTIVE_RUN_STATUSES,
    InvalidTransitionError,
    can_transition_platform,
    can_transition_run,
    is_terminal_platform,
    is_terminal_run,
    transition_platform,
    transition_run,
)


class TestPlatformStateMachine:
    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            (PlatformStatus.pending, PlatformStatus.deploying),
            (PlatformStatus.deploying, PlatformStatus.ready),
            (PlatformStatus.deploying, PlatformStatus.degraded),
            (PlatformStatus.deploying, PlatformStatus.failed),
            (PlatformStatus.failed, PlatformStatus.deploying),  # retry
            (PlatformStatus.failed, PlatformStatus.destroying),  # rollback
            (PlatformStatus.destroying, PlatformStatus.destroyed),
            (PlatformStatus.ready, PlatformStatus.deploying),  # config change
            (PlatformStatus.ready, PlatformStatus.degraded),  # health failure
            (PlatformStatus.ready, PlatformStatus.destroying),  # destroy
            (PlatformStatus.degraded, PlatformStatus.deploying),
            (PlatformStatus.degraded, PlatformStatus.destroying),
        ],
    )
    def test_allowed_transitions(self, current, requested):
        assert can_transition_platform(current, requested)
        assert transition_platform(current, requested) is requested

    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            (PlatformStatus.pending, PlatformStatus.ready),
            (PlatformStatus.pending, PlatformStatus.destroyed),
            (PlatformStatus.ready, PlatformStatus.pending),
            (PlatformStatus.destroyed, PlatformStatus.deploying),
            (PlatformStatus.destroyed, PlatformStatus.ready),
            (PlatformStatus.failed, PlatformStatus.ready),  # must retry first
        ],
    )
    def test_forbidden_transitions(self, current, requested):
        assert not can_transition_platform(current, requested)
        with pytest.raises(InvalidTransitionError):
            transition_platform(current, requested)

    def test_same_status_is_noop(self):
        assert transition_platform(PlatformStatus.ready, PlatformStatus.ready) is (
            PlatformStatus.ready
        )

    def test_destroyed_is_terminal(self):
        assert is_terminal_platform(PlatformStatus.destroyed)
        assert not is_terminal_platform(PlatformStatus.ready)


class TestRunStateMachine:
    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            (RunStatus.queued, RunStatus.running),  # worker picks up
            (RunStatus.running, RunStatus.succeeded),  # all steps done
            (RunStatus.running, RunStatus.failed),  # step failed
            (RunStatus.failed, RunStatus.running),  # retry-from-step
            (RunStatus.failed, RunStatus.rolled_back),  # rollback complete
            (RunStatus.running, RunStatus.paused),  # credentials expired
            (RunStatus.paused, RunStatus.running),  # refresh + resume
        ],
    )
    def test_allowed_transitions(self, current, requested):
        assert can_transition_run(current, requested)
        assert transition_run(current, requested) is requested

    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            (RunStatus.succeeded, RunStatus.running),
            (RunStatus.succeeded, RunStatus.failed),
            (RunStatus.rolled_back, RunStatus.running),
            (RunStatus.queued, RunStatus.succeeded),
            (RunStatus.paused, RunStatus.succeeded),  # must resume first
        ],
    )
    def test_forbidden_transitions(self, current, requested):
        assert not can_transition_run(current, requested)
        with pytest.raises(InvalidTransitionError):
            transition_run(current, requested)

    def test_terminal_states(self):
        assert is_terminal_run(RunStatus.succeeded)
        assert is_terminal_run(RunStatus.rolled_back)
        assert not is_terminal_run(RunStatus.paused)

    def test_active_statuses_cover_one_active_run_invariant(self):
        """The partial unique index guards exactly these statuses."""
        assert {
            RunStatus.queued,
            RunStatus.running,
            RunStatus.paused,
        } == ACTIVE_RUN_STATUSES

    def test_credential_expiry_pauses_never_destroys(self):
        """running -> paused on credential expiry; paused cannot jump to a
        terminal state without going through running (R-06: nothing is
        destroyed automatically)."""
        paused = transition_run(RunStatus.running, RunStatus.paused)
        assert paused is RunStatus.paused
        assert not can_transition_run(paused, RunStatus.rolled_back)
        assert not can_transition_run(paused, RunStatus.succeeded)
        assert can_transition_run(paused, RunStatus.running)


class TestPartialUniqueIndexInvariant:
    def test_one_active_run_per_platform_sql(self):
        """The DeploymentRun table declares the partial unique index used to
        enforce one active run per platform (data-model.md invariant 3)."""
        from datafoundry.controlplane.db.models import DeploymentRun

        index_names = {ix.name for ix in DeploymentRun.__table__.indexes}
        assert "uq_one_active_run_per_platform" in index_names
        index = next(
            ix
            for ix in DeploymentRun.__table__.indexes
            if ix.name == "uq_one_active_run_per_platform"
        )
        assert index.unique
        assert "status IN ('queued', 'running', 'paused')" in str(
            index.dialect_options["postgresql"]["where"]
        )

    def test_platform_unique_constraint(self):
        """(provider, cloud_scope_id, name) uniqueness (FR-013)."""
        from datafoundry.controlplane.db.models import Platform

        constraint_names = {c.name for c in Platform.__table__.constraints}
        assert "uq_platform_scope_name" in constraint_names
