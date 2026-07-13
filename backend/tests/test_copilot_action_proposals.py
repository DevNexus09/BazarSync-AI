from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import unittest
from uuid import UUID, uuid4

from app.models.copilot import CopilotActionProposalStatus, CopilotActionType
from app.services.copilot.action_proposal_service import (
    APPROVAL_MESSAGE,
    REJECTION_MESSAGE,
    CopilotActionProposalNotFoundError,
    CopilotActionProposalService,
    CopilotActionProposalTransitionError,
)


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_SELLER_ID = UUID("00000000-0000-0000-0000-000000000002")


@dataclass
class _Proposal:
    id: UUID
    seller_id: UUID
    action_type: CopilotActionType = CopilotActionType.PRICE_CHANGE
    status: CopilotActionProposalStatus = CopilotActionProposalStatus.PROPOSED
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    executed_at: datetime | None = None
    expires_at: datetime | None = None
    proposed_payload_json: dict | None = None
    safety_checks_json: dict | None = None
    expected_impact_json: dict | None = None
    evidence_json: list | None = None


class _ProposalRepository:
    def __init__(self, proposals: list[_Proposal] | None = None) -> None:
        self.proposals = proposals or []
        self.saved: list[_Proposal] = []
        self.accessed_seller_ids: list[UUID] = []

    def list_action_proposals(self, *, seller_id, status=None, limit=20, offset=0):
        self.accessed_seller_ids.append(seller_id)
        rows = [item for item in self.proposals if item.seller_id == seller_id]
        if status is not None:
            rows = [item for item in rows if item.status == status]
        return rows[offset : offset + limit], len(rows)

    def get_action_proposal(self, *, seller_id, proposal_id):
        self.accessed_seller_ids.append(seller_id)
        for item in self.proposals:
            if item.seller_id == seller_id and item.id == proposal_id:
                return item
        return None

    def save_action_proposal(self, proposal):
        self.saved.append(proposal)
        return proposal


class CopilotActionProposalServiceTests(unittest.TestCase):
    def test_approval_does_not_execute(self):
        proposal = _Proposal(id=uuid4(), seller_id=SELLER_ID)
        repo = _ProposalRepository([proposal])

        updated, message = CopilotActionProposalService(repository=repo).approve(
            seller_id=SELLER_ID,
            proposal_id=proposal.id,
        )

        self.assertEqual(APPROVAL_MESSAGE, message)
        self.assertEqual(CopilotActionProposalStatus.APPROVED, updated.status)
        self.assertIsNotNone(updated.approved_at)
        self.assertIsNone(updated.executed_at)

    def test_rejection_works(self):
        proposal = _Proposal(id=uuid4(), seller_id=SELLER_ID)
        repo = _ProposalRepository([proposal])

        updated, message = CopilotActionProposalService(repository=repo).reject(
            seller_id=SELLER_ID,
            proposal_id=proposal.id,
        )

        self.assertEqual(REJECTION_MESSAGE, message)
        self.assertEqual(CopilotActionProposalStatus.REJECTED, updated.status)
        self.assertIsNotNone(updated.rejected_at)
        self.assertIsNone(updated.executed_at)

    def test_cross_seller_proposal_access_blocked(self):
        proposal = _Proposal(id=uuid4(), seller_id=OTHER_SELLER_ID)

        with self.assertRaises(CopilotActionProposalNotFoundError):
            CopilotActionProposalService(repository=_ProposalRepository([proposal])).get_proposal(
                seller_id=SELLER_ID,
                proposal_id=proposal.id,
            )

    def test_proposal_expires_if_configured(self):
        proposal = _Proposal(
            id=uuid4(),
            seller_id=SELLER_ID,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        repo = _ProposalRepository([proposal])

        updated = CopilotActionProposalService(repository=repo).get_proposal(
            seller_id=SELLER_ID,
            proposal_id=proposal.id,
        )

        self.assertEqual(CopilotActionProposalStatus.EXPIRED, updated.status)
        self.assertEqual([updated], repo.saved)

    def test_expired_proposal_cannot_be_approved(self):
        proposal = _Proposal(
            id=uuid4(),
            seller_id=SELLER_ID,
            status=CopilotActionProposalStatus.EXPIRED,
        )

        with self.assertRaises(CopilotActionProposalTransitionError):
            CopilotActionProposalService(repository=_ProposalRepository([proposal])).approve(
                seller_id=SELLER_ID,
                proposal_id=proposal.id,
            )


if __name__ == "__main__":
    unittest.main()
