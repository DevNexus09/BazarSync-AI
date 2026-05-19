import { Link } from "react-router-dom"

type AuthFooterLinkProps = {
  prompt: string
  to: string
  label: string
}

export function AuthFooterLink({ prompt, to, label }: AuthFooterLinkProps) {
  return (
    <span>
      {prompt}{" "}
      <Link className="font-medium text-foreground hover:underline" to={to}>
        {label}
      </Link>
    </span>
  )
}
