import apiClient from "@/api/client"
import type { Product, ProductInput } from "@/types/product"

type ApiProduct = {
  id: string
  seller_id: string
  title: string
  description?: string | null
  category?: string | null
  specifications?: Record<string, string> | null
  searchable_text?: string | null
  cost_price: number | string
  selling_price: number | string
  stock_quantity: number
  supplier_lead_time: number
  minimum_margin: number | string
  created_at?: string
  pricing_warning?: string | null
}

type ProductListResponse = {
  items: ApiProduct[]
  total: number
  limit: number
  offset: number
}

type ProductDetailResponse = {
  message: string
  product: ApiProduct
}

const toNumber = (value: number | string) =>
  typeof value === "string" ? Number(value) : value

const mapProduct = (product: ApiProduct): Product => ({
  id: String(product.id),
  sellerId: product.seller_id,
  title: product.title,
  description: product.description ?? "",
  category: product.category ?? "Uncategorized",
  specifications: product.specifications ?? {},
  searchableText: product.searchable_text ?? null,
  costPrice: toNumber(product.cost_price),
  sellingPrice: toNumber(product.selling_price),
  stockQuantity: product.stock_quantity,
  supplierLeadTime: product.supplier_lead_time,
  minimumMargin: toNumber(product.minimum_margin),
  pricingWarning: product.pricing_warning ?? null,
  createdAt: product.created_at,
})

export async function getProducts(): Promise<Product[]> {
  const { data } = await apiClient.get<ProductListResponse>("/products")
  return data.items.map(mapProduct)
}

export async function getProduct(productId: string): Promise<Product> {
  const { data } = await apiClient.get<ApiProduct>(`/products/${productId}`)
  return mapProduct(data)
}

export async function createProduct(input: ProductInput): Promise<Product> {
  const payload = {
    title: input.title,
    description: input.description,
    category: input.category,
    specifications: input.specifications,
    cost_price: input.costPrice,
    selling_price: input.sellingPrice,
    stock_quantity: input.stockQuantity,
    supplier_lead_time: input.supplierLeadTime,
    minimum_margin: input.minimumMargin,
  }
  const { data } = await apiClient.post<ProductDetailResponse>("/products", payload)
  return mapProduct(data.product)
}

export async function updateProduct(
  productId: string,
  input: ProductInput
): Promise<Product> {
  const payload = {
    title: input.title,
    description: input.description,
    category: input.category,
    specifications: input.specifications,
    cost_price: input.costPrice,
    selling_price: input.sellingPrice,
    stock_quantity: input.stockQuantity,
    supplier_lead_time: input.supplierLeadTime,
    minimum_margin: input.minimumMargin,
  }
  const { data } = await apiClient.put<ProductDetailResponse>(
    `/products/${productId}`,
    payload
  )
  return mapProduct(data.product)
}

export async function deleteProduct(productId: string): Promise<void> {
  await apiClient.delete(`/products/${productId}`)
}
