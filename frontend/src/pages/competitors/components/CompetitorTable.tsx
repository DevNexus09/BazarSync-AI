import { useMemo } from "react"

import type { Competitor } from "../types/competitor.types"
import { CompetitorRow } from "./CompetitorRow"

type CompetitorTableProps = {
  competitors: Competitor[]
}

export function CompetitorTable({ competitors }: CompetitorTableProps) {
  const sortedCompetitors = useMemo(() => {
    const sorted = [...competitors]
    sorted.sort((a, b) => {
      const rankA = a.marketRank ?? Number.POSITIVE_INFINITY
      const rankB = b.marketRank ?? Number.POSITIVE_INFINITY
      if (rankA !== rankB) {
        return rankA - rankB
      }
      const marketScoreA = a.marketScore ?? -1
      const marketScoreB = b.marketScore ?? -1
      if (marketScoreA !== marketScoreB) {
        return marketScoreB - marketScoreA
      }
      const scoreA = a.matchConfidence ?? a.similarityScore ?? 0
      const scoreB = b.matchConfidence ?? b.similarityScore ?? 0
      return scoreB - scoreA
    })
    return sorted
  }, [competitors])

  return (
    <div className="space-y-4">
      <div className="hidden overflow-hidden rounded-xl border bg-background shadow-sm md:block">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Competitor</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">Price</th>
              <th className="px-4 py-3">Rating</th>
              <th className="px-4 py-3">Sold</th>
              <th className="px-4 py-3">Stock</th>
              <th className="px-4 py-3">Similarity</th>
              <th className="px-4 py-3">Store</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {sortedCompetitors.map((competitor) => (
              <CompetitorRow key={competitor.id} competitor={competitor} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:hidden">
        {sortedCompetitors.map((competitor) => (
          <CompetitorRow
            key={`card-${competitor.id}`}
            competitor={competitor}
            variant="card"
          />
        ))}
      </div>
    </div>
  )
}
