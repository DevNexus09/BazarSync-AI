export type EnvConfig = {
  apiBaseUrl: string
  appEnv: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL

if (!apiBaseUrl) {
  console.warn(
    "VITE_API_BASE_URL is not set. Falling back to http://localhost:8000/api/v1"
  )
}

export const env: EnvConfig = {
  apiBaseUrl: apiBaseUrl ?? "http://localhost:8000/api/v1",
  appEnv: import.meta.env.MODE,
}

/** Pricing redesign (overview, product workspace, setup checklist). Default off. */
export const pricingV2Enabled = import.meta.env.VITE_PRICING_V2_UI === "true"

/** Inventory redesign (Today / Reorder / Slow & dead stock tabs, product drawer). Default off. */
export const inventoryV2Enabled = import.meta.env.VITE_INVENTORY_V2_UI === "true"
