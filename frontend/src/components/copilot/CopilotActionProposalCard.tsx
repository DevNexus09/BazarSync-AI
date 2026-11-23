import { useState } from "react"
import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  useApproveActionProposal,
  useRejectActionProposal,
} from "@/hooks/useCopilot"
import type { CopilotActionProposal } from "@/types/copilot"

export function CopilotActionProposalCard({
  proposal,
  onStatusChange,
}: {
  proposal: CopilotActionProposal
  onStatusChange?: (proposal: CopilotActionProposal) => void
}) {
  const approve = useApproveActionProposal()
  const reject = useRejectActionProposal()
  const [message, setMessage] = useState<string | null>(null)
  const isPending = approve.isPending || reject.isPending

  const handleApprove = () => {
    approve.mutate(proposal.id, {
      onSuccess: (response) => {
        setMessage(response.message)
        onStatusChange?.(response.proposal)
      },
    })
  }

  const handleReject = () => {
    reject.mutate(proposal.id, {
      onSuccess: (response) => {
        setMessage(response.message)
        onStatusChange?.(response.proposal)
      },
    })
  }

  return (
    <div className="rounded-lg border border-primary/35 bg-primary/10 p-3 text-xs text-foreground">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Action proposal: {proposal.action_type}</p>
          <p className="mt-1 text-muted-foreground">
            {proposal.summary ?? "Review this proposal before any future execution."}
          </p>
          <p className="mt-2 rounded-md border border-amber-400/40 bg-amber-500/10 px-2 py-1 text-warning">
            Approval does not execute live marketplace changes yet.
          </p>
          {proposal.expected_impact ? (
            <p className="mt-2 text-muted-foreground">
              Expected impact is attached from backend safety checks.
            </p>
          ) : null}
          <p className="mt-2 text-muted-foreground">Status: {proposal.status}</p>
        </div>
      </div>
      {proposal.requires_confirmation ? (
        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            type="button"
            onClick={handleApprove}
            disabled={isPending || proposal.status === "APPROVED"}
          >
            <CheckCircle2 className="size-3.5" />
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            type="button"
            onClick={handleReject}
            disabled={isPending || proposal.status === "REJECTED"}
          >
            <XCircle className="size-3.5" />
            Reject
          </Button>
        </div>
      ) : null}
      {message ? <p className="mt-2 text-muted-foreground">{message}</p> : null}
      {approve.isError || reject.isError ? (
        <p className="mt-2 text-warning">
          Action proposal could not be updated. Please try again.
        </p>
      ) : null}
    </div>
  )
}
