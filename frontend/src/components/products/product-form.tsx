import * as React from "react"
import { Link } from "react-router-dom"
import { Plus, X } from "lucide-react"

import { FormField } from "@/components/common/form-field"
import { InlineAlert } from "@/components/common/inline-alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { ProductInput } from "@/types/product"
import { formatCurrency, formatPercent } from "@/utils/formatters"

export type ProductFormValues = {
  title: string
  sku: string
  status: NonNullable<ProductInput["status"]>
  description: string
  category: string
  costPrice: string
  sellingPrice: string
  stockQuantity: string
  supplierLeadTime: string
  minimumMargin: string
}

type SpecField = {
  key: string
  label: string
  placeholder?: string
}

type SpecEntry = {
  key: string
  value: string
}

type ProductFormProps = {
  onSubmit: (input: ProductInput) => Promise<void>
  initialValues?: ProductInput
  isSubmitting?: boolean
  successMessage?: string | null
  errorMessage?: string | null
  submitLabel?: string
  cancelHref?: string
}

const initialValues: ProductFormValues = {
  title: "",
  sku: "",
  status: "ACTIVE",
  description: "",
  category: "",
  costPrice: "",
  sellingPrice: "",
  stockQuantity: "",
  supplierLeadTime: "",
  minimumMargin: "",
}

type FieldErrors = Partial<Record<keyof ProductFormValues, string>>

const CATEGORY_SPEC_FIELDS: Record<string, SpecField[]> = {
  Electronics: [
    { key: "storage", label: "Storage", placeholder: "128GB" },
    { key: "ram", label: "RAM", placeholder: "8GB" },
    { key: "processor", label: "Processor", placeholder: "A16 Bionic" },
    { key: "model", label: "Model number", placeholder: "A1234" },
    { key: "color", label: "Color", placeholder: "Silver" },
  ],
  Clothing: [
    { key: "size", label: "Size", placeholder: "M / 32 / 40" },
    { key: "fabric", label: "Fabric", placeholder: "Cotton" },
    { key: "color", label: "Color", placeholder: "Black" },
  ],
  Cosmetics: [
    { key: "skin_type", label: "Skin type", placeholder: "Dry / Oily" },
    { key: "volume", label: "Volume", placeholder: "200ml" },
    { key: "ingredients", label: "Key ingredients", placeholder: "Vitamin C" },
  ],
  Furniture: [
    { key: "dimensions", label: "Dimensions", placeholder: "120x60x75cm" },
    { key: "material", label: "Material", placeholder: "Engineered wood" },
    { key: "color", label: "Color", placeholder: "Walnut" },
    { key: "weight", label: "Weight", placeholder: "12kg" },
  ],
  Other: [],
}

const CATEGORY_OPTIONS = Object.keys(CATEGORY_SPEC_FIELDS)

const toStringNumber = (value?: number) => {
  if (value === 0) {
    return "0"
  }
  if (!value) {
    return ""
  }
  return String(value)
}

const normalizeCategory = (category?: string) => {
  if (!category) {
    return ""
  }
  return CATEGORY_OPTIONS.includes(category) ? category : "Other"
}

const buildInitialValues = (input?: ProductInput): ProductFormValues => {
  if (!input) {
    return initialValues
  }

  return {
    title: input.title ?? "",
    sku: input.sku ?? "",
    status: input.status ?? "ACTIVE",
    description: input.description ?? "",
    category: normalizeCategory(input.category),
    costPrice: toStringNumber(input.costPrice),
    sellingPrice: toStringNumber(input.sellingPrice),
    stockQuantity: toStringNumber(input.stockQuantity),
    supplierLeadTime: toStringNumber(input.supplierLeadTime),
    minimumMargin: toStringNumber(input.minimumMargin),
  }
}

const splitSpecifications = (
  specs: Record<string, string>,
  category: string
) => {
  const categoryFields = CATEGORY_SPEC_FIELDS[category] ?? []
  const categoryKeys = new Set(categoryFields.map((field) => field.key))
  const categorySpecs: Record<string, string> = {}

  categoryFields.forEach((field) => {
    categorySpecs[field.key] = specs[field.key] ?? ""
  })

  const customSpecs = Object.entries(specs)
    .filter(([key]) => !categoryKeys.has(key))
    .map(([key, value]) => ({ key, value }))

  return { categorySpecs, customSpecs }
}

function parseNumber(value: string) {
  if (!value) {
    return NaN
  }

  return Number(value)
}

export function ProductForm({
  onSubmit,
  initialValues: providedValues,
  isSubmitting = false,
  successMessage,
  errorMessage,
  submitLabel = "Save product",
  cancelHref,
}: ProductFormProps) {
  const resolvedInitialValues = React.useMemo(
    () => buildInitialValues(providedValues),
    [providedValues]
  )
  const initialSpecs = splitSpecifications(
    providedValues?.specifications ?? {},
    resolvedInitialValues.category
  )
  const [values, setValues] = React.useState<ProductFormValues>(
    resolvedInitialValues
  )
  const [errors, setErrors] = React.useState<FieldErrors>({})
  const [specifications, setSpecifications] = React.useState<Record<string, string>>(
    initialSpecs.categorySpecs
  )
  const [customSpecs, setCustomSpecs] = React.useState<SpecEntry[]>(
    initialSpecs.customSpecs
  )

  const actualMargin = React.useMemo(() => {
    const cost = parseNumber(values.costPrice)
    const selling = parseNumber(values.sellingPrice)

    if (!Number.isFinite(cost) || !Number.isFinite(selling) || selling <= 0) {
      return null
    }

    return ((selling - cost) / selling) * 100
  }, [values.costPrice, values.sellingPrice])

  const validate = (formValues: ProductFormValues) => {
    const nextErrors: FieldErrors = {}

    if (!formValues.title.trim()) {
      nextErrors.title = "Product title is required."
    }

    if (!formValues.description.trim()) {
      nextErrors.description = "Product description is required."
    }

    if (!formValues.category.trim()) {
      nextErrors.category = "Product category is required."
    }

    const cost = parseNumber(formValues.costPrice)
    if (!Number.isFinite(cost) || cost <= 0) {
      nextErrors.costPrice = "Cost price must be greater than 0."
    }

    const selling = parseNumber(formValues.sellingPrice)
    if (!Number.isFinite(selling) || selling <= 0) {
      nextErrors.sellingPrice = "Selling price must be greater than 0."
    }

    if (Number.isFinite(cost) && Number.isFinite(selling) && selling < cost) {
      nextErrors.sellingPrice = "Selling price should be higher than cost."
    }

    const stock = parseNumber(formValues.stockQuantity)
    if (!Number.isFinite(stock) || stock < 0) {
      nextErrors.stockQuantity = "Stock quantity must be 0 or higher."
    }

    const leadTime = parseNumber(formValues.supplierLeadTime)
    if (!Number.isFinite(leadTime) || leadTime <= 0) {
      nextErrors.supplierLeadTime = "Lead time must be greater than 0."
    }

    const minimumMargin = parseNumber(formValues.minimumMargin)
    if (!Number.isFinite(minimumMargin) || minimumMargin < 0) {
      nextErrors.minimumMargin = "Minimum margin must be 0% or higher."
    }

    return nextErrors
  }

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setValues((prev) => ({ ...prev, [name]: value }))
    setErrors((prev) => ({ ...prev, [name]: undefined }))
  }

  const handleStatusChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setValues((prev) => ({
      ...prev,
      status: event.target.value as NonNullable<ProductInput["status"]>,
    }))
  }

  const handleDescriptionChange = (
    event: React.ChangeEvent<HTMLTextAreaElement>
  ) => {
    const { value } = event.target
    setValues((prev) => ({ ...prev, description: value }))
    setErrors((prev) => ({ ...prev, description: undefined }))
  }

  const handleCategoryChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const category = event.target.value
    setValues((prev) => ({ ...prev, category }))
    setErrors((prev) => ({ ...prev, category: undefined }))

    const nextSpecs: Record<string, string> = {}
    const nextFields = CATEGORY_SPEC_FIELDS[category] ?? []
    nextFields.forEach((field) => {
      nextSpecs[field.key] = specifications[field.key] ?? ""
    })
    setSpecifications(nextSpecs)
    const nextKeys = new Set(nextFields.map((field) => field.key))
    setCustomSpecs((prev) => prev.filter((spec) => !nextKeys.has(spec.key)))
  }

  const handleSpecChange = (key: string, value: string) => {
    setSpecifications((prev) => ({ ...prev, [key]: value }))
  }

  const handleCustomSpecChange = (
    index: number,
    key: string,
    value: string
  ) => {
    setCustomSpecs((prev) =>
      prev.map((item, idx) =>
        idx === index ? { key, value } : item
      )
    )
  }

  const handleAddCustomSpec = () => {
    setCustomSpecs((prev) => [...prev, { key: "", value: "" }])
  }

  const handleRemoveCustomSpec = (index: number) => {
    setCustomSpecs((prev) => prev.filter((_, idx) => idx !== index))
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const validationErrors = validate(values)
    setErrors(validationErrors)

    if (Object.keys(validationErrors).length > 0) {
      return
    }

    const input: ProductInput = {
      title: values.title.trim(),
      sku: values.sku.trim() || null,
      status: values.status ?? "ACTIVE",
      description: values.description.trim(),
      category: values.category.trim(),
      specifications: {
        ...Object.fromEntries(
          Object.entries(specifications).filter(([, value]) => value.trim())
        ),
        ...Object.fromEntries(
          customSpecs
            .filter((spec) => spec.key.trim() && spec.value.trim())
            .map((spec) => [spec.key.trim(), spec.value.trim()])
        ),
      },
      costPrice: parseNumber(values.costPrice),
      sellingPrice: parseNumber(values.sellingPrice),
      stockQuantity: parseNumber(values.stockQuantity),
      supplierLeadTime: parseNumber(values.supplierLeadTime),
      minimumMargin: parseNumber(values.minimumMargin),
    }

    await onSubmit(input)
  }

  const sellingValue = parseNumber(values.sellingPrice)
  const costValue = parseNumber(values.costPrice)
  const minMarginValue = parseNumber(values.minimumMargin)
  const marginOk =
    actualMargin !== null && Number.isFinite(minMarginValue)
      ? actualMargin >= minMarginValue
      : null

  return (
    <form onSubmit={handleSubmit} noValidate>
      <fieldset
        className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start"
        disabled={isSubmitting}
      >
        <div className="space-y-6">
          {errorMessage ? <InlineAlert variant="error" message={errorMessage} /> : null}
          {successMessage ? <InlineAlert variant="success" message={successMessage} /> : null}

          <FormSection
            title="Basic information"
            description="How this product is identified across marketplaces."
          >
            <FormField
              id="product-title"
              name="title"
              label="Product title"
              value={values.title}
              placeholder="Premium denim jacket"
              onChange={handleChange}
              error={errors.title}
            />

            <div className="grid gap-4 md:grid-cols-3">
              <FormField
                id="product-sku"
                name="sku"
                label="SKU (optional)"
                value={values.sku}
                placeholder="SKU-001"
                onChange={handleChange}
              />
              <SelectField id="product-category" label="Category" error={errors.category}>
                <select
                  id="product-category"
                  value={values.category}
                  onChange={handleCategoryChange}
                  className={selectClass}
                  aria-invalid={Boolean(errors.category)}
                >
                  <option value="" disabled>
                    Select category
                  </option>
                  {CATEGORY_OPTIONS.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </SelectField>
              <SelectField id="product-status" label="Status">
                <select
                  id="product-status"
                  value={values.status}
                  onChange={handleStatusChange}
                  className={selectClass}
                >
                  {["ACTIVE", "INACTIVE", "DRAFT", "ARCHIVED", "DISCONTINUED"].map((status) => (
                    <option key={status} value={status}>
                      {status.charAt(0) + status.slice(1).toLowerCase()}
                    </option>
                  ))}
                </select>
              </SelectField>
            </div>

            <SelectField id="product-description" label="Description" error={errors.description}>
              <textarea
                id="product-description"
                name="description"
                value={values.description}
                onChange={handleDescriptionChange}
                rows={4}
                aria-invalid={Boolean(errors.description)}
                className="w-full rounded-xl border border-border/70 bg-card/70 px-3 py-2 text-sm text-foreground outline-none transition focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30"
                placeholder="Describe the product, materials and variants."
              />
            </SelectField>
          </FormSection>

          <FormSection
            title="Specifications"
            description="Clear specs like storage, colour or size reduce false competitor matches."
          >
            {!values.category ? (
              <p className="text-sm text-muted-foreground">
                Choose a category above to see suggested attributes.
              </p>
            ) : (
              <>
                {CATEGORY_SPEC_FIELDS[values.category]?.length ? (
                  <div className="grid gap-4 md:grid-cols-2">
                    {CATEGORY_SPEC_FIELDS[values.category].map((field) => (
                      <FormField
                        key={field.key}
                        id={`spec-${field.key}`}
                        name={`spec-${field.key}`}
                        label={field.label}
                        value={specifications[field.key] ?? ""}
                        placeholder={field.placeholder}
                        onChange={(event) => handleSpecChange(field.key, event.target.value)}
                      />
                    ))}
                  </div>
                ) : null}
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-foreground">Custom attributes</p>
                    <Button type="button" variant="outline" size="sm" onClick={handleAddCustomSpec}>
                      <Plus /> Add attribute
                    </Button>
                  </div>
                  {customSpecs.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      Anything else buyers compare on, like warranty or pack size.
                    </p>
                  ) : (
                    customSpecs.map((spec, index) => (
                      <div key={`custom-${index}`} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                        <Input
                          value={spec.key}
                          onChange={(event) =>
                            handleCustomSpecChange(index, event.target.value, spec.value)
                          }
                          placeholder="Name"
                          aria-label={`Attribute ${index + 1} name`}
                        />
                        <Input
                          value={spec.value}
                          onChange={(event) =>
                            handleCustomSpecChange(index, spec.key, event.target.value)
                          }
                          placeholder="Value"
                          aria-label={`Attribute ${index + 1} value`}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-lg"
                          className="h-11 text-muted-foreground hover:text-danger"
                          onClick={() => handleRemoveCustomSpec(index)}
                          aria-label={`Remove attribute ${index + 1}`}
                        >
                          <X />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </FormSection>

          <FormSection
            title="Pricing and inventory"
            description="Feeds AI pricing recommendations, MarginGuard and restock forecasts."
          >
            <div className="grid gap-4 md:grid-cols-3">
              <FormField
                id="product-cost"
                name="costPrice"
                label="Cost price (BDT)"
                type="number"
                inputMode="decimal"
                min={1}
                step={0.01}
                value={values.costPrice}
                placeholder="1200"
                onChange={handleChange}
                error={errors.costPrice}
              />
              <FormField
                id="product-selling"
                name="sellingPrice"
                label="Selling price (BDT)"
                type="number"
                inputMode="decimal"
                min={0}
                step={0.01}
                value={values.sellingPrice}
                placeholder="1790"
                onChange={handleChange}
                error={errors.sellingPrice}
              />
              <FormField
                id="product-margin"
                name="minimumMargin"
                label="Minimum margin (%)"
                type="number"
                inputMode="decimal"
                min={0}
                step={0.1}
                value={values.minimumMargin}
                placeholder="18"
                onChange={handleChange}
                error={errors.minimumMargin}
              />
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <FormField
                id="product-stock"
                name="stockQuantity"
                label="Stock quantity"
                type="number"
                inputMode="numeric"
                min={0}
                step={1}
                value={values.stockQuantity}
                placeholder="150"
                onChange={handleChange}
                error={errors.stockQuantity}
              />
              <FormField
                id="product-lead-time"
                name="supplierLeadTime"
                label="Supplier lead time (days)"
                type="number"
                inputMode="numeric"
                min={0}
                step={1}
                value={values.supplierLeadTime}
                placeholder="7"
                onChange={handleChange}
                error={errors.supplierLeadTime}
              />
            </div>
          </FormSection>
        </div>

        <aside className="glass-panel space-y-4 p-5 lg:sticky lg:top-6">
          <h3 className="text-sm font-semibold text-foreground">Pricing summary</h3>
          <dl className="space-y-3 text-sm">
            <SummaryRow
              label="Selling price"
              value={Number.isFinite(sellingValue) ? formatCurrency(sellingValue) : "—"}
            />
            <SummaryRow
              label="Profit per unit"
              value={
                Number.isFinite(sellingValue) && Number.isFinite(costValue)
                  ? formatCurrency(sellingValue - costValue)
                  : "—"
              }
            />
            <SummaryRow
              label="Margin"
              value={
                actualMargin === null ? (
                  "—"
                ) : (
                  <span className={cn(marginOk === false ? "text-danger" : marginOk ? "text-success" : "")}>
                    {formatPercent(actualMargin)}
                  </span>
                )
              }
            />
          </dl>
          {marginOk === false ? (
            <p className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
              Margin is below your {formatPercent(minMarginValue)} minimum.
            </p>
          ) : marginOk ? (
            <p className="rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-xs text-success">
              Meets your {formatPercent(minMarginValue)} minimum margin.
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Enter cost, selling price and minimum margin to check profitability.
            </p>
          )}
          <div className="flex flex-col gap-2 border-t border-border/60 pt-4">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving..." : submitLabel}
            </Button>
            {cancelHref ? (
              <Button variant="ghost" asChild>
                <Link to={cancelHref}>Cancel</Link>
              </Button>
            ) : null}
          </div>
        </aside>
      </fieldset>
    </form>
  )
}

const selectClass =
  "h-11 w-full rounded-xl border border-border/70 bg-card/70 px-3 text-sm text-foreground outline-none transition focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30"

function FormSection({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section className="glass-panel space-y-4 p-5">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  )
}

function SelectField({
  id,
  label,
  error,
  children,
}: {
  id: string
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-foreground" htmlFor={id}>
        {label}
      </label>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  )
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  )
}
