import type { CopilotLanguage, CopilotReplyLanguage, CopilotStreamStage } from "@/types/copilot"

/** Interface language of the chat widget (Auto follows the last answer, else English). */
export type CopilotUiLanguage = CopilotReplyLanguage

const strings = {
  title: { en: "AI Business Copilot", bn: "এআই বিজনেস কোপাইলট", banglish: "AI Business Copilot" },
  subtitle: {
    en: "Seller-scoped business answers",
    bn: "শুধু আপনার ব্যবসার তথ্য থেকে উত্তর",
    banglish: "Shudhu apnar business data theke uttor",
  },
  newChat: { en: "New chat", bn: "নতুন চ্যাট", banglish: "Notun chat" },
  history: { en: "Conversations", bn: "আগের কথোপকথন", banglish: "Ager conversation" },
  noHistory: { en: "No earlier conversations yet.", bn: "এখনো কোনো কথোপকথন নেই।", banglish: "Ekhono kono conversation nei." },
  untitled: { en: "Untitled conversation", bn: "শিরোনামহীন কথোপকথন", banglish: "Untitled conversation" },
  language: { en: "Reply language", bn: "উত্তরের ভাষা", banglish: "Uttorer bhasha" },
  inputLabel: { en: "Ask Copilot a business question", bn: "Ask Copilot a business question", banglish: "Ask Copilot a business question" },
  inputPlaceholder: {
    en: "Ask about restock, pricing, competitors...",
    bn: "রিস্টক, দাম, প্রতিযোগী নিয়ে জিজ্ঞেস করুন...",
    banglish: "Restock, dam, competitor niye jiggesh korun...",
  },
  inputHint: {
    en: "Shift+Enter adds a new line. Marketplace changes are not executed automatically.",
    bn: "Shift+Enter দিলে নতুন লাইন হবে। মার্কেটপ্লেসে কোনো পরিবর্তন স্বয়ংক্রিয়ভাবে হয় না।",
    banglish: "Shift+Enter dile notun line hobe. Marketplace e kono change automatic hoy na.",
  },
  thinking: {
    en: "Thinking",
    bn: "বিশ্লেষণ করা হচ্ছে",
    banglish: "Analyzing",
  },
  stageUnderstanding: { en: "Thinking", bn: "বিশ্লেষণ করা হচ্ছে", banglish: "Analyzing" },
  stagePlanning: { en: "Choosing data sources", bn: "তথ্যের উৎস নির্বাচন করা হচ্ছে", banglish: "Choosing data sources" },
  stageTool: { en: "Checked", bn: "যাচাই সম্পন্ন", banglish: "Checked" },
  stageWriting: { en: "Writing answer", bn: "উত্তর প্রস্তুত করা হচ্ছে", banglish: "Preparing answer" },
  stepLookup: { en: "Checking", bn: "যাচাই করা হচ্ছে:", banglish: "Checking" },
  progress: { en: "Answer progress", bn: "উত্তরের অগ্রগতি", banglish: "Uttorer progress" },
  sources: { en: "Sources", bn: "উৎস", banglish: "Source" },
  sourcesData: { en: "Business data checked", bn: "যে তথ্য দেখা হয়েছে", banglish: "Je data check kora hoyeche" },
  sourcesMemory: { en: "From your history", bn: "আপনার আগের তথ্য থেকে", banglish: "Apnar ager data theke" },
  notRecorded: { en: "Not recorded", bn: "রেকর্ড নেই", banglish: "Record nei" },
  unavailable: { en: "unavailable", bn: "পাওয়া যায়নি", banglish: "pawa jayni" },
  freshFRESH: { en: "Fresh", bn: "হালনাগাদ", banglish: "Fresh" },
  freshSTALE: { en: "Stale", bn: "পুরনো", banglish: "Purono" },
  freshMISSING: { en: "Missing", bn: "নেই", banglish: "Nei" },
  freshUNKNOWN: { en: "Unknown age", bn: "সময় অজানা", banglish: "Shomoy ojana" },
  answerReady: { en: "New Copilot answer", bn: "Copilot নতুন উত্তর দিয়েছে", banglish: "Copilot notun uttor diyeche" },
  copy: { en: "Copy answer", bn: "উত্তর কপি করুন", banglish: "Answer copy korun" },
  copied: { en: "Copied", bn: "কপি হয়েছে", banglish: "Copy hoyeche" },
  regenerate: { en: "Ask again", bn: "আবার জিজ্ঞেস করুন", banglish: "Abar jiggesh korun" },
  helpful: { en: "Helpful", bn: "সহায়ক", banglish: "Helpful" },
  notHelpful: { en: "Not helpful", bn: "সহায়ক নয়", banglish: "Helpful na" },
  thanks: { en: "Thanks for the feedback", bn: "মতামতের জন্য ধন্যবাদ", banglish: "Feedback er jonno dhonnobad" },
  followUps: { en: "Ask next", bn: "এরপর জিজ্ঞেস করুন", banglish: "Erpor jiggesh korun" },
  nextSteps: { en: "Next steps", bn: "পরবর্তী পদক্ষেপ", banglish: "Porer step" },
  retry: { en: "Retry", bn: "আবার চেষ্টা করুন", banglish: "Abar try korun" },
  failedQuestion: { en: "Not sent", bn: "পাঠানো যায়নি", banglish: "Pathano jayni" },
  errorTitle: { en: "Copilot could not answer right now.", bn: "Copilot এখন উত্তর দিতে পারেনি।", banglish: "Copilot ekhon uttor dite pareni." },
  errorGeneric: { en: "Please try again.", bn: "অনুগ্রহ করে আবার চেষ্টা করুন।", banglish: "Doya kore abar try korun." },
  errorRateLimited: {
    en: "You are asking very quickly. Please wait a moment and try again.",
    bn: "খুব দ্রুত প্রশ্ন করা হচ্ছে। একটু অপেক্ষা করে আবার চেষ্টা করুন।",
    banglish: "Khub druto proshno kora hocche. Ektu wait kore abar try korun.",
  },
  errorTimeout: {
    en: "The answer took too long. Please try again.",
    bn: "উত্তর আসতে অনেক সময় লেগেছে। আবার চেষ্টা করুন।",
    banglish: "Uttor ashte onek time lagche. Abar try korun.",
  },
  errorServer: {
    en: "The Copilot service had a problem. Please try again shortly.",
    bn: "Copilot সার্ভিসে সমস্যা হয়েছে। একটু পরে আবার চেষ্টা করুন।",
    banglish: "Copilot service e problem hoyeche. Ektu pore abar try korun.",
  },
  errorNetwork: {
    en: "You seem to be offline. Check your connection and try again.",
    bn: "ইন্টারনেট সংযোগ নেই মনে হচ্ছে। সংযোগ দেখে আবার চেষ্টা করুন।",
    banglish: "Internet connection nei mone hocche. Connection check kore abar try korun.",
  },
  openSetup: { en: "Open setup", bn: "সেটআপ খুলুন", banglish: "Setup khulun" },
} as const

export type CopilotStringKey = keyof typeof strings

export function t(language: CopilotUiLanguage, key: CopilotStringKey): string {
  return strings[key][language] ?? strings[key].en
}

export const languageOptions: Array<{ value: CopilotLanguage; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "en", label: "English" },
  { value: "bn", label: "বাংলা" },
  { value: "banglish", label: "Banglish" },
]

export function resolveUiLanguage(
  selected: CopilotLanguage,
  lastReply?: CopilotReplyLanguage | null
): CopilotUiLanguage {
  if (selected !== "auto") {
    return selected
  }
  return lastReply ?? "en"
}

const domainNames: Record<string, Record<CopilotUiLanguage, string>> = {
  PRODUCT_CATALOG: { en: "Products", bn: "পণ্য", banglish: "Product" },
  SALES_REVENUE: { en: "Sales", bn: "বিক্রি", banglish: "Sales" },
  PROFIT_MARGIN: { en: "Profit", bn: "লাভ", banglish: "Profit" },
  INVENTORY: { en: "Inventory", bn: "স্টক", banglish: "Stock" },
  COMPETITOR: { en: "Competitors", bn: "প্রতিযোগী", banglish: "Competitor" },
  PRICING: { en: "Pricing", bn: "দাম", banglish: "Dam" },
  PROMOTION: { en: "Promotions", bn: "প্রমোশন", banglish: "Promotion" },
  DEAD_STOCK: { en: "Dead stock", bn: "ডেড স্টক", banglish: "Dead stock" },
  SEO_VISIBILITY: { en: "Visibility", bn: "ভিজিবিলিটি", banglish: "Visibility" },
  RECOMMENDATIONS: { en: "Recommendations", bn: "পরামর্শ", banglish: "Recommendation" },
  ALERTS: { en: "Alerts", bn: "সতর্কতা", banglish: "Alert" },
  RAG_MEMORY: { en: "Business memory", bn: "ব্যবসার ইতিহাস", banglish: "Business memory" },
  COPILOT: { en: "Copilot", bn: "Copilot", banglish: "Copilot" },
}

/** Readable domain name instead of the raw enum ("SALES_REVENUE" -> "Sales"). */
export function domainLabel(domain: string, language: CopilotUiLanguage = "en"): string {
  return domainNames[domain]?.[language] ?? humanize(domain)
}

/** Readable tool name ("get_inventory_risks" -> "Inventory risks"). */
export function toolLabel(name: string): string {
  return humanize(name.replace(/^get_/, ""))
}

function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim().toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : value
}

export function stageText(stage: CopilotStreamStage, language: CopilotUiLanguage): string {
  switch (stage.stage) {
    case "understanding":
      return t(language, "stageUnderstanding")
    case "planning":
      return t(language, "stagePlanning")
    case "tool":
      return `${t(language, "stageTool")}: ${stage.tool}`
    case "writing":
      return t(language, "stageWriting")
  }
}

/** BCP 47 tag for an answer so screen readers and fonts treat Banglish as Latin-script Bangla. */
export function langAttribute(replyLanguage?: CopilotReplyLanguage | null, text?: string): string | undefined {
  if (replyLanguage === "banglish") {
    return "bn-Latn"
  }
  if (replyLanguage === "bn" || (replyLanguage == null && text && /[ঀ-৿]/.test(text))) {
    return "bn"
  }
  return replyLanguage === "en" ? "en" : undefined
}

export type CopilotErrorKind = "rate_limited" | "timeout" | "server" | "network" | "generic"

export function classifyCopilotError(error: unknown): CopilotErrorKind {
  if (!error || typeof error !== "object") {
    return "generic"
  }
  const candidate = error as { code?: string; message?: string; response?: { status?: number } }
  const status = candidate.response?.status
  if (status === 429) {
    return "rate_limited"
  }
  if (candidate.code === "ECONNABORTED" || /timeout|timed out/i.test(candidate.message ?? "")) {
    return "timeout"
  }
  if (status !== undefined && status >= 500) {
    return "server"
  }
  if (candidate.code === "ERR_NETWORK" || (status === undefined && /network/i.test(candidate.message ?? ""))) {
    return "network"
  }
  return "generic"
}

const errorKeys: Record<CopilotErrorKind, CopilotStringKey> = {
  rate_limited: "errorRateLimited",
  timeout: "errorTimeout",
  server: "errorServer",
  network: "errorNetwork",
  generic: "errorGeneric",
}

export function errorText(kind: CopilotErrorKind, language: CopilotUiLanguage): string {
  return t(language, errorKeys[kind])
}

const NUMBER = "[\\d০-৯][\\d০-৯,]*(?:\\.[\\d০-৯]+)?"
// Money (BDT, Tk, ৳, টাকা) or a counted quantity. Bare numbers, dates and percentages never qualify.
const FIGURE = new RegExp(
  // "top 3 products" is a rank, not a result.
  `(?<!\\btop\\s)(?:(?:BDT|Tk\\.?|৳)\\s?${NUMBER}|${NUMBER}\\s?(?:BDT|টাকা|taka|units?|orders?|products?|items?|টি|ইউনিট|অর্ডার))`,
  "gi"
)

/** The one money or count figure a sentence states, for the answer headline; null when there are none or several. */
export function headlineFigure(text?: string | null): string | null {
  const figures = new Set((text ?? "").match(FIGURE)?.map((figure) => figure.trim().replace(/,+$/, "")) ?? [])
  return figures.size === 1 ? [...figures][0] : null
}
